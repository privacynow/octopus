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

1. **Clone the repo**

   ```bash
   git clone git@github.com:privacynow/octopus.git ~/telegram-agent-bot
   cd ~/telegram-agent-bot
   ```

2. **Create `.env.bot`** with your token, provider, and access (example):

   ```bash
   TELEGRAM_BOT_TOKEN=<from @BotFather>
   BOT_PROVIDER=claude
   BOT_ALLOWED_USERS=123456789
   ```

   Use `BOT_ALLOW_OPEN=1` instead of `BOT_ALLOWED_USERS` only if you want an open bot. Do **not** set `BOT_DATABASE_URL` in `.env.bot` (Compose sets it for the container).

3. **Run the guided setup and start**

   ```bash
   ./scripts/guided_start.sh
   ```

   That script: starts Postgres and the database, builds (or reuses) the bot image for your provider, runs interactive provider login if needed, then starts the bot. When it finishes, message the bot in Telegram.

That’s the main path. Manual steps and reference are below.

---

## Manual steps (reference)

If you prefer to run steps yourself instead of `guided_start.sh`:

- **Postgres and DB (no `.env.bot` required):**  
  `./scripts/dev_up.sh` — starts Postgres, then runs db-doctor; if the DB already has schema it runs db-update, otherwise db-bootstrap, then db-doctor.  
  One-off: `docker compose up -d postgres`, then `docker compose --profile tools run --rm db-bootstrap` (fresh DB) or `db-update` (existing schema), then `docker compose --profile tools run --rm db-doctor`.

- **Build bot image:**  
  `./scripts/build_bot_image.sh` (uses `BOT_PROVIDER` from `.env.bot`) or `./scripts/build_bot_image.sh claude` / `./scripts/build_bot_image.sh codex`.  
  Images are tagged `telegram-agent-bot:claude` and `telegram-agent-bot:codex`.

- **Provider login (one-time):**  
  `./scripts/provider_login.sh`  
  Codex: complete sign-in in the browser. Claude: in the Claude window run `/login` and complete auth. Login state is stored in the `bot-home` volume.

- **Start the bot:**  
  `docker compose --profile bot --env-file .env.bot up -d bot`  
  Foreground (e.g. for logs): `docker compose --profile bot run --rm --env-file .env.bot bot`

The bot service is under the **`bot`** profile so that `docker compose up -d postgres` and the DB tooling work in a clean repo without `.env.bot`.

## After Updating

After a `git pull`, the bot runs from a **prebuilt image** (`telegram-agent-bot:claude` or `:codex`). To run the updated code you must **rebuild that image**, then restart:

```bash
docker compose --profile tools run --rm db-update
./scripts/build_bot_image.sh
docker compose --profile bot --env-file .env.bot up -d bot
```

Run `db-update` when the repo adds new SQL. Rebuild the image so the new code is in the image; then `up -d bot` recreates the container with the new image. If you omit the build step, the existing (possibly stale) image keeps running. If you use **`./scripts/guided_start.sh`** after a pull, it will rebuild the image when any code or config that goes into the image changed (e.g. `Dockerfile.bot`, `requirements.txt`, or files under `app/`, `scripts/`, `sql/`, `skills/`) since the image was built.

## Common Commands

| Command | Purpose |
|---|---|
| `./scripts/guided_start.sh` | **One path:** Postgres → build → provider login (if needed) → start bot |
| `./scripts/dev_up.sh` | Start Postgres, run DB bootstrap or update (then doctor); no `.env.bot` needed |
| `./scripts/build_bot_image.sh` | Build `telegram-agent-bot:claude` or `:codex` (from `.env.bot` or arg) |
| `./scripts/provider_login.sh` | One-time interactive provider auth |
| `./scripts/provider_status.sh` | **Provider auth and runtime only** (not DB/Telegram) |
| `./scripts/provider_logout.sh` | Clear provider auth (best-effort) |
| `docker compose up -d postgres` | Start Postgres only (tooling independent of bot config) |
| `docker compose --profile tools run --rm db-bootstrap` | Apply full schema |
| `docker compose --profile tools run --rm db-update` | Apply pending schema versions |
| `docker compose --profile tools run --rm db-doctor` | Validate Postgres and schema |
| `docker compose --profile bot --env-file .env.bot up -d bot` | Start the bot (background) |
| `docker compose --profile bot run --rm --env-file .env.bot bot` | Start the bot (foreground) |

### Building the bot image and provider auth

The bot uses **provider-tagged images** (`telegram-agent-bot:claude`, `telegram-agent-bot:codex`) and **persistent provider login** in the `bot-home` volume. Build with **`./scripts/build_bot_image.sh`**; run **`./scripts/provider_login.sh`** once to authenticate. **`./scripts/provider_status.sh`**, **`./scripts/provider_login.sh`**, and **`./scripts/provider_logout.sh`** use a Compose service that has no Postgres dependency, so they check or change only provider auth/runtime (no DB). For full app health (DB, Telegram) run `docker compose --profile bot run --rm --env-file .env.bot bot python -m app.main --doctor`. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details.

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
| `/cancel` | Cancel credential setup or a pending request |
| `/doctor` | Show a health report |

### Output and session

| Command | What it does |
|---|---|
| `/raw` | Show the full last output |
| `/compact on\|off` | Toggle compact mode |
| `/export` | Export session output |
| `/session` | Show current session details |

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

The bot validates provider auth at startup. If you see “Provider not authenticated or unavailable” and a suggestion to run `./scripts/provider_login.sh`, run that script once to sign in (Codex: browser sign-in; Claude: run `/login` in the Claude window). Login state is stored in the `bot-home` volume and reused. Use `./scripts/provider_status.sh` to verify provider auth and runtime only; for full app health (DB, Telegram) run `docker compose --profile bot run --rm --env-file .env.bot bot python -m app.main --doctor`. Use `./scripts/provider_logout.sh` to clear auth (best-effort) and re-login.

### `BOT_DATABASE_URL is required`

The runtime is Postgres-only. For container runs, Compose sets the container DB
URL to `postgresql://bot:bot@postgres:5432/bot`.

### `claude` or `codex` not found

The supported path uses a **real** provider-enabled image. Build it with
`./scripts/build_bot_image.sh` (and the same `BOT_PROVIDER` as in `.env.bot`).
Ensure you have built the image for your chosen provider before running the bot.

### DB doctor says bootstrap or update is required

Use **db-bootstrap** for a fresh DB (no schema yet). Use **db-update** when the DB already has schema (e.g. after a git pull with new migrations). Then run db-doctor to confirm.

```bash
docker compose --profile tools run --rm db-bootstrap   # fresh DB
# or
docker compose --profile tools run --rm db-update      # existing schema
docker compose --profile tools run --rm db-doctor
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
