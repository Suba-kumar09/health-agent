# health-agent

A cross-platform, privacy-first background agent that passively senses system-level
activity — keyboard/mouse intensity, the foreground app/window, and (via a companion
browser extension) the active browser tab — to infer wellbeing signals such as typing
intensity, break/idle patterns, and screen time. It captures events locally, buffers them
in an encrypted SQLite database, and periodically batch-uploads to a health-monitoring
ingest server (contract-only in Phase 1; there is no real server yet).

Windows is the primary/validated target. macOS and Linux platform backends
(`agent/platform/macos.py`, `agent/platform/linux.py`) are written to the same interface
but unverified where noted.

## Setup

Requires Python 3.10+.

### Windows

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,windows]"
```

### Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,linux]"
```

(macOS follows the same pattern as Linux, installing the `macos` extra instead —
`pip install -e ".[dev,macos]"` — but this path is unverified; see the platform-backend
note above.)

## Running it

```bash
# Dry run: logs upload payloads instead of sending them to a real server
python -m agent.main --dry-run --data-dir ./demo_run --no-tray
# Ctrl+C to stop. `y` at the first-run consent prompt is required before any collector starts.
```

Drop `--no-tray` to get the `pystray` tray icon (pause/resume/stop). Omit `--dry-run` and
set `agent.server_url` in `config.toml` to point at a real ingest server once one exists.

While the agent runs, `telemetry.html` and `events_export.json` (paths configurable under
`[reports]` in `config.toml`) auto-refresh every `interval_secs` so you can watch captured
data without stopping the agent. See `scripts/generate_telemetry_html.py`,
`scripts/export_readable_json.py`, and `scripts/export_readable_csv.py` for one-shot,
full-history (or `--since`/`--until` custom-range) exports.

## Consent model

Two independent consent flags, tracked in `<data-dir>/consent.json`:

- **Basic consent** — required before *any* collector starts. The agent prompts for this
  on first run; declining exits without starting anything.
- **Detailed consent** — required before `capture_mode = "detailed"` (which additionally
  records key *codes*, never reconstructed text) is honored. Run once, explicitly:

  ```bash
  python -m agent.main --enable-detailed-consent --data-dir ./demo_run
  ```

  Without this, a configured `capture_mode = "detailed"` silently falls back to
  `"aggregate"` (counts only — keypresses, clicks, scrolls, active seconds; never which
  keys were pressed or any typed content), and a warning is logged. Every session where
  detailed mode is active writes an audit log line.

## Tests and lint

```bash
pytest -q
ruff check .
```

See `CLAUDE.md` for architecture notes and non-obvious invariants if you're modifying the
agent itself.
