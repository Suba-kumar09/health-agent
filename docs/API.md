# Ingest API contract

The agent implements the client side of this contract in full
(`agent/sync/uploader.py`, `agent/sync/api.py`, `agent/sync/enroll.py`). A
reference server implementation now lives in `server/` (FastAPI + Postgres,
see `server/main.py`), covering both endpoints below.

## POST /v1/ingest

```
Headers:
  Authorization: Bearer <device_token>
  Idempotency-Key: <batch_id>
  Content-Encoding: gzip            (optional; agent sends gzip by default)
  Content-Type: application/json

Body:
{
  "device_id": "...",
  "agent_version": "0.1.0",
  "os": "Windows",
  "os_version": "11",
  "batch_id": "<uuid>",
  "sent_at": 1732000000.0,
  "events": [
    {
      "event_id": "<uuid>",
      "collector": "input_watcher" | "window_watcher" | "afk" | "browser_bridge",
      "ts": 1732000000.0,
      "duration": 30.0,
      "data": { ... collector-specific, see below ... }
    }
  ]
}
```

### Responses

| Status | Body | Client behavior |
|---|---|---|
| 200 | `{"accepted": [event_id...], "duplicates": [event_id...]}` | Both lists are marked synced locally; `duplicates` means the server already had that event_id from a prior attempt with the same or a different batch_id -- this is what makes retries safe. |
| 401 | -- | Auth failed. Client backs off (exponential) and does not mark events synced. |
| 413 | -- | Batch too large. Client currently backs off; a future client revision could shrink `batch_max_events`/`batch_max_bytes` in response. |
| 429 | `{"retry_after": <seconds>}` | Client blocks all uploads until `retry_after` elapses (takes precedence over the exponential backoff curve). |

Server implementation: `server/routes/ingest.py`. Dedup is enforced durably
via a unique constraint on `event_id` (`server/db.py`'s
`insert_ignore_conflict`), not just in-memory, so a server restart between
"accepted" and the client marking rows synced is safe. Rate limiting is a
per-device fixed window (`server/ratelimit.py`), and the size limit (413) and
gzip decompression are handled by `server/middleware.py` before the request
reaches the route.

### Idempotency

The client persists `batch_id` on every event row in that batch *before*
sending (see `Storage.assign_batch`), and always retries an in-flight batch
under the same `batch_id`/event_id set rather than minting a new one -- so a
crash between "server accepted" and "client marked synced" just means the
server sees the same batch_id and event_ids again and should return them in
`duplicates`. The server must dedupe on `event_id` (globally unique, UUID),
not just `batch_id`, since a batch's membership is fixed once assigned but
the server has no other way to know a retry is "the same" data.

### Collector `data` payloads

- `input_watcher` (aggregate mode): `{keypress_count, click_count, scroll_count, mouse_dist_px, active_secs}`
  (detailed mode adds `key_codes: [str]`)
- `window_watcher`: `{app, title}` (event `duration` is heartbeat-extended
  while the same window stays foreground; see `agent/collectors/coalescing.py`)
- `afk`: `{state: "active" | "afk"}` (also heartbeat-extended)
- `browser_bridge`: `{url, title}`

## POST /v1/enroll

```
Body:    {"enrollment_code": "...", "device_name": "...", "os": "...", "os_version": "..."}
Response 200: {"device_id": "...", "device_token": "..."}
Response 403: enrollment code missing, already used, or expired
```

Client implementation: `agent.sync.enroll.enroll()`. The returned
`device_token` is persisted via `agent.secrets.SecretStore` (OS keychain,
with an encrypted-file fallback when no keychain backend is available).

Server implementation: `server/routes/enroll.py` + `server/auth.py`.
Enrollment codes are minted out-of-band via `python -m server.admin_cli
mint-code` (there's no dashboard or user-account system in this phase) --
each code is single-use and expires after `ENROLLMENT_CODE_TTL_HOURS`
(default 36h). On success the server stores only a sha256 hash of the
device token, never the plaintext.

## GET /v1/messages/pending

```
Headers: Authorization: Bearer <device_token>
Response 200: {"messages": [{"message_id": "...", "text": "...", "created_at": 1732000000.0}, ...]}
Response 401: -- auth failed
```

LLM-generated wellbeing "intimate messages" (Phase-2 addition), queued server-side and
delivered to the owning device on poll. Server implementation: `server/routes/messages.py`
(auth via the same `resolve_device_dependency` as `/v1/ingest`) + `server/wellbeing.py`
(generation) + `server/main.py`'s `run_wellbeing_tick` (an APScheduler job, same library the
agent uses, started from `create_app()`'s lifespan). Each returned message is marked delivered
in the same request that returns it -- at-most-once, not durable-retry like `/v1/ingest`, since
a missed notification is a UX gap, not a correctness bug.

Client implementation: `agent.sync.messages.MessagesPoller`, polled on an APScheduler interval
(`agent.messages_poll_interval_secs`, default 300s) from `agent/main.py`, same
`token_provider`/`http_client` wiring as `Uploader`. Each message's `text` is handed to
`TrayController.show_message()`, which surfaces it as a native OS notification via
`pystray`'s `icon.notify()` (falls back to a log line with `--no-tray` or on backends that
don't support `notify()`).

Server-side generation (`server/wellbeing.py`): each tick, for every enrolled device,
`continuous_active_streak()` sums that device's `afk` events backward from the most recent one
until it hits a `state="afk"` (idle) row -- this is the device's current unbroken working
streak, in seconds (summed across however many rows it's split into at sync-interval
boundaries; see `agent/collectors/coalescing.py`'s `extend_duration` gate). If that streak is
still `state="afk"` (they're currently idle) or hasn't yet reached `WELLBEING_BREAK_THRESHOLD_SECS`
(default 1800s/30min), nothing happens that tick. Once it crosses the threshold, a message is
generated *once* for that streak (tracked by comparing the streak's start timestamp against the
device's last-sent message) -- the streak has to break (a fresh `afk` idle event) and cross the
threshold again before another message is sent, so it isn't repeated every tick while someone
keeps working. The prompt asks a local Ollama instance (`OLLAMA_URL`, default
`http://127.0.0.1:11434`; `WELLBEING_MODEL`, default `qwen2.5:3b`) for one concrete, actionable
sentence naming the actual minutes worked -- not vague encouragement. An unreachable/slow LLM is
caught and logged, not fatal to the tick. Toggle the whole feature off with
`WELLBEING_ENABLED=false`.

`Message.kind` (`"break"` | `"distraction"`) distinguishes which generator produced a given row
and scopes each generator's own "don't repeat for the same streak" dedup check independently --
a break reminder must never suppress a distraction reminder for the same device, or vice versa.

## GET /goal, POST /goal

Not part of the device wire contract -- a small human-facing HTML form (no device auth), served
by the same FastAPI app, for an employee to record today's goal. Server implementation:
`server/routes/goals.py`.

```
GET /goal            -> HTML form: system name, goal text, hours to complete
POST /goal (form-encoded: system_name, text, hours)
  -> 200 HTML confirmation, on success
  -> 200 HTML error page, if system_name isn't a registered employee machine
     (same `resolve_employee_by_system_name()` lookup used at enrollment, server/auth.py)
```

Submitting a goal inserts a new `Goal` row (`employee_id`, `text`, `deadline_at`, `created_at`);
there's no edit/complete flow yet (MVP scope) -- "current goal" for an employee is just their
latest `Goal` row whose `deadline_at` is still in the future (`server/goals.py`'s
`current_goal()`).

### Distraction reminders (`server/goals.py`)

A second, independent message generator, delivered through the same `GET /v1/messages/pending`
endpoint and agent-side `MessagesPoller`/tray popup as wellbeing messages above -- the agent
needs no changes to support this, it already just displays whatever `text` it's handed.

Each tick (`DISTRACTION_CHECK_INTERVAL_SECS`, default 300s), for every enrolled device,
`continuous_distraction_streak()` sums the device's most recent `window_watcher`/`browser_bridge`
events backward from the latest one, for as long as each event's `title`/`url`/`app` matches a
keyword in `DISTRACTION_KEYWORDS` (default: youtube, netflix, instagram, facebook, twitter,
tiktok, twitch, reddit, hotstar, prime video) -- same walk-backward-and-sum shape (and the same
large-gap-breaks-the-streak rule) as the wellbeing tick's `continuous_active_streak()`.

**A goal is never required** for a distraction reminder to fire -- once the streak crosses
`DISTRACTION_THRESHOLD_SECS` (default 300s) and hasn't already been messaged for *this* streak,
a message always generates:
- if the device's employee has a current goal, the prompt names the distraction, how long, the
  goal text, and minutes remaining to its deadline
- if not, the prompt just names the distraction and how long, with no task/deadline framing

Both branches call the same shared `wellbeing.call_llm(prompt, ollama_url, model)` helper (it
takes an already-built prompt string, not a hardcoded template, precisely so this module and
`server/wellbeing.py` can share it). Toggle the whole feature off with `DISTRACTION_ENABLED=false`.

---

# Browser bridge (agent <-> companion extension)

Not server-facing -- documented here because it's the other "API" a
Phase-1-compatible integration needs to know about. Implemented in
`agent/collectors/browser_bridge.py` + `browser-extension/`.

The agent runs a plain HTTP server bound to `127.0.0.1` on a random port
(logged at startup). Because any open browser tab can `fetch()` a localhost
port, every write path is authenticated -- an Origin allowlist
(`chrome-extension://*`, `moz-extension://*`) is the first filter, and a
paired bearer token is the actual access control.

### POST /pair (one-time, out-of-band code required)

```
Body:    {"code": "<6-digit pairing code, shown in agent log/tray, 5 min TTL, single-use>"}
Response 200: {"token": "<bearer token, persisted by both sides>"}
Response 401: {"error": "invalid_or_expired_code"}
Response 403: {"error": "origin_not_allowed"}
```

### POST /tab-event

```
Headers: Authorization: Bearer <token from /pair>
Body:    {"url": "...", "title": "...", "ts": 1732000000.0}
Response 200: {"ok": true}
Response 401: {"error": "auth_failed"}
Response 403: {"error": "origin_not_allowed"}
```

The extension applies privacy filtering (query-string stripping, a domain denylist,
incognito exclusion, and a whole-bridge on/off toggle -- see `browser-extension/options.html`)
*before* sending, entirely client-side; the agent has no visibility into filtered-out tabs.
It also retries failed sends from a small size-capped local queue and skips sending when the
url+title are unchanged from the last successfully sent event.

### POST /unpair

```
Headers: Authorization: Bearer <current token>
Response 200: {"ok": true}
Response 401: {"error": "auth_failed"}
Response 403: {"error": "origin_not_allowed"}
```

Invalidates the current bearer token (same effect as the tray's "Unpair" menu item) --
requires the current token, so an unauthenticated caller can't force an unpair. After this,
`/tab-event` returns 401 until a new pairing code is issued and the extension re-pairs.
The extension's options page calls this (best-effort) when its own "Unpair" button is
clicked, and always clears its local `bridgePort`/`bridgeToken` regardless of whether the
agent was reachable to confirm it.
