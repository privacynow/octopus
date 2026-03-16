# Registry Service API

Code-based reference for the HTTP routes exposed by
[app/registry_service/app.py](/Users/tinker/output/bots/telegram-agent-bot/app/registry_service/app.py).

This document is intentionally derived from the current handlers and shared
wire types in:
- [app/registry_service/app.py](/Users/tinker/output/bots/telegram-agent-bot/app/registry_service/app.py)
- [app/agents/client.py](/Users/tinker/output/bots/telegram-agent-bot/app/agents/client.py)
- [app/agents/types.py](/Users/tinker/output/bots/telegram-agent-bot/app/agents/types.py)
- [app/registry_service/store_base.py](/Users/tinker/output/bots/telegram-agent-bot/app/registry_service/store_base.py)

It covers every HTTP route currently implemented by the registry service:
- health
- agent runtime endpoints
- bearer-authenticated JSON UI endpoints
- browser/session routes

## Base URL

Examples below assume a registry running on:

```text
http://localhost:8787
```

## Authentication

### No auth

- `GET /healthz`

### Agent bearer auth

Used by the bot runtime / registry client for most `/v1/agents/*` routes.

```http
Authorization: Bearer <agent_token>
```

The token is issued by `POST /v1/agents/enroll` and then used by:
- register
- heartbeat
- timeline publish
- conversation binding
- discovery search
- routed-task submission
- poll
- ack
- routed-task status/result updates
- deregister

### Enrollment token

`POST /v1/agents/enroll` does **not** use the bearer header. It expects the
enrollment token in the JSON body:

```json
{
  "enrollment_token": "…",
  "agent_card": { ... }
}
```

If the token is wrong, the handler returns:
- `401 {"detail": "Invalid enrollment token"}`

### UI bearer auth

Used by all `/v1/ui/*` JSON routes.

```http
Authorization: Bearer <REGISTRY_UI_TOKEN>
```

Behavior comes directly from `require_ui_token()`:
- if `REGISTRY_UI_TOKEN` is unset, UI bearer auth is bypassed
- if it is set and the bearer token is missing or wrong, the handler returns:
  - `401 {"detail": "Invalid UI token"}`

### Browser session auth

Used by:
- `GET /ui`
- `GET /ui/login`
- `POST /ui/login`
- `GET /ui/logout`

The HTML UI uses `SessionMiddleware` with the `registry_session` cookie.
If `REGISTRY_UI_TOKEN` is unset, the UI is effectively unauthenticated and
`/ui/login` redirects straight to `/ui`.

## Shared JSON Shapes

These are the main wire objects exposed by current code.

### Agent Card

Current runtime clients send this shape via [app/agents/types.py](/Users/tinker/output/bots/telegram-agent-bot/app/agents/types.py):

```json
{
  "agent_id": "",
  "display_name": "Build Bot",
  "slug": "build-bot",
  "role": "developer",
  "skills": ["python", "tests"],
  "tags": ["backend"],
  "description": "Builds and validates code",
  "provider": "codex",
  "mode": "registry",
  "connectivity_state": "connected",
  "current_capacity": 0,
  "max_capacity": 2,
  "surface_capabilities": ["telegram", "registry"],
  "version": "test"
}
```

### Agent Object

Returned by registry store methods such as `register()`, `list_agents()`, and
discovery search:

```json
{
  "agent_id": "abc123",
  "display_name": "Build Bot",
  "slug": "build-bot",
  "role": "developer",
  "skills": ["python", "tests"],
  "tags": ["backend"],
  "description": "Builds and validates code",
  "provider": "codex",
  "mode": "registry",
  "connectivity_state": "connected",
  "current_capacity": 0,
  "max_capacity": 2,
  "surface_capabilities": ["telegram", "registry"],
  "version": "test",
  "last_heartbeat_at": "2026-03-16T18:42:10+00:00",
  "updated_at": "2026-03-16T18:42:10+00:00"
}
```

### Timeline Event

Current runtime clients send this shape from `TimelineEvent`:

```json
{
  "event_id": "evt-1",
  "conversation_id": "conv-1",
  "kind": "progress",
  "title": "Working",
  "body": "Doing the work",
  "status": "",
  "progress": null,
  "metadata": {},
  "created_at": "2026-03-16T18:42:10+00:00"
}
```

### Routed Task Request

Current runtime clients send this shape from `RoutedTaskRequest`:

```json
{
  "routed_task_id": "task-1",
  "parent_conversation_id": "conv-1",
  "origin_agent_id": "origin-agent",
  "target_agent_id": "target-agent",
  "title": "Review task",
  "instructions": "Review the spec",
  "context": {},
  "constraints": {},
  "requested_capabilities": ["reviewer"],
  "priority": "normal",
  "created_at": "2026-03-16T18:42:10+00:00"
}
```

### Delivery Item

Returned by `GET /v1/agents/poll`:

```json
{
  "cursor": "12",
  "delivery_id": "d1",
  "kind": "surface_input",
  "payload": {
    "conversation_id": "conv-1",
    "text": "hello",
    "surface": "registry"
  },
  "state": "leased",
  "created_at": "2026-03-16T18:42:10+00:00"
}
```

### Conversation Summary

Returned by `GET /v1/ui/conversations` and inside `ui_bootstrap()`:

```json
{
  "conversation_id": "conv-1",
  "target_agent_id": "agent-1",
  "target_display_name": "Build Bot",
  "title": "Nightly report",
  "status": "running",
  "created_at": "2026-03-16T18:42:10+00:00",
  "updated_at": "2026-03-16T18:43:10+00:00",
  "timeline_event_count": 3
}
```

### Conversation Detail

Returned by `GET /v1/ui/conversations/{conversation_id}` and by
`POST /v1/ui/conversations`:

```json
{
  "conversation_id": "conv-1",
  "target_agent_id": "agent-1",
  "target_display_name": "Build Bot",
  "title": "Nightly report",
  "status": "open",
  "created_at": "2026-03-16T18:42:10+00:00",
  "updated_at": "2026-03-16T18:42:10+00:00",
  "timeline_event_count": 1,
  "linked_routed_tasks": []
}
```

### Skill Record

Returned by `GET /v1/ui/skills`:

```json
{
  "skill_name": "web_search",
  "declared_by_agents": ["alpha-bot", "beta-bot"],
  "enabled": null
}
```

`enabled` meanings:
- `null`: no override row, default enabled
- `true`: explicitly enabled override
- `false`: explicitly disabled override

### Routed Task Summary

Returned by `GET /v1/ui/tasks` and embedded in conversation detail:

```json
{
  "routed_task_id": "task-1",
  "parent_conversation_id": "conv-1",
  "origin_agent_id": "origin-agent",
  "origin_display_name": "Planner Bot",
  "target_agent_id": "target-agent",
  "target_display_name": "Worker Bot",
  "title": "Review task",
  "status": "queued",
  "summary": "",
  "created_at": "2026-03-16T18:42:10+00:00",
  "updated_at": "2026-03-16T18:42:10+00:00"
}
```

## Health

### `GET /healthz`

No auth.

Response:

```json
{
  "ok": true,
  "bots": 3
}
```

## Agent Runtime API

These routes are used by the bot runtime via
[app/agents/client.py](/Users/tinker/output/bots/telegram-agent-bot/app/agents/client.py).

### `POST /v1/agents/enroll`

Auth:
- body `enrollment_token`
- no bearer header

Request:

```json
{
  "enrollment_token": "enroll-secret",
  "agent_card": { "...Agent Card..." }
}
```

Response:

```json
{
  "agent_id": "abc123",
  "slug": "build-bot",
  "agent_token": "secret-token",
  "poll_cursor": "0"
}
```

Errors:
- `401` invalid enrollment token

### `POST /v1/agents/register`

Auth:
- agent bearer token

Request:

```json
{
  "agent_card": { "...Agent Card..." },
  "connectivity_state": "connected",
  "current_capacity": 0,
  "max_capacity": 2
}
```

Response:
- full Agent Object

Errors:
- `401` unknown or invalid agent token

### `POST /v1/agents/heartbeat`

Auth:
- agent bearer token

Request:

```json
{
  "connectivity_state": "connected",
  "current_capacity": 0,
  "max_capacity": 2,
  "active_work_count": 0,
  "timeline_checkpoint": ""
}
```

Only `connectivity_state`, `current_capacity`, and `max_capacity` are consumed
by the current handler/store path. Extra fields are accepted and ignored.

Response:

```json
{
  "agent": { "...Agent Object..." },
  "server_time": "2026-03-16T18:42:10+00:00"
}
```

Errors:
- `401` unknown or invalid agent token

### `POST /v1/agents/timeline`

Auth:
- agent bearer token

Request:

```json
{
  "events": [{ "...Timeline Event..." }],
  "checkpoint": ""
}
```

Only `events` is consumed by the current handler. `checkpoint` is accepted and ignored.

Response:

```json
{
  "accepted": 1
}
```

Errors:
- `401` unknown token, unknown conversation, or publishing to a conversation owned by another agent

### `POST /v1/agents/conversations/bind`

Auth:
- agent bearer token

Request:

```json
{
  "conversation_id": "telegram:bot:123",
  "title": "Telegram chat 123",
  "origin_surface": "telegram",
  "external_id": "123"
}
```

`external_id` is accepted by the client and tests but is not currently consumed by the handler/store path.

Response:
- Conversation Detail object

Errors:
- `401` unknown or invalid agent token

### `POST /v1/agents/discovery/search`

Auth:
- agent bearer token

Request:

```json
{
  "role": "",
  "skills": [],
  "tags": [],
  "free_text": "",
  "exclude_agent_ids": [],
  "required_state": "connected"
}
```

Response:

```json
{
  "agents": [{ "...Agent Object..." }]
}
```

Notes:
- the handler heartbeats the caller with `connectivity_state="connected"` before searching
- disabled skills are filtered inside the registry store

Errors:
- `401` unknown or invalid agent token

### `POST /v1/agents/routed-tasks`

Auth:
- agent bearer token

Request:
- Routed Task Request JSON
- current code also honors an optional top-level `skill` field for disabled-skill enforcement

Response:

```json
{
  "routed_task_id": "task-1",
  "delivery_id": "delivery-1"
}
```

Errors:
- `401` unknown or invalid agent token
- `409 {"detail": "skill_disabled"}` when the requested skill is globally disabled

### `GET /v1/agents/poll`

Auth:
- agent bearer token

Query parameters:
- `cursor` string, default `"0"`
- `limit` integer, default `20`, range `1..100`
- `wait_seconds` integer, default `1`, range `0..30`

Note:
- the current handler accepts `wait_seconds` but explicitly ignores it

Response:

```json
{
  "deliveries": [{ "...Delivery Item..." }],
  "next_cursor": "12"
}
```

Errors:
- `401` unknown or invalid agent token

### `POST /v1/agents/ack`

Auth:
- agent bearer token

Request:

```json
{
  "delivery_ids": ["d1", "d2"],
  "classification": "accepted"
}
```

Recognized classifications in current code:
- `accepted`
- `rejected`
- `retry_later`

Anything else falls back to queued behavior.

Response:

```json
{
  "updated": 2,
  "classification": "accepted"
}
```

Errors:
- `401` unknown or invalid agent token

### `POST /v1/agents/routed-tasks/{routed_task_id}/status`

Auth:
- agent bearer token

Request:

```json
{
  "status": "running",
  "summary": "Started work",
  "timeline_events": [{ "...Timeline Event..." }],
  "progress": 50,
  "updated_at": "2026-03-16T18:42:10+00:00"
}
```

Current store behavior consumes:
- `status`
- `summary`
- `timeline_events`

Extra fields such as `progress` and `updated_at` are accepted by the route and ignored by the store update path.

Response:

```json
{
  "routed_task_id": "task-1",
  "status": "running"
}
```

Errors:
- `401` unknown or invalid agent token

### `POST /v1/agents/routed-tasks/{routed_task_id}/result`

Auth:
- agent bearer token

Request:

```json
{
  "routed_task_id": "task-1",
  "status": "completed",
  "summary": "Finished",
  "full_text": "…",
  "artifacts": [],
  "follow_up_questions": [],
  "completed_at": "2026-03-16T18:42:10+00:00"
}
```

Response:

```json
{
  "routed_task_id": "task-1",
  "status": "completed"
}
```

Errors:
- `401` unknown or invalid agent token
- `404 {"detail": "Unknown routed task: <id>"}` when the task ID is unknown

### `POST /v1/agents/deregister`

Auth:
- agent bearer token

Request:
- empty JSON object is typical, but the handler ignores the body

Response:

```json
{
  "agent_id": "abc123",
  "connectivity_state": "offline"
}
```

Errors:
- `401` unknown or invalid agent token

## JSON UI API

These routes all use UI bearer auth via `REGISTRY_UI_TOKEN`.

### `GET /v1/ui/bootstrap`

Response:

```json
{
  "bots": [{ "...Agent Object..." }],
  "conversations": [{ "...Conversation Summary..." }],
  "tasks": [{ "...Routed Task Summary..." }]
}
```

### `GET /v1/ui/bots`

Response:

```json
{
  "bots": [{ "...Agent Object..." }]
}
```

### `GET /v1/ui/conversations`

Response:

```json
{
  "conversations": [{ "...Conversation Summary..." }]
}
```

### `GET /v1/ui/search`

Query parameters:
- `q` string, default `""`
- `limit` integer, default `20`

Behavior:
- if `q.strip()` is shorter than 3 characters, returns `{"results": []}`
- `limit` is clamped to at most `100`

Response:

```json
{
  "results": [
    {
      "conversation_id": "conv-1",
      "snippet": "the <b>quick</b> brown fox"
    }
  ]
}
```

### `GET /v1/ui/skills`

Response:
- array of Skill Record objects

### `POST /v1/ui/skills/{skill_name}/enable`

Response:

```json
{
  "skill_name": "web_search",
  "enabled": true
}
```

### `POST /v1/ui/skills/{skill_name}/disable`

Response:

```json
{
  "skill_name": "web_search",
  "enabled": false
}
```

### `POST /v1/ui/conversations`

This is both the Registry UI’s conversation-creation endpoint and the
programmatic trigger API.

Request validation is handled by a Pydantic model in the route.

Request:

```json
{
  "target_agent_id": "abc123",
  "title": "Nightly report",
  "message_text": "Run the nightly report"
}
```

Rules:
- `target_agent_id`: required, non-empty
- `message_text`: required, non-empty
- `title`: optional, defaults to `""`

Response:
- `201 Created`
- Conversation Detail object

Errors:
- `401` missing or invalid UI bearer token
- `404 {"detail": "Unknown agent: <id>"}` when no listed agent matches `target_agent_id`
- `422` validation failure for missing/invalid fields

Example:

```bash
curl -X POST http://localhost:8787/v1/ui/conversations \
  -H "Authorization: Bearer $REGISTRY_UI_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "target_agent_id": "abc123",
    "title": "Nightly report",
    "message_text": "Run the nightly report"
  }'
```

### `GET /v1/ui/conversations/{conversation_id}`

Response:
- Conversation Detail object

Errors:
- `404 {"detail": "Unknown conversation: <id>"}`

### `GET /v1/ui/conversations/{conversation_id}/timeline`

Response:

```json
{
  "events": [{ "...Timeline Event..." }]
}
```

Note:
- timeline items returned from the store include:
  - `event_id`
  - `conversation_id`
  - `routed_task_id`
  - `agent_id`
  - `kind`
  - `title`
  - `body`
  - `status`
  - `progress`
  - `metadata`
  - `created_at`

### `GET /v1/ui/conversations/{conversation_id}/export`

Response:
- `text/markdown`
- `Content-Disposition: attachment; filename="conversation-<id>.md"`

Errors:
- `404 {"detail": "Conversation not found"}`

### `POST /v1/ui/conversations/{conversation_id}/messages`

Request:

```json
{
  "text": "Follow up message"
}
```

Response:

```json
{
  "conversation_id": "conv-1",
  "accepted": true
}
```

Important current-code note:
- the handler does not currently translate unknown conversation IDs into `404`
- if the store raises `KeyError`, this route currently surfaces that as a server error rather than a structured JSON not-found response

### `POST /v1/ui/conversations/{conversation_id}/actions`

Request:

```json
{
  "action": "approve_delegation",
  "payload": {}
}
```

Response:

```json
{
  "conversation_id": "conv-1",
  "accepted": true
}
```

Important current-code note:
- unknown conversation handling is the same as the `/messages` route above: there is no explicit `404` translation in the current handler

### `POST /v1/ui/conversations/{conversation_id}/cancel`

Request:
- no body required

Response:

```json
{
  "conversation_id": "conv-1",
  "accepted": true
}
```

Important current-code note:
- unknown conversation handling is the same as the `/messages` route above: there is no explicit `404` translation in the current handler

### `GET /v1/ui/tasks`

Response:

```json
{
  "tasks": [{ "...Routed Task Summary..." }]
}
```

## Browser / Session Routes

These routes are HTML/browser-facing rather than JSON API endpoints.

### `GET /ui/login`

Behavior:
- if an authenticated session already exists, redirects to `/ui` with `303`
- if `REGISTRY_UI_TOKEN` is unset, also redirects to `/ui`
- otherwise returns the HTML login page

### `POST /ui/login`

Form fields:
- `password`

Behavior:
- if an authenticated session already exists, redirects to `/ui` with `303`
- if `REGISTRY_UI_TOKEN` is set and the password is wrong, returns the login page HTML with an inline error
- otherwise sets `request.session["ui_authenticated"] = True` and redirects to `/ui` with `303`

### `GET /ui/logout`

Behavior:
- clears the session
- redirects to `/ui/login` with `303`

### `GET /ui`

Behavior:
- if the session is valid, returns the HTML Registry UI shell
- otherwise redirects to `/ui/login` with `302`

## Notes on Stability

Current code has two levels of contract stability:

- **More stable, externally meaningful routes**
  - `GET /healthz`
  - `/v1/agents/*` routes used by `AgentRegistryClient`
  - `POST /v1/ui/conversations`
  - read-oriented `/v1/ui/*` routes used by the Registry UI

- **Less hardened JSON write routes**
  - `POST /v1/ui/conversations/{conversation_id}/messages`
  - `POST /v1/ui/conversations/{conversation_id}/actions`
  - `POST /v1/ui/conversations/{conversation_id}/cancel`

Those write routes work and are used by the UI, but they still accept raw dict
payloads and do not yet normalize all not-found errors into structured `404`
responses.
