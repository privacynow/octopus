# Octopus Agent Platform

Octopus runs Claude or Codex behind Telegram and adds a local registry so
operators can manage bots, monitor work, review approvals, inspect
conversations, route tasks, manage skills, and edit provider guidance from a
browser UI.

The main entrypoint is:

```bash
./octopus
```

`./octopus` manages local deployment state under `.deploy/`, starts and
reconnects the local registry stack, and handles normal operator lifecycle
work.

## Quick Start

1. Create a Telegram bot with `@BotFather` and copy the token.
2. Clone the repo into a persistent checkout:

```bash
git clone git@github.com:privacynow/octopus.git ~/octopus
cd ~/octopus
./octopus
```

Setup offers three modes:

- **Autonomous**: private bot, no approval gates
- **Safe**: default; requests go through approval mode
- **Advanced**: manual role, tags, description, default skills, allowed users,
  working dir, and timeout settings

## How People Use Octopus

Octopus has two primary user roles:

- **end users** interact with the bot in Telegram
- **operators** manage bots and work through the CLI and registry UI

### End Users

For most users, Octopus is just a Telegram chat bot.

- send a normal message to ask for work
- use `/help` for command discovery
- if approval mode is enabled, the bot pauses for review before executing
- if routed work is used, the parent reply still comes back into the same
  Telegram chat

Common user-facing commands:

```text
/help
/skills
/skills list
/skills add <name>
/skills remove <name>
/skills setup <name>
/skills clear
```

### Operators

Operators work through two surfaces:

- the `./octopus` CLI
- the local registry UI at `/ui`

Core CLI commands:

```bash
./octopus
./octopus status
./octopus start registry
./octopus connect
./octopus restart bots
./octopus redeploy registry
./octopus shell m1
./octopus doctor m1
./octopus clean
```

Core registry UI routes:

- **Dashboard**: open conversations, running work, recent completions,
  follow-up items, and agent health
- **Approvals**: pending operator decisions
- **Agents**: roster plus direct open-conversation actions
- **Conversations**: active thread list and quick-start row
- **Conversation detail**: one workspace for replies, routing, tasks, and full
  activity
- **Tasks**: cross-conversation routed-task queue
- **Usage**: per-conversation token and cost rollups
- **Skills** and **Guidance**: operator management surfaces

## Deployment Model

For the shipped Telegram runtime in this repo:

- bots run in `BOT_AGENT_MODE=registry`
- Telegram startup expects registry connectivity
- the local operator experience assumes registry-connected bots

Important URLs and env values:

- local registry UI: `http://localhost:<port>/ui`
- bot-to-registry URL inside Docker: `http://registry:8787`
- operator login secret: `REGISTRY_UI_TOKEN` from `.deploy/registry/.env`

The runtime supports multiple registry records through indexed
`BOT_AGENT_REGISTRY_<n>_*` env vars, but the `./octopus` CLI is intentionally
local-registry-first.

## Clean Deploy Workflow

For a persistent `~/octopus` checkout, the repo also ships non-interactive ops
helpers under [`scripts/ops/`](/Users/tinker/output/bots/telegram-agent-bot/scripts/ops):

```bash
bash scripts/ops/backup_octopus_deploy.sh --help
bash scripts/ops/refresh_octopus_with_backup.sh --help
```

The clean refresh flow is:

1. back up `~/octopus/.deploy`
2. `git pull --ff-only`
3. run `./octopus clean`
4. restore `.deploy`
5. start the registry and bots again
6. reconnect bots to the registry
7. verify registry health and bot freshness

## Shared Workspaces

Workspaces let multiple bots collaborate on the same host directory mounted at
`/workspace/<name>` inside the container.

Use:

1. `./octopus`
2. `Workspaces`
3. create the workspace
4. attach bots
5. restart the affected bots

Each member bot receives a `BOT_PROJECTS` entry, so users can switch into the
workspace with `/project <name>`.

## Skills And Guidance

Skills and guidance are operator-managed capabilities, but they are not the
main entrypoint into Octopus.

- builtin skills come with the bot runtime and can be enabled per chat through
  Telegram `/skills ...` commands or turned on by default with `BOT_SKILLS`
- imported skills come from a remote registry and require `BOT_REGISTRY_URL`
  before the browser **Skills** page can install them
- the browser **Skills** page manages the catalog and lifecycle; it does not
  activate a skill into one specific conversation
- guidance is provider-level instruction state for Claude/Codex behavior and is
  managed through Telegram `/guidance ...` commands or the browser
  **Guidance** page

If you need the full model for builtin skills, imported registry skills,
conversation activation, and provider guidance, see
[ARCHITECTURE.md](/Users/tinker/output/bots/telegram-agent-bot/ARCHITECTURE.md)
and [docs/manual/README.md](/Users/tinker/output/bots/telegram-agent-bot/docs/manual/README.md).

## Troubleshooting

If something fails:

1. `./octopus status`
2. `./octopus doctor <bot>`
3. inspect the relevant `.deploy/.../.env` file and registry settings

If a remote registry connection fails:

1. confirm the URL is `https://...`
2. confirm the enrollment token and scope values
3. inspect the indexed `BOT_AGENT_REGISTRY_<n>_*` env records
4. run `./octopus doctor <bot>` and inspect per-registry state

## Repo Layout

The codebase is split into four main packages:

- `app/`: shipped Telegram bot runtime and the `./octopus` CLI
- `octopus_registry/`: standalone registry service, websocket layer, store,
  ingress, and operator SPA
- `octopus_sdk/`: shared runtime contracts, workflows, registry protocols, and
  composition seams
- `octopus_sdk/testing/`: test-only SDK fixtures used by wiring verification

## Documentation

- [ARCHITECTURE.md](/Users/tinker/output/bots/telegram-agent-bot/ARCHITECTURE.md):
  system shape, ports, stores, interaction flows, and operator SPA model
- [docs/manual/README.md](/Users/tinker/output/bots/telegram-agent-bot/docs/manual/README.md):
  operator and user manual
- [docs/registry-guide.md](/Users/tinker/output/bots/telegram-agent-bot/docs/registry-guide.md):
  registry lifecycle and browser walkthrough
- [docs/flows-catalog.md](/Users/tinker/output/bots/telegram-agent-bot/docs/flows-catalog.md):
  flow inventory with code pointers

**Repo:** [github.com/privacynow/octopus](https://github.com/privacynow/octopus)
