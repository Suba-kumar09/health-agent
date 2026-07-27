# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Phase 1 of a cross-platform health-monitoring end-device agent. It runs in the background on a
user's machine, passively observes keyboard/mouse intensity, the foreground app/window, and
(via a companion browser extension) the active browser tab, buffers everything locally in
SQLite, and periodically batch-uploads it to a not-yet-built ingest server. Offline-first by
design: the agent must keep working and buffering with no network, and must never lose or
duplicate events when connectivity returns.

Windows is the primary/validated target. macOS and Linux platform backends
(`agent/platform/macos.py`, `agent/platform/linux.py`) are written per the same interface but
unverified — there is no machine to test them on in this environment.

## Common commands

```powershell
# Activate the venv (already created at .venv)
.venv\Scripts\Activate.ps1

# Run the full test suite
python -m pytest -q

# Run a single test file / test
python -m pytest tests/test_storage.py -q
python -m pytest tests/test_uploader.py::test_batch_resumes_same_batch_id -q

# Run the agent for real (dry-run = logs upload payloads instead of sending them)
python -m agent.main --dry-run --data-dir ./demo_run --no-tray
# then Ctrl+C to stop; `y` at the first-run consent prompt is required before any collector starts

# One-time explicit consent flow required before capture_mode="detailed" is honored
python -m agent.main --enable-detailed-consent --data-dir ./demo_run

# Build a standalone Windows exe (PyInstaller)
pyinstaller health-agent.spec

# Lint (also run in CI)
ruff check .
```

Because collector threads write to the local SQLite buffer, avoid running two `agent.main`
instances against the same `--data-dir` at once (WAL mode tolerates concurrent readers, not
concurrent writer processes).

## Architecture

**Data flow:** independent collector threads → `Storage` (encrypted SQLite buffer) →
`Uploader` (APScheduler-driven, paced batch drain) → ingest server (contract-only in Phase 1;
`--dry-run` swaps in `LoggingTransport` from `agent/main.py` instead of a real server).

`agent/main.py` is the orchestrator — it is the one place that wires config → consent → secrets
→ cipher → storage → collectors → tray → uploader → scheduler. Read it first when tracing how
a setting actually takes effect.

### Storage (`agent/storage.py`)

Single `events` table: `event_id, collector, ts, duration, data, synced, batch_id`. Only the
`data` JSON blob is encrypted (via `agent/crypto.py`'s `FieldCipher`, Fernet-based) — the other
columns stay plaintext so sync/dedup queries don't need decryption. `NullCipher` is a no-op
passthrough used when `privacy.encrypt_at_rest = false`.

`Storage` wraps **every** connection access in a single `threading.Lock` (`self._lock`). This
is load-bearing, not incidental: a bare `sqlite3.Connection` with `check_same_thread=False` is
still not safe under concurrent `execute()` from multiple threads (two threads can each trigger
an implicit `BEGIN` and collide with "cannot start a transaction within a transaction"). Every
collector runs on its own thread and writes through this same `Storage` instance — if you add a
new method, it must take the lock too.

### Collectors (`agent/collectors/`)

All implement a small `Collector` protocol (`base.py`) with `start()`/`stop()`. Each owns its
own thread; `main.py`'s per-collector `on_*` callbacks are what actually construct `Event`
objects and call `storage.append()` — collectors themselves know nothing about storage.

- **`input_watcher.py`**: `InputBucketAggregator` is pure logic (no `pynput` dependency),
  deliberately separated from `InputWatcherCollector` (the real `pynput` wrapper) so bucket-math
  is unit-testable without a real input backend. Fixed 30s buckets by default; `capture_mode`
  gates whether `key_codes` are ever recorded (never in `aggregate` mode — only counts).
- **`window_watcher.py`**: dispatches to `agent/platform/{windows,macos,linux}.py` via
  `_resolve_backend()` based on `platform.system()`. On Linux, `is_wayland()` is checked first
  and the collector disables itself with a warning rather than silently returning wrong data —
  Wayland foreground-window inspection is a known Phase-1 gap, don't try to work around it.
- **`afk.py`**: derives active/idle purely from `input_watcher`'s
  `aggregator.last_activity_ts` (passed in as a callback from `main.py`, not a shared object) —
  `afk` cannot run if `input_watcher` is disabled.
- **`coalescing.py`**: `CoalescingStatePoller` is shared, generic heartbeat logic used by both
  `window_watcher` and `afk`. Consecutive polls with an identical state key extend the current
  event's `duration` via `Storage.extend_duration` instead of inserting a new row; a changed
  state key finalizes the previous event and inserts a new one. `extend_duration` only succeeds
  while the row is `synced=0 AND batch_id IS NULL` — once a batch claims it, the row is frozen
  and the next poll starts a fresh event.
- **`browser_bridge.py`**: a stdlib `ThreadingHTTPServer` bound to `127.0.0.1` on a random port
  (any open browser tab can `fetch()` a localhost port, so this is deliberately hardened, not
  an oversight). Two independent gates on every POST: an Origin allowlist
  (`chrome-extension://`, `moz-extension://` — ordinary web pages can't spoof these schemes) as
  defense-in-depth, and a paired bearer token as the actual access control. Pairing
  (`/pair`) uses a random 6-digit code, 5 min TTL, single-use, checked with
  `secrets.compare_digest`. If you touch this file, preserve both checks — neither is
  redundant with the other.

### Consent (`agent/consent.py`)

`basic_consent` (any monitoring at all) and `detailed_consent` (recording actual keys / more
sensitive detail) are tracked as separate flags in `consent.json`, not one combined toggle.
`resolve_capture_mode()` silently downgrades a configured `capture_mode="detailed"` back to
`"aggregate"` if detailed consent isn't on record — `main.py` logs a warning when this happens.
Detailed mode also writes an audit log line every session it's active. Don't bypass
`ensure_first_run_consent()` — it's the gate that must run before any collector starts.

### Secrets (`agent/secrets.py`)

Wraps the OS keychain (via `keyring`) for `data_encryption_key`, `local_device_id`, and
`browser_bridge_token`, service name `"health-agent"`. Falls back to a 0600-permissioned file
under the given `fallback_dir` when `keyring.errors.KeyringError` is raised (e.g. headless
Linux with no D-Bus session) — this fallback is intentionally quieter-but-not-silent; check
`agent/secrets.py` before assuming a warning was logged for a given call site.

Tests must never touch the real OS keychain. Existing tests monkeypatch
`agent.secrets.keyring.get_password`/`set_password` to raise `KeyringError` (see
`tests/test_secrets.py` and `tests/test_browser_bridge.py`) so each test run is isolated —
follow that pattern for any new test that constructs a `SecretStore`. If you run `agent.main`
manually against your own OS keychain (e.g. for a live smoke test), clean up the
`data_encryption_key` / `local_device_id` / `browser_bridge_token` entries under service
`"health-agent"` afterward via `keyring.delete_password("health-agent", key)`.

### Sync (`agent/sync/`)

`api.py` holds the pydantic contract models (`IngestEvent`, `IngestRequest`, `IngestResponse`,
`EnrollRequest`, `EnrollResponse`) — these *are* the wire contract; keep them in sync with
`docs/API.md` if either changes.

`uploader.py`'s `Uploader.run_tick()` is the core loop, called on an APScheduler interval from
`main.py`. Idempotency is the central design constraint: `_next_batch()` always checks
`storage.pending_batch_ids()` (batches already assigned an id but not yet confirmed synced)
*before* minting a new batch, and retries that exact batch_id/event_id set. This is what makes
a crash between "server accepted" and "client marked synced" safe — the server sees the same
batch_id/event_ids again and should return them in the response's `duplicates` list, which
`run_tick()` treats the same as `accepted` for the purpose of marking rows synced locally.
Backoff (`BackoffState`) is exponential but a server-supplied `Retry-After` (on 429) always
takes precedence over the computed curve.

`enroll.py` implements the client side of the not-yet-built `/v1/enroll` endpoint (see
`docs/API.md`); there is no real server for either endpoint in Phase 1.

### Tray (`agent/tray.py`)

`pystray`-based; pause/resume/stop call back into the same `collectors` list `main.py` built,
plus a `capture_mode` indicator (icon color: green=aggregate, orange=detailed, gray=paused).
This is the actual mechanism satisfying the "visible pause/stop" requirement — don't treat it
as optional UI chrome.

### Browser extension (`browser-extension/`)

MV3, dual Chrome/Firefox support via `browser_specific_settings.gecko` in `manifest.json` (uses
the `chrome.*` namespace, which Firefox also implements under MV3). `options.js` is the pairing
UI: takes the port + 6-digit code shown in the agent's log (log only for now — issued once at
startup, no tray display or re-issue/unpair yet), POSTs to `/pair`, stores the returned token.
`background.js` listens on `chrome.tabs.onActivated`/`onUpdated` and POSTs `{url, title, ts}` to
`/tab-event` with the stored bearer token.

## Testing conventions

- `tests/mock_server.py` provides a FastAPI-based `MockIngestServer` fixture for integration
  tests against `Uploader` — implements the same `/v1/ingest` contract from `docs/API.md`.
- `tests/test_integration.py` uses `fastapi.testclient.TestClient`, not
  `httpx.Client(transport=httpx.ASGITransport(...))` directly — `ASGITransport` doesn't support
  a sync `httpx.Client` (no `handle_request`), which is why `TestClient`'s sync wrapper is used
  instead.
- Any test constructing a `SecretStore` or exercising `browser_bridge`'s pairing must
  monkeypatch `keyring` to raise `KeyringError` (see above) or it will read/write real OS
  keychain state and can leak state between test runs.
- `freezegun` is available (dev dependency) for time-dependent tests (backoff, batch pacing,
  pairing-code TTL).

## Key non-obvious invariants (don't casually change)

- `extend_duration` only succeeds while `synced=0 AND batch_id IS NULL` — this ordering (not a
  simple flag check) is what prevents a heartbeat-coalesced event from mutating after it's
  already been claimed by an in-flight batch.
- `next_run_time` must **not** be passed (not even `None`) to `scheduler.add_job(...)` in
  `main.py` — passing `next_run_time=None` silently disables the job entirely rather than using
  the default schedule. This was a real bug found via live testing, not a hypothetical.
- The browser bridge's Origin allowlist and bearer-token check are independent layers; the
  token is the actual access control, the Origin check is defense-in-depth against the specific
  threat of an arbitrary web page's `fetch()` reaching the localhost port. Don't consolidate
  them into a single check.
- `docs/API.md` is the source of truth for the `/v1/ingest` and `/v1/enroll` wire contracts and
  for the browser bridge's `/pair` + `/tab-event` contract — update it alongside `agent/sync/api.py`
  or `agent/collectors/browser_bridge.py` if either payload shape changes.
