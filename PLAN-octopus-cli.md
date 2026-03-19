# Implementation Plan: `./octopus` Unified CLI

## Product Contract

- One public command: `./octopus`
- Subcommands: `./octopus status`, `./octopus start`, `./octopus stop`,
  `./octopus logs`, `./octopus doctor`, `./octopus registry`
- No-arg invocation: guided menu (state-aware)
- Delete the legacy guided starter, shared-runtime starter, and env shim entirely
- Keep low-level helpers (`start_instance.sh`, `stop_instance.sh`,
  `logs_instance.sh`) as internal building blocks
- README mentions exactly one primary command

## Data Model

### Per-bot state (source of truth: filesystem)

```
.deploy/
  provider-auth/
    claude/               # Shared Claude auth state (reused across bots)
    codex/                # Shared Codex auth state (reused across bots)
  registry/
    .env                  # REGISTRY_ENROLL_TOKEN, REGISTRY_UI_TOKEN, REGISTRY_PORT, etc.
  bots/
    my-bot/
      .env                # TELEGRAM_BOT_TOKEN, BOT_PROVIDER, BOT_AGENT_MODE, etc.
    work-bot/
      .env
```

Each bot `.env` contains everything needed to run that bot:
- `BOT_INSTANCE=my-bot` (legacy-compatible local instance alias; same as slug for current build)
- `BOT_SLUG=my-bot` (directory name, compose project suffix)
- `BOT_AGENT_SLUG=my-bot` (registry agent mirror of slug)
- `BOT_TELEGRAM_ID=123456789` (stable Telegram bot identity)
- `BOT_TELEGRAM_USERNAME=my_support_bot` (public Telegram handle)
- `BOT_DISPLAY_NAME=My Support Bot` (Octopus display label, editable)
- `BOT_AGENT_DISPLAY_NAME=My Support Bot` (registry agent mirror of display name)
- `TELEGRAM_BOT_TOKEN=...`
- `BOT_PROVIDER=claude|codex`
- `BOT_AGENT_MODE=standalone|registry`
- `BOT_AGENT_REGISTRY_URL=http://registry:8787|https://remote.example.com`
- `BOT_AGENT_REGISTRY_ENROLL_TOKEN=...` (required until enrollment
  succeeds; retained for recovery/re-enrollment)
- All other config (role, tags, timeout, working_dir, etc.)

No generated compose files. One base compose file + per-bot env file +
per-bot compose project name.

### Bot identity model

All bot identity is derived from the Telegram token via `getMe`. The
user is never asked to name the bot — Telegram is the source of truth.

`getMe` returns three identity fields:
- **id** (`123456789`) — stable Telegram bot identity
- **username** (`my_support_bot`) — unique, stable, used for discovery
- **first_name** (`My Support Bot`) — display label, not unique, can change

Octopus persists these in the bot env and maps them to:
- **BOT_TELEGRAM_ID** — the stable bot identity used to detect an
  existing deployment for the same Telegram bot
- **BOT_TELEGRAM_USERNAME** — the public Telegram handle shown in
  status and manage views
- **BOT_AGENT_* mirrors** — the runtime also consumes mirrored registry
  agent fields such as `BOT_AGENT_SLUG`, `BOT_AGENT_DISPLAY_NAME`,
  `BOT_AGENT_ROLE`, and `BOT_AGENT_CAPABILITIES`. These duplicate the
  Octopus-facing fields intentionally so the registry runtime can read a
  single consistent agent-oriented schema.
- **slug** — derived from Telegram username, normalized. Used for Docker
  project names, volume names, filesystem paths. **Immutable after
  creation.** Renaming a slug would require Docker resource migration,
  so it is not supported.
- **display name** (`BOT_DISPLAY_NAME` in `.env`) — set from Telegram
  `first_name` on creation. Editable later via guided edit submenu.

Duplicate detection rules:
- If `BOT_TELEGRAM_ID` already exists in any `.deploy/bots/*/.env`, the
  token belongs to an existing bot. Octopus must offer to manage or
  repair that bot instead of creating `slug-2`.
- `BOT_TELEGRAM_ID` is the authoritative identity key.
- `BOT_TELEGRAM_USERNAME` is a human-readable secondary check and may be
  useful when older env files are incomplete during development.

If the Telegram username later changes, Octopus does not silently
rename Docker resources. A future version may detect the mismatch
and offer a controlled rename, but for this build, the slug is fixed.

```bash
normalize_slug() {
  # Normalize Telegram username to a filesystem/Docker-safe slug
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9-' '-' | sed 's/^-//;s/-$//' | cut -c1-32
}
```

Example: `getMe` returns id `123456789`, username `my_support_bot`,
first_name `My Support Bot` → slug is `my-support-bot`, display name is
`My Support Bot`, Telegram handle is stored as `my_support_bot`.

### Docker resource naming

All Docker resources use the `octopus-` prefix plus the bot slug.
No checkout-scoped hashing — one deployment per bot name.

| Resource | Naming | Example |
|---|---|---|
| Compose project (bot) | `octopus-<slug>` | `octopus-my-support-bot` |
| Bot volume | `octopus-<slug>_bot-home` | Compose auto-prefixes. |
| Network | `octopus-net` | Shared across all bots. |
| Registry project | `octopus-registry` | Single local registry. |
| Registry volume | `octopus-registry_data` | Compose auto-prefixes. |
| Provider auth | `.deploy/provider-auth/<provider>/` | Bind mount, not Docker volume. |

Bots reach local registry at `http://registry:8787` via a network
alias (not `container_name`). Browser reaches it at
`http://localhost:<port>/ui` where `<port>` comes from
`.deploy/registry/.env` `REGISTRY_PORT`.

**Deferred constraint: multi-checkout coexistence is NOT supported.**
Docker resource names (`octopus-net`, `octopus-<slug>`) are
host-global. Two checkouts running the same bot slug will collide.
This is an explicit non-goal for the current build. When multi-checkout
support is added later, it will require checkout-scoped prefixes and
a migration path for running bots. Do not mistake the current naming
scheme for a property that supports concurrent checkouts.

### Registry port model

On first local registry creation, the script picks an available port
(default 8787, increment if taken) and writes it to
`.deploy/registry/.env` as `REGISTRY_PORT`.

### Provider auth model

Provider auth is shared across all bots that use the same provider.
A single Claude or Codex login is reused by every bot using that
provider.

#### Concrete auth paths per provider

**Claude CLI** stores auth at:
- `/home/bot/.claude/`
- `/home/bot/.claude.json`

**Codex CLI** stores auth at:
- `/home/bot/.codex/`

These paths come from the slice-3 integration probe against the actual
provider images, not from historical CLI assumptions.

#### Shared auth directory layout

```
.deploy/provider-auth/
  claude/                  # Contains .claude/ and .claude.json
  codex/                   # Contains .codex/
```

Each provider-auth directory mirrors the subset of the home directory
that contains auth state. It is mounted into containers at the
appropriate paths.

#### Mount model

The provider-auth directory is mounted **read-write** in all
containers. Read-only is attractive but may break runtime behavior:
provider CLIs may need to refresh tokens, update config, write caches,
or manage lock files. Start with read-write scoped to auth paths;
tighten to read-only only after verifying both providers work
correctly with restricted mounts.

```yaml
# In docker-compose.yml — bot service
volumes:
  - ${PROVIDER_AUTH_DIR:-.deploy/provider-auth/${BOT_PROVIDER}}:/home/bot/.provider-auth:rw
  - bot-home:/home/bot/data
```

#### Entrypoint changes for provider-auth mounts

The current `docker-entrypoint.sh` recursively `chown`s all of
`/home/bot` on every container start. This will mutate ownership on
host-side provider-auth files if they are bind-mounted under
`/home/bot`. The entrypoint must be changed to:

1. **Create provider-auth symlinks first** (before chown, before
   dropping privileges):

   **For Claude:**
   ```bash
   ln -sfn /home/bot/.provider-auth/.claude /home/bot/.claude
   ln -sfn /home/bot/.provider-auth/.claude.json /home/bot/.claude.json
   ```

   **For Codex:**
   ```bash
   ln -sfn /home/bot/.provider-auth/.codex /home/bot/.codex
   ```

2. **Only chown the writable bot data path**, not all of `/home/bot`:
   ```bash
   chown -R bot:bot /home/bot/data
   ```
   Do NOT recurse into `/home/bot/.provider-auth` (the bind mount).

3. **Drop privileges** and exec the bot process as usual.

This means:
- One `claude` login → all Claude bots are authenticated
- One `codex` login → all Codex bots are authenticated
- Adding a second Claude bot does NOT require another login
- Provider auth persists across bot creation/deletion
- Host-side auth file ownership is not mutated by container starts

#### BOT_DATA_DIR residual

The Python config loader still falls back to
`Path.home() / ".octopus-agent" / instance` when `BOT_DATA_DIR` is not
set. The compose files explicitly set `BOT_DATA_DIR=/home/bot/data`, so
the containerized `./octopus` path is correct. This remains a debugging
residual for host-run paths: if `BOT_DATA_DIR` is missing, data can land
outside the mounted volume. A future hardening pass could make
`BOT_DATA_DIR` mandatory in Docker.

#### Auth flows by context

**Login flow** (`provider_login.sh`):
- Mount `.deploy/provider-auth/<provider>/` read-write at `/home/bot/.provider-auth`
- Run interactive login inside container
- Auth state writes to the shared directory

**Runtime flow** (bot container):
- Same mount, same symlinks (created by entrypoint)
- Provider CLI reads (and may refresh) auth from shared directory

**Health check flow** (`provider_status.sh`):
- Same mount
- Runs provider CLI status/health command
- This is the authoritative check — not a filesystem marker

#### Auth hint semantics

`provider_auth_hint()` is a fast UX signal for menu display. It does
NOT make authoritative decisions. The hint is:
- **Written** by the octopus CLI after a successful `provider_is_authed()`
  check (writes a `.authed` marker file to `.deploy/provider-auth/<provider>/`)
- **Cleared** by the octopus CLI if `provider_is_authed()` fails
  (removes the marker)
- **Never written by the provider CLI itself** — it is purely an
  octopus-managed cache of the last known auth state

The marker can go stale (e.g. provider-side token expiry). This is
acceptable because:
- It is only used for menu display ("claude: authenticated")
- Any action that depends on auth (starting a bot, skipping login)
  uses the authoritative `provider_is_authed()` check
- If the authoritative check contradicts the hint, the hint is updated

Do NOT use directory existence or file count as a hint. Use only the
explicit `.authed` marker written after a successful status check.

#### Permission hardening

- `.deploy/provider-auth/` directories: `0700`
- Files within: restricted by provider CLI (not overridden)
- `.deploy/provider-auth/` is in `.gitignore`

### Per-deployment state

- Optional local registry under `.deploy/registry/`
- Shared Docker network `octopus-net`
- Base compose files remain in `infra/compose/`

## Internal File Structure

```
octopus                           # Public entrypoint (executable, no .sh)
scripts/
  lib/
    state.sh                      # Discover bots, registry, network, Docker status
    bot.sh                        # Bot env read/write/validate, prompt helpers
    registry.sh                   # Registry lifecycle: create, start, reuse, status
    docker.sh                     # Network creation, compose wrappers, volume helpers
    provider.sh                   # Provider auth: login, status, shared auth volume
    ui.sh                         # Box drawing, menus, progress display
  app/
    start_instance.sh             # Internal: start one bot container
    stop_instance.sh              # Internal: stop one bot container
    logs_instance.sh              # Internal: follow one bot's logs
  provider/
    build_bot_image.sh            # Unchanged
    container_provider_login.sh   # Unchanged
    provider_login.sh             # Updated: uses .deploy/ paths + shared auth volume
    provider_status.sh            # Updated: uses .deploy/ paths + shared auth volume
  registry/
    start.sh                      # Internal: start local registry container
    stop.sh                       # Internal: stop local registry container
  legacy env shim                 # DELETED (absorbed into scripts/lib/*.sh)
  legacy guided starter           # DELETED
  legacy shared-runtime starter   # DELETED
```

The legacy env shim is split into focused files under `scripts/lib/`. The
current 319-line file mixes prompt helpers, env file I/O, Docker compose
wrappers, token validation, and doctor output formatting — that split
maps naturally to `bot.sh`, `docker.sh`, `ui.sh`, `provider.sh`.

## State Detection (`scripts/lib/state.sh`)

```bash
list_bot_slugs()        # ls .deploy/bots/
count_bots()            # list_bot_slugs | wc -l
has_local_registry()    # test -f .deploy/registry/.env
bot_env_file()          # echo ".deploy/bots/$slug/.env"
bot_registry_url()      # grep BOT_AGENT_REGISTRY_URL from bot env
bot_is_standalone()     # BOT_AGENT_MODE=standalone or absent
bot_is_registry()       # BOT_AGENT_MODE=registry
bot_uses_local_reg()    # registry URL matches http://registry:8787
bot_uses_remote_reg()   # registry URL starts with https://
bot_is_running()        # docker compose -p octopus-$slug ps
registry_is_running()   # docker compose -p octopus-registry ps service
network_exists()        # docker network inspect octopus-net
provider_auth_hint()    # test -f .deploy/provider-auth/<provider>/.authed
                        # Fast hint for menu display only — NOT authoritative
                        # Written by octopus after successful authoritative check
provider_is_authed()    # Run provider CLI status command inside container
                        # This is the authoritative check before skipping login
```

These are pure queries — they read `.deploy/` and Docker state, they
do not modify anything.

`provider_auth_hint()` vs `provider_is_authed()`: The hint checks for
a filesystem marker and is fast enough for menu display. The
authoritative check runs the actual provider health/status command.
Use the hint for UX speed; use the authoritative check before any
decision that would skip the login flow.

## Menu Logic

### No-arg invocation: `./octopus`

```
if count_bots == 0:
    run first_bot_flow()

else:
    show menu:
      1. Add a bot
      2. Manage bots          (status, logs, stop, start, doctor)
      3. Connect bot to registry
      4. Advanced              (webhook mode, remote registry, etc.)
```

**Rules:**
- 0 bots → no menu, straight to first-bot flow
- 1 bot → "manage bots" operates on it without asking "which one?"
- 2+ bots → ask only when the operation is bot-specific

### Subcommand invocations

| Command | Behavior |
|---|---|
| `./octopus` | Guided menu (state-aware) |
| `./octopus status` | Show all bots + registry + provider auth status |
| `./octopus start [slug]` | Start existing bot. 1 bot = no slug needed. |
| `./octopus stop [slug]` | Stop bot. 1 bot = no slug needed. |
| `./octopus logs [slug]` | Follow logs. 1 bot = no slug needed. |
| `./octopus doctor [slug]` | Health check. 1 bot = no slug needed. |
| `./octopus registry` | Registry status / manage |

Every subcommand that takes `[slug]` auto-selects when there's one bot.
With 2+ bots and no slug provided, list bots and ask.

## Journeys

### J1: First bot (quick mode — the default)

Trigger: `count_bots == 0`

```
"Let's set up your first bot."

1. Ask: Telegram bot token
   - Show BotFather help if user says "help" or "?"
   - Validate format (digits:alphanumeric)
   - Reject known placeholders

2. Validate token via Telegram getMe API
   - Use Python helper that reads token from stdin (see Token Validation)
   - On success: read id, username, and first_name from response
   - Show: "This token belongs to <first_name> (@<username>)."
   - Derive slug from username, set display name from first_name
   - If BOT_TELEGRAM_ID already exists in `.deploy/bots/*/.env`, this is
     an existing bot: offer to manage/repair that bot instead of
     creating a new deployment
   - On failure: "Token was rejected by Telegram. Check with @BotFather."
     Allow retry (loop back to step 1)

3. Ask: Provider (Claude or Codex) [default: claude]

4. Build Docker image if needed
   - "Building bot image for <provider>... (first time only)"
   - If image exists and repo rev matches: skip silently

5. Provider auth (uses shared provider-auth volume)
   - Run provider_is_authed() (authoritative CLI check, not marker)
   - If already authenticated: skip silently
   - If not: run provider login flow
     (Codex: device-auth URL+code. Claude: interactive /login)
   - Verify auth after login via provider_is_authed()

6. Ensure Docker network
   - Create octopus-net if it doesn't exist

7. Write .deploy/bots/<slug>/.env
   - BOT_SLUG, BOT_TELEGRAM_ID, BOT_TELEGRAM_USERNAME, BOT_DISPLAY_NAME
   - TELEGRAM_BOT_TOKEN, BOT_PROVIDER
   - BOT_AGENT_MODE=standalone
   - BOT_COMPACT_MODE=1, BOT_ALLOW_OPEN=1
   - BOT_TIMEOUT_SECONDS=3600, BOT_WORKING_DIR=/home/bot
   - File permissions: 0600

8. Run health check (--doctor) inside container
   - On Telegram token rejection: offer inline repair (re-ask token)
   - On other failure: show sanitized diagnostics, exit

9. Start bot container
   - docker compose -p octopus-<slug> ... up -d bot
   - Wait 5s, verify container is running
   - On failure: run doctor, show diagnostics, offer token repair

10. Print success box
    ╔═══════════════════════════════════════════╗
    ║  Bot is running!                          ║
    ║                                           ║
    ║  Open Telegram and message @<username>    ║
    ║                                           ║
    ║  ./octopus status    — check bot health   ║
    ║  ./octopus logs      — follow live logs   ║
    ║  ./octopus stop      — stop the bot       ║
    ║                                           ║
    ║  Run ./octopus again to add more bots     ║
    ║  or connect to a registry.                ║
    ╚═══════════════════════════════════════════╝

    If quick mode was used:
    "Advanced settings (role, tags, skills, allowed users) can be
     configured by running ./octopus and choosing Manage bots."
```

### J1-full: First bot (full mode)

Same as J1 but after step 3, before step 4:

```
(Display name and slug are already derived from getMe — no naming prompt.)

4a. Ask: Role [default: empty]
4b. Ask: Tags (comma-separated) [default: empty]
4c. Ask: Description [default: empty]
4d. Ask: Skills (comma-separated) [default: empty]
4e. Ask: Allowed users (blank = open) [default: open]
4f. Ask: Working directory [default: /home/bot]
4g. Ask: Timeout seconds [default: 3600]
4h. Ask: Standalone or Registry? [default: standalone]
    If registry → run J3 inline
4i. Ask: Completion webhook URL [default: empty]
```

Full mode is triggered by: `./octopus --full` or answering "full" when
quick mode offers the hatch: `"Press Enter for quick setup, or type
'full' for advanced options."`

### J2: Add another bot

Trigger: user selects "Add a bot" from menu

Same flow as J1 but:
- Slug and display name derived from getMe (same as J1, no naming prompt)
- If `BOT_TELEGRAM_ID` already exists, do not create a duplicate
  deployment. Offer to manage/repair the existing bot instead.
- Provider auth step uses authoritative check first — if the same
  provider is already authenticated, no login prompt needed
- After step 3, ask: "Connect to registry? [y/N]"
  - If yes:
    - Default to local if local registry exists
    - Still offer "or enter a remote registry URL" as explicit alternative
  - If no: standalone

### J3: Connect bot to registry

Trigger: user selects "Connect bot to registry" or during add-bot

```
1. Select bot (auto if only one)
   - Must be standalone (if already on registry, offer switch instead)

2. Ask: Local or remote registry?
   Default: local

3a. If local:
    - If local registry exists and is running: reuse
    - If local registry exists but stopped: start it
    - If no local registry: create .deploy/registry/.env with
      generated tokens, pick available port, start registry container
    - Registry URL = http://registry:8787
    - Enrollment token = read from .deploy/registry/.env

3b. If remote:
    - Ask: Registry URL (must be https://)
    - Ask: Enrollment token

4. Update bot .env:
   - BOT_AGENT_MODE=registry
   - BOT_AGENT_REGISTRY_URL=<url>
   - BOT_AGENT_REGISTRY_ENROLL_TOKEN=<token>

5. Restart bot container
   - Stop, then start with updated env

6. Verify enrollment
   - Primary: inspect bot's persisted agent state for agent_id/agent_token
     (run doctor/health check that confirms registry connection)
   - Fallback: check container logs for enrollment confirmation
   - Do not rely on log scraping as primary success criterion

7. Print success (context-aware):
   If local registry:
     "Bot <slug> is now connected to the local registry."
     "Registry UI: http://localhost:<port>/ui"
   If remote registry:
     "Bot <slug> is now connected to the registry at <url>."
```

### J4: Disconnect bot from registry

```
1. Select bot (auto if only one, must be registry-connected)
2. Confirm: "Disconnect <slug> from registry? Bot data is preserved. [y/N]"
3. Update bot .env:
   - BOT_AGENT_MODE=standalone
   - Remove BOT_AGENT_REGISTRY_URL, BOT_AGENT_REGISTRY_ENROLL_TOKEN
4. Restart bot container
5. Check: any other bots still using local registry?
   - If no: "No bots use the local registry. Stop it? [y/N]"
6. Print success
```

### J5: Switch bot from local to remote registry

```
1. Select bot (auto if only one, must be on local registry)
2. Ask: Remote registry URL (must be https://)
3. Ask: Remote enrollment token
4. Update bot .env with remote URL + token
5. Restart bot
6. Verify enrollment (state/API-based, not log-based)
7. Check: any other bots still on local registry?
   - If no: offer to stop local registry
8. Print success:
   "Bot <slug> is now connected to the registry at <url>."
```

### J6: Switch bot from remote to local registry

```
1. Select bot (must be on remote registry)
2. Ensure local registry exists and is running (auto-start)
3. Update bot .env: URL=http://registry:8787, token from local .env
4. Restart bot
5. Verify enrollment (state/API-based, not log-based)
6. Print success:
   "Bot <slug> is now connected to the local registry."
   "Registry UI: http://localhost:<port>/ui"
```

### J-status: `./octopus status`

```
Bots:
  My Bot (@my_bot)        claude   standalone   running    (up 3 hours)
  Work Bot (@work_bot)    codex    registry     stopped

Registry:
  local      running    http://localhost:8787/ui

Provider auth:
  claude     authenticated
  codex      not configured
```

If no bots: "No bots configured. Run ./octopus to get started."

Provider auth status uses `provider_auth_hint()` for fast display.
If the user then tries to start a bot and the hint was stale, the
authoritative check will catch it.

### J-manage: Manage bots (from menu)

```
Bot: My Bot (@my_bot) — claude, standalone, running

  1. View logs
  2. Restart
  3. Stop
  4. Health check
  5. Edit settings
  6. Connect to registry
  7. Back
```

"Edit settings" presents a guided submenu for common fields:

```
  Current settings for My Bot (@my_bot):
    Display name:  My Bot
    Provider:      claude
    Mode:          standalone
    Role:          (not set)
    Timeout:       3600s

  What would you like to change?
  1. Display name
  2. Role
  3. Tags
  4. Allowed users
  5. Timeout
  6. Open full config in editor
  7. Back
```

Option 6 opens `$EDITOR` on the env file (or prints its path if no
editor is set). All other options use guided prompts showing the current
value as the default.

## Docker Network Setup (`scripts/lib/docker.sh`)

```bash
ensure_network() {
  if ! docker network inspect octopus-net >/dev/null 2>&1; then
    docker network create octopus-net
  fi
}
```

The compose files use a parameterized external network:

```yaml
# In docker-compose.yml
networks:
  default:
    name: ${OCTOPUS_NETWORK:-octopus-net}
    external: true

services:
  service:
    # ...
    networks:
      default:
        aliases:
          - registry
```

The `OCTOPUS_NETWORK` env var is set by the compose wrapper before
invocation. The registry gets a network alias `registry` (not
`container_name`) so bots can reach it at `http://registry:8787`.

## Compose Wrappers (`scripts/lib/docker.sh`)

```bash
bot_compose() {
  local slug="$1"; shift
  local env_file=".deploy/bots/$slug/.env"
  local provider
  provider="$(read_bot_env_value BOT_PROVIDER "$env_file")"
  local provider_auth_dir=".deploy/provider-auth/${provider:-claude}"
  ensure_network
  OCTOPUS_NETWORK="octopus-net" \
  PROVIDER_AUTH_DIR="$provider_auth_dir" \
  docker compose \
    --project-directory . \
    -p "octopus-${slug}" \
    -f infra/compose/docker-compose.yml \
    --profile bot \
    --env-file "$env_file" \
    "$@"
}

registry_compose() {
  ensure_network
  OCTOPUS_NETWORK="octopus-net" \
  docker compose \
    --project-directory . \
    -p "octopus-registry" \
    -f infra/compose/docker-compose.yml \
    --profile registry \
    --env-file .deploy/registry/.env \
    "$@"
}

provider_compose() {
  local provider="$1"; shift
  local auth_dir=".deploy/provider-auth/$provider"
  mkdir -p "$auth_dir"
  chmod 700 "$auth_dir"
  ensure_network
  OCTOPUS_NETWORK="octopus-net" \
  PROVIDER_AUTH_DIR="$auth_dir" \
  docker compose \
    --project-directory . \
    -p "octopus-auth-${provider}" \
    -f infra/compose/docker-compose.yml \
    --profile bot \
    "$@"
}
```

Per-bot volumes are automatically namespaced by the compose project
name: `octopus-my-support-bot_bot-home`. No additional volume
configuration needed. Provider auth is a bind mount shared across all
bots using that provider.

## Token Validation via getMe

The legacy guided startup flow validated the token format but didn't call
`getMe` until the Docker health check. The consolidated flow should
validate early — before building the image or running provider auth.

The token must not appear in process argv (visible in `ps`). Shell
tools like `curl` put URLs in argv. Use a Python helper instead:

```bash
validate_telegram_token() {
  # Token is passed via stdin — never appears in process args
  # Returns three lines on success: id, username, then first_name
  local token="$1"
  printf '%s' "$token" | python3 -c "
import sys, urllib.request, json

token = sys.stdin.read().strip()
url = f'https://api.telegram.org/bot{token}/getMe'
try:
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read())
    if data.get('ok'):
        result = data['result']
        print(result.get('id', ''))
        print(result.get('username', ''))
        print(result.get('first_name', ''))
        sys.exit(0)
except Exception:
    pass
sys.exit(1)
"
}

# Usage:
# result="$(validate_telegram_token "$token")" || { echo "rejected"; exit 1; }
# telegram_id="$(sed -n '1p' <<< "$result")"
# username="$(sed -n '2p' <<< "$result")"
# display_name="$(sed -n '3p' <<< "$result")"
```

The token is piped via stdin to Python, which uses `urllib` to make
the HTTP call. Python's `urlopen` does not expose the URL in process
argv. The token never appears in:
- shell process args (`ps aux`)
- error output (only "Token was rejected by Telegram.")
- `/proc/<pid>/cmdline`

Returns three lines on success: Telegram id (line 1, used for duplicate
detection), Telegram username (line 2, used to derive slug), and
Telegram first_name (line 3, used as display name). Returns empty +
nonzero exit on failure.

## Replacement of Old Scripts

### Files deleted
- legacy guided startup script
- legacy shared-runtime startup script
- legacy env shim

### Files absorbed
All reusable functions from the legacy env shim move to `scripts/lib/`:
- `prompt_with_default`, `escape_env_value`, `write_env_assignment_line`,
  `upsert_env_file_value`, `prompt_channel_token_with_help`,
  `redact_value_for_prompt`, `print_channel_setup_help` → `scripts/lib/bot.sh`
- `bot_compose`, `bot_shared_compose`, `check_provider_image` → `scripts/lib/docker.sh`
- `format_doctor_output_for_operator`, `print_doctor_output_for_operator`,
  `doctor_output_has_token_rejection` → `scripts/lib/ui.sh`
- `read_bot_env_value`, `get_bot_provider`, `check_env_bot_required`,
  `restrict_secret_file_permissions`, `telegram_token_is_placeholder`,
  `require_real_telegram_token`, `channel_token_looks_plausible`,
  `registry_url_is_local` → `scripts/lib/bot.sh`

### Files updated
- `scripts/app/start_instance.sh` — reads from `.deploy/bots/<slug>/.env`
- `scripts/app/stop_instance.sh` — same
- `scripts/app/logs_instance.sh` — same
- `scripts/provider/provider_login.sh` — uses shared auth volume
- `scripts/provider/provider_status.sh` — uses shared auth volume
- `scripts/registry/start.sh` — writes to `.deploy/registry/.env`,
  uses `octopus-registry` project and network, picks available port
- `scripts/docker/docker-entrypoint.sh` — adds provider auth symlinks
- `infra/compose/docker-compose.yml` — parameterized external network,
  registry network alias, provider-auth bind mount
- `README.md` — single entry point: `./octopus`

## Error Handling Principles

Every user-facing error must follow these rules:

1. **Say what happened** in plain language, not technical jargon
2. **Say what the user can do** — a concrete next action
3. **Never show raw exceptions**, tokens, URLs with auth params, or
   internal paths
4. **Log the technical detail** at debug/warning level for operators
5. **Offer inline repair** when possible (token rejection → re-ask)

Examples:

```
Bad:   telegram.error.InvalidToken: The token `123:fake` was rejected
Good:  Telegram rejected the bot token. Check with @BotFather that
       the token is correct, then paste it here.

Bad:   docker: Error response from daemon: network octopus-net not found
Good:  Docker network setup failed. Is Docker running?
       Try: docker info

Bad:   ConnectionRefusedError: [Errno 111] Connection refused
Good:  Could not reach the registry at http://localhost:8787.
       Is the registry running? Try: ./octopus registry
```

## Delivery Order

### Slice 1: Library foundation

Create `scripts/lib/` directory. Split the legacy env shim into:
- `scripts/lib/bot.sh` — all bot env I/O and token helpers
- `scripts/lib/docker.sh` — compose wrappers, network helpers
- `scripts/lib/provider.sh` — provider auth: login, status, shared volume
- `scripts/lib/ui.sh` — doctor output formatting, box drawing, menus
- `scripts/lib/state.sh` — deployment state queries
- `scripts/lib/registry.sh` — registry lifecycle

Update `start_instance.sh`, `stop_instance.sh`, `logs_instance.sh` to
source from `scripts/lib/` instead of the legacy env shim.

Verify: all existing scripts that sourced the legacy env shim still work.
Run existing tests.

**Commit: "octopus-cli / slice 1: split lib_env into focused libraries"**

### Slice 2: Deploy directory

Create `.deploy/` structure with `provider-auth/`, `registry/`,
`bots/` directories. Add `.deploy/` to `.gitignore`.

Update compose wrappers in `scripts/lib/docker.sh` to read from
`.deploy/bots/<slug>/.env` and use `octopus-<slug>` project names.

Update `start_instance.sh`, `stop_instance.sh`, `logs_instance.sh` to
accept a slug and resolve it through `.deploy/`.

**Commit: "octopus-cli / slice 2: deploy directory structure"**

### Slice 3: Provider auth volume

Create `scripts/lib/provider.sh`. Implement shared provider-auth
directory model with concrete per-provider paths:
- `ensure_provider_auth_dir()` — creates `.deploy/provider-auth/<provider>/`
  with `0700` permissions and the expected subdirectory structure
- `provider_auth_hint()` — fast filesystem marker check (for UX)
- `provider_is_authed()` — runs provider CLI status command (authoritative)
- `provider_login()` — runs login in container with shared auth volume
- `provider_status()` — checks auth in container with shared auth volume

Update `provider_login.sh` and `provider_status.sh` to use the shared
volume. Update compose `bot-provider` service to mount
`PROVIDER_AUTH_DIR`.

Update `docker-entrypoint.sh`:
- Create provider-auth symlinks before chown
- Restrict chown to `/home/bot/data` only (not all of `/home/bot`)
- Leave the shared provider-auth bind mount ownership alone

**Integration probe (required before proceeding to slice 4):**
Build the bot image for each provider. Run a login inside the
container and then `find` the auth directory to confirm exactly which
paths each CLI actually writes to. Compare against the assumed paths
in this plan. If they differ, update the symlink model before
continuing. This is not a test that runs in CI — it is a one-time
manual verification step during development. Record the actual paths
found as a comment in `scripts/lib/provider.sh`.

Test: login once for claude, verify a second bot with the same provider
does not require re-login. Verify host-side auth file ownership is
not mutated by container starts.

**Commit: "octopus-cli / slice 3: shared provider auth volume"**

### Slice 4: Docker network and registry alias

Add `ensure_network()` to `scripts/lib/docker.sh`.
Add parameterized `networks` section to `docker-compose.yml` using
`${OCTOPUS_NETWORK}`.
Add `registry` as a network alias (not `container_name`).
Update `registry/start.sh` to use `octopus-registry` project and
network.
Update bot compose wrapper to pass `OCTOPUS_NETWORK`.

Test: start a registry and a bot, verify the bot can reach
`http://registry:8787` from inside its container.

**Commit: "octopus-cli / slice 4: shared Docker network with registry alias"**

### Slice 5: Token validation via getMe

Add `validate_telegram_token()` to `scripts/lib/bot.sh`.
Token passed via stdin to Python helper — never in process argv.
Returns username on success, empty on failure.
Token never appears in error output.

Test: valid token returns username, invalid token returns empty +
error code, placeholder token is rejected before API call,
`ps aux` during validation does not show the token.

**Commit: "octopus-cli / slice 5: early Telegram token validation"**

### Slice 6: `./octopus` first-bot flow

Create `octopus` (executable, no .sh extension) at repo root.
Implement J1 (first bot quick mode):
- State detection → 0 bots → first-bot flow
- Token prompt → getMe validation (Python, no argv leak) → Telegram id,
  username, display name, and duplicate-bot detection
- Provider selection → authoritative auth check → image build → provider auth
- Write `.deploy/bots/<slug>/.env`
- Health check → start → verify → success box

Test manually: run `./octopus` with no `.deploy/`, verify full flow
produces a running bot.

**Commit: "octopus-cli / slice 6: first-bot flow"**

### Slice 7: `./octopus` add-bot and subcommands

Implement:
- Menu display (when 1+ bots exist)
- J2 (add another bot) — verify shared provider auth works
  - Registry prompt offers remote as explicit alternative even when
    local registry exists
- `./octopus status` (including provider auth status via hint)
- `./octopus start [slug]`
- `./octopus stop [slug]`
- `./octopus logs [slug]`
- `./octopus doctor [slug]`
- Auto-select when 1 bot, ask when 2+

**Commit: "octopus-cli / slice 7: multi-bot management"**

### Slice 8: Registry connect/switch flows

Implement:
- J3 (connect standalone → registry) with auto port selection
  - Enrollment verification via bot state/doctor, not log scraping
  - Context-aware success message (local vs remote)
- J4 (disconnect from registry)
- J5 (local → remote registry)
- J6 (remote → local registry)
- `./octopus registry` subcommand
- Auto-start local registry when needed
- "Any bots still using local registry?" check before offering teardown

**Commit: "octopus-cli / slice 8: registry connect and switch"**

### Slice 9: Full mode, guided edit, and advanced options

Implement:
- J1-full (extended first-bot prompts)
- `--full` flag
- J-manage guided edit submenu (display name, role, tags, timeout, etc.)
- Webhook mode (advanced path only)
- Advanced menu items

**Commit: "octopus-cli / slice 9: full mode, guided edit, advanced"**

### Slice 10: Delete old scripts, update docs

- Delete the legacy guided startup script
- Delete the legacy shared-runtime startup script
- Delete the legacy env shim
- Update `README.md`: single entry point `./octopus`
- Update `ARCHITECTURE.md` if it references old scripts
- Update any test references
- Verify no script or doc references the deleted files

**Commit: "octopus-cli / slice 10: remove old scripts, update docs"**

### Slice 11: Tests

- State detection unit tests (mock filesystem)
- Menu routing tests (0 bots, 1 bot, 2+ bots)
- Token validation tests (Python helper, no token in argv via ps check)
- Telegram identity persistence tests (`BOT_TELEGRAM_ID`,
  `BOT_TELEGRAM_USERNAME`, `BOT_DISPLAY_NAME`)
- Duplicate-bot detection tests (same Telegram id routes to existing bot
  instead of creating `slug-2`)
- Compose wrapper tests (correct project names, env files, network names)
- Single-bot auto-select tests
- Provider auth sharing tests (one login, two bots)
- Provider auth hint vs authoritative check tests
- Registry port selection tests (no collision)
- Enrollment verification tests (state-based, not log-based)
- Provider-auth directory permission tests (0700)
- Doc references: no mention of deleted scripts

**Commit: "octopus-cli / slice 11: CLI tests"**

## Exit Gates

- [ ] `./octopus` with 0 bots runs first-bot flow without a menu
- [ ] `./octopus` with 1+ bots shows state-aware menu
- [ ] `./octopus status` shows all bots, registry, and provider auth
- [ ] `./octopus logs` auto-selects with 1 bot, asks with 2+
- [ ] Quick mode asks only token and provider; no naming prompt
- [ ] Bot env persists `BOT_TELEGRAM_ID`, `BOT_TELEGRAM_USERNAME`, and `BOT_DISPLAY_NAME`
- [ ] Slug derived from Telegram username via getMe; display name from first_name
- [ ] Slug is immutable after creation; display name is editable
- [ ] User sees "This token belongs to <name> (@<username>)" confirmation
- [ ] Re-adding the same Telegram bot routes to the existing deployment instead of creating `slug-2`
- [ ] Provider auth runs only if needed (authoritative CLI check, not marker)
- [ ] Token is validated via getMe before any Docker work
- [ ] Token does not appear in process argv during validation (Python helper)
- [ ] Bot username from getMe is used as default slug
- [ ] Per-bot Docker volumes are isolated (different bots don't share data)
- [ ] Provider auth is shared (one login per provider, not per bot)
- [ ] Adding a second bot with the same provider does not require re-login
- [ ] Provider auth paths verified by slice-3 integration probe against real image
- [ ] Entrypoint chowns only /home/bot/data, not /home/bot (no host auth mutation)
- [ ] Provider-auth symlinks created before chown and before dropping privileges
- [ ] Auth hint (.authed marker) written only after successful authoritative check
- [ ] Local registry uses a network alias `registry`, not `container_name`
- [ ] Local registry is reachable at `http://registry:8787` from bot containers
- [ ] Registry auto-starts when a bot needs it and it's not running
- [ ] Registry port is auto-selected to avoid collisions
- [ ] Standalone → registry conversion preserves bot data
- [ ] Local → remote registry switch works per-bot, not globally
- [ ] J2 registry prompt offers remote as alternative even when local exists
- [ ] Enrollment verification is state/API-based, not log-scraping
- [ ] Enrollment token is retained in bot env for recovery/re-enrollment
- [ ] Success messages are context-aware (local vs remote registry)
- [ ] Common config edits use guided prompts, not raw file editing
- [ ] No raw exceptions, tokens, or internal paths in user-facing output
- [ ] All env files created with 0600 permissions
- [ ] Provider-auth directories created with 0700 permissions
- [ ] Provider-auth mount is read-write (tighten only after verification)
- [ ] the legacy startup scripts and env shim are deleted
- [ ] README mentions only `./octopus` as the primary command
- [ ] All existing tests pass
