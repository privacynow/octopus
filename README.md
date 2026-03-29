# Octopus Agent Platform

Run Claude or Codex through Telegram with built-in registry participation for
operator visibility, routed tasks, multi-agent coordination, and a browser UI.

The primary command is:

```bash
./octopus
```

`./octopus` sets up bots, manages local deployment state under `.deploy/`,
starts/stops/redeploys Docker services, manages workspaces, and operates the
local registry.

## What It Includes

- Telegram chat UX for end users
- `./octopus` operator CLI for setup, lifecycle, logs, shell, doctor, and
  local registry operations
- registry-backed operator stack with:
  - operator browser UI at `/ui`
  - mirrored conversation projection
  - structured routed-task coordination
  - agent discovery and health publication
  - per-connection scope: `full`, `channel`, or `coordination`
- Claude or Codex provider runtimes
- SQLite by default, with optional Postgres for runtime and registry stores

## Repo Layout

The current codebase is split into four primary packages:

- `app/`
  - the shipped Telegram bot runtime and the `./octopus` deployment CLI
- `octopus_registry/`
  - the standalone registry management plane: API, websocket server, store,
    presenters, and browser UI
- `octopus_sdk/`
  - shared runtime contracts, workflow implementations, registry protocols,
    and composition helpers used by both the bot runtime and registry server
- `octopus_sdk/testing/`
  - test-only in-memory SDK fixtures used by wiring verification tests; these
    are deliberately fenced away from runtime defaults and rejected by
    `WorkflowComposer.build()`

## Quick Start

1. Create a Telegram bot with `@BotFather` and copy the token.
2. Clone the repo.
3. Run:

```bash
git clone git@github.com:privacynow/octopus.git ~/octopus
cd ~/octopus
./octopus
```

Setup offers three modes:

- **Autonomous** — private bot, no approval gates, full provider permissions
- **Safe** — default; review before execution, sandboxed provider behavior
- **Advanced** — manual role/tags/description/skills/allowed users/working
  dir/timeout/completion webhook configuration

## Core Operator Commands

```bash
./octopus                     # dynamic menu
./octopus status              # bots, registry, auth, image freshness
./octopus start registry      # start local registry
./octopus connect             # connect eligible bots to the local registry
./octopus restart bots        # restart all bots
./octopus redeploy registry   # rebuild/recreate registry, preserve data
./octopus logs m1 --follow    # follow one bot's logs
./octopus shell m1            # open a shell in one bot container
./octopus doctor m1           # health check for one bot
./octopus clean               # destructive local reset
```

Notes:

- mutating commands preview the resolved targets and ask once for confirmation
  unless `--yes` is provided
- short selectors such as `m1` work when they are unique
- `restart` preserves state and reuses images
- `redeploy` rebuilds/recreates managed targets while preserving state by
  default

## Ops Helper Scripts

For a live `~/octopus` checkout, the repo also includes two non-interactive ops
helpers under [`scripts/ops/`](/Users/tinker/output/bots/telegram-agent-bot/scripts/ops):

```bash
bash scripts/ops/backup_octopus_deploy.sh --help
bash scripts/ops/refresh_octopus_with_backup.sh --help
```

Use them like this:

```bash
# copy ~/octopus/.deploy into a timestamped backup directory
bash scripts/ops/backup_octopus_deploy.sh \
  --source /Users/tinker/octopus \
  --target /tmp/octopus-backup

# pull the latest code into ~/octopus, run a destructive clean,
# restore the saved .deploy snapshot, rebuild fresh images, and reconnect
bash scripts/ops/refresh_octopus_with_backup.sh \
  /Users/tinker/octopus \
  /Users/tinker/output/bots/telegram-agent-bot/.tmp/octopus-refresh-backups
```

`refresh_octopus_with_backup.sh` is the “clean deploy” path we use for the
live local registry stack:

1. backup `~/octopus/.deploy`
2. `git pull --ff-only`
3. `./octopus clean`
4. restore the saved `.deploy`
5. `./octopus start --yes`
6. `./octopus connect --yes`
7. verify registry health, connected bots, and rebuilt images

## Registry Model

For the shipped Telegram runtime in this repo, registry participation is part
of the product profile.

- Telegram bots run in `BOT_AGENT_MODE=registry`
- Telegram startup requires registry connections with full participant
  coverage across `channel` and `coordination`
- the SDK can still model other transport profiles, including registry-only or
  non-enrolled runtimes, but the local Octopus Telegram deployment and
  operator UI assume registry-connected bots

- local registry UI: `http://localhost:<port>/ui`
- bot-to-local-registry URL inside Docker: `http://registry:8787`
- operator login secret: `REGISTRY_UI_TOKEN` from `.deploy/registry/.env`

The runtime/config model still supports multiple registry connections per bot
through indexed `BOT_AGENT_REGISTRY_<n>_*` env records. The current `./octopus`
CLI is intentionally local-first:

- local registry lifecycle is first-class
- local registry connect/disconnect is first-class
- remote/multi-registry capability still exists in the runtime, but is not
  currently exposed through an equally rich local CLI wizard

## Registry UI

The operator UI under `octopus_registry/ui/` is a vanilla SPA with no framework
or build step. It is designed as an operator console, not a generic admin
panel: one left rail, one main work surface per route, compact metadata, and
the same conversation and task model on desktop and mobile.

The registry is the management plane. Bots in `app/` do not expose their own
operator HTTP API. Instead, the registry talks to connected bots over the typed
management protocol in `octopus_sdk.registry.management`, and management
capabilities light up when a compatible bot is connected.

Current main routes:

- **Dashboard** — dense overview of what needs attention now: open
  conversations, running work, follow-up items, and agent health
- **Approvals** — pending operator decisions with direct approve/reject/open
  actions
- **Agents** — roster with search + state filters and direct
  **Open conversation** actions
- **Conversations** — compact quick-start row for connected agents, server-side
  search/status filters, and a list of active threads
- **Conversation detail** — one composer for both replies and direct routing,
  tabs for **Conversation**, **Tasks**, and **Full activity**, compact
  operator-facing header metadata (`With`, `Assigned to`, `Started in`), plus
  export/cancel and activity/ref actions
- **Tasks** — routed-task queue with compact summary cards, segmented status
  filters, expandable task rows that stay open across live task refreshes, and
  links back to the parent conversation
- **Agent detail task threads** — recipient-side routed-task projections are
  shown separately from direct conversations so delegated work does not blur
  into ordinary chat history
- **Usage** — per-conversation token/cost rollups
- **Capabilities**, **Skills**, **Guidance** — operator configuration and
  catalog surfaces

Conversation work now happens in one flow:

- type a normal message to continue the thread
- start with `@m2`, `@cap:review`, or `@role:reviewer` to submit a structured
  direct assignment from the same composer
- use **Tasks** for routed-work state and actions
- use the conversation **Tasks** tab for per-thread routed work without
  leaving the active conversation
- use **Full activity** for the full stored event stream when you need
  diagnostics

Route changes now prepare the next route off-DOM and wait for its initial
local-registry data before swapping it into `#content`. The previous route
stays visible until the next one is ready, so the swap is old real content to
new real content without route-transition skeletons, spinners, or partial
header-only shells.

Usage reflects provider-response costs/tokens and rolls delegated child work up
into the parent conversation when that routed work returns usage data.

Realtime comes from `/v1/ws` and uses explicit typed topics:

- `summary`
- `agents`
- `conversations`
- `tasks`
- `approvals`
- `usage`

Mounted routes debounce invalidation bursts, skip unchanged payloads, and avoid
background-tab refresh churn so the operator UI does not keep repainting whole
sections for no visible change.

## Runtime Notes

- `app/main.py` is the runnable entrypoint
- `app/runtime/startup.py` owns startup validation, doctor/provider-health
  modes, provider/database checks, and the guarded handoff into the runtime
- `app/runtime/services.py` builds the shipped runtime profile by composing:
  - control-plane services
  - registry participant services
  - workflow composition
  - transport stack builders
  - `octopus_sdk.bot_runtime.BotRuntime`
- `app/runtime/composition.py` is the app-side wrapper over
  `octopus_sdk.composition.WorkflowComposer`; app code provides concrete ports,
  the SDK owns the workflow graph
- `app/runtime/transport_builders.py` registers Telegram plus registry-scoped
  delivery transports behind one dispatcher
- `octopus_sdk.transport.BotRuntimeHandle` now includes direct delegation
  continuation; routed-task results resume the parent transport through
  `BotRuntime.continue_delegation(...)` instead of re-entering the runtime as
  a synthetic fresh inbound message
- once composition is complete, `BotRuntime.run()` owns transport startup,
  worker admission, claim processing, and shutdown
- `octopus_registry/main.py` is the standalone registry server entrypoint
- `octopus_registry/ingress.py` is the registry-side management adapter over
  the typed bot-management protocol in `octopus_sdk.registry.management`
- `.deploy/bots/<slug>/.env` and `.deploy/registry/.env` are operator-owned
  deployment state
- runtime-owned bot identity and per-registry state live under
  `BOT_DATA_DIR/agent/`
- SQLite is the default backend
- set `BOT_DATABASE_URL` to move the bot runtime to Postgres
- set `REGISTRY_DATABASE_URL` to move the registry service to Postgres
- `BOT_REGISTRY_PUBLISH_LEVEL`:
  - `minimal`: `message.user`, `message.bot`, `task.status`, `error`
  - `standard`: minimal + `provider.request`, `provider.response`,
    `tool.execution`, `approval.requested`, `approval.decided`,
    `delegation.proposed`, `delegation.submitted`, `delegation.completed`
  - `full`: currently the same set as `standard`

Delegation and routed work are now structured end to end:

- registry-origin direct assignment and delegation go through typed
  conversation actions
- routed-task results resume the original parent transport through the SDK
  continuation seam, preserving the parent transport ref/key instead of
  fabricating a new inbound user message
- routed tasks use explicit lifecycle transitions such as `queued`, `leased`,
  `running`, `completed`, `failed`, `cancelled`, and `timed_out`
- recipient-side routed-task projections are typed as task threads in the
  registry store and UI instead of being treated as ordinary conversations

The serialized inbound contract also carries an explicit admission class:

- `external` for normal Telegram or registry-origin user/operator ingress
- `internal` for SDK-owned replay/recovery work

That lets the runtime distinguish real external access control from internal
replay/recovery flows without transport-specific hacks.

Registry UI live-refresh reconciliation follows the same rule:

- keyed subtree signatures are based on the text and badges the operator can
  see
- relative-time fields are signed from `UI.relativeTime(...)`, not the raw ISO
  timestamp
- backend-only metadata is not included in signatures

That keeps heartbeat and invalidate traffic from repainting rows whose visible
content has not changed.

## SDK Wiring Verification

The SDK includes a dedicated wiring-verification test under
`octopus_sdk/tests/test_wiring_verification.py`. It proves that SDK-owned
workflow implementations can be composed without importing `app/` or
`octopus_registry/`, but it is deliberately not a production template.

- `WorkflowComposer.build()` rejects test-only implementations
- `WorkflowComposer.build_for_testing()` is the explicit test-only path
- `octopus_sdk/testing/` contains non-durable in-memory fixtures such as
  `InMemoryWorkQueue` and `InMemorySessionStore`
- those fixtures are not re-exported from `octopus_sdk/__init__.py`
- app/runtime and registry code must not import `octopus_sdk.testing`

## Shared Workspaces

Workspaces let multiple bots collaborate on the same host directory mounted at
`/workspace/<name>` inside the container.

Use:

1. `./octopus`
2. `Workspaces`
3. create the workspace
4. attach bots
5. restart affected bots with `./octopus restart <slug>`

Each member bot receives a `BOT_PROJECTS` entry, so users can switch into the
workspace with `/project <name>`.

## Troubleshooting

If something fails:

1. `./octopus status`
2. `./octopus doctor <bot>`
3. `./octopus logs <bot>`

If a manually configured remote registry connection fails:

1. confirm the URL is `https://...`
2. confirm the enrollment token and scope values
3. inspect the indexed `BOT_AGENT_REGISTRY_<n>_*` records in the bot env file
4. run `./octopus doctor <bot>` and inspect per-registry state

## Live Smoke

For end-to-end verification against the current source tree, use the isolated
snapshot-based harness instead of testing against a live `~/octopus` checkout.

```bash
bash scripts/e2e/run_live_registry_smoke.sh \
  --snapshot-deploy /path/to/saved/.deploy
```

This harness:

- copies the saved deployment snapshot into `.tmp/e2e-live-smoke/`
- launches a fresh disposable registry + bot stack from the current repo
- runs API smoke plus the Chromium live smoke
- covers the operator UI on desktop and mobile, including dark theme and
  keyboard navigation on segmented controls
- tears the disposable stack down afterward

Use `--skip-playwright` to run the API/runtime portion only.

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — systems, subsystems, ports, SDK, APIs,
  stores, interaction flows, and the current registry SPA model
- [docs/manual/README.md](docs/manual/README.md) — operator/user manual
- [docs/registry-guide.md](docs/registry-guide.md) — registry lifecycle,
  operator UI tour, and screenshot regeneration guide
- [docs/flows-catalog.md](docs/flows-catalog.md) — flow inventory with code
  pointers

The registry guide and manual pages now track the same desktop and mobile
screenshots generated from `docs/registry-ui-screenshots/`, so those docs are
the authoritative browser walkthrough for the current UI.

**Repo:** [github.com/privacynow/octopus](https://github.com/privacynow/octopus)
