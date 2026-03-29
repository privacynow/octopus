# Octopus Agent Platform

Octopus runs Claude or Codex behind Telegram, with a local registry that gives
operators a browser UI for conversations, tasks, approvals, usage, skills, and
guidance.

The main entrypoint is:

```bash
./octopus
```

`./octopus` sets up bots, manages local deployment state under `.deploy/`,
starts and reconnects the local registry stack, and handles day-to-day operator
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
- **Safe**: default; execution goes through approval mode
- **Advanced**: manual role, tags, description, default skills, allowed users,
  working dir, and timeout settings

## What End Users See

For most users, Octopus is just a Telegram chat bot.

- Send a normal message to ask for work.
- Use `/help` for command discovery.
- If approval mode is enabled, the bot will stop for review before executing.
- If routed work is used, the parent reply still comes back into the same
  Telegram chat.

Important user-facing commands:

```text
/help
/skills
/skills list
/skills add <name>
/skills remove <name>
/skills setup <name>
/skills clear
```

The Telegram command help is the current call to action for skills. The bot
already tells users to use `/skills list` and `/skills add <name>` when skills
are relevant.

## What Operators Use

Operators work through two surfaces:

- the `./octopus` CLI
- the local registry UI at `/ui`

Core commands:

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

Useful registry UI routes:

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

## Skills And Guidance

These two features are related, but they are not the same thing.

### Builtin Skills

Builtin skills are part of the bot runtime catalog. They do not need to be
installed from a remote registry before use.

They can be used in two ways:

- **default-on for every conversation** via `BOT_SKILLS`
- **activated per conversation** in Telegram with `/skills add <name>`

User-facing skill flow:

1. `/skills list` to see what is available
2. `/skills info <name>` if the user needs details
3. `/skills add <name>` to activate it for the current conversation
4. `/skills setup <name>` if the skill needs credentials
5. `/skills remove <name>` or `/skills clear` to deactivate

If activation would materially increase prompt size, the bot shows an inline
confirmation before enabling the skill.

### Imported Registry Skills

Registry-imported skills are different from builtin skills.

- They come from a remote skill registry, not the local builtin catalog.
- They are only installable if the bot is configured with a registry source.
- After install, they are still activated the same way as builtin skills:
  `/skills add <name>`.

For true registry installs to work, the bot must have a configured
`BOT_REGISTRY_URL`. Without that, registry search may still display local
catalog information, but install actions will not be usable.

### Skills In The Registry UI

The browser **Skills** page is currently a catalog and lifecycle surface, not a
conversation activation surface.

What it does well:

- shows the local runtime catalog
- shows registry search matches
- exposes install, update, and uninstall for the relevant rows

What it does **not** currently do:

- it does not activate a skill into a specific conversation

Conversation-level skill activation still happens through Telegram commands,
not through the browser UI.

### Guidance

Guidance is operator-managed provider instruction state, not an end-user chat
feature.

It controls provider-specific system guidance such as the effective Claude or
Codex instruction body.

It can be managed through:

- Telegram `/guidance ...` commands
- the browser **Guidance** page

Typical guidance flow:

1. preview the current provider guidance
2. edit or save a draft
3. submit / approve / reject if lifecycle gates are in use
4. publish the guidance

Guidance requires a connected bot that advertises the `provider_guidance`
management capability.

## Deployment Model

For the shipped Telegram runtime in this repo:

- bots run in `BOT_AGENT_MODE=registry`
- Telegram startup expects registry connectivity
- the local operator experience assumes registry-connected bots

Important URLs and env values:

- local registry UI: `http://localhost:<port>/ui`
- bot-to-registry URL inside Docker: `http://registry:8787`
- operator login secret: `REGISTRY_UI_TOKEN` from `.deploy/registry/.env`

The runtime still supports multiple registry records through indexed
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
