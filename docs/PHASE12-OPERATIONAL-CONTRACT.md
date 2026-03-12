# Phase 12 — Operational Contract

This document defines the environment and bootstrap contract introduced in Phase 12.
It is the source of truth for: who provisions what, who runs which commands, and
what the app is allowed to do at startup. Current implementation status is in
[STATUS-commercial-polish.md](STATUS-commercial-polish.md).

## Responsibilities (three separate layers)

1. **Infrastructure provisioning**
   - A Postgres service exists and is reachable.
   - May be Docker-managed in development, Docker or external in staging,
     external/managed in production. Phase 12 does not hard-code a specific
     hosting platform.

2. **Database bootstrap and update**
   - The database, runtime role, schema namespace, tables, indexes, and
     schema-version records are created and updated by **explicit repo-owned
     commands** (e.g. `scripts/db_bootstrap.sh`, `scripts/db_update.sh`).
   - This is **not** implicit application startup behavior.

3. **Application runtime**
   - The bot reads runtime config, connects to Postgres, validates schema
     compatibility, and runs.
   - The bot does **not** create the Postgres server, create the database,
     create the role, or apply schema changes on startup.

## Startup rule

- **App startup is validate-only:**
  - Read `BOT_DATABASE_URL`
  - Connect
  - Validate schema/version/layout
  - Fail clearly if not ready
- App startup is **not** allowed to auto-migrate, auto-create roles, or
  "repair" missing schema.

## Environment model

Each running bot environment is an explicit unit.

- One environment has:
  - Environment name (e.g. `dev-alice`, `staging-main`, `prod`)
  - Bot instance name
  - Telegram bot token
  - Runtime config / env file
  - Database: host, database name, schema namespace, runtime role
  - Working directory / branch or release source
- **One database per environment.** Do not mix multiple branch/staging/dev
  environments in one shared runtime database.
- Inside each database, use one runtime schema namespace (e.g. `bot_runtime`).

Side-by-side branch testing = separate app instances and separate Postgres
databases, not one shared database with mixed state.

## Repo-owned workflows (four explicit workflows)

These are the only supported lifecycle operations. The app does not absorb them.

| Workflow      | Purpose |
|---------------|---------|
| **App bootstrap** | Python deps, image build, or app/runtime preparation. `scripts/bootstrap.sh` remains the anchor for non-container and local test environments. |
| **DB bootstrap**  | Apply repo-owned schema to an *existing* database. The database and runtime role must already exist (e.g. Compose postgres image env, or out-of-band provisioning for external Postgres). The CLI reads `BOT_DATABASE_URL` and runs schema SQL only; it does not create the database or role. |
| **DB update**     | Apply pending schema versions to an existing environment before app restart when the repo adds new SQL files. |
| **DB doctor**     | Validate connectivity, schema version, required tables, required indexes, and compatibility with the current build. Can be run without starting the app. |

## Suggested command surface

- `scripts/bootstrap.sh` — app/runtime bootstrap (existing)
- `scripts/db_bootstrap.sh` — first-time DB + schema creation
- `scripts/db_update.sh` — apply pending schema versions
- `scripts/db_doctor.sh` — connectivity and schema validation
- Optional convenience for local dev: e.g. `scripts/dev_up.sh` or `make dev-first`
  or Compose profiles plus one-shot services

CI/CD can automate these later; Phase 12 makes them usable manually first.

## First-time sequence (brand-new development environment)

1. Build or bootstrap the app runtime.
2. Start the Compose Postgres service (or ensure external Postgres is reachable).
3. Wait for Postgres readiness.
4. Run **DB bootstrap** against that Postgres (the DB and role must already exist; with Compose, the postgres image creates them from env):
   - Create schema namespace and apply all repo SQL
5. Write the environment config for the bot:
   - Telegram token, provider/model settings
   - `BOT_DATABASE_URL`
   - Working-dir and policy settings
6. Run **DB doctor**.
7. Start the app container (or host-run app).

The long-term UX can be wrapped in a single convenience command; Phase 12
documents the underlying steps clearly first.

## Zero to running (development, copy-paste)

From a clean clone, with Docker and Docker Compose installed:

1. **Start Postgres and run DB bootstrap and doctor (one-shot):**
   ```bash
   ./scripts/dev_up.sh
   ```
   Or step by step:
   ```bash
   docker compose up -d postgres
   # Wait for healthy (e.g. 5–10 seconds), then:
   docker compose --profile tools run --rm db-bootstrap
   docker compose --profile tools run --rm db-doctor
   ```

2. **Configure the bot:** Create a `.env` in the repo root with at least:
   ```bash
   BOT_DATABASE_URL=postgresql://bot:bot@localhost:5432/bot
   TELEGRAM_BOT_TOKEN=<your Telegram bot token>
   ```
   Add other options as needed (see app config / README).

3. **Start the bot:**
   ```bash
   docker compose up bot
   ```
   Or run on the host (with Python deps and Postgres reachable):
   ```bash
   scripts/bootstrap.sh   # if not done
   export BOT_DATABASE_URL=postgresql://bot:bot@localhost:5432/bot
   python -m app.main
   ```

The app validates the Postgres schema at startup and exits with a clear error if
the database is missing, unreachable, or behind the required schema version.

## Update sequence (existing environment)

- **Code-only change:** Rebuild app image or refresh Python deps, then restart app.
- **Schema change:** Run **DB update** first, then restart app.
- App startup must fail if schema is behind the current build.
- Do not hide schema updates inside bot startup "just this once".

## Canonical development shape

- **Docker:** Both app and Postgres in Docker; Docker Compose as the canonical
  local bring-up path. See repo root `docker-compose.yml` and `Dockerfile`.
- **Services:** `postgres`, `bot`, and one-shot helpers `db-bootstrap`,
  `db-update`, `db-doctor` (profile `tools`; run with
  `docker compose run --rm db-bootstrap` etc.).
- Helper services run from the repo/app image so SQL and validation logic are
  versioned with the code.
- The app container does not run systemd; the container runtime owns the process.

## Runtime config

- `BOT_DATABASE_URL` — app runtime connection string (required when Postgres is
  the backend).
- Pool settings (min/max connections, connect timeout, statement timeout) as
  needed.
- Bootstrap/admin credentials are separate from app runtime credentials; Phase 12
  may use a separate bootstrap URL or bootstrap-only inputs for first-time
  DB/role creation.
- The bot app must not depend on cloud-provider admin credentials; provisioning
  belongs to environment/bootstrap tooling.
