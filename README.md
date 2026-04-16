# Octopus Agent Platform

Octopus runs Claude or Codex behind bot runtimes and adds a local registry UI
for operators. In the shipped product you can talk to bots from Telegram or
from registry-origin browser conversations, and you use the registry to inspect
conversations, review approvals, manage skills and guidance, define reusable
protocols, launch protocol runs, and inspect agent health.

The main entrypoint is:

```bash
./octopus
```

`./octopus` manages the local Docker deployment under `.deploy/`. For the
standard local setup, it starts the registry stack and one bot stack per bot,
including the Postgres containers those stacks need. You normally do not need
to wire the database manually.

## Prerequisites

Before you start, for the standard local Telegram-enabled setup:

- Docker Desktop is running
- you have a Telegram bot token from `@BotFather`
- you have provider auth available for Claude or Codex
- you cloned the repo into a persistent checkout

The shipped runtime can also run in registry-only mode when no Telegram token
is configured, but this README walks through the standard Telegram-enabled
deployment.

## Quick Start

Clone the repo and run the setup flow:

```bash
git clone git@github.com:privacynow/octopus.git ~/octopus
cd ~/octopus
./octopus
```

The setup flow will:

- create or update `.deploy/`
- configure the registry
- configure one or more bots
- start the local Docker stacks
- connect the bots to the registry

When setup finishes, verify the stack:

```bash
./octopus status
```

You should see:

- the registry is `running`
- your bots are `running`
- registry connection state is `connected`
- execution state is `healthy`

## Open The Registry

`./octopus status` prints the registry URL. By default it is:

- [http://127.0.0.1:8787/ui](http://127.0.0.1:8787/ui)

Use the registry to:

- inspect agents
- open conversations
- send operator messages in registry-origin conversations
- review approvals
- manage skills
- manage provider guidance
- define and publish protocols
- inspect protocol runs

If you want the browser workflow in detail, use
[docs/registry-user-guide.md](docs/registry-user-guide.md).

## Use The Telegram Bot

If Telegram is configured, after the stack is up:

1. open Telegram
2. find your bot
3. send a normal message
4. if approval mode is enabled, approve the request in Telegram or the registry

Useful Telegram commands:

- `/help`
- `/project <name>`
- `/skills ...`
- `/guidance ...`
- `/protocol list`
- `/protocol start <slug> <problem statement>`
- `/protocol status <run_id>`

If you want the Telegram workflow in detail, use
[docs/telegram-user-guide.md](docs/telegram-user-guide.md).

## Common Commands

```bash
./octopus
./octopus status
./octopus start registry
./octopus start bots
./octopus restart bots
./octopus connect m1
./octopus logs m1 --follow
./octopus shell m1
./octopus doctor m1
./octopus clean
```

## Skills

Skills are the main way you control what a bot can do.

The important states are:

- `Available on this bot`
- `Default for new conversations`
- `Active in this conversation`

Skills can come from:

- `Core`
- `Store`
- `Custom`

For the practical guide to installing, activating, configuring, and authoring
skills, use [docs/skills-guide.md](docs/skills-guide.md).

For the lower-level shared model, use
[docs/skills-model.md](docs/skills-model.md).

## Protocols

Protocols are reusable multi-stage workflows stored in the registry control
plane and executed through the shared SDK/runtime path.

The current shipped model is:

- define and edit protocol definitions in the registry UI
- validate and publish immutable protocol versions
- start protocol runs from the registry UI or from Telegram
- observe run progress, stage transitions, and outcomes in the registry

The first built-in protocol is `software-engineering`, which models planning,
review, architecture, implementation, review, and acceptance over durable repo
artifacts.

For the detailed project specification, use
[protocol_plan.md](protocol_plan.md).

`./octopus` generates `BOT_CREDENTIAL_KEY` for managed bot env files. Keep it:

- present in each bot `.env`
- stable across restarts and redeploys
- independent from `TELEGRAM_BOT_TOKEN`

## Troubleshooting

If something is wrong, start here:

1. `./octopus status`
2. `./octopus doctor <bot>`
3. inspect the relevant `.deploy/.../.env` file
4. confirm the registry is reachable and provider auth is valid

If a bot is running but not connected, check its registry state first.

If a bot is connected but not executing, check provider auth and execution
fault state.

## Further Reading

- [docs/registry-user-guide.md](docs/registry-user-guide.md)
  Browser/operator guide
- [docs/telegram-user-guide.md](docs/telegram-user-guide.md)
  Telegram user guide
- [docs/skills-guide.md](docs/skills-guide.md)
  Core, store, and custom skills
- [docs/sdk-bot-development.md](docs/sdk-bot-development.md)
  SDK-oriented bot development guide
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
  System architecture and runtime boundaries

**Repo:** [github.com/privacynow/octopus](https://github.com/privacynow/octopus)
