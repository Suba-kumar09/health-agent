# Health Agent

[![tests](https://github.com/Suba-kumar09/health-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/Suba-kumar09/health-agent/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platforms](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

A cross-platform, privacy-first **health-monitoring agent** that runs quietly in the
background on a user's computer. It measures *how* the device is being used — typing and
mouse intensity, the foreground app, idle time, and the active browser tab — buffers
everything locally in an encrypted SQLite store, and uploads it in batches to an ingest
server.

It is **offline-first**: the agent keeps working with no network, and when connectivity
returns it uploads without ever losing or duplicating an event.

> **Status — Phase 1.** The device agent, browser extension, and the server wire contract are
> complete. The ingest server itself is a later phase; use `--dry-run` to see what would be
> uploaded. Windows is the primary validated platform; macOS and Linux backends are
> implemented against the same interface but not yet verified on real hardware.

---

## Features

**Data collection**
- **Input activity** — keypress, click and scroll counts, mouse distance and active seconds,
  aggregated into 30-second buckets (no keystrokes recorded by default)
- **Foreground window** — active application and window title, per OS
  (Windows / macOS / Linux X11)
- **AFK detection** — active vs. idle state, derived from input activity
- **Browser tabs** — active tab URL and title via a companion Chrome/Firefox (MV3) extension
- **Heartbeat coalescing** — repeated identical states extend one event's duration instead of
  creating thousands of rows

**Privacy & security**
- **Explicit consent** before any collector starts; a separate, one-time opt-in for
  *detailed* mode, with an audit log entry each session it is active
- **Encryption at rest** — event payloads encrypted with Fernet (AES)
- **OS keychain** for keys, device ID and tokens, with a permission-restricted file fallback
- **Hardened localhost bridge** — browser extension must pass an Origin allowlist *and* a
  paired bearer token (6-digit, single-use, 5-minute pairing code)
- **System tray** with visible pause / resume / stop and a capture-mode indicator
  (green = aggregate, orange = detailed, gray = paused)

**Reliable sync**
- Batched, gzip-compressed uploads, sized by event count and bytes
- **Idempotent retries** — an in-flight batch is always retried with the same `batch_id` and
  event IDs, so a crash mid-upload is safe
- Exponential backoff that respects the server's `Retry-After` on HTTP 429
- Configurable retention: delete after sync, or keep for N days
- Device enrollment via a one-time code

---

## Architecture

```
 ┌──────────────── Collectors (one thread each) ────────────────┐
 │  input_watcher   window_watcher   afk   browser_bridge ◄──── │── Browser extension
 └──────────────────────────────┬───────────────────────────────┘    (Chrome / Firefox)
                                │ events
                                ▼
                 Storage — SQLite (WAL), encrypted `data` column
                                │
                                ▼
            Uploader — APScheduler tick, batching, backoff, retries
                                │  POST /v1/ingest (gzip, Idempotency-Key)
                                ▼
                     Ingest server (later phase)
```

`agent/main.py` is the orchestrator that wires everything together:
config → consent → secrets → cipher → storage → collectors → tray → uploader → scheduler.

```
agent/
├── main.py              # entry point and orchestration
├── config.py            # typed config (pydantic) loaded from config.toml
├── consent.py           # basic / detailed consent flags
├── crypto.py            # Fernet field encryption
├── secrets.py           # OS keychain with file fallback
├── storage.py           # thread-safe encrypted SQLite buffer
├── tray.py              # system tray (pystray)
├── collectors/          # input, window, afk, browser bridge, coalescing
├── platform/            # windows.py, macos.py, linux.py
└── sync/                # api.py (wire models), uploader.py, enroll.py
browser-extension/       # MV3 extension: tab events + pairing UI
scripts/                 # CSV export and HTML telemetry report
tests/                   # pytest suite + mock ingest server
docs/API.md              # ingest, enroll and browser-bridge contracts
```

---

## Tech stack

| Area | Tools |
|---|---|
| Language | Python 3.10+ |
| Data & validation | SQLite (WAL), pydantic v2 |
| Networking & scheduling | httpx, APScheduler |
| Security | cryptography (Fernet), keyring |
| OS integration | pynput, psutil, pystray, pywin32 / pyobjc / python-xlib |
| Browser | Manifest V3 extension (Chrome & Firefox) |
| Testing & CI | pytest, freezegun, FastAPI mock server, ruff, GitHub Actions (Windows + Ubuntu) |
| Packaging | PyInstaller (standalone Windows `.exe`) |

---

## Getting started

### 1. Install

```bash
git clone https://github.com/Suba-kumar09/health-agent.git
cd health-agent
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -e ".[dev,windows]"  # or [dev,macos] / [dev,linux]
```

### 2. Configure

```bash
cp config.example.toml config.toml
```

Key settings in `config.toml`:

| Setting | Default | Meaning |
|---|---|---|
| `agent.capture_mode` | `aggregate` | `aggregate` (counts only) or `detailed` (requires extra consent) |
| `agent.sync_interval_secs` | `5400` | Upload every 90 minutes |
| `agent.bucket_seconds` | `30` | Input aggregation window |
| `retention.mode` | `delete_after_sync` | or `keep_days` |
| `privacy.encrypt_at_rest` | `true` | Encrypt event payloads |
| `privacy.afk_threshold_secs` | `120` | Idle time before marked AFK |
| `collectors.*` | `true` | Turn individual collectors on or off |

### 3. Run

```bash
# Dry run: logs upload payloads instead of sending them
python -m agent.main --dry-run --data-dir ./demo_run

# Headless (no tray icon)
python -m agent.main --dry-run --data-dir ./demo_run --no-tray
```

On first run you'll be asked for consent (`y`) before any collection starts. Stop with
**Ctrl+C** or from the tray menu.

| Flag | Purpose |
|---|---|
| `--config PATH` | Config file (default `config.toml`) |
| `--data-dir PATH` | Where the local database and secrets fallback live |
| `--dry-run` | Log payloads instead of uploading |
| `--no-tray` | Run without the tray icon |
| `--enable-detailed-consent` | One-time opt-in for `detailed` capture mode, then exit |
| `--enrollment-code CODE` | Exchange a one-time code for a device token |

### 4. Connect the browser extension (optional)

1. Open `chrome://extensions` (or `about:debugging` in Firefox), enable developer mode and
   load the `browser-extension/` folder.
2. Open the extension's options page.
3. Enter the port and 6-digit pairing code shown in the agent's log / tray.

### 5. View your data

```bash
# Self-contained HTML dashboard with summary stats and a timeline
python scripts/generate_telemetry_html.py --data-dir ./demo_run --out telemetry.html

# Decrypted, human-readable CSV
python scripts/export_readable_csv.py --data-dir ./demo_run --out events_readable.csv
```

---

## Testing

```bash
ruff check .
python -m pytest -q
```

The suite covers storage, encryption, secrets, consent, config, every collector, the
uploader's batching/backoff/idempotency, enrollment, and an end-to-end integration test
against a FastAPI mock ingest server. CI runs lint and tests on **Windows and Ubuntu** for
every push and pull request.

## Build a Windows executable

```bash
pyinstaller health-agent.spec
```

---

## API

The full wire contract — `POST /v1/ingest`, `POST /v1/enroll`, and the browser bridge's
`/pair` and `/tab-event` endpoints, including payloads and retry behavior — is documented in
[`docs/API.md`](docs/API.md).

## Roadmap

- [x] Phase 1 — device agent, local encrypted buffer, resumable batched upload, browser extension
- [ ] Ingest server implementing `docs/API.md`
- [ ] Verified macOS and Linux support (Wayland foreground-window detection)
- [ ] Health insights dashboard built on the collected data
