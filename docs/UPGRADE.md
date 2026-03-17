# Upgrade Guide

1. Run `git pull`.
2. Run `pip install -r requirements.txt`.
3. Restart the bot. SQLite migrations run automatically on startup.
4. Restart the registry service if it is running.
5. Check `journalctl -u telegram-agent-bot -n 50` for migration log lines.

Notes:
- Sessions and conversations are preserved across upgrades.
- Bot and registry schema versions are tracked automatically and migrate in place on startup.
- Restarting the registry service clears all active Registry UI login sessions.
- `REGISTRY_SESSION_SECRET` (optional): if set, Registry UI login sessions
  survive service restarts. If not set, a random key is generated each time
  the registry starts and all sessions are invalidated on restart. Set this
  in `.env.registry` to preserve sessions across upgrades or restarts.
  Generate a value with: `python3 -c "import secrets; print(secrets.token_hex(32))"`
- Rollback is not automated. If you need to downgrade, restore from a backup taken before upgrading.

## Shared Runtime

Shared Runtime is the split-role deployment tier:

- webhook ingress persists worker-owned updates and returns promptly
- one or more worker processes drain the shared queue
- queue admission is durable per conversation
- stale claimed work re-enters through replay/discard recovery, never auto-runs

### Prerequisites

- Docker
- a built provider image, for example `./scripts/provider/build_bot_image.sh claude`
- `.env.bot` (or `.env.bot.<instance>`) with `TELEGRAM_BOT_TOKEN`
- `BOT_WEBHOOK_URL` set to a publicly reachable HTTPS webhook URL

### SQLite Shared Runtime

- default backend when `BOT_DATABASE_URL` is unset
- supported on one Docker host only
- all bot containers share the same local `bot-home` volume and `BOT_DATA_DIR`
- do not treat network filesystems as supported here

### Postgres Shared Runtime

- enable with `BOT_DATABASE_URL`
- transport and session state move into Postgres
- `bot-home` is still used for provider auth and other bot-local files
- the backend is network-safe for queue/session state, but bot-local files still
  need an intentional deployment layout

### Start Shared Runtime

Run:

```bash
./scripts/app/shared_start.sh
```

The script:

- validates `BOT_WEBHOOK_URL` and `TELEGRAM_BOT_TOKEN`
- rejects registry-mode multi-replica startup for now
- bootstraps/updates Postgres when `BOT_DATABASE_URL` is set
- registers the Telegram webhook and checks for `"ok": true`
- starts the Shared Runtime Compose services:
  - `bot-webhook`
  - `bot-worker` scaled with `BOT_WORKER_REPLICAS`

Scale workers with:

```bash
BOT_WORKER_REPLICAS=4 ./scripts/app/shared_start.sh
```

### Verify Shared Runtime

- inspect logs with:

```bash
BOT_ENV_FILE=.env.bot docker compose --project-directory . \
  -f infra/compose/docker-compose.yml \
  -f infra/compose/docker-compose.shared.yml \
  --profile bot logs -f bot-webhook bot-worker
```

- confirm distinct worker IDs appear as `host:pid:uuid`
- in SQLite mode, keep all containers on the same host

### Revert to Local Runtime

- stop the shared stack
- start the default Local Runtime path again with `./scripts/app/guided_start.sh`
