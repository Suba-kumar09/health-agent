# Ingest API contract

Phase 1 scope: the agent implements the client side of this contract in full
(`agent/sync/uploader.py`, `agent/sync/api.py`, `agent/sync/enroll.py`).
The server side is out of scope for Phase 1 -- this document is what a later
phase's ingest service needs to implement to be compatible.

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

## POST /v1/enroll (contract only, server deferred)

```
Body:    {"enrollment_code": "...", "device_name": "...", "os": "...", "os_version": "..."}
Response 200: {"device_id": "...", "device_token": "..."}
```

Client implementation: `agent.sync.enroll.enroll()`. The returned
`device_token` is persisted via `agent.secrets.SecretStore` (OS keychain,
with an encrypted-file fallback when no keychain backend is available).

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
