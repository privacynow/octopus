# Octopus Agent Platform

Run Claude or Codex through Telegram, with an optional registry for operator
visibility, routed tasks, multi-agent coordination, and a browser UI.

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
- optional registry mode with:
  - operator browser UI at `/ui`
  - conversation projection
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

## Registry Model

Registry mode is optional.

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

The operator UI under `ui/` is a vanilla SPA with no framework and no build
step. Main screens:

- **Dashboard** — compact operator workspace for blocking approvals, open
  conversations, task follow-up, and agent health
- **Approvals** — pending operator decisions
- **Agents** — list rows with server-side search/state filters
- **Conversations** — server-side search/status filters, a main composer that
  routes on leading `@agent` / `@cap:` / `@role:`, tabs for Conversation,
  Tasks, and Full activity, plus cancel/export
- **Tasks** — status board plus detailed task log with retry/cancel actions and
  parent-conversation links
- **Capabilities**, **Skills**, **Usage**, **Guidance**

Conversation compose is now one flow:

- type a normal message to continue the conversation
- start with `@m2`, `@cap:review`, or `@role:reviewer` to submit a structured
  direct assignment from the same composer
- use the dedicated **Tasks** tab in conversation detail to monitor routed work
  and retry/cancel it without reading raw activity cards

Realtime comes from `/v1/ws` and uses explicit typed topics for:

- `summary`
- `agents`
- `conversations`
- `tasks`
- `approvals`
- `usage`

## Runtime Notes

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
- tears the disposable stack down afterward

Use `--skip-playwright` to run the API/runtime portion only.

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — systems, subsystems, ports, SDK, APIs,
  stores, and interaction flows
- [docs/manual/README.md](docs/manual/README.md) — operator/user manual
- [docs/registry-guide.md](docs/registry-guide.md) — registry lifecycle and UI
  guide
- [docs/flows-catalog.md](docs/flows-catalog.md) — flow inventory with code
  pointers

**Repo:** [github.com/privacynow/octopus](https://github.com/privacynow/octopus)
