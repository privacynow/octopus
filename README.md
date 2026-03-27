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

The operator UI under `ui/` is a vanilla SPA with no framework or build step.
It is designed as an operator console, not a generic admin panel: one left rail,
one main work surface per route, compact metadata, and the same conversation
and task model on desktop and mobile.

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

Usage reflects provider-response costs/tokens and rolls delegated child work up
into the parent conversation when that routed work returns usage data.

Realtime comes from `/v1/ws` and uses explicit typed topics:

- `summary`
- `agents`
- `conversations`
- `tasks`
- `approvals`
- `usage`

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
- `app/runtime/transport_builders.py` registers Telegram plus registry-scoped
  delivery transports behind one dispatcher
- once composition is complete, `BotRuntime.run()` owns transport startup,
  worker admission, claim processing, and shutdown
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
- routed tasks use explicit lifecycle transitions such as `queued`, `leased`,
  `running`, `completed`, `failed`, `cancelled`, and `timed_out`

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
