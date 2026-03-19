# Octopus Agent Platform

Talk to Claude or Codex from Telegram.

The normal path is simple:

1. create a Telegram bot token with `@BotFather`
2. run `./scripts/app/guided_start.sh`
3. message your bot in Telegram

You do not need to pick a database, understand the runtime, or learn Docker
details to get started.

**Repo:** [github.com/privacynow/octopus](https://github.com/privacynow/octopus)

## What This Bot Does

- answers normal Telegram messages with Claude or Codex
- can show a plan before execution
- accepts file uploads and can send files back
- supports reusable skills and credential setup
- optionally connects to a Registry UI if you want a browser-based control panel

## What You Need

- Docker and Docker Compose
- a Telegram bot token from `@BotFather`
- one provider: `claude` or `codex`

For one private bot, that is enough.

## First-Time Setup

### Step 1 — Create your Telegram bot token

1. Open Telegram and search for **@BotFather**.
2. Send `/newbot`.
3. Choose a display name and a username ending in `bot`.
4. Copy the token BotFather gives you.

### Step 2 — Clone the repo

```bash
git clone git@github.com:privacynow/octopus.git ~/octopus
cd ~/octopus
```

### Step 3 — Run the guided setup

```bash
./scripts/app/guided_start.sh
```

The script will:

- create `.env.bot` if needed
- help you choose `claude` or `codex`
- walk you through provider login if required
- start the bot in Docker
- optionally start a local Registry if you choose registry mode

For most people:

- choose `quick`
- choose `standalone` if you want one private bot
- choose `registry` only if you want the optional browser UI

If you want multiple bots from one checkout, give each one an instance name:

```bash
./scripts/app/guided_start.sh reviewer
./scripts/app/guided_start.sh developer
```

### Step 4 — Message the bot in Telegram

Find your bot by username, send `/start`, then send a normal request like:

> Review this diff and suggest a safer refactor.

## Verify it's working

After setup, send this message to the bot:

> What files are in my working directory?

You should get a reply within a few seconds.

If you chose registry mode, the setup output also prints the Registry UI URL.

## Registry UI

Registry mode is optional. If you turn it on, setup prints a URL like:

```text
http://localhost:8787/ui
```

Log in with `REGISTRY_UI_TOKEN` from `.env.registry`.

![Registry UI screenshot](registry-ui-screenshot.png)

Use the Registry UI when you want to:

- see connected bots in one place
- search conversations and timelines
- start work from a browser instead of Telegram
- approve or cancel delegation plans
- manage skills centrally

Telegram is still the main end-user surface. The Registry UI is optional.

## Credentials

If you use skills that need API keys or tokens, the bot stores them encrypted.

For the safest setup, set `BOT_CREDENTIAL_KEY` in your bot env file before you
start saving credentials. If you leave it unset, the bot falls back to
`TELEGRAM_BOT_TOKEN` for compatibility.

Credential validation is restricted by default. Built-in validation currently
allows `api.github.com`, `*.openai.com`, `*.anthropic.com`, and
`*.googleapis.com`. If you trust another provider, add it with
`BOT_CREDENTIAL_VALIDATION_ALLOWED_HOSTS`.

## Day-To-Day Use

Most interaction is just normal Telegram chat.

- send a message to ask for work
- turn approval on if you want to review a plan first
- upload files when you want the bot to inspect them
- use `/cancel` to stop the current request
- use `/settings` if you want to change chat behavior
- use `/doctor` if you want a plain-language health check

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

## Troubleshooting

### Provider not authenticated or unavailable

If startup tells you to run `./scripts/provider/provider_login.sh`, do that and
then run `./scripts/app/guided_start.sh` again.

If you want a health check from inside Telegram, use `/doctor`.

If you want the full local health check, use:

```bash
docker compose --project-directory . -f infra/compose/docker-compose.yml --profile bot --env-file .env.bot run --rm bot python -m app.main --doctor
```

### The bot will not start

Try these in order:

1. Run `./scripts/app/guided_start.sh` again.
2. Complete provider login if the script asks for it.
3. Send `/doctor` in Telegram.
4. Run the full `app.main --doctor` command above.

### The Registry UI is not updating

If you are using registry mode:

1. make sure the registry is running
2. check that your bot appears in the UI
3. rerun `./scripts/app/guided_start.sh`

### After a `git pull`

Run:

```bash
./scripts/app/guided_start.sh
```

That is the normal restart path.

## Advanced Use

If you later need a more advanced deployment with webhook ingress and separate
workers, start with a working local bot first and then use:

```bash
./scripts/app/shared_start.sh
```

This is optional. Most users should stay with `guided_start.sh`.

## More Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md): system architecture and boundaries
