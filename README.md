# Octopus Agent Platform

Talk to Claude Code or Codex from Telegram, with an optional Registry UI for
multi-bot coordination and a shared-runtime deployment path for operators.

This repo is for two audiences:

- **End users** who want one private Telegram bot that can help with coding,
  reviews, files, and approvals
- **Operators** who want to run that bot reliably, connect it to the Registry
  UI, or scale it with split-role Shared Runtime

The normal path is simple:

1. create a Telegram bot token with `@BotFather`
2. run `./scripts/app/guided_start.sh`
3. message the bot in Telegram

You do **not** need to choose a database, wire up Postgres tooling, or learn
the internal runtime architecture to get started.

**Repo:** [github.com/privacynow/octopus](https://github.com/privacynow/octopus)

## What This Bot Does

- answers normal Telegram messages with Claude Code or Codex
- lets you review a plan before execution
- accepts file uploads and can send files back
- supports reusable skills and credential setup
- exposes a Registry UI when you want search, delegation, and multi-bot
  visibility
- supports a split-role Shared Runtime for operators who need webhook ingress
  plus multiple workers

## What You Need

- Docker and Docker Compose
- a Telegram bot token from `@BotFather`
- one provider: `claude` or `codex`

For a single private bot, that is enough. The guided setup handles the rest.

## Credential Key Management

Stored skill credentials are encrypted at rest. For stable key management,
set `BOT_CREDENTIAL_KEY` in your bot env file before you start using
credentials.

If `BOT_CREDENTIAL_KEY` is unset, the bot falls back to
`TELEGRAM_BOT_TOKEN` for backwards compatibility. That works, but rotating
the Telegram bot token later will make existing stored credentials
unreadable unless you set `BOT_CREDENTIAL_KEY` to the previous key material
first.

Credential validation for skill setup is host-restricted by default. Built-in
validation currently allows `api.github.com`, `*.openai.com`,
`*.anthropic.com`, and `*.googleapis.com`. If you trust an additional
provider, add it with `BOT_CREDENTIAL_VALIDATION_ALLOWED_HOSTS`.

## Choose A Path

| If you want... | Use... |
|---|---|
| one private bot for yourself | `./scripts/app/guided_start.sh` |
| a bot that appears in the Registry UI | `./scripts/app/guided_start.sh` and choose registry mode |
| multiple bots from one checkout | `./scripts/app/guided_start.sh <instance>` |
| webhook ingress plus multiple workers | `./scripts/app/shared_start.sh` after your bot is already configured |

If you are unsure, start with `guided_start.sh`. It is the primary path.

## First-Time Setup

### Step 1 — Create your Telegram bot token

1. Open Telegram, search for **@BotFather**, and tap Start.
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

The script:

- creates `.env.bot` if needed
- helps you choose `claude` or `codex`
- walks you through provider login if required
- starts the bot in Docker
- can also start a local registry if you choose registry mode

For most people:

- choose `quick` setup
- choose `standalone` if you want one private bot
- choose `registry` if you want the Registry UI and multi-bot features

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
Open it, log in with `REGISTRY_UI_TOKEN`, and confirm the bot appears as
connected.

## Registry UI

When you run in registry mode, the setup output prints a URL like:

```text
http://localhost:8787/ui
```

Log in with `REGISTRY_UI_TOKEN` from `.env.registry`.

![Registry UI screenshot](registry-ui-screenshot.png)

Use the Registry UI when you want to:

- see all connected bots in one place
- search conversations and browse timelines
- start work without switching to Telegram
- approve or cancel delegation plans
- inspect runtime-health summaries for registry-connected bots
- manage skills centrally

The Registry UI is the operator-facing control plane. Telegram is still the
main end-user surface.

## Day-To-Day Use

Most interaction is just normal Telegram chat.

- send a message to ask for work
- turn approval on if you want to review a plan first
- upload files when you want the bot to inspect them
- use `/cancel` to stop the current request
- use `/settings` if you want to change chat behavior
- use `/doctor` if you want a plain-language health check

Long replies work well on mobile with compact mode enabled. Use `/raw` if you
need the full uncompressed response.

## Shared Runtime For Operators

Shared Runtime is the scaled deployment path:

- one webhook process receives Telegram updates
- one or more worker processes drain the durable queue
- queue ownership and stale-claim recovery are handled by the app runtime

Use this when you need:

- webhook-based deployment instead of a single local process
- multiple workers
- durable replay-notice recovery after worker failure

Start it with:

```bash
./scripts/app/shared_start.sh
```

This is an operator path, not the first-time-user path. Start with
`guided_start.sh`, confirm the bot works, then move to Shared Runtime if you
actually need it.

### Shared Runtime prerequisites

- Docker
- a configured bot env file from the guided setup
- a publicly reachable HTTPS webhook URL
- a built and authenticated provider image

Backend rules:

- SQLite Shared Runtime is supported on one Docker host only
- Postgres Shared Runtime is supported when you intentionally switch the bot to Postgres
- even with Postgres, bot-local files still live in the shared bot volume

### Shared Runtime scaling

Scale workers with:

```bash
BOT_WORKER_REPLICAS=4 ./scripts/app/shared_start.sh
```

### Shared Runtime verification

Check logs with:

```bash
BOT_ENV_FILE=.env.bot docker compose --project-directory . \
  -f infra/compose/docker-compose.yml \
  -f infra/compose/docker-compose.shared.yml \
  --profile bot logs -f bot-webhook bot-worker
```

What to verify:

- the webhook service is up
- worker processes have distinct `host:pid:uuid` worker IDs
- work is draining from the queue
- in registry mode, the Registry UI shows runtime-health summary badges

### Return to Local Runtime

Stop the shared stack and go back to:

```bash
./scripts/app/guided_start.sh
```

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

If you want the full operator health check locally, use:

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
2. check that your bot shows as connected in the UI
3. rerun `./scripts/app/guided_start.sh`

For manual registry startup, use:

```bash
./scripts/registry/start.sh
```

### After a `git pull`

Run:

```bash
./scripts/app/guided_start.sh
```

That is the normal upgrade/restart path for the primary setup flow.

If you are running Shared Runtime instead, rerun:

```bash
./scripts/app/shared_start.sh
```

## Programmatic API

The registry service exposes a JSON API in addition to the browser UI.

Live API reference is built in:

- Swagger UI: `http://localhost:8787/docs`
- OpenAPI JSON: `http://localhost:8787/openapi.json`

Authentication modes:

- `GET /healthz`: no auth
- `/v1/agents/*`: `Authorization: Bearer <agent_token>`
- `/v1/ui/*`: `Authorization: Bearer <REGISTRY_UI_TOKEN>`
- `/ui`: browser session/cookie auth

External systems can start registry-backed conversations without using the UI:

```bash
curl -X POST http://localhost:8787/v1/ui/conversations \
  -H "Authorization: Bearer $REGISTRY_UI_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target_agent_id": "abc123", "message_text": "Run the nightly report"}'
```

Bots use the agent API to enroll, heartbeat, publish timeline events, poll
deliveries, and acknowledge work. The interactive schema and request/response
models are available from the built-in FastAPI docs.

## More Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md): system architecture and boundaries
