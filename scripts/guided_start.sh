#!/usr/bin/env bash
# Single guided path: Postgres, build, provider login (if needed), then start the bot.
# For non-technical users: one script from .env.bot to running bot.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

echo "=== Guided setup and start ==="

# 1. .env.bot
if [ ! -f .env.bot ]; then
  echo "Create .env.bot first with: TELEGRAM_BOT_TOKEN, BOT_PROVIDER (claude or codex), and BOT_ALLOWED_USERS or BOT_ALLOW_OPEN=1"
  echo "Example:"
  echo "  TELEGRAM_BOT_TOKEN=<from @BotFather>"
  echo "  BOT_PROVIDER=claude"
  echo "  BOT_ALLOWED_USERS=123456789"
  echo "See README.md Quick Start step 2."
  exit 1
fi

env_provider=$(grep -E '^\s*BOT_PROVIDER=' .env.bot 2>/dev/null | sed 's/.*=\s*//' | tr -d '\r' | tr -d '"' | tr -d "'" || true)
env_provider="${env_provider:-claude}"

# 2. Postgres + bootstrap + doctor (no bot config required)
echo "Step 1/4: Postgres and database..."
./scripts/dev_up.sh

# 3. Ensure provider image exists and is not stale (repo/Dockerfile changed since build)
echo ""
echo "Step 2/4: Bot image for $env_provider..."
need_build=0
if ! docker image inspect "telegram-agent-bot:$env_provider" >/dev/null 2>&1; then
  need_build=1
else
  # Repo rev changed (e.g. git pull, or file deletions) -> rebuild
  if [ -f .bot-image-build-rev ]; then
    current_rev=$(git rev-parse HEAD 2>/dev/null)
    built_rev=$(cat .bot-image-build-rev 2>/dev/null)
    if [ -n "$current_rev" ] && [ -n "$built_rev" ] && [ "$current_rev" != "$built_rev" ]; then
      need_build=1
      echo "Repo revision changed since image was built; rebuilding."
    fi
  fi
  if [ "$need_build" -eq 0 ]; then
  image_created=$(docker image inspect "telegram-agent-bot:$env_provider" --format '{{.Created}}' 2>/dev/null)
  if [ -n "$image_created" ]; then
    # Parse RFC3339 image timestamp as UTC to avoid timezone skew on non-UTC hosts.
    image_ts=$(python3 -c "
import datetime
s = '''${image_created}'''.strip()
s = s.split('.')[0]
if s.endswith('Z'):
    s = s[:-1] + '+00:00'
elif s[-6] in '+-' and ':' in s[-5:]:
    pass
else:
    s = s + '+00:00'
dt = datetime.datetime.fromisoformat(s)
if dt.tzinfo is None:
    dt = dt.replace(tzinfo=datetime.timezone.utc)
print(int(dt.timestamp()))
" 2>/dev/null)
    get_mtime() { case "$(uname -s)" in Darwin) stat -f %m "$1" 2>/dev/null ;; *) stat -c %Y "$1" 2>/dev/null ;; esac; }
    file_ts=0
    for f in Dockerfile.bot requirements.txt; do
      [ -f "$f" ] && t=$(get_mtime "$f") && [ -n "$t" ] && [ "$t" -gt "$file_ts" ] && file_ts=$t
    done
    for dir in app scripts sql skills; do
      [ -d "$dir" ] && while IFS= read -r f; do
        t=$(get_mtime "$f") && [ -n "$t" ] && [ "$t" -gt "$file_ts" ] && file_ts=$t
      done < <(find "$dir" -type f 2>/dev/null)
    done
    if [ -n "$image_ts" ] && [ "$file_ts" -gt 0 ] && [ "$file_ts" -gt "$image_ts" ]; then
      echo "Repo code or Dockerfile changed since image was built; rebuilding."
      need_build=1
    fi
  fi
  fi
fi
if [ "$need_build" -eq 1 ]; then
  ./scripts/build_bot_image.sh "$env_provider"
else
  echo "Image telegram-agent-bot:$env_provider already present and up to date."
fi

# 4. Provider auth: check, run login if needed, then re-check
echo ""
echo "Step 3/4: Provider auth..."
if ./scripts/provider_status.sh >/dev/null 2>&1; then
  echo "Provider already authenticated."
else
  echo "Provider not authenticated. Running one-time interactive login..."
  ./scripts/provider_login.sh "$env_provider"
  echo "Verifying provider auth..."
  if ! ./scripts/provider_status.sh; then
    echo "Provider health check still failed after login (see above). Check your subscription or re-run provider_login.sh." >&2
    exit 1
  fi
fi

# 5. Start bot and verify it stayed up
echo ""
echo "Step 4/4: Starting bot (background service)..."
docker compose --profile bot --env-file .env.bot up -d bot

echo "Waiting a few seconds to confirm the bot stayed up..."
sleep 5
if docker compose --profile bot ps -a --format '{{.Status}}' bot 2>/dev/null | grep -q Exited; then
  echo "Bot failed to start (container exited). Last logs:" >&2
  docker compose --profile bot logs --tail=40 bot >&2
  exit 1
fi

echo ""
echo "Bot started. Message it in Telegram to use it."
echo "Logs: docker compose --profile bot logs -f bot   Stop: docker compose --profile bot stop bot"
