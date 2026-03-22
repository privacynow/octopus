# Registry guide

This guide explains **why** you use the registry, **how** `./octopus` fits in, and **how to use the Registry web UI** screen by screen. Terminal flows use the existing SVG assets under `docs/assets/registry/`; **browser** sections use screenshots captured from the current UI (see [Regenerating UI screenshots](#regenerating-ui-screenshots)).

## Contents

1. [When to use registry mode](#when-to-use-registry-mode)
2. [Concepts (read this once)](#concepts-read-this-once)
3. [CLI: lifecycle with `./octopus`](#cli-lifecycle-with-octopus)
4. [Browser: sign in](#browser-sign-in)
5. [Browser: every screen](#browser-every-screen)
6. [What the UI does *not* do yet](#what-the-ui-does-not-do-yet)
7. [Verification & troubleshooting](#verification--troubleshooting)
8. [Regenerating UI screenshots](#regenerating-ui-screenshots)

---

## When to use registry mode

Use registry mode when you want:

- A **browser UI** to inspect enrolled bots, conversations, and coordination state.
- **Routed-task** coordination and **agent discovery** (depending on registry scope).
- **One registry** shared by several bots, or **one bot** connected to **multiple** registries with different scopes.

---

## Concepts (read this once)

| Term | Meaning |
|------|---------|
| **Registry service** | HTTP API + optional Web UI (`/ui`). Bots call `/v1/…` with agent tokens; operators use the browser with `REGISTRY_UI_TOKEN`. |
| **Registry scope** | What a *bot* may do on that connection: `full` (conversations + coordination), `channel` (conversation surfaces only), `coordination` (tasks/discovery/health, no conversation channel). |
| **Operator** | A human using the **Registry UI** (password = `REGISTRY_UI_TOKEN`). |
| **Agent token** | Issued at enroll time; bots use `Authorization: Bearer …` on `/v1/`. |
| **Conversation** | Registry row keyed by `(target_agent_id, origin_channel, external_conversation_ref)`. Events live in the `events` table. |
| **Routed task** | Delegation record from an **origin** bot to a **target** bot, tied to a **parent conversation**. |

**URLs**

- Operator browser (local): `http://localhost:<port>/ui` (port from `./octopus registry` or `.deploy/registry/.env`).
- Bots inside Docker: `http://registry:8787` (same API, no `/ui` required).

---

## CLI: lifecycle with `./octopus`

The following workflows are illustrated with **terminal diagrams** (SVG). They are unchanged in spirit from earlier docs; use them for **add / switch / disconnect** registry connections.

| Step | Topic | Asset |
|------|--------|--------|
| Check status | `./octopus registry` menu | [`01-local-registry-states.svg`](assets/registry/01-local-registry-states.svg) |
| Start local registry | Option `1` | [`02-start-local-registry.svg`](assets/registry/02-start-local-registry.svg) |
| Connect existing bot | Manage bots | [`04-connect-local.svg`](assets/registry/04-connect-local.svg) |
| New bot in registry mode | First-run prompts | [`05-add-bot-local.svg`](assets/registry/05-add-bot-local.svg) |
| Remote registry | HTTPS + enrollment token | [`06-connect-remote.svg`](assets/registry/06-connect-remote.svg) |
| Multiple connections | Add/remove | [`10-manage-registry-connections.svg`](assets/registry/10-manage-registry-connections.svg) |
| Switch local ↔ remote | Requires exactly one connection | [`07-switch-local-remote.svg`](assets/registry/07-switch-local-remote.svg), [`08-switch-remote-local.svg`](assets/registry/08-switch-remote-local.svg) |
| Disconnect | Back to standalone or trim connections | [`09-disconnect-registry.svg`](assets/registry/09-disconnect-registry.svg) |
| Logs / stop | Maintenance menu | [`11-registry-maintenance.svg`](assets/registry/11-registry-maintenance.svg) |

After startup, note:

- **Browser URL** printed by Octopus.
- **`REGISTRY_UI_TOKEN`** in `.deploy/registry/.env` (this is the UI password).
- **Bot URL** `http://registry:8787` for containers.

---

## Browser: sign in

1. Open the printed URL (often `http://localhost:8787/ui` or similar).
2. Sign in with **`REGISTRY_UI_TOKEN`** from `.deploy/registry/.env` — there is no separate username.

![Login](assets/registry/ui/00-login-annotated.png)

---

## Browser: every screen

The UI is a **single-page app**: the sidebar switches views; URLs like `/ui/conversations` load the same shell and are safe to **bookmark or refresh** (the server serves `index.html` for those paths when you are logged in).

### Sidebar (applies to all pages)

| Item | Route | Purpose |
|------|-------|---------|
| **Agents** | `/ui` | All enrolled agents; entry point to agent detail. |
| **Conversations** | `/ui/conversations` | All conversations (search after 3+ characters). |
| **Tasks** | `/ui/tasks` | Routed tasks table; click a row to jump to the **parent conversation**. |
| **Capabilities** | `/ui/capabilities` | Global enable/disable for coordination capabilities (operator). |
| **Skills** | `/ui/skills` | Runtime skill catalog cards (from registry store). |
| **Usage** | `/ui/usage` | Token/cost aggregates when usage metadata exists. |
| **Logout** | `/ui/logout` | Ends operator session. |

### 1. Agents (home)

![Agents](assets/registry/ui/01-agents-annotated.png)

- Each **card** is one enrolled agent; **connectivity** badge reflects last heartbeat path.
- **Click** a card → **Agent detail**.

### 2. Agent detail

![Agent detail](assets/registry/ui/02-agent-detail-annotated.png)

- Shows **identity**, **registry scope**, **capabilities/tags**, **heartbeat**, and optional **worker** rows when reported.
- **“Conversations →”** scopes the conversation list to **this agent** (same data as the global list, filtered).

### 3. Agent conversations

![Agent conversations](assets/registry/ui/03-agent-conversations-annotated.png)

- Lists conversations involving this agent. **Click** a row → **Conversation detail**.

### 4. All conversations

![Conversations](assets/registry/ui/04-conversations-annotated.png)

- **Search bar**: type **three or more** characters to filter (debounced).
- Click a **row** → **Conversation detail**.

### 5. Conversation detail (timeline)

![Conversation detail](assets/registry/ui/05-conversation-detail-annotated.png)

- **Header**: title, target display name, `origin_channel` (e.g. `registry-ui`, `telegram`), status badge.
- **Timeline**:
  - `message.user` / `message.bot` render as **chat bubbles**.
  - Other event kinds render as **collapsible cards** (kind label + metadata JSON).
- **Live updates**: the page subscribes to WebSocket topics when the server exposes `/v1/ws` (see [limitations](#what-the-ui-does-not-do-yet)).

### 6. Tasks (routed tasks)

![Tasks](assets/registry/ui/06-tasks-annotated.png)

- Shows **title, origin, target, status, last update**.
- **Clicking a row** navigates to the **parent conversation** (delegation context).

### 7. Capabilities

![Capabilities](assets/registry/ui/07-capabilities-annotated.png)

- Operator-only **global toggles** for coordination features.
- Mutations use **POST** with **CSRF** when using cookie sessions (`/v1/auth/csrf`).

### 8. Skills

![Skills](assets/registry/ui/08-skills-annotated.png)

- High-level **catalog** view (installed/custom skills as returned by `/v1/catalog/skills`).

### 9. Usage

![Usage](assets/registry/ui/09-usage-annotated.png)

- Aggregated **prompt/completion tokens and cost** by conversation when the store has usage rows.

---

## What the UI does *not* do yet

Be explicit so expectations match the code:

| Area | Notes |
|------|--------|
| **Send message / approval / export from the timeline** | The REST API exposes `POST …/messages`, `POST …/actions`, `GET …/export`, but the **current** `conversation-detail` view is **read-only** (timeline + metadata). Use API clients or future UI work for compose/export. |
| **WebSocket “live” badge** | Real-time updates need a WebSocket-capable ASGI stack (e.g. `uvicorn[standard]` with `websockets`/`wsproto`). Without it, `/v1/ws` may not upgrade; the UI still loads history via `GET …/events`. |
| **Provider guidance editor** | Not a top-level nav item; advanced flows go through `/v1/provider-guidance/...` and related ingress (operator tooling may expand later). |

---

## Verification & troubleshooting

After any registry change:

```bash
./octopus status
./octopus doctor
```

Expect: bots in **registry** mode when connected, one connection line per registry with expected `registry_id`, `scope`, state, URL; local registry **running** when using local mode.

| Symptom | Things to check |
|---------|------------------|
| UI does not load | Registry container up; port in `.deploy/registry/.env`; try `./octopus registry` → start. |
| “No agents” | Bot not enrolled or heartbeat path broken — `./octopus doctor`, reconnect bot. |
| Remote connect fails | URL must be `https://…`; enrollment token correct; scope appropriate. |
| Switch unavailable | **Switch** flows need **exactly one** registry connection — remove extras first. |

**Nuclear reset** (local dev only):

```bash
./octopus clean
```

Stops services, removes Docker volumes/networks and `.deploy/`.

---

## Regenerating UI screenshots

Screenshots and annotated copies live under `docs/assets/registry/ui/`.

From the repo root (requires Node + project `.venv` with app dependencies):

```bash
cd docs/registry-ui-screenshots
npm install
npx playwright install chromium   # once per machine
npm run capture                   # starts uvicorn on 127.0.0.1:19987, seeds SQLite, saves PNGs
./.venv/bin/python annotate.py
```

The capture harness uses **non-default** tokens (`guide-capture-*`) and a throwaway SQLite file under `docs/registry-ui-screenshots/.capture-registry.sqlite3`.

---

## Quick reference: registry scopes

| Scope | Conversation UI / timelines | Routed tasks & discovery |
|-------|------------------------------|---------------------------|
| `full` | Yes | Yes |
| `channel` | Yes | No |
| `coordination` | No | Yes |

---

*Screenshots in this revision were generated with Playwright (Chromium) against the in-repo Registry UI; yellow callouts are added automatically for teaching clarity.*
