# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Phase 1 of a cross-platform health-monitoring system, in two halves that live in the same repo:

- **`agent/`** — a background end-device agent. It runs on a user's machine, passively
  observes keyboard/mouse intensity, the foreground app/window, and (via a companion browser
  extension) the active browser tab, buffers everything locally in SQLite, and periodically
  batch-uploads it to the ingest server. Offline-first by design: the agent must keep working
  and buffering with no network, and must never lose or duplicate events when connectivity
  returns.
- **`server/`** — the FastAPI ingest server the agent uploads to: device enrollment
  (`/v1/enroll`), event ingest (`/v1/ingest`), Postgres-backed in production (SQLite for
  local dev/CI), migrated via Alembic.
- **Wellbeing messages** (`server/wellbeing.py` + `server/routes/messages.py` +
  `agent/sync/messages.py`) — a background scheduler on the server detects a device's
  continuous-active streaks (no break) from its already-ingested `afk` events, asks a local
  Ollama model for a short "take a break" reminder, and the agent polls it back down and
  shows it as a native OS notification via the tray icon. See the dedicated section below.

Windows is the primary/validated target for the agent. macOS and Linux platform backends
(`agent/platform/macos.py`, `agent/platform/linux.py`) are written per the same interface but
unverified — there is no machine to test them on in this environment.

## Common commands

```powershell
# Activate the venv (already created at .venv)
.venv\Scripts\Activate.ps1

# Install (dev + agent). Add ",server" to also work on server/.
pip install -e ".[dev,windows]"     # Windows
pip install -e ".[dev,server]"      # server/ work (what CI installs for tests)

# Run the full test suite
python -m pytest -q

# Run a single test file / test
python -m pytest tests/test_storage.py -q
python -m pytest tests/test_uploader.py::test_batch_resumes_same_batch_id -q

# Lint (also run in CI)
ruff check .

# Run the agent for real (dry-run = logs upload payloads instead of sending them)
python -m agent.main --dry-run --data-dir ./demo_run --no-tray
# then Ctrl+C to stop; `y` at the first-run consent prompt is required before any collector starts

# One-time explicit consent flow required before capture_mode="detailed" is honored
python -m agent.main --enable-detailed-consent --data-dir ./demo_run

# Build a standalone Windows exe (PyInstaller)
pyinstaller health-agent.spec

# Run the ingest server locally (SQLite auto-created, no Docker needed)
uvicorn server.main:app --reload --port 8001
# ...or, defaults to 0.0.0.0:8001 without needing flags on the command line:
python -m server.main
# ...or:
make run-server

# ...or with Postgres via docker-compose
docker compose up

# Mint a device enrollment code (only way to issue one -- no admin UI in this phase)
python -m server.admin_cli mint-code [--issued-for NAME] [--ttl-hours N]

# Create/apply Alembic migrations against DATABASE_URL
alembic revision --autogenerate -m "message"
alembic upgrade head
```

Wellbeing-message settings are env-driven like everything else in `server/config.py`:
`WELLBEING_ENABLED` (default true), `OLLAMA_URL` (default `http://127.0.0.1:11434`),
`WELLBEING_MODEL` (default `qwen2.5:3b`), `WELLBEING_INTERVAL_SECS` (scheduler tick, default
300), `WELLBEING_BREAK_THRESHOLD_SECS` (continuous-active seconds before a reminder fires,
default 1800). On the agent side, `messages_poll_interval_secs` in `config.toml`'s `[agent]`
section (default 300) controls how often it checks for a new message.

Because collector threads write to the local SQLite buffer, avoid running two `agent.main`
instances against the same `--data-dir` at once (WAL mode tolerates concurrent readers, not
concurrent writer processes).

CI (`.github/workflows/tests.yml`) runs on both `windows-latest` and `ubuntu-latest`: installs
`.[dev,server]`, runs `ruff check .` then `pytest -q`, then (separately) builds the PyInstaller
exe from `.[dev]`.

## Architecture

### Agent data flow

independent collector threads → `Storage` (encrypted SQLite buffer) → `Uploader`
(APScheduler-driven, paced batch drain) → ingest server (`server/`, or `LoggingTransport` from
`agent/main.py` when run with `--dry-run`).

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
  `afk` cannot run if `input_watcher` is disabled. `_poll_loop` wraps `poll_once()` in
  try/except (mirroring `window_watcher.py`'s loop) — without it, a single unhandled exception
  kills this daemon thread silently forever, with zero crash and zero log line, while every
  other collector keeps running normally. This was a real, hard-to-diagnose live bug: `afk`
  would work for one or two state transitions after a restart, then go permanently dark.
- **`coalescing.py`**: `CoalescingStatePoller` is shared, generic heartbeat logic used by both
  `window_watcher` and `afk`. Consecutive polls with an identical state key extend the current
  event's `duration` via `Storage.extend_duration` instead of inserting a new row; a changed
  state key finalizes the previous event and inserts a new one. `extend_duration` only succeeds
  while the row is `synced=0 AND batch_id IS NULL` — once a batch claims it, the row is frozen.
  `on_extend` returns that success/failure as a bool, and when it's `False` (row got frozen,
  state itself hasn't changed) `poll()` mints a fresh event for the *same* key instead of
  quietly continuing to call `on_extend` on a dead row forever — a real bug found via live
  testing: `afk` in particular can hold one state for a very long time, so without this
  recovery path a device's whole continuous-activity history after the first sync silently
  stops growing (this is what `server/wellbeing.py`'s streak detection depends on being
  accurate). `window_watcher` mostly masked the same underlying bug before this fix, since its
  state (app/title) changes often enough to self-heal via the "state changed" path anyway.
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
`EnrollRequest`, `EnrollResponse`) — these *are* the wire contract. `server/schemas.py` imports
these same classes directly rather than redefining them, so client and server structurally
cannot drift; still update `docs/API.md` if the shape changes, since it's the human-readable
source of truth for both this contract and the browser bridge's `/pair` + `/tab-event` contract.

`uploader.py`'s `Uploader.run_tick()` is the core loop, called on an APScheduler interval from
`main.py`. Idempotency is the central design constraint: `_next_batch()` always checks
`storage.pending_batch_ids()` (batches already assigned an id but not yet confirmed synced)
*before* minting a new batch, and retries that exact batch_id/event_id set. This is what makes
a crash between "server accepted" and "client marked synced" safe — the server sees the same
batch_id/event_ids again and should return them in the response's `duplicates` list, which
`run_tick()` treats the same as `accepted` for the purpose of marking rows synced locally.
Backoff (`BackoffState`) is exponential but a server-supplied `Retry-After` (on 429) always
takes precedence over the computed curve.

`enroll.py` implements the client side of `/v1/enroll` (see `docs/API.md` and `server/routes/enroll.py`).

### Tray (`agent/tray.py`)

`pystray`-based; pause/resume/stop call back into the same `collectors` list `main.py` built,
plus a `capture_mode` indicator (icon color: green=aggregate, orange=detailed, gray=paused).
This is the actual mechanism satisfying the "visible pause/stop" requirement — don't treat it
as optional UI chrome.

### Browser extension (`browser-extension/`)

MV3, dual Chrome/Firefox support via `browser_specific_settings.gecko` in `manifest.json` (uses
the `chrome.*` namespace, which Firefox also implements under MV3). `options.js` is the pairing
UI: takes the port + 6-digit code shown in the agent's log, or reissued on demand via the tray's
"Pair browser extension..." menu item ("Unpair" clears the stored token), POSTs to `/pair`,
stores the returned token.
`background.js` listens on `chrome.tabs.onActivated`/`onUpdated` and POSTs `{url, title, ts}` to
`/tab-event` with the stored bearer token.

### Server (`server/`)

`server/main.py`'s `create_app()` wires middleware + the `enroll`/`ingest` routers; production
entrypoint is `uvicorn server.main:app` (see `Dockerfile`). Settings (`server/config.py`) are
entirely env-driven (`DATABASE_URL`, `MAX_REQUEST_BYTES`, `RATE_LIMIT_*`,
`ENROLLMENT_CODE_TTL_HOURS`) so the same code runs unmodified in CI (SQLite), docker-compose
(Postgres via `db` service), and the real deployment.

- **`db.py`**: Postgres is the schema of record — `server/alembic/` migrations own it exclusively.
  Against SQLite, `create_app()` instead calls `Base.metadata.create_all()` directly (dev/test
  convenience only). `insert_ignore_conflict()` is a dialect-aware `ON CONFLICT DO NOTHING`
  helper (Postgres vs. SQLite `insert()` variants) — this is what makes `/v1/ingest` idempotent
  server-side, matching the client's retry-safe batch design in `agent/sync/uploader.py`.
- **`models.py`**: all timestamps are Unix epoch floats, not SQL `DateTime` — deliberately
  matches the client-side convention (`agent/storage.py`'s `ts`) and sidesteps a real
  cross-dialect trap where `DateTime(timezone=True)` round-trips as naive on SQLite but
  tz-aware on Postgres.
- **`auth.py`**: device tokens are random (`secrets.token_urlsafe(32)`), only their sha256 hash
  is ever persisted; the plaintext is returned exactly once, at enrollment. `enroll_device()`
  and `ratelimit.check_and_increment()` both use `SELECT ... FOR UPDATE` (`with_for_update()`)
  to close a TOCTOU race between two concurrent requests reading the same row before either
  commits — mirror this pattern for any new check-then-write logic here.
- **`ratelimit.py`**: per-device fixed-window limiting, counters stored in Postgres/SQLite
  (not Redis/in-process) so it stays correct if the web service scales to multiple instances.
- **`middleware.py`**: `GzipAndSizeLimitMiddleware` enforces a real 413 on oversized bodies,
  checked via `Content-Length` before any body is read, and separately guards against a gzip
  bomb by decompressing in a bounded, streaming loop rather than one unbounded
  `gzip.decompress()` call — a small compressed payload can still expand past the cap.
- **`admin_cli.py`**: `python -m server.admin_cli mint-code` is the *only* way to issue a device
  enrollment code in this phase — there is no dashboard or user-account system.
- **`schemas.py`**: re-exports `agent.sync.api`'s pydantic models rather than redefining them
  (see Sync section above).

### Wellbeing messages (`server/wellbeing.py`, `server/routes/messages.py`, `agent/sync/messages.py`)

Server-driven, agent-delivered: the server decides when a device needs a break reminder and
generates the text; the agent's job is only to poll for and display whatever it's handed.

- **`continuous_active_streak()`** (`server/wellbeing.py`) sums a device's `afk` events
  backward from the most recent one until it hits a `state="afk"` row, or a gap of more than
  `_STREAK_GAP_BREAK_SECS` (600s) between two consecutive `state="active"` rows — a gap that
  large almost always means the agent simply wasn't running (device off/asleep/restarted), not
  that someone worked continuously across it. Without this second check, a device whose `afk`
  history has no genuine idle row yet (e.g. only run in short bursts across separate days)
  would read as one streak spanning however many days back its history goes.
- **`generate_for_device()`** only calls the LLM once a streak crosses
  `WELLBEING_BREAK_THRESHOLD_SECS`, and only once per streak — it compares the streak's start
  timestamp against the device's most-recently-generated `Message.created_at` and skips if a
  message already covers this streak. This is also why the gap-break check above matters: a
  `streak_start_ts` that never advances (because nothing ever broke the "streak") permanently
  suppresses all future messages for that device once any message has ever been sent.
- The prompt (`_PROMPT_TEMPLATE`) explicitly asks for one concrete, actionable sentence naming
  the real minutes worked — an earlier version asked for generic encouragement and produced
  vague praise instead of something someone would actually act on.
- **`run_wellbeing_tick()`** (`server/main.py`) iterates every enrolled `Device` each tick with
  a per-device try/except — a slow/unreachable LLM or one bad device must not block the tick
  for the rest. Scheduled via a `BackgroundScheduler` started in `create_app()`'s `lifespan`,
  guarded by `WELLBEING_ENABLED`. It deliberately does not run during `pytest` — the
  `tests/server/conftest.py` fixtures build `TestClient(app)` without a `with` block, which
  never triggers ASGI lifespan — so the test suite has no Ollama dependency.
- **`GET /v1/messages/pending`** (`server/routes/messages.py`) uses the same
  `resolve_device_dependency` auth as `/v1/ingest` (factored into `server/auth.py` so the two
  routes can't drift on bearer-token handling) and marks returned messages delivered in the
  same request — at-most-once, not durable-retry like ingest, since a missed notification is a
  UX gap, not a correctness bug.
- **`agent/sync/messages.py`**'s `MessagesPoller` mirrors `Uploader`'s
  `http_client`/`token_provider` wiring but has no batching/backoff of its own. Delivered text
  reaches the screen via `TrayController.show_message()` (`agent/tray.py`), which reuses the
  same `pystray` `icon.notify()` mechanism already used for the browser-bridge pairing-code
  notification — falls back to a log line if there's no tray (`--no-tray`) or the backend
  doesn't support `notify()`.

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
- `tests/server/` covers the FastAPI app directly (via `conftest.py` fixtures) rather than
  through `mock_server.py`, which exists for the *client*-side (`Uploader`) tests instead.
- `tests/server/test_wellbeing.py` monkeypatches `server.wellbeing.call_llm` rather than
  hitting a real Ollama instance — keep new wellbeing tests off the network the same way.

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
  for the browser bridge's `/pair` + `/tab-event` contract — update it alongside
  `agent/sync/api.py` (server/schemas.py just re-exports it, see above) or
  `agent/collectors/browser_bridge.py` if either payload shape changes.
- `enroll_device()` and `ratelimit.check_and_increment()` both rely on `with_for_update()` row
  locks to close a TOCTOU race between concurrent requests — don't remove these under the
  assumption a single `SELECT` then `UPDATE` is equivalent.
- `agent/main.py`'s shutdown sequence calls `scheduler.shutdown(wait=True)`, not `wait=False`,
  before `storage.close()`. With `wait=False`, a `Uploader.run_tick()` still mid-flight (e.g.
  blocked in an HTTP call to an unreachable server) can resume *after* `storage.close()` has
  already run and crash with `sqlite3.ProgrammingError: Cannot operate on a closed database`.
  Found via live testing, not a hypothetical — this was intermittently killing agent shutdown.
- `server/wellbeing.py`'s per-device "already notified for this streak" check compares against
  `streak_start_ts`, which only advances when `continuous_active_streak()` actually finds a
  break (a real `afk` row, or a >600s gap). Don't change the renotify check to compare against
  something that doesn't track a genuine streak boundary, or a device can get permanently stuck
  never receiving another message after its first one (see the Wellbeing messages section).
