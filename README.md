# Octopus Agent Platform

Talk to Claude or Codex from Telegram.

The primary command is:

```bash
./octopus
```

It validates your Telegram bot token, handles provider login, writes bot
configuration under `.deploy/`, and starts the bot in Docker.

**Repo:** [github.com/privacynow/octopus](https://github.com/privacynow/octopus)

## What You Need

- Docker and Docker Compose
- a Telegram bot token from `@BotFather`
- one provider: `claude` or `codex`

## First-Time Setup

### Step 1: Create your Telegram bot

1. Open Telegram and search for `@BotFather`.
2. Send `/newbot`.
3. Choose a display name and a username ending in `bot`.
4. Copy the token BotFather gives you.

### Step 2: Clone the repo

```bash
git clone git@github.com:privacynow/octopus.git ~/octopus
cd ~/octopus
```

### Step 3: Run Octopus

```bash
./octopus
```

Octopus will:

- validate the Telegram token with Telegram before any Docker work
- detect the bot identity from the token
- help you choose `claude` or `codex`
- run provider login only if needed
- create `.deploy/bots/<slug>/.env`
- start the bot

If you want advanced setup fields on first run:

```bash
./octopus --full
```

### Step 4: Message the bot

Open Telegram, find the bot by username, and send a normal message.

Example:

> Review this diff and suggest a safer refactor.

## Day-To-Day Commands

```bash
./octopus status
./octopus start
./octopus stop
./octopus logs
./octopus doctor
./octopus registry
```

If more than one bot exists, Octopus will ask which bot to use only when the
choice is ambiguous.

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

Registry mode is optional. You can connect a bot to a local or remote registry
from the guided menu.

For a local registry, Octopus prints a browser URL like:

```text
http://localhost:8787/ui
```

Log in with `REGISTRY_UI_TOKEN` from `.deploy/registry/.env`.

![Registry UI screenshot](registry-ui-screenshot.png)

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

If you use optional Postgres instead of the default SQLite runtime:

1. Run `./scripts/db/dev_up_postgres.sh`.
2. Set `BOT_DATABASE_URL` in the bot env file.
3. Restart with `./octopus`.

## More Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md): system architecture and boundaries
