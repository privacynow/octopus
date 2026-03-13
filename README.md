# Telegram Agent Bot

Talk to Claude Code or Codex from Telegram. The bot runs in Docker, keeps its
runtime state in Postgres, and sends results back to the same chat.

**Repo:** [github.com/privacynow/octopus](https://github.com/privacynow/octopus)

## What It Does

- talk to your coding agent from Telegram
- review plans before execution
- send files in and get files back
- add skills and credentials
- run separate bot environments with separate databases and tokens

## Recommended Path

Use Docker for both the bot and Postgres.

This is the primary operational model for development now and the intended path
for staging and production as well.

## What You Need

- Docker and Docker Compose
- a Telegram bot token from `@BotFather`
- one provider:
  - `claude`
  - or `codex`
- a bot image that includes that provider CLI

The repo already ships:

- a Postgres Compose stack
- DB bootstrap, update, and doctor commands
- the base app image

The default `Dockerfile` installs Python dependencies only. To run the bot
container, use an image that also includes your chosen provider CLI.

## Quick Start

### 1. Clone the repo

```bash
git clone git@github.com:privacynow/octopus.git ~/telegram-agent-bot
cd ~/telegram-agent-bot
```

### 2. Start Postgres and initialize the database

```bash
./scripts/dev_up.sh
```

That command:

- starts Postgres
- runs DB bootstrap
- runs DB doctor

You can also do it manually:

```bash
docker compose up -d postgres
docker compose --profile tools run --rm db-bootstrap
docker compose --profile tools run --rm db-doctor
```

### 3. Create bot runtime config

Create an env file for the bot container, for example `.env.bot`:

```bash
TELEGRAM_BOT_TOKEN=<your bot token>
BOT_PROVIDER=claude
BOT_ALLOWED_USERS=123456789
```

You can use `BOT_ALLOW_OPEN=1` instead of `BOT_ALLOWED_USERS`, but that is only
appropriate if you intentionally want an open bot.

The container DB URL is already set by Compose to use the `postgres` service, so
you normally do **not** put `BOT_DATABASE_URL` in `.env.bot`.

### 4. Start the bot

```bash
docker compose run --rm --env-file .env.bot bot
```

When the bot starts cleanly, message it in Telegram and begin using it.

## After Updating

After a `git pull`:

```bash
docker compose --profile tools run --rm db-update
docker compose run --rm --env-file .env.bot bot
```

Use `db-update` before restarting the bot whenever the repo adds new SQL files.

## Common Commands

| Command | Purpose |
|---|---|
| `./scripts/dev_up.sh` | Start Postgres, run DB bootstrap, run DB doctor |
| `docker compose --profile tools run --rm db-bootstrap` | Apply full schema to an existing Postgres database |
| `docker compose --profile tools run --rm db-update` | Apply pending schema versions |
| `docker compose --profile tools run --rm db-doctor` | Validate Postgres connectivity and schema compatibility |
| `docker compose run --rm --env-file .env.bot bot` | Start the bot container |

## Using the Bot

Send a normal message:

> Review this diff and suggest a safer refactor.

Upload files and ask:

> Summarize these logs and tell me what broke.

### Review before execution

Turn on approval mode and the bot shows you a plan before doing anything.

```text
                    You send a request
                           |
                           v
                     Bot drafts plan
                           |
                           v
                 You review in Telegram
                    /approve  /reject
                       |          |
                       v          v
              Bot executes task   Nothing runs
                    |
                    v
              You get the result
```

Use `/approval on` to enable this. Use `/approve` or `/reject` (or the inline
buttons) to respond.

### Work with files

Upload logs, screenshots, or documents alongside your message. The bot passes
them to the agent and can send files back when done.

Use `/send <path>` to retrieve any file the agent created.

### Use skills

Skills extend the bot with domain knowledge, credentials, and integrations.

- `/skills list` shows what is active in the current chat
- `/skills add <name>` activates a capability
- `/skills setup <name>` captures credentials when required
- `/skills info <name>` shows the resolved tier and compatibility

If a skill would make the composed prompt too large, the bot warns you first.

### Compact mode for mobile

Long responses get summarized automatically when compact mode is on. Use `/raw`
to see the full output whenever you need it.

## Commands

### Core flow

| Command | What it does |
|---|---|
| `/start` | Show onboarding and current settings |
| `/new` | Clear the current conversation |
| `/help` | Show help |
| `/approval on\|off` | Toggle approval mode |
| `/approve` | Approve the current pending plan |
| `/reject` | Reject the current pending plan |
| `/retry` | Retry the last failed run when available |
| `/cancel` | Cancel the current run |
| `/doctor` | Show a health report |

### Output and session

| Command | What it does |
|---|---|
| `/raw` | Show the full last output |
| `/compact on\|off` | Toggle compact mode |
| `/export` | Export session output |
| `/session` | Show current session details |
| `/clear` | Clear current session state |

### Skills and settings

| Command | What it does |
|---|---|
| `/skills list` | Show active skills |
| `/skills add <name>` | Activate a skill |
| `/skills remove <name>` | Remove a skill |
| `/skills setup <name>` | Configure a skill |
| `/settings` | Open settings |
| `/model` | Show or change profile |
| `/project` | Show or change project binding |
| `/policy inspect\|edit` | Show or change file-access policy |
| `/clear_credentials [skill]` | Remove stored skill credentials |

### Admin and managed skills

| Command | What it does |
|---|---|
| `/skills create <name>` | Scaffold a custom skill |
| `/skills install <name>` | Install a managed skill from the bundled store or registry |
| `/skills uninstall <name>` | Remove a managed skill |
| `/skills update <name>` | Update a managed skill |
| `/skills update all` | Update all managed skills |
| `/skills updates` | Show available managed skill updates |
| `/skills diff <name>` | Show a managed skill diff |

## Troubleshooting

### `BOT_DATABASE_URL is required`

The runtime is Postgres-only. For container runs, Compose sets the container DB
URL to `postgresql://bot:bot@postgres:5432/bot`.

### `claude` or `codex` not found

Your bot image does not include the provider CLI. Use an image that bundles the
provider runtime.

### DB doctor says bootstrap or update is required

Run:

```bash
docker compose --profile tools run --rm db-bootstrap
```

or:

```bash
docker compose --profile tools run --rm db-update
```

### Polling conflict

Telegram allows a single active polling connection per bot token. If you see
`Conflict: terminated by other getUpdates request`, another process is already
using that token. Stop it first, then start the current instance.

## Advanced and Internal Details

The README intentionally keeps one Docker-first path.

For deeper details, use:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): runtime, storage, bootstrap, and testing contracts
- [docs/PLAN-commercial-polish.md](docs/PLAN-commercial-polish.md): product definition, roadmap, and design decisions
- [docs/STATUS-commercial-polish.md](docs/STATUS-commercial-polish.md): current shipped state and progress
