# Registry guide

This guide ties the CLI lifecycle, the registry service, and the current
operator UI together. It is written against the current codebase and screenshot
set, not the older dashboard-first or board-plus-log UI revisions.

For the full flow inventory, see
[flows-catalog.md](/Users/tinker/output/bots/telegram-agent-bot/docs/flows-catalog.md).

## Contents

1. [When to use registry mode](#when-to-use-registry-mode)
2. [Concepts](#concepts)
3. [CLI lifecycle with `./octopus`](#cli-lifecycle-with-octopus)
4. [Backup and clean refresh helpers](#backup-and-clean-refresh-helpers)
5. [Browser sign in](#browser-sign-in)
6. [Browser screens](#browser-screens)
7. [Mobile quick look](#mobile-quick-look)
8. [Verification and troubleshooting](#verification-and-troubleshooting)
9. [Regenerating UI screenshots](#regenerating-ui-screenshots)

## When to use registry mode

Use registry mode when you want:

- a browser UI for operators
- shared visibility across multiple bots
- routed tasks and direct cross-agent assignment
- approvals, health, task state, and full activity in one place
- one local operator console instead of following every bot through Telegram

Registry mode is optional. Bots can still run without it.

## Concepts

| Term | Meaning |
|---|---|
| **Registry service** | FastAPI service for enroll/register/heartbeat, conversations, tasks, approvals, usage, websocket realtime, and the `/ui` SPA |
| **Operator** | Human using the browser UI with `REGISTRY_UI_TOKEN` |
| **Agent token** | Bearer token issued at enroll time for bot/runtime calls to `/v1/...` |
| **Scope** | Registry permission lane for a bot connection: `full`, `channel`, or `coordination` |
| **Conversation** | Registry conversation row plus stored event stream |
| **Routed task** | Structured delegated work tied back to a parent conversation |

Important URLs:

- operator UI: `http://localhost:<port>/ui`
- bot-to-registry URL inside Docker: `http://registry:8787`

## CLI lifecycle with `./octopus`

Use the verb-first commands or the no-argument menu.

| Step | Command | Reference |
|---|---|---|
| Check local state | `./octopus status` | bots, registry, auth, image freshness |
| Start local registry | `./octopus start registry` | starts the operator UI and API |
| Connect eligible bots | `./octopus connect` | enrolls and connects local bots |
| Restart registry | `./octopus redeploy registry` | rebuild/recreate while preserving state |
| Follow logs | `./octopus logs registry` | registry runtime output |
| Reset local state | `./octopus clean` | destructive local reset |

After startup, note:

- the `/ui` URL printed by Octopus
- `REGISTRY_UI_TOKEN` from `.deploy/registry/.env`
- bot URL `http://registry:8787` for containers

The CLI lifecycle SVGs in
[`docs/assets/registry/`](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry)
still map to the current local-registry deployment model.

## Backup and clean refresh helpers

When you need to refresh a live local checkout like `~/octopus` without losing
its configured bots and registry state, use the ops helpers in
[`scripts/ops/`](/Users/tinker/output/bots/telegram-agent-bot/scripts/ops).

### Backup only

```bash
bash scripts/ops/backup_octopus_deploy.sh --help

bash scripts/ops/backup_octopus_deploy.sh \
  --source /Users/tinker/octopus \
  --target /tmp/octopus-backup
```

This copies `/Users/tinker/octopus/.deploy` into `/tmp/octopus-backup/.deploy`
with the same exclusions the refresh helper uses for transient provider-auth
scratch directories.

### Clean refresh with restore

```bash
bash scripts/ops/refresh_octopus_with_backup.sh --help

bash scripts/ops/refresh_octopus_with_backup.sh \
  /Users/tinker/octopus \
  /Users/tinker/output/bots/telegram-agent-bot/.tmp/octopus-refresh-backups
```

This is the consistent “deploy clean” workflow:

1. back up `~/octopus/.deploy`
2. pull the latest code into `~/octopus`
3. run `./octopus clean`
4. restore the saved `.deploy`
5. start the registry and bots again
6. reconnect the saved bots
7. verify registry health, bot connectivity, and rebuilt images

At the end it prints the saved deploy snapshot path so you can inspect or reuse
the captured `.deploy` later.

## Browser sign in

1. Open the local `/ui` URL.
2. Sign in with `REGISTRY_UI_TOKEN` from `.deploy/registry/.env`.

![Login](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui/00-login.png)

## Browser screens

The UI is one responsive SPA. The left rail changes routes; the shell is the
same on desktop and mobile.

### Sidebar routes

| Route | Purpose |
|---|---|
| `/ui` | Dashboard |
| `/ui/approvals` | Pending decisions |
| `/ui/agents` | Agent roster |
| `/ui/conversations` | Quick start plus active thread list |
| `/ui/tasks` | Routed-task queue |
| `/ui/capabilities` | Global capability toggles |
| `/ui/skills` | Skill catalog |
| `/ui/usage` | Usage rollups |
| `/ui/guidance` | Provider guidance |

### Dashboard

The dashboard is an operator overview, not a metrics wall.

- summary rail for conversations, tasks, follow-up, and agents
- `Needs attention` for approvals, failed work, and unhealthy agents
- `Open conversations`, `Running tasks`, and `Agents` as direct jump targets

![Dashboard](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui/01-dashboard.png)

### Approvals

Approvals is the fastest screen for clearing blocked work.

- request summary
- requester/trust/expiry facts
- direct `Open`, `Approve`, and `Reject`

![Approvals](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui/01b-approvals.png)

### Agents

The agent roster is action-first.

- server-side search
- segmented state filter
- one row per agent with heartbeat context
- direct `Open` conversation action

![Agents](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui/02-agents.png)

### Agent detail

Agent detail is the compact health-and-entry workspace for one agent.

- `Open conversation`
- overview facts
- capabilities
- workers snapshot when published
- inline conversations for that agent

![Agent detail](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui/03-agent-detail.png)

The compatibility route `/ui/agents/{agent_id}/conversations` still exists, but
it renders the same workspace:

![Agent conversation deep link](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui/04-agent-conversations.png)

### Conversations

The conversations index is the main operator thread list.

Top of page:

- compact quick-start chips for connected agents
- overflow path to `Agents`
- `Approvals` shortcut

Main list:

- server-side search
- segmented status filter
- paginated rows into conversation detail

![Conversations](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui/05-conversations.png)

Search stays on the same route and sends `q` to the server:

![Conversations filtered](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui/05b-conversations-filtered.png)

### Conversation detail

Conversation detail is the main operator workspace.

Header behavior:

- title plus export/cancel actions
- operator-facing metadata such as:
  - `With M1`
  - `Assigned to M2`
  - `Started in registry`
  - `Updated just now`
- status chip
- `Activity (n)` shortcut into `Full activity`
- `Copy ref` action instead of a raw reference blob in the main hierarchy

Tabs:

- **Conversation** — messages, approvals, delegation milestones, task-status milestones, errors
- **Tasks** — store-backed routed tasks with retry/cancel where valid
- **Full activity** — raw stored event stream for diagnostics

Composer behavior:

- plain text sends a normal operator message
- leading selectors such as `@m2`, `@cap:review`, or `@role:reviewer` submit a
  typed direct assignment from the same composer

Conversation milestones are rendered as human events, not raw task payloads:

- `Task submitted`
- `Assigned to M2`
- `Task completed`
- terminal task summaries where available

![Conversation detail](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui/06-conversation-detail.png)

### Tasks

Tasks is the routed-work queue across all conversations.

- summary rail for pending/running/follow-up
- segmented status filter
- expandable task rows
- parent-conversation link plus retry/cancel actions when valid

![Tasks](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui/07-tasks.png)

### Capabilities

Capabilities shows global capability toggles exposed by the registry service.

![Capabilities](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui/08-capabilities.png)

### Skills

Skills is the runtime catalog surface.

- client-side search
- install/uninstall actions

![Skills](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui/09-skills.png)

### Usage

Usage rolls provider-response usage into per-conversation totals.

- segmented date ranges
- summary rail
- per-conversation table
- delegated child work can roll into the parent conversation when usage is
  reported back through routed-task results

![Usage](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui/10-usage.png)

### Provider guidance

Guidance is the provider-specific prompt/editor surface.

![Guidance](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui/11-guidance.png)

### Deep links

These routes load the same views as in-app navigation:

- `/ui/agents/{agent_id}`
- `/ui/conversations/{conversation_id}`

![Agent detail via URL](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui/12-agent-detail-deep-link.png)

![Conversation detail via URL](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui/13-conversation-deep-link.png)

## Mobile quick look

Mobile uses the same routes and state model.

- sidebar becomes a drawer
- segmented controls stay horizontal and scroll instead of wrapping
- dashboard sections stack
- conversation detail keeps the composer inside the main workspace

![Mobile dashboard](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui/14-mobile-dashboard.png)

![Mobile approvals](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui/15-mobile-approvals.png)

![Mobile conversation detail](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui/16-mobile-conversation.png)

## Verification and troubleshooting

After any registry change:

```bash
./octopus status
./octopus doctor <bot>
```

Common checks:

| Symptom | Check |
|---|---|
| UI does not load | registry container, port, `./octopus start registry` |
| No agents | bot not connected or heartbeat missing |
| No conversations/tasks | registry scope, websocket/API errors, bot publish level |
| Usage is zero | no usage-bearing provider responses were stored for that range |

For a destructive local reset:

```bash
./octopus clean
```

## Regenerating UI screenshots

Desktop and mobile docs screenshots are generated from
`docs/registry-ui-screenshots/` against a throwaway registry instance started
by Playwright.

```bash
cd docs/registry-ui-screenshots
npm install
npx playwright install chromium
npm run capture
npm run annotate
```

`npm run capture` refreshes:

- desktop route screenshots
- mobile reference screenshots
- sibling `*.meta.json` files used by `annotate.py`

If you need to validate the live runtime instead of the seeded screenshot app,
use the disposable live smoke harness from the repo root:

```bash
bash scripts/e2e/run_live_registry_smoke.sh \
  --snapshot-deploy /path/to/saved/.deploy
```
