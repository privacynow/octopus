# Integration: Registry HTTP API

[← Manual home](README.md) · [Prev: Telegram](04-product-telegram.md) · [Next: Troubleshooting →](06-troubleshooting.md)

Bots and automation call **`/v1/...`** on the registry with **agent tokens**.
Operators use the same resource API through **session cookies + CSRF** from the
browser or tools that mimic the browser session flow.

## Surface map

![Main API areas](../assets/product/api-surface.svg)

## Implementation

- **Routes:** [`app/channels/registry/http.py`](../../app/channels/registry/http.py)
- **Realtime:** [`app/channels/registry/ws.py`](../../app/channels/registry/ws.py) plus typed envelopes in [`registry_sdk/realtime.py`](../../registry_sdk/realtime.py)
- **UI coverage:** the Registry SPA covers the dashboard summary, agents,
  paginated conversations/tasks, approvals, operator **compose / cancel /
  export** on conversations, capabilities, skills catalog, usage ranges, and
  the **provider guidance** editor. **Not** covered as first-class UI flows:
  full skill **lifecycle** beyond install / uninstall, and conversation-bound
  skill activation.

## API surfaces

- **Agent API** — enroll/register/heartbeat/delivery/task/search flows used by
  bots and processor/runtime code
- **Resource API** — `/v1/summary`, `/v1/agents`, `/v1/conversations`,
  `/v1/tasks`, `/v1/approvals`, `/v1/capabilities`, `/v1/usage`, skill
  catalog, provider guidance
- **Realtime** — `WS /v1/ws` with typed envelopes:
  - `event`
  - `heartbeat`
  - `progress`
  - `invalidate`

Current collection invalidation topics are:

- `summary`
- `agents`
- `conversations`
- `tasks`
- `approvals`
- `usage`

## Skill catalog lifecycle (API)

Draft → submit → approve → publish → install/update/uninstall — all under `/v1/catalog/skills/...`. See code for exact verbs.

## Provider guidance (API)

`/v1/provider-guidance/{provider}/...` — draft and publish flows for operator-tuned prompts; the Registry UI now exposes this surface at **`/ui/guidance`**.

## CSRF and sessions

State-changing **POST** requests from the browser use `/v1/auth/csrf` (see UI network traffic when toggling capabilities).
