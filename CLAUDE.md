# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An employee wellbeing/activity system with three parts:

- **Agent** (`agent/`) — runs in the background on each employee's machine, passively observes
  keyboard/mouse intensity, the foreground app/window, workstation lock state, and (via a
  companion browser extension) the active browser tab, buffers everything locally in SQLite,
  batch-uploads it to the server, and shows the server's wellbeing reminders as popups.
  Offline-first by design: it must keep working and buffering with no network, and must never
  lose or duplicate events when connectivity returns.
- **Server** (`server/`) — FastAPI + SQLAlchemy. Ingests events, enrolls devices, generates
  LLM-written reminders (break / idle / distraction), and serves the dashboard API with
  per-employee login.
- **Dashboard** (`dashboard/`) — React + TypeScript + Vite. Admins see the whole organization;
  employees see only their own day.

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

# Lint (ruff, configured in pyproject.toml; CI runs `ruff check .` and `pytest -q`)
python -m ruff check .

# One-time explicit consent flow required before capture_mode="detailed" is honored
python -m agent.main --enable-detailed-consent --data-dir ./demo_run

# Build a standalone Windows exe (PyInstaller)
pyinstaller health-agent.spec

# Dashboard: type-check + production build (run inside dashboard/)
npm run build
```

Server and agent commands run from the repo root; only the `npm` commands run inside `dashboard/`.

Because collector threads write to the local SQLite buffer, avoid running two `agent.main`
instances against the same `--data-dir` at once (WAL mode tolerates concurrent readers, not
concurrent writer processes).

### Running the app (server + dashboard + agent)

Three independent long-running processes, each in its own terminal:

```powershell
# 1. Backend (FastAPI ingest server + dashboard API) -- http://127.0.0.1:8001
.venv\Scripts\python.exe -m server.main

# 2. Dashboard frontend (Vite dev server) -- must come up on :5173
cd dashboard
npm run dev

# 3. Agent (real mode -- omit --dry-run/--data-dir to use the default local data dir)
.venv\Scripts\python.exe -m agent.main
```

Or start all three at once with `.\start.ps1` (repo root) — it opens each in its own titled
window, waits 4s after the server before starting the agent so :8001 is bound first, and is
safe to re-run: the server/agent/Vite each refuse to start a second copy.

The dashboard (http://localhost:5173) requires a login. Employees and logins are managed with
`server/admin_cli.py` — there is no sign-up page:

```powershell
.venv\Scripts\python.exe -m server.admin_cli add-employee --name "Name" --system-name PC-NAME
.venv\Scripts\python.exe -m server.admin_cli set-login --system-name PC-NAME --role admin   # prompts for the password
.venv\Scripts\python.exe -m server.admin_cli list-employees
```

An employee's `system_name` must equal the agent's hostname (`platform.node()`) — it is both
how enrollment matches a machine to an employee and one of the two login names (the other is an
optional email). New logins are `employee` role unless `--role admin` is given.

## Architecture

**Data flow:** independent collector threads → `Storage` (encrypted SQLite buffer) →
`Uploader` (APScheduler-driven, paced batch drain) → server `POST /v1/ingest` → server
orchestrator writes reminder `Message` rows → agent's `MessagesPoller` fetches, shows, and acks
them → dashboard reads everything through `/v1/me/*` and `/v1/admin/*`. (`--dry-run` swaps in
`LoggingTransport` from `agent/main.py` instead of a real server.)

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
- **`afk.py`**: derives active/idle from `input_watcher`'s `aggregator.last_activity_ts`
  (passed in as a callback from `main.py`, not a shared object) — `afk` cannot run if
  `input_watcher` is disabled. It also reports `state="locked"` when the workstation is locked
  (`is_workstation_locked()` in `agent/platform/*`), so the dashboard can tell "away" from "idle".
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

Wraps the OS keychain (via `keyring`) for `data_encryption_key`, `local_device_id`,
`device_token` (from enrollment), and `browser_bridge_token`, service name `"health-agent"`.
The keychain is per-OS-user, not per-folder: every checkout/worktree on the same machine shares
the same `device_token`, and enrollment is skipped when one already exists — a stale token from
another database means every request 401s until the keychain entry is deleted and the agent
re-enrolls. Falls back to a 0600-permissioned file
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
`EnrollRequest`, `EnrollResponse`, `PendingMessagesResponse`, `AckMessagesRequest`,
`AckMessagesResponse`) — these *are* the wire contract (the server imports them via
`server/schemas.py` rather than redefining them); keep them in sync with `docs/API.md`.

`messages.py`'s `MessagesPoller` delivers reminders **at-least-once**: it shows each message,
then acks only the ones actually shown (`POST /v1/messages/ack`). A failed popup stays un-acked
and is re-sent on the next poll; a message already shown whose ack failed is re-acked, never
re-shown.

`uploader.py`'s `Uploader.run_tick()` is the core loop, called on an APScheduler interval from
`main.py`. Idempotency is the central design constraint: `_next_batch()` always checks
`storage.pending_batch_ids()` (batches already assigned an id but not yet confirmed synced)
*before* minting a new batch, and retries that exact batch_id/event_id set. This is what makes
a crash between "server accepted" and "client marked synced" safe — the server sees the same
batch_id/event_ids again and should return them in the response's `duplicates` list, which
`run_tick()` treats the same as `accepted` for the purpose of marking rows synced locally.
Backoff (`BackoffState`) is exponential but a server-supplied `Retry-After` (on 429) always
takes precedence over the computed curve.

`enroll.py` implements the client side of `/v1/enroll` (see `docs/API.md`). `main.py` only
tries enrollment once at startup and only when no `device_token` is in the keychain. An
enrollment code that starts with `-` must be passed as `--enrollment-code="-..."`.

### Tray (`agent/tray.py`)

`pystray`-based; pause/resume/stop call back into the same `collectors` list `main.py` built,
plus a `capture_mode` indicator (icon color: green=aggregate, orange=detailed, gray=paused).
This is the actual mechanism satisfying the "visible pause/stop" requirement — don't treat it
as optional UI chrome. `show_message()` shows a reminder as a WinRT toast (falling back to the
tray balloon) and returns whether it was shown — that bool decides the message ack.

## Server (`server/`)

- `main.py` — app factory. On SQLite (local dev) it runs `create_all` plus
  `db.add_missing_sqlite_columns()`, which adds new model columns to an existing
  `server_dev.db`; Postgres schema changes go through Alembic (`server/alembic/versions/`).
  Also starts the orchestrator scheduler (one per machine, guarded by `InstanceLock`).
- `orchestrator.py` — each tick picks at most one reminder per device (priority: distraction >
  idle > break), gated by `policy.py` (cooldown, daily limit, quiet hours) and by "no un-shown
  recent message". Generators: `wellbeing.py` (break), `productivity.py` (idle), `goals.py`
  (distraction, keyword + exempt-keyword match). Text comes from OpenAI (`call_llm`,
  `WELLBEING_MODEL`, default `gpt-4o-mini`).
- `activity.py` — turns raw `afk` / `window_watcher` / `browser_bridge` events into dashboard
  segments (active / distraction / idle / locked), each with the windows on screen. Rows last
  until the next row unless the gap shows the agent was off; idle pauses under 2 min between
  activity count as working; a distraction shorter than 20 s stays active. Titles are cleaned
  (browser/app suffixes, tab counters, status glyphs).
- `dashboard_auth.py` + `routes/auth.py` — people login (separate from device auth in
  `auth.py`): PBKDF2 password hashes, bearer session tokens stored only as sha256 in
  `DashboardSession`, 5-failures-per-5-min login throttle. `current_employee` / `require_admin`
  are the dependencies.
- `routes/dashboard.py` (`/v1/me/*`, the signed-in employee's own data only) and
  `routes/admin.py` (`/v1/admin/*`, admin role only); shared shapes in `dashboard_views.py`.
- Settings are env vars read in `config.py` (a local `.env` is loaded automatically), e.g.
  `ADMIN_SHOW_WINDOW_TITLES` (hide titles from admins), `WORKDAY_HOURS` (default 8),
  `DASHBOARD_SESSION_TTL_HOURS`, the `*_THRESHOLD_SECS` and `POLICY_*` reminder settings.
- `admin_cli.py` — mint enrollment codes, add employees, set logins/roles.

## Dashboard (`dashboard/`)

React 19 + TypeScript + Vite 8 + React Router, plain CSS (`src/theme.css`, light/dark tokens),
charts hand-built in SVG/CSS (no chart library). Vite proxies `/v1` to `http://127.0.0.1:8001`
and runs with `strictPort` on 5173 (the server's CORS allow-list). Pages: `LoginPage`,
`AdminPage` (admins only; non-admins are redirected to `/me`), `MePage`. The session token is
kept in `localStorage`; any 401 sends the user back to login.

### Browser extension (`browser-extension/`)

MV3, dual Chrome/Firefox support via `browser_specific_settings.gecko` in `manifest.json` (uses
the `chrome.*` namespace, which Firefox also implements under MV3). `options.js` is the pairing
UI: takes the port + 6-digit code shown in the agent's log/tray, POSTs to `/pair`, stores the
returned token. `background.js` listens on `chrome.tabs.onActivated`/`onUpdated` and POSTs
`{url, title, ts}` to `/tab-event` with the stored bearer token.

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
- Server tests live in `tests/server/` and use the `client` / `db_session` fixtures from
  `tests/server/conftest.py` (a temp-file SQLite DB). Tests that create login passwords use
  `hash_password(..., iterations=1000)` to stay fast.

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
- `docs/API.md` is the source of truth for the device wire contracts (`/v1/ingest`,
  `/v1/enroll`, `/v1/messages/*`), the dashboard API, and the browser bridge's `/pair` +
  `/tab-event` contract — update it alongside `agent/sync/api.py`, the server routes, or
  `agent/collectors/browser_bridge.py` if a payload shape changes.
- Admin-facing data must honor `ADMIN_SHOW_WINDOW_TITLES`: when it is off, `/v1/admin/*` returns
  no window titles, no message labels, and no distraction-message text (which usually quotes the
  title). Employees always see their own titles.
- `agent/single_instance.py`'s `InstanceLock` binds a localhost port (not a lock file) to stop a
  second `agent.main`/`server.main` from running concurrently — deliberately *without*
  `SO_REUSEADDR`, since on Windows that flag lets a second process bind the same port anyway,
  which would silently defeat the guard. If you add another long-running entrypoint that must be
  a singleton, reuse this pattern rather than a lock file.
