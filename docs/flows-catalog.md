# Operator and product flows (canonical catalog)

This document **enumerates every operator-facing and product-facing flow** implemented in the repo: **where it lives in code**, and **which human-oriented doc or asset** already explains it (if any). It is the inventory; the **narrated manual with annotated screenshots** is [docs/manual/README.md](manual/README.md). Shorter tutorials remain in [README.md](../README.md), [docs/registry-guide.md](registry-guide.md), and [ARCHITECTURE.md](../ARCHITECTURE.md).

**Legend**

| Column | Meaning |
|--------|---------|
| **Surface** | How the user triggers the flow |
| **Implementation** | Source of truth in the repo |
| **Documented in** | Primary pointer for operators |

---

## 1. Operator: `./octopus` (CLI and menus)

Implementation: [`octopus`](../octopus) (thin wrapper) → [`app/octopus_cli/`](../app/octopus_cli/).

| Flow | Surface | Implementation | Documented in |
|------|---------|----------------|---------------|
| Dynamic operator menu | Run `./octopus` | `OctopusCLI.interactive_menu` | [README.md](../README.md), `./octopus help` |
| Recommended actions | No-arg menu → **Recommended Actions** | `OctopusCLI.recommended_actions` | — |
| Lifecycle actions | `./octopus start|stop|restart|redeploy ...` or menu → **Lifecycle** | `OctopusCLI.run_mutating` + `OctopusManager` lifecycle methods | [README.md](../README.md), `./octopus help` |
| Add bot | Menu → **Bots** → **Add bot** | `OctopusManager.add_bot_interactive` | [README.md](../README.md) Quick Start |
| Connect / disconnect local registry | `./octopus connect|disconnect ...` or menu → **Bots** | `OctopusManager.connect_bot_to_local_registry`, `disconnect_bot_from_local_registry` | [docs/registry-guide.md](registry-guide.md) |
| Logs / shell / doctor | `./octopus logs|shell|doctor ...` or menu → **Diagnose** | `OctopusCLI.cmd_logs`, `cmd_shell`, `cmd_doctor` | README |
| Registry lifecycle | `./octopus start|stop|restart|redeploy registry` or menu → **Registry** | `OctopusManager.start_registry`, `stop_registry` | [docs/registry-guide.md](registry-guide.md) |
| Workspace management | Menu → **Workspaces** | `OctopusManager.create_workspace`, `add_bot_to_workspace`, `remove_bot_from_workspace` | README |
| Status and freshness | `./octopus status` or menu → **Status** | `OctopusCLI.render_*_status` | README |
| Destructive reset | `./octopus clean` | `OctopusManager.clean_all` | README |

**SVG storyboards (general Octopus):** [`docs/assets/octopus/README.md`](assets/octopus/README.md) — main menu, Bots submenu, Workspaces submenu, Diagnose submenu, clean. **`./octopus help`:** [`docs/assets/quickstart/04-octopus-help.svg`](assets/quickstart/04-octopus-help.svg).

### 1.1 Registry connection flows (Octopus ↔ bot env)

Current Octopus uses one consistent local-registry connection flow:

| Flow | When | Documented in |
|------|------|----------------|
| Connect eligible bots to local registry | `./octopus connect` or menu → **Bots** → **Connect** | [docs/registry-guide.md](registry-guide.md) |
| Disconnect local registry | `./octopus disconnect` or menu → **Bots** → **Disconnect** | [docs/registry-guide.md](registry-guide.md) |
| Start / stop / redeploy registry | lifecycle verbs or menu → **Registry** | [docs/registry-guide.md](registry-guide.md) |

---

## 2. Operator: Registry web UI (browser)

Implementation: [`ui/`](../ui/) (SPA), entry [`ui/js/app.js`](../ui/js/app.js), routing [`ui/js/router.js`](../ui/js/router.js).

| Flow | Route / action | Documented in |
|------|----------------|---------------|
| Sign in | `/ui/login` → session cookie | [docs/registry-guide.md](registry-guide.md) §Browser, `00-login-annotated.png` |
| Sign out | Sidebar **Logout** → `/ui/logout` | registry-guide sidebar table |
| Dashboard summary | `/ui`, `/ui/` | `01-dashboard-annotated.png` |
| Pending approvals queue | `/ui/approvals` | `01b-approvals-annotated.png` |
| Agents list | `/ui/agents` | `02-agents-annotated.png` |
| Agent detail | `/ui/agents/:id` | `03-agent-detail-annotated.png`, `12-agent-detail-deep-link-annotated.png` |
| Agent-scoped conversations | `/ui/agents/:id/conversations` | `04-agent-conversations-annotated.png` |
| All conversations + search + status + pagination | `/ui/conversations` | `05`, `05b` |
| Conversation detail (human-first timeline, compose, cancel, export, scroll-up history, WS) | `/ui/conversations/:id` | `06-conversation-detail-annotated.png` |
| Routed tasks → open parent conversation | `/ui/tasks` | `07-tasks-annotated.png` |
| Routing policy | `/ui/routing` | `08-capabilities-annotated.png` |
| Skill catalog | `/ui/skills` | `09-skills-annotated.png` |
| Usage aggregates | `/ui/usage` | `10-usage-annotated.png` |
| Provider guidance editor | `/ui/guidance` | `11-guidance-annotated.png` |

**Not a separate screen:** bookmarking **`/ui/conversations/:id`** loads the same conversation detail as clicking a row (parity with agent deep links).

**API-first (not full Registry UI):** skill draft/submit/approve/publish lifecycle beyond install/uninstall, and conversation-bound skill activation — see [registry-guide](registry-guide.md) §“What the UI does *not* do yet”.

---

## 3. Operator / automation: Registry HTTP API (bots and tools)

Implementation: [`app/channels/registry/http.py`](../app/channels/registry/http.py).

Grouped by **concern** (each endpoint is a **machine flow**; only a subset is mirrored in the UI above).

| Domain | Endpoints (summary) | UI overlap |
|--------|----------------------|------------|
| **Auth / session** | `POST` enroll/register/heartbeat/deregister/ack; `GET` agents, agent status | Partially visible via agent list/detail |
| **Discovery / tasks** | `POST` discovery/search, routed-tasks, status, result; `GET` poll | Tasks view, conversation context |
| **Conversations** | `GET/POST` conversations; `GET/POST` events; `GET/POST` messages; `POST` actions; `GET` export | Detail view: messages, compose, cancel, export, event pagination; not all approval paths |
| **Routing policy** | `GET/POST` routing skill enable/disable | Routing view |
| **Usage** | `GET /v1/usage` | Usage view |
| **Skill catalog (full lifecycle)** | `GET` search/detail/lifecycle/diff; `PUT` draft; `POST` submit/approve/reject/publish/archive/install/uninstall/update | Skills view = **catalog only** (not full lifecycle UI) |
| **Conversation-bound skills** | `GET/POST` …/skills, activate/deactivate/clear | Not dedicated top-level UI |
| **Provider guidance** | `GET/PUT` draft; `POST` preview/submit/approve/reject/publish/archive | Guidance editor at `/ui/guidance` |
| **Realtime** | `GET` CSRF; `WS /v1/ws` | Optional live updates |

---

## 4. Product: Telegram chat (end user + admin)

Implementation: [`app/channels/telegram/bootstrap.py`](../app/channels/telegram/bootstrap.py) registers handlers; handlers in [`app/channels/telegram/ingress.py`](../app/channels/telegram/ingress.py).

Two **runtime shapes**:

- **`runtime_mode != "shared"`** (default single-bot process): **full** command set including `/new`, `/approval`, `/guidance`, `/cancel`, etc.
- **`runtime_mode == "shared"`**: smaller direct set; **delegation / approval / skills / project / policy / model** go through `shared_command_handler` and shared callbacks.

### 4.1 Commands (always registered in both modes)

| Command | Purpose (high level) |
|---------|----------------------|
| `/start`, `/help` | Help and entry |
| `/session` | Session info |
| `/settings` | Chat settings (callbacks `setting_*`) |
| `/clear_credentials` | Clear stored credentials (callback `clear_cred_*`) |
| `/raw` | Raw mode |
| `/send` | Send/fetch file path |
| `/id` | Show ids |
| `/doctor` | Bot health |
| `/discover` | Agent discovery (registry-related) |
| `/allowuser`, `/blockuser`, `/listaccess` | Access control |
| `/export` | Export |
| `/admin` | Admin |

### 4.2 Commands (standalone / worker mode only — not direct in shared)

These are registered **only** when `config.runtime_mode != "shared"`: `/new`, `/approval`, `/approve`, `/reject`, `/skills`, `/guidance`, `/cancel`, `/role`, `/compact`, `/project`, `/policy`, `/model`.

### 4.3 Commands (shared runtime — routed to shared worker)

Registered under `runtime_mode == "shared"` for: `new`, `approval`, `approve`, `reject`, `skills`, `cancel`, `role`, `compact`, `project`, `policy`, `model` (via `shared_command_handler`).

### 4.4 Non-command product flows

| Flow | Mechanism |
|------|-----------|
| **Free-text / media message** | `MessageHandler` → `ingress.handle_message` (main agent loop) |
| **Inline buttons** | Callbacks: `retry_`, `approval_`, `delegation_`, `recovery_`, `setting_`, `expand:`, `collapse:`, `skill_add_`, `skill_update_` |
| **Unknown command** | `handle_unknown_command` |

---

## 5. Operator: Postgres database (optional)

When `BOT_DATABASE_URL` is set, operators may run:

| Flow | Command | Implementation |
|------|---------|----------------|
| Bootstrap schema | `python -m app.db.cli bootstrap` | [`app/db/cli.py`](../app/db/cli.py) |
| Migrate / update | `python -m app.db.cli update` | same |
| DB health | `python -m app.db.cli doctor` | same |

---

## 6. Cross-cutting configuration “flows”

These are not single screens but **modes** that change behavior across surfaces:

| Topic | Config / code | Where it appears |
|-------|----------------|------------------|
| Standalone vs registry bot | `BOT_AGENT_MODE`, registry connection records | Octopus, bot runtime, registry UI |
| Registry **scope** | `full` / `channel` / `coordination` per connection | local-registry connect flow, bot env records, [registry-guide](registry-guide.md) scope table |
| Multi-registry per bot | Multiple indexed rows in bot env | runtime/config capability; not currently a symmetric first-class Octopus wizard flow |
| Publish level | `BOT_REGISTRY_PUBLISH_LEVEL` | README, runtime → registry events |
| Webhook vs polling | `BOT_MODE`, webhook env | deployment/runtime config and startup behavior |

---

## 7. Coverage checklist

- **Octopus menus and subcommands:** §1 and §1.1 (this file) + `./octopus help`.
- **Registry UI pages:** §2 + [docs/registry-guide.md](registry-guide.md) screenshots.
- **Registry CLI storyboards:** `docs/assets/registry/*.svg`.
- **Telegram:** §4 — command lists mirror [`bootstrap.py`](../app/channels/telegram/bootstrap.py).
- **Registry API:** §3 — exhaustive list in `http.py` (use for integrations not covered by UI).

**Intentionally not duplicated here:** prose tutorials for every API endpoint and every Telegram sub-command; use code and API discovery, or add focused guides later under `docs/` as needed.
