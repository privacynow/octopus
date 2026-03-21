# Octopus Agent Platform

Run Claude or Codex through Telegram, with an optional registry for operator
visibility, multi-agent coordination, and browser-based administration.

The primary command is:

```bash
./octopus
```

`./octopus` validates your Telegram bot token, handles provider login, writes
bot configuration under `.deploy/`, and starts the bot in Docker.

**Repo:** [github.com/privacynow/octopus](https://github.com/privacynow/octopus)

## What Octopus Includes

- Telegram chat UX for end users
- optional registry mode with:
  - an agent-facing HTTP API
  - a browser UI for operators
  - registry-backed routing, timeline projection, and coordination
- Claude or Codex provider runtimes
- SQLite by default, with optional Postgres for runtime and registry stores

## What You Need

- Docker and Docker Compose
- a Telegram bot token from `@BotFather`
- one provider: `claude` or `codex`

## Quick Start

### 1. Create a Telegram bot

1. Open Telegram and search for `@BotFather`.
2. Send `/newbot`.
3. Choose a display name and a username ending in `bot`.
4. Copy the token BotFather gives you.

### 2. Clone the repo

```bash
git clone git@github.com:privacynow/octopus.git ~/octopus
cd ~/octopus
```

### 3. Run Octopus

```bash
./octopus
```

Octopus will:

- validate the Telegram token before starting Docker
- detect the bot identity from the token
- walk provider setup for `claude` or `codex`
- create `.deploy/bots/<slug>/.env`
- start the bot

If you want the full guided setup flow on first run:

```bash
./octopus --full
```

### 4. Message the bot

Open Telegram, find the bot by username, and send a normal message.

Example:

> Review this diff and suggest a safer refactor.

## Operating Modes

Octopus can run in two practical shapes:

- **Telegram-first standalone bot**
  - users talk to the bot directly in Telegram
  - no registry UI is required
- **Registry-backed bot**
  - Telegram remains the user-facing chat surface
  - a registry adds operator UI, timelines, coordination, and routed-task flows

Registry mode can point at:

- a **local registry** managed from `./octopus registry`
- a **remote registry** over HTTPS

## Day-To-Day Commands

```bash
./octopus status
./octopus start
./octopus stop
./octopus logs
./octopus doctor
./octopus registry
```

If more than one bot exists, Octopus asks which bot to use only when the choice
is ambiguous.

## Most Useful Commands

| Command | What it does |
|---|---|
| `/start` | Show the main help |
| `/help` | Show help |
| `/approval on\|off\|status` | Review plans before execution |
| `/approve` | Approve the current pending plan |
| `/reject` | Reject the current pending plan |
| `/cancel` | Stop the current request or pending action |
| `/send <path>` | Retrieve a file the bot created |
| `/skills` | Show active skills |
| `/skills list` | Show available skills |
| `/skills add <name>` | Activate a skill |
| `/skills setup <name>` | Configure a skill when prompted |
| `/settings` | Open chat settings |
| `/session` | Show current session details |
| `/doctor` | Run the bot health check |

## Registry UI

Registry mode is optional. When enabled, Octopus can connect the bot to a local
or remote registry.

For a local registry, Octopus prints a browser URL like:

```text
http://localhost:8787/ui
```

Log in with `REGISTRY_UI_TOKEN` from `.deploy/registry/.env`.

Typical operator uses:

- inspect connected agents
- review conversation timelines and registry-backed activity
- follow routed-task and coordination state
- manage capability, skill, and provider-guidance surfaces

![Registry UI screenshot](registry-ui-screenshot.png)

## Storage and Runtime Notes

- SQLite is the default runtime and registry backend
- Postgres is optional and supported for the main durable seams
- the startup path validates Postgres schema health before boot when
  `BOT_DATABASE_URL` is set
- registry mode can run in a single process or in shared ingress/worker roles

If you use Postgres instead of the default SQLite runtime:

1. Run `./scripts/db/dev_up_postgres.sh`.
2. Set `BOT_DATABASE_URL` in the bot env file.
3. Restart with `./octopus`.

## Verify It Works

After setup, send this message to the bot:

> What files are in my working directory?

You should get a reply within a few seconds.

Inside Telegram, `/doctor` runs a plain-language health check.

## Troubleshooting

If the bot will not start:

1. Run `./octopus` again.
2. If provider auth expired, Octopus will walk you through login again.
3. Run `./octopus doctor`.
4. Send `/doctor` to the bot in Telegram if it is reachable.

If the registry UI is not updating:

1. Run `./octopus registry`.
2. Confirm the bot is connected in registry mode.
3. Re-run `./octopus` and choose the registry management path.

## More Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md): current runtime, control-plane, registry, and store architecture
- [docs/registry-guide.md](docs/registry-guide.md): step-by-step local and remote registry guide with screenshots
