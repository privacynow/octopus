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
- one provider: `claude` or `codex`

You build the bot image **once** for your chosen provider; the repo’s build
script uses `BOT_PROVIDER` (from `.env.bot` or the command line) so you don’t
choose Docker targets manually. The image includes the real Claude or Codex
CLI. See [Building the bot image](#building-the-bot-image) below.

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

### 4. Build the bot image

Build the bot image for your provider (the script reads `BOT_PROVIDER` from `.env.bot` if present):

```bash
./scripts/build_bot_image.sh
```

Or pass the provider explicitly: `./scripts/build_bot_image.sh claude` or `./scripts/build_bot_image.sh codex`.

### 5. Provider login (one-time)

Authenticate the provider CLI so the bot can talk to Claude or Codex. Login state is stored in a Docker volume and reused by the bot.

```bash
./scripts/provider_login.sh
```

- **Codex:** completes ChatGPT sign-in in the browser.
- **Claude:** in the Claude window, run `/login` and complete auth in the browser.

The script runs a **provider-only** health check after login (no DB or Telegram); if it fails, fix the reported issue and run login again.

### 6. Start the bot

**Recommended (runs as a background service):**

```bash
docker compose up -d bot
```

To run in the foreground instead (e.g. to see logs in the terminal):

```bash
docker compose run --rm --env-file .env.bot bot
```

When the bot is running, message it in Telegram and begin using it.

**Alternative: one guided script** — If you prefer a single flow that does Postgres, build, provider login check, and start: run **`./scripts/guided_start.sh`** after creating `.env.bot`. It will prompt you to run `./scripts/provider_login.sh` once if not already authenticated, then start the bot.

## After Updating

After a `git pull`:

```bash
docker compose --profile tools run --rm db-update
docker compose up -d bot
```

Use `db-update` before restarting the bot whenever the repo adds new SQL files. If the bot is already running, `docker compose up -d bot` will recreate the container with the new image.

## Common Commands

| Command | Purpose |
|---|---|
| `./scripts/dev_up.sh` | Start Postgres, run DB bootstrap, run DB doctor |
| `./scripts/guided_start.sh` | Single guided flow: Postgres → build → provider login (if needed) → start bot |
| `./scripts/build_bot_image.sh` | Build the bot image for the provider in `.env.bot` (or pass `claude` / `codex`) |
| `./scripts/provider_login.sh` | One-time interactive provider auth (state stored in bot-home volume) |
| `./scripts/provider_status.sh` | Check **provider auth and runtime only** (no DB/Telegram) |
| `./scripts/provider_logout.sh` | Clear provider auth state (best-effort; switch accounts or re-login) |
| `docker compose --profile tools run --rm db-bootstrap` | Apply full schema to an existing Postgres database |
| `docker compose --profile tools run --rm db-update` | Apply pending schema versions |
| `docker compose --profile tools run --rm db-doctor` | Validate Postgres connectivity and schema compatibility |
| `docker compose up -d bot` | Start the bot as a background service (uses `.env.bot`) |
| `docker compose run --rm --env-file .env.bot bot` | Start the bot in the foreground |

### Building the bot image and provider auth

The supported path uses a **real** provider-enabled image and **persistent provider login** in a Docker volume (`bot-home`). Build the image with **`./scripts/build_bot_image.sh`**, then run **`./scripts/provider_login.sh`** once to authenticate (Codex: `codex --login`; Claude: run `/login` in the Claude window). Login state is reused by the bot. Use **`./scripts/provider_status.sh`** to verify **provider auth and runtime only** (no DB or Telegram). Use **`./scripts/provider_logout.sh`** to clear auth (best-effort; see script comment). If you **change BOT_PROVIDER** in `.env.bot`, run `./scripts/build_bot_image.sh` again and run `./scripts/provider_login.sh` for the new provider; **`./scripts/guided_start.sh`** will warn if the provider changed since the last build. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details.

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

### Provider not authenticated or unavailable

The bot validates provider auth at startup. If you see “Provider not authenticated or unavailable” and a suggestion to run `./scripts/provider_login.sh`, run that script once to sign in (Codex: browser sign-in; Claude: run `/login` in the Claude window). Login state is stored in the `bot-home` volume and reused. Use `./scripts/provider_status.sh` to verify provider auth and runtime only; for full app health (DB, Telegram) run `docker compose run --rm --env-file .env.bot bot python -m app.main --doctor`. Use `./scripts/provider_logout.sh` to clear auth (best-effort) and re-login.

### `BOT_DATABASE_URL is required`

The runtime is Postgres-only. For container runs, Compose sets the container DB
URL to `postgresql://bot:bot@postgres:5432/bot`.

### `claude` or `codex` not found

The supported path uses a **real** provider-enabled image. Build it with
`./scripts/build_bot_image.sh` (and the same `BOT_PROVIDER` as in `.env.bot`).
Ensure you have built the image for your chosen provider before running the bot.

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
