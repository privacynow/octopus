# Operator: Registry web UI

[← Manual home](README.md) · [Prev: Octopus](02-operator-octopus.md) · [Next: Telegram →](04-product-telegram.md)

The Registry **operator UI** is a small **vanilla** SPA (`ui/`: HTML, CSS, JS—no build step). Use it to inspect enrolled bots, conversations, routed tasks, and coordination state after a bot is connected to a registry. Octopus prints a browser URL when the registry runs (often `http://localhost:8787/ui` or similar).

**Annotated screenshots** for every screen live in the **[Registry guide § Browser: every screen](../registry-guide.md#browser-every-screen)** (`docs/assets/registry/ui/*-annotated.png`). This chapter stays **text-first** so the manual stays fast to read; open the guide when you want visuals side-by-side with the same routes.

---

## 1. Sign in

1. Open the registry **`/ui/login`** URL from Octopus or your deploy docs.
2. Enter **`REGISTRY_UI_TOKEN`** from **`.deploy/registry/.env`** as the password (there is no separate username).
3. The app sets a **session cookie**; mutating API calls use **CSRF** from **`GET /v1/auth/csrf`**.

If login fails, confirm the registry process is up, the token matches the server env, and you are not mixing HTTP/HTTPS in a way that drops cookies. **Screenshot:** [Registry guide — Browser: sign in](../registry-guide.md#browser-sign-in).

---

## 2. Shell and navigation

| Area | Route | What you do there |
|------|-------|-------------------|
| **Agents** | `/ui` | Paginated **cards**; badge shows connectivity. **Click** a card → agent detail. |
| **Conversations** | `/ui/conversations` | All conversations; **pagination**; **search** (type **≥3** characters, debounced, server `q`); **status** filter. Row → detail. |
| **Tasks** | `/ui/tasks` | **Routed tasks** table; pagination and **status** filter. **Row** → parent conversation. |
| **Capabilities** | `/ui/capabilities` | Global coordination toggles; changes are **confirmed** and sent with CSRF. |
| **Skills** | `/ui/skills` | **Catalog** browse; client-side search. Full skill **lifecycle** remains API-first. |
| **Usage** | `/ui/usage` | **Today / 7 days / 30 days** drives `since` / `until` on usage rollups when data exists. |

**Responsive layout:** narrow viewports use a **hamburger** drawer; mid-width sidebar **collapses** to icons; desktop shows full labels. The sidebar footer shows **WebSocket** status when the client can reach **`/v1/ws`** (if the server cannot upgrade, the UI still works over REST).

**Bookmarkable URLs:** `/ui/agents/{agent_id}`, `/ui/agents/{agent_id}/conversations`, `/ui/conversations/{conversation_id}` load the same views as in-app navigation.

---

## 3. Agents and agent detail

**Agents list**

- One **card** per enrolled agent: display name, slug hints, **connectivity** state, tags/capabilities as badges.
- Lists are **paginated** (cursor + **Previous / Next**).

**Agent detail**

- **Identity:** agent id, slug, registry **scope**, version, last heartbeat.
- **Capabilities / tags** as badges; optional **worker** rows when the runtime reports them.
- **Conversations for this agent** appear **inline** below (paginated), same data as the dedicated scoped route.

**Agent-scoped conversation list (full page)**

- **`/ui/agents/{id}/conversations`** shows only conversations involving that agent—useful to **share a link** or keep a narrow bookmark.

---

## 4. Conversations (global list)

- **Pagination:** use **Next / Previous**; the UI tracks cursor history for “back” a page.
- **Search:** nothing is sent until the query is at least **three** characters (reduces noise and load).
- **Status filter:** limits rows server-side together with search.
- **Open a thread:** click a row → **conversation detail** (same as opening from a task or a deep link).

---

## 5. Conversation detail (operator actions)

This is where most **operator** actions live:

| Action | Behavior |
|--------|----------|
| **Compose** | Send an operator message (`POST` messages); **Enter** to send; requires session + CSRF. |
| **Cancel** | Conversation-level cancel action (`POST` actions). |
| **Export** | Download markdown export (`GET` export). |
| **Messages only** | Toggle whether the timeline shows only chat messages or **all** event kinds. |
| **Load older** | Pull earlier events when the API returns a cursor for history. |

**Timeline:** user and bot lines render as **bubbles**; other kinds (approvals, provider metadata, task status, errors, etc.) render as **collapsible** cards. With a working WebSocket upgrade, new events can **append** live; otherwise rely on navigation and REST-loaded history.

---

## 6. Tasks

- Table columns typically include **title**, **origin**, **target**, **status**, **updated** time.
- **Click a row** to jump to the **parent conversation** (delegation context).
- Status and pagination match the **Conversations** pattern; filter helps when many tasks exist.

---

## 7. Capabilities, skills, usage (short)

- **Capabilities** — operator-only **global** switches for coordination features; mis-clicks ask for confirmation.
- **Skills** — read-oriented **catalog** from the registry/shipped skills; installing, drafts, approvals, and publish flows are **not** fully mirrored here (use **`/v1/catalog/skills/...`** or tooling).
- **Usage** — summary and per-conversation totals **when** the store has usage rows; empty period is normal if bots are not publishing usage-shaped data.

---

## 8. What the UI does not replace

Draft → submit → approve → publish for **skills**, **provider guidance** editing, and some **approval** paths are **API- or product-first**. See [registry-guide.md § What the UI does *not* do yet](../registry-guide.md#what-the-ui-does-not-do-yet).

---

## 9. CLI flows and refreshing screenshots

- **Octopus / registry CLI** storyboards: **SVG** under [`docs/assets/registry/`](../assets/registry/) (connect, disconnect, switch, etc.)—linked from [Octopus CLI](02-operator-octopus.md) and the registry guide.
- **Browser PNGs:** regenerate with Playwright after UI changes—[registry-guide.md § Regenerating UI screenshots](../registry-guide.md#regenerating-ui-screenshots) (`docs/registry-ui-screenshots/`: `npm run capture`, `npm run annotate`).

---

**Full visual tour (login → every screen → deep links):** [registry-guide.md — Browser: every screen](../registry-guide.md#browser-every-screen).
