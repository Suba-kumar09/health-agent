from __future__ import annotations

import argparse
import gzip
import json
import logging
import platform
import signal
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx
from apscheduler.schedulers.background import BackgroundScheduler

from agent.collectors.afk import AfkCollector
from agent.collectors.browser_bridge import BrowserBridgeCollector
from agent.collectors.input_watcher import InputBucket, InputWatcherCollector
from agent.collectors.window_watcher import WindowWatcherCollector
from agent.config import Config
from agent.consent import (
    ConsentManager,
    ensure_first_run_consent,
    resolve_capture_mode,
    run_detailed_consent_flow,
)
from agent.crypto import FieldCipher, NullCipher, get_or_create_fernet_key
from agent.json_log import JsonEventLogger
from agent.reports import refresh_reports
from agent.secrets import SecretStore
from agent.storage import Event, Storage, run_retention
from agent.sync.enroll import EnrollmentError, enroll
from agent.sync.uploader import Uploader
from agent.tray import TrayController

logger = logging.getLogger("agent")

AGENT_VERSION = "0.1.0"


class LoggingTransport(httpx.BaseTransport):
    """Stands in for a real server in --dry-run: logs the payload, echoes 200s."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = request.read()
        if request.headers.get("content-encoding") == "gzip":
            body = gzip.decompress(body)
        payload = json.loads(body)
        logger.info(
            "[dry-run] batch %s: %d event(s) -> %s",
            payload["batch_id"],
            len(payload["events"]),
            [e["collector"] for e in payload["events"]],
        )
        event_ids = [e["event_id"] for e in payload["events"]]
        return httpx.Response(200, json={"accepted": event_ids, "duplicates": []})


def maybe_enroll(
    secret_store: SecretStore,
    http_client: httpx.Client,
    server_url: str,
    enrollment_code: str | None,
    device_name: str,
    os_name: str,
    os_version: str,
    device_id: str,
    device_token: str,
) -> tuple[str, str]:
    """Exchange `enrollment_code` for a real device_token if not already enrolled.

    Returns (device_id, device_token), updated on success; unchanged (and logged) on
    failure or when there's nothing to do -- callers should always continue running
    with whatever this returns rather than treating enrollment as required.
    """
    if device_token != "unenrolled" or not enrollment_code:
        return device_id, device_token
    try:
        resp = enroll(
            http_client=http_client,
            server_url=server_url,
            enrollment_code=enrollment_code,
            device_name=device_name,
            os_name=os_name,
            os_version=os_version,
        )
    except EnrollmentError as exc:
        logger.warning("Enrollment failed (%s) -- continuing unenrolled", exc)
        return device_id, device_token
    secret_store.set("device_token", resp.device_token)
    # get_or_create_local_device_id() reads this back on every future run, before
    # maybe_enroll() ever runs -- without persisting it here, the next restart pairs
    # the real (persisted) device_token with a stale local device_id, and the server's
    # payload.device_id != device.device_id check (server/routes/ingest.py) 401s every
    # upload from then on.
    secret_store.set("local_device_id", resp.device_id)
    logger.info("Enrolled successfully (device_id=%s)", resp.device_id)
    return resp.device_id, resp.device_token


def get_or_create_local_device_id(secret_store: SecretStore) -> str:
    existing = secret_store.get("local_device_id")
    if existing:
        return existing
    device_id = str(uuid.uuid4())
    secret_store.set("local_device_id", device_id)
    return device_id


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Health-monitoring end-device agent")
    parser.add_argument("--config", default="config.toml", help="Path to config.toml")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log upload payloads instead of sending to the real server_url",
    )
    parser.add_argument("--data-dir", default=".", help="Directory for the local SQLite buffer + secrets fallback")
    parser.add_argument(
        "--enable-detailed-consent",
        action="store_true",
        help="Run the one-time explicit consent flow for detailed capture_mode, then exit",
    )
    parser.add_argument("--no-tray", action="store_true", help="Run without the tray icon (e.g. headless)")
    parser.add_argument(
        "--no-reports",
        action="store_true",
        help="Don't auto-regenerate telemetry.html/events_export.json while running",
    )
    parser.add_argument(
        "--enrollment-code",
        default=None,
        help="One-time code to exchange for a device_token via POST /v1/enroll, if not already enrolled",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = build_arg_parser().parse_args(argv)

    config_path = Path(args.config)
    config = Config.load(config_path) if config_path.exists() else Config.default()
    if not config_path.exists():
        logger.warning("Config file %s not found, using defaults", config_path)

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    consent = ConsentManager(data_dir)

    if args.enable_detailed_consent:
        granted = run_detailed_consent_flow(consent, prompt_fn=input)
        logger.info("Detailed-mode consent %s", "granted" if granted else "declined")
        return

    if not ensure_first_run_consent(consent, prompt_fn=input):
        logger.warning("Monitoring consent declined -- exiting without starting any collector")
        return

    capture_mode = resolve_capture_mode(config.agent.capture_mode, consent)
    if capture_mode != config.agent.capture_mode:
        logger.warning(
            "capture_mode=%s requested but detailed-mode consent not on record "
            "(run --enable-detailed-consent first) -- falling back to aggregate",
            config.agent.capture_mode,
        )
    if capture_mode == "detailed":
        consent.log_detailed_mode_audit()
        logger.warning("detailed capture_mode is ACTIVE this session (audit-logged)")

    secret_store = SecretStore(fallback_dir=data_dir / "secrets")
    device_id = config.agent.device_id or get_or_create_local_device_id(secret_store)
    device_token = secret_store.get("device_token") or "unenrolled"  # real /v1/enroll flow: later milestone

    cipher = FieldCipher(get_or_create_fernet_key(secret_store)) if config.privacy.encrypt_at_rest else NullCipher()
    json_logger = JsonEventLogger(data_dir / "events.jsonl") if config.privacy.json_log_enabled else None
    storage = Storage(data_dir / "events.db", cipher=cipher, json_logger=json_logger)

    collectors = []
    input_watcher = None
    if config.collectors.input_watcher:
        def on_bucket(bucket: InputBucket) -> None:
            detailed = capture_mode == "detailed"
            event = Event(
                collector="input_watcher",
                ts=bucket.bucket_start,
                duration=config.agent.bucket_seconds,
                data=bucket.to_data(detailed=detailed),
            )
            storage.append(event)
            logger.debug("input_watcher bucket flushed: %s", event.data)

        input_watcher = InputWatcherCollector(
            bucket_seconds=config.agent.bucket_seconds,
            capture_mode=capture_mode,
            on_bucket=on_bucket,
        )
        input_watcher.start()
        collectors.append(input_watcher)
        logger.info(
            "input_watcher started (capture_mode=%s, bucket_seconds=%d)", capture_mode, config.agent.bucket_seconds
        )
    else:
        logger.info("input_watcher disabled in config")

    if config.collectors.window_watcher:
        def on_new_window(info: dict, ts: float) -> str:
            event = Event(
                collector="window_watcher",
                ts=ts,
                duration=0.0,
                data={"app": info.get("app"), "title": info.get("title")},
            )
            storage.append(event)
            logger.debug("window_watcher new state: %s", event.data)
            return event.event_id

        def on_extend_window(event_id: str, duration: float) -> None:
            storage.extend_duration(event_id, duration)

        window_watcher = WindowWatcherCollector(on_new_window=on_new_window, on_extend=on_extend_window)
        window_watcher.start()
        collectors.append(window_watcher)
        logger.info("window_watcher started (poll_interval=%.1fs)", window_watcher.poll_interval_secs)
    else:
        logger.info("window_watcher disabled in config")

    if config.collectors.afk:
        if input_watcher is None:
            logger.warning("afk disabled: requires input_watcher to derive idle state from")
        else:
            def on_new_afk_state(info: dict, ts: float) -> str:
                event = Event(collector="afk", ts=ts, duration=0.0, data={"state": info["state"]})
                storage.append(event)
                logger.debug("afk state changed: %s", info["state"])
                return event.event_id

            def on_extend_afk(event_id: str, duration: float) -> None:
                storage.extend_duration(event_id, duration)

            afk = AfkCollector(
                get_last_activity_ts=lambda: input_watcher.aggregator.last_activity_ts,
                on_new_state=on_new_afk_state,
                on_extend=on_extend_afk,
                threshold_secs=config.privacy.afk_threshold_secs,
            )
            afk.start()
            collectors.append(afk)
            logger.info("afk started (threshold=%ds)", config.privacy.afk_threshold_secs)
    else:
        logger.info("afk disabled in config")

    if config.collectors.browser_bridge:
        def on_tab_event(data: dict) -> None:
            event = Event(
                collector="browser_bridge",
                ts=data.get("ts", time.time()),
                duration=0.0,
                data={"url": data.get("url"), "title": data.get("title")},
            )
            storage.append(event)
            logger.debug("browser_bridge tab event: %s", event.data)

        browser_bridge = BrowserBridgeCollector(
            secret_store=secret_store,
            on_tab_event=on_tab_event,
            port=config.agent.browser_bridge_port,
        )
        browser_bridge.start()
        collectors.append(browser_bridge)
        logger.info("browser_bridge started on 127.0.0.1:%d", browser_bridge.port)
    else:
        logger.info("browser_bridge disabled in config")

    stop_event = threading.Event()

    def pause_collectors() -> None:
        for c in collectors:
            c.stop()
        logger.info("Collectors paused via tray")

    def resume_collectors() -> None:
        for c in collectors:
            c.start()
        logger.info("Collectors resumed via tray")

    def stop_from_tray() -> None:
        stop_event.set()

    tray = None
    if not args.no_tray:
        tray = TrayController(
            on_pause=pause_collectors,
            on_resume=resume_collectors,
            on_stop=stop_from_tray,
            capture_mode=capture_mode,
        )
        tray.start()

    if args.dry_run:
        http_client = httpx.Client(transport=LoggingTransport())
        logger.info("Running in --dry-run mode: uploads are logged, not sent")
    else:
        http_client = httpx.Client()

    device_id, device_token = maybe_enroll(
        secret_store=secret_store,
        http_client=http_client,
        server_url=config.agent.server_url,
        enrollment_code=args.enrollment_code,
        device_name=platform.node(),
        os_name=platform.system(),
        os_version=platform.release(),
        device_id=device_id,
        device_token=device_token,
    )

    uploader = Uploader(
        storage=storage,
        http_client=http_client,
        sync_cfg=config.sync,
        server_url=config.agent.server_url,
        device_id=device_id,
        agent_version=AGENT_VERSION,
        os_name=platform.system(),
        os_version=platform.release(),
        token_provider=lambda: device_token,
    )

    scheduler = BackgroundScheduler()
    scheduler.add_job(uploader.run_tick, "interval", seconds=config.agent.sync_interval_secs)
    scheduler.add_job(
        lambda: run_retention(storage, config.retention),
        "interval",
        seconds=max(config.agent.sync_interval_secs, 3600),
    )
    if config.reports.enabled and not args.no_reports:
        html_out = Path(config.reports.html_path)
        json_out = Path(config.reports.json_path)
        scheduler.add_job(
            lambda: refresh_reports(data_dir, html_out, json_out),
            "interval",
            seconds=config.reports.interval_secs,
        )
        logger.info(
            "Live reports enabled: %s / %s refreshed every %ds",
            html_out,
            json_out,
            config.reports.interval_secs,
        )
    scheduler.start()

    def handle_signal(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    logger.info(
        "Agent running (device_id=%s, unsynced=%d). Ctrl+C or tray 'Stop agent' to stop.",
        device_id,
        storage.count_unsynced(),
    )
    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    finally:
        logger.info("Shutting down: flushing collectors and buffer")
        for c in collectors:
            c.stop()
        if tray is not None:
            tray.stop()
        scheduler.shutdown(wait=False)
        uploader.run_tick()  # final drain attempt before exit
        storage.close()


if __name__ == "__main__":
    main(sys.argv[1:])
