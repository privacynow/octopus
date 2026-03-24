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

Implementation: [`octopus`](../octopus) (shell), with helpers under [`scripts/lib/`](../scripts/lib/).

| Flow | Surface | Implementation | Documented in |
|------|---------|----------------|---------------|
| First-time guided setup | Run `./octopus` with **no bots** | `first_bot_flow` (quick or `--full` advanced) | [README.md](../README.md) Quick Start |
| Main menu (existing bots) | Run `./octopus` when ≥1 bot exists | `main_menu` | [README.md](../README.md), `./octopus help` |
| Add another bot (quick) | Main menu **1** | `add_bot_flow quick` → `prepare_new_bot_setup` | — |
| Add another bot (full options) | Main menu **5** Advanced → **1** | `add_bot_flow full` | — |
| First bot with full prompts | `./octopus --full` | `first_bot_flow full` | — |
| **Manage bot** | Main menu **2** | `manage_bot_menu` | — |
| View logs | Manage **1** | `cmd_logs` | `./octopus help` |
| Restart bot | Manage **2** | `cmd_start` after stop | — |
| Stop bot | Manage **3** | `cmd_stop` | — |
| Health check | Manage **4** | `cmd_doctor` (optional `--live-provider`) | README, registry-guide troubleshooting |
| **Edit settings** | Manage **5** | `edit_bot_settings_menu`: display name, role, tags, allowed users, timeout, open editor | — |
| **Registry connection for bot** | Manage **6** or main **3** | `manage_bot_registry_flow` / `connect_bot_to_registry_flow` / `connect_bot_to_local_registry_menu` | [docs/registry-guide.md](registry-guide.md) CLI SVGs |
| Workspaces | Main menu **4** | `cmd_workspace` | `./octopus help` |
| **Advanced** | Main menu **5** | `advanced_menu`: full add-bot, **webhook mode** | — |
| Webhook mode setup | Advanced **2** | `configure_webhook_mode_flow` | [ARCHITECTURE.md](../ARCHITECTURE.md) (deployment context) |
| Status (all bots + registry + auth) | `./octopus status` | `cmd_status` | README |
| Start / stop / logs | `./octopus start|stop|logs [slug]` | `cmd_*` | `./octopus help` |
| Doctor | `./octopus doctor [--live-provider] [slug]` | `cmd_doctor` | README |
| **Local registry** | `./octopus registry …` | `cmd_registry` → `registry_start_cmd`, `registry_stop_cmd`, `registry_logs_cmd`, `registry_status_cmd`, `registry_connect_cmd`, `registry_interactive_menu` | [docs/registry-guide.md](registry-guide.md) §CLI + SVGs under `docs/assets/registry/*.svg` |
| **Workspace subcommands** | `./octopus workspace create|remove|add-bot|remove-bot|status|verify` | `workspace_*` functions | `./octopus help` |
| **Nuclear reset** | `./octopus clean` | `cmd_clean` | README Security / troubleshooting |

**SVG storyboards (general Octopus):** [`docs/assets/octopus/README.md`](assets/octopus/README.md) — main menu, manage bot, workspace, advanced/webhook, clean. **`./octopus help`:** [`docs/assets/quickstart/04-octopus-help.svg`](assets/quickstart/04-octopus-help.svg).

### 1.1 Registry connection flows (Octopus ↔ bot env)

These are the **logical** branches inside `manage_bot_registry_flow` and related helpers (`add_registry_connection_flow`, `disconnect_bot_from_registry_flow`, `switch_local_bot_to_remote_registry_flow`, `switch_remote_bot_to_local_registry_flow`, `connect_bot_to_registry_flow` for standalone → first connection).

| Flow | When | Documented in |
|------|------|----------------|
| Connect standalone bot to registry | Bot in standalone mode | [`04-connect-local.svg`](assets/registry/04-connect-local.svg), [`05-add-bot-local.svg`](assets/registry/05-add-bot-local.svg) |
| Connect to **remote** HTTPS registry | Prompts URL + enrollment token + scope | [`06-connect-remote.svg`](assets/registry/06-connect-remote.svg) |
| **Multiple** registry connections | `manage_bot_registry` when count > 1 | [`10-manage-registry-connections.svg`](assets/registry/10-manage-registry-connections.svg) |
| Switch local ↔ remote | Exactly one connection; branch in menu | [`07-switch-local-remote.svg`](assets/registry/07-switch-local-remote.svg), [`08-switch-remote-local.svg`](assets/registry/08-switch-remote-local.svg) |
| Disconnect / return to standalone | `disconnect_bot_from_registry_flow` | [`09-disconnect-registry.svg`](assets/registry/09-disconnect-registry.svg) |
| Local registry **maintenance** | `./octopus registry` interactive menu | [`11-registry-maintenance.svg`](assets/registry/11-registry-maintenance.svg) |
| Start local registry | `registry start` | [`02-start-local-registry.svg`](assets/registry/02-start-local-registry.svg) |
| Registry state overview | `registry status` / `status` | [`01-local-registry-states.svg`](assets/registry/01-local-registry-states.svg) |

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
| Global capability toggles | `/ui/capabilities` | `08-capabilities-annotated.png` |
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
| **Operator capabilities** | `GET/POST` capabilities enable/disable | Capabilities view |
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
| Registry **scope** | `full` / `channel` / `coordination` per connection | Octopus prompts, [registry-guide](registry-guide.md) scope table |
| Multi-registry per bot | Multiple rows in bot env | Octopus `manage_bot_registry_flow` when count > 1 |
| Publish level | `BOT_REGISTRY_PUBLISH_LEVEL` | README, runtime → registry events |
| Webhook vs polling | `BOT_MODE`, webhook env | `configure_webhook_mode_flow`, deployment docs |

---

## 7. Coverage checklist

- **Octopus menus and subcommands:** §1 and §1.1 (this file) + `./octopus help`.
- **Registry UI pages:** §2 + [docs/registry-guide.md](registry-guide.md) screenshots.
- **Registry CLI storyboards:** `docs/assets/registry/*.svg`.
- **Telegram:** §4 — command lists mirror [`bootstrap.py`](../app/channels/telegram/bootstrap.py).
- **Registry API:** §3 — exhaustive list in `http.py` (use for integrations not covered by UI).

**Intentionally not duplicated here:** prose tutorials for every API endpoint and every Telegram sub-command; use code and API discovery, or add focused guides later under `docs/` as needed.
