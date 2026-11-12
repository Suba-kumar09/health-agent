"""Regenerate the human-readable telemetry views from a data-dir's events.db.

`generate_html` and `export_json` both decrypt the full accumulated history
(same key the agent itself uses) and rewrite their output file from scratch,
so calling them again after more events have been captured grows the report
instead of replacing it with just the latest run. The running agent calls
these itself on a timer (see `agent/main.py`'s reports job) so telemetry.html
and events_export.json stay live without a separate process; `scripts/
generate_telemetry_html.py` and `scripts/export_readable_json.py` remain as
thin one-shot CLI wrappers around the same functions.
"""
from __future__ import annotations

import csv
import datetime
import json
import sqlite3
import time
from pathlib import Path

from agent.config import Config
from agent.crypto import cipher_for_config
from agent.secrets import SecretStore


def _time_filter_sql(since: float | None, until: float | None) -> tuple[str, list[float]]:
    """Builds an optional `WHERE ts >= ? AND ts <= ?` clause for a `since`/`until` window.

    Returns ("", []) when both are None, so callers get the same unbounded query as
    before when no window is requested (one-shot CLI use, or a caller with no config).
    """
    clauses = []
    params: list[float] = []
    if since is not None:
        clauses.append("ts >= ?")
        params.append(since)
    if until is not None:
        clauses.append("ts <= ?")
        params.append(until)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params

TEMPLATE = """<title>Session Telemetry — health-agent</title>
<style>
  :root {
    --ink: #eef1ef; --ink-text: #16201d; --ink-soft: #4a5854; --ink-faint: #7c8b86;
    --line: #ccd6d1; --panel: #ffffff;
    --trace: #2a8f7f; --trace-soft: #2a8f7f22;
    --pulse: #b5741f; --pulse-soft: #b5741f1e;
    --rest: #5c5f86; --rest-soft: #5c5f861e;
    color-scheme: light;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --ink: #10161a; --ink-text: #dfe7e4; --ink-soft: #93a29d; --ink-faint: #5d6b67;
      --line: #263230; --panel: #161e22;
      --trace: #4fc3ae; --trace-soft: #4fc3ae22;
      --pulse: #d99f4f; --pulse-soft: #d99f4f22;
      --rest: #8d90c4; --rest-soft: #8d90c422;
      color-scheme: dark;
    }
  }
  :root[data-theme="dark"] {
    --ink: #10161a; --ink-text: #dfe7e4; --ink-soft: #93a29d; --ink-faint: #5d6b67;
    --line: #263230; --panel: #161e22;
    --trace: #4fc3ae; --trace-soft: #4fc3ae22;
    --pulse: #d99f4f; --pulse-soft: #d99f4f22;
    --rest: #8d90c4; --rest-soft: #8d90c422;
    color-scheme: dark;
  }
  :root[data-theme="light"] {
    --ink: #eef1ef; --ink-text: #16201d; --ink-soft: #4a5854; --ink-faint: #7c8b86;
    --line: #ccd6d1; --panel: #ffffff;
    --trace: #2a8f7f; --trace-soft: #2a8f7f22;
    --pulse: #b5741f; --pulse-soft: #b5741f1e;
    --rest: #5c5f86; --rest-soft: #5c5f861e;
    color-scheme: light;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    background: var(--ink); color: var(--ink-text);
    font-family: -apple-system, "Segoe UI", "SF Pro Display", "Helvetica Neue", sans-serif;
    -webkit-font-smoothing: antialiased;
    padding: clamp(20px, 4vw, 56px);
    max-width: 900px; margin: 0 auto;
  }
  .mono { font-family: ui-monospace, "Cascadia Code", "SF Mono", Consolas, "Liberation Mono", monospace; font-variant-numeric: tabular-nums; }
  header { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; border-bottom: 1px solid var(--line); padding-bottom: 18px; margin-bottom: 22px; flex-wrap: wrap; }
  .eyebrow { text-transform: uppercase; letter-spacing: 0.11em; font-size: 11px; color: var(--ink-faint); margin: 0 0 6px; font-weight: 600; }
  h1 { margin: 0; font-size: 22px; font-weight: 650; letter-spacing: -0.01em; text-wrap: balance; }
  .device { text-align: right; font-size: 12px; color: var(--ink-faint); line-height: 1.5; }
  .device .status { color: var(--trace); font-weight: 600; }
  .status::before { content: "●"; margin-right: 5px; font-size: 9px; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 1px; background: var(--line); border: 1px solid var(--line); border-radius: 6px; overflow: hidden; margin-bottom: 28px; }
  .stat { background: var(--panel); padding: 14px 16px; }
  .stat .num { font-size: 24px; font-weight: 650; line-height: 1.1; }
  .stat .label { font-size: 11px; color: var(--ink-faint); text-transform: uppercase; letter-spacing: 0.08em; margin-top: 5px; }
  .section-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--ink-faint); font-weight: 600; margin: 0 0 12px; display: flex; justify-content: space-between; }
  .log { position: relative; padding-left: 20px; }
  .log::before { content: ""; position: absolute; left: 3px; top: 6px; bottom: 6px; width: 1px; background: var(--line); }
  .row { position: relative; display: grid; grid-template-columns: 68px 92px 1fr; gap: 14px; align-items: start; padding: 10px 0; border-bottom: 1px solid var(--line); }
  .row:last-child { border-bottom: none; }
  .row::before { content: ""; position: absolute; left: -20px; top: 16px; width: 7px; height: 7px; border-radius: 50%; background: var(--dot); box-shadow: 0 0 0 3px var(--ink); }
  .row.window_watcher { --dot: var(--trace); }
  .row.input_watcher { --dot: var(--pulse); }
  .row.afk { --dot: var(--rest); }
  .row.browser_bridge { --dot: var(--trace); }
  .time { font-size: 13px; color: var(--ink-soft); padding-top: 2px; }
  .day-divider { grid-column: 1 / -1; font-size: 11px; color: var(--ink-faint); text-transform: uppercase; letter-spacing: 0.08em; padding: 14px 0 6px; }
  .chip { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 20px; width: fit-content; white-space: nowrap; }
  .chip::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
  .window_watcher .chip, .browser_bridge .chip { background: var(--trace-soft); color: var(--trace); }
  .input_watcher .chip { background: var(--pulse-soft); color: var(--pulse); }
  .afk .chip { background: var(--rest-soft); color: var(--rest); }
  .detail { font-size: 13.5px; line-height: 1.5; }
  .detail .primary { color: var(--ink-text); font-weight: 550; }
  .detail .secondary { color: var(--ink-faint); font-size: 12px; }
  .metrics { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 3px; }
  .metric { font-size: 12px; color: var(--ink-soft); }
  .metric b { color: var(--ink-text); font-weight: 650; }
  .bar-track { height: 4px; border-radius: 2px; background: var(--line); margin-top: 6px; max-width: 220px; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 2px; background: var(--dot); }
  footer { margin-top: 30px; padding-top: 16px; border-top: 1px solid var(--line); font-size: 12px; color: var(--ink-faint); line-height: 1.6; }
  footer strong { color: var(--ink-soft); }
  @media (max-width: 520px) {
    .row { grid-template-columns: 56px 1fr; }
    .row .chip-cell { grid-column: 2; order: -1; margin-bottom: 2px; }
    .time { grid-row: 1; }
  }
</style>

<header>
  <div>
    <p class="eyebrow">health-agent · local capture log</p>
    <h1>Session Telemetry</h1>
  </div>
  <div class="device">
    <div class="status">__GENERATED_AT__</div>
    <div>__DATA_DIR__</div>
  </div>
</header>

<div class="stats" id="stats"></div>

<p class="section-label"><span>Chronological log</span><span id="row-count" class="mono"></span></p>
<div class="log" id="log"></div>

<footer>
  <strong>Reading this:</strong> the colored dot marks which watcher recorded the row — teal for
  window focus, amber for typing/click activity, violet for active/idle state. Bar length under a
  window row shows how long that app stayed focused, relative to the longest entry shown. Keypress
  and click figures are counts only — never the actual keys typed. This report accumulates every
  event ever written to this data-dir's database, oldest first.
</footer>

<script>
const events = __EVENTS_JSON__;

const labels = { window_watcher: "window", input_watcher: "input", afk: "afk", browser_bridge: "browser" };

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

function renderStats() {
  const totalKeys = events.filter(e => e.collector === "input_watcher").reduce((a, e) => a + (e.data.keypress_count || 0), 0);
  const totalClicks = events.filter(e => e.collector === "input_watcher").reduce((a, e) => a + (e.data.click_count || 0), 0);
  const totalScrolls = events.filter(e => e.collector === "input_watcher").reduce((a, e) => a + (e.data.scroll_count || 0), 0);
  const switches = events.filter(e => e.collector === "window_watcher").length;
  const spanSecs = events.length ? Math.round(events[events.length - 1].ts - events[0].ts) : 0;
  const spanLabel = spanSecs >= 3600 ? `${(spanSecs / 3600).toFixed(1)}h` : spanSecs >= 60 ? `${Math.round(spanSecs / 60)}m` : `${spanSecs}s`;

  const stats = [
    ["Events", events.length],
    ["Span", spanLabel],
    ["Keypresses", totalKeys],
    ["Clicks", totalClicks],
    ["Scrolls", totalScrolls],
    ["Window switches", switches],
  ];
  document.getElementById("stats").innerHTML = stats.map(([label, num]) =>
    `<div class="stat"><div class="num mono">${num}</div><div class="label">${label}</div></div>`
  ).join("");
  document.getElementById("row-count").textContent = `${events.length} row${events.length === 1 ? "" : "s"}`;
}

function renderRow(e, maxDuration, showDayDivider) {
  const chip = `<span class="chip">${labels[e.collector] || e.collector}</span>`;
  let detail = "";
  if (e.collector === "window_watcher" || e.collector === "browser_bridge") {
    const pct = Math.max(4, Math.round((e.duration / maxDuration) * 100));
    const primary = e.data.app || e.data.url || "";
    const secondary = e.data.title || "";
    detail = `
      <div class="primary">${escapeHtml(primary)}</div>
      <div class="secondary">${escapeHtml(secondary)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
    `;
  } else if (e.collector === "input_watcher") {
    detail = `
      <div class="primary">${e.data.active_secs}s active of ${e.duration.toFixed(0)}s bucket</div>
      <div class="metrics">
        <span class="metric"><b>${e.data.keypress_count}</b> keys</span>
        <span class="metric"><b>${e.data.click_count}</b> clicks</span>
        <span class="metric"><b>${e.data.scroll_count}</b> scrolls</span>
        <span class="metric"><b>${Math.round(e.data.mouse_dist_px)}</b>px moved</span>
      </div>
    `;
  } else if (e.collector === "afk") {
    detail = `<div class="primary">Marked ${e.data.state} for ${e.duration.toFixed(1)}s</div>`;
  }
  const divider = showDayDivider ? `<div class="day-divider">${showDayDivider}</div>` : "";
  return `
    ${divider}
    <div class="row ${e.collector}">
      <div class="time mono">${e.time}</div>
      <div class="chip-cell">${chip}</div>
      <div class="detail">${detail}</div>
    </div>
  `;
}

function renderLog() {
  const maxDuration = Math.max(...events.map(e => e.duration), 1);
  let lastDay = null;
  const html = events.map(e => {
    const day = e.day;
    const divider = day !== lastDay ? day : null;
    lastDay = day;
    return renderRow(e, maxDuration, divider);
  }).join("");
  document.getElementById("log").innerHTML = html;
}

renderStats();
renderLog();
</script>
"""


def generate_html(
    data_dir: Path,
    out: Path,
    config: Config | None = None,
    since: float | None = None,
    until: float | None = None,
) -> int:
    """Regenerate `out` from `data_dir`'s events.db history. Returns row count.

    With `since`/`until` left as None (the default for direct/CLI calls), the full
    history is used, same as before. `refresh_reports` passes an automatic `since`
    for the recurring in-process job -- see its docstring.
    """
    store = SecretStore(fallback_dir=data_dir / "secrets")
    cipher = cipher_for_config(config or Config.default(), store)

    con = sqlite3.connect(data_dir / "events.db")
    where_sql, params = _time_filter_sql(since, until)
    rows = con.execute(
        f"SELECT collector, ts, duration, data FROM events{where_sql} ORDER BY ts ASC", params
    ).fetchall()
    con.close()

    events = []
    for collector, ts, duration, raw in rows:
        decrypted = cipher.decrypt_json(raw)
        dt = datetime.datetime.fromtimestamp(ts)
        events.append(
            {
                "time": dt.strftime("%H:%M:%S"),
                "day": dt.strftime("%A, %B %d"),
                "ts": ts,
                "collector": collector,
                "duration": round(duration, 1),
                "data": decrypted,
            }
        )

    html = TEMPLATE.replace("__EVENTS_JSON__", json.dumps(events))
    html = html.replace(
        "__GENERATED_AT__",
        f"generated {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    )
    html = html.replace("__DATA_DIR__", f"data-dir: {data_dir}")

    Path(out).write_text(html, encoding="utf-8")
    return len(events)


def export_json(
    data_dir: Path,
    out: Path,
    config: Config | None = None,
    since: float | None = None,
    until: float | None = None,
) -> int:
    """Regenerate `out` from `data_dir`'s events.db history. Returns event count.

    See `generate_html` for the `since`/`until` behavior.
    """
    store = SecretStore(fallback_dir=data_dir / "secrets")
    cipher = cipher_for_config(config or Config.default(), store)

    con = sqlite3.connect(data_dir / "events.db")
    where_sql, params = _time_filter_sql(since, until)
    rows = con.execute(
        f"SELECT event_id, collector, ts, duration, data, synced FROM events{where_sql} ORDER BY ts ASC",
        params,
    ).fetchall()
    con.close()

    events = []
    for event_id, collector, ts, duration, raw, synced in rows:
        events.append(
            {
                "event_id": event_id,
                "collector": collector,
                "ts": ts,
                "time": datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
                "duration": round(duration, 1),
                "uploaded": bool(synced),
                "data": cipher.decrypt_json(raw),
            }
        )

    Path(out).write_text(json.dumps(events, indent=2), encoding="utf-8")
    return len(events)


def export_csv(
    data_dir: Path,
    out: Path,
    config: Config | None = None,
    since: float | None = None,
    until: float | None = None,
) -> int:
    """Regenerate `out` (a human-readable CSV) from `data_dir`'s events.db history.

    Returns row count. See `generate_html` for the `since`/`until` behavior. Used by
    `scripts/export_readable_csv.py` so that script no longer duplicates its own
    decrypt/read loop.
    """
    store = SecretStore(fallback_dir=data_dir / "secrets")
    cipher = cipher_for_config(config or Config.default(), store)

    con = sqlite3.connect(data_dir / "events.db")
    where_sql, params = _time_filter_sql(since, until)
    rows = con.execute(
        f"SELECT collector, ts, duration, data, synced FROM events{where_sql} ORDER BY ts ASC",
        params,
    ).fetchall()
    con.close()

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "collector", "duration_secs", "uploaded", "details"])
        for collector, ts, duration, raw, synced in rows:
            decrypted = cipher.decrypt_json(raw)
            t = datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")
            details = ", ".join(f"{k}={v}" for k, v in decrypted.items())
            writer.writerow([t, collector, f"{duration:.1f}", "yes" if synced else "no", details])

    return len(rows)


def refresh_reports(data_dir: Path, html_out: Path, json_out: Path, config: Config | None = None) -> None:
    """Regenerate both telemetry.html and events_export.json in one call.

    Bounds the recurring in-process refresh to the last `config.reports.window_days`
    (default 7) so it doesn't reload the agent's entire history on every tick; direct/
    CLI calls to generate_html/export_json are unaffected since they default to
    since=None (full history) unless the caller passes its own bound.
    """
    cfg = config or Config.default()
    since = time.time() - cfg.reports.window_days * 86400
    generate_html(data_dir, html_out, cfg, since=since)
    export_json(data_dir, json_out, cfg, since=since)
