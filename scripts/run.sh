#!/usr/bin/env bash
# Run the bot for a given instance.
# Usage: ./scripts/run.sh <instance>
#        ./scripts/run.sh m1
set -euo pipefail

INSTANCE="${1:?Usage: $0 <instance>}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_DIR/.venv"

if [ ! -d "$VENV" ]; then
    echo "No virtualenv found. Run ./scripts/bootstrap.sh first." >&2
    exit 1
fi

# shellcheck disable=SC1091
source "$REPO_DIR/scripts/env-setup.sh"

# Prevent a parent shell or user-manager environment from overriding the
# selected instance's config file.
unset TELEGRAM_BOT_TOKEN
unset BOT_ALLOW_OPEN
unset BOT_ALLOWED_USERS
unset BOT_PROVIDER
unset BOT_DATABASE_URL
unset BOT_DB_POOL_MIN_SIZE
unset BOT_DB_POOL_MAX_SIZE
unset BOT_DB_CONNECT_TIMEOUT
unset BOT_MODEL
unset BOT_WORKING_DIR
unset BOT_EXTRA_DIRS
unset BOT_DATA_DIR
unset BOT_TIMEOUT_SECONDS
unset BOT_APPROVAL_MODE
unset BOT_ROLE
unset BOT_SKILLS
unset BOT_STREAM_UPDATE_INTERVAL
unset BOT_TYPING_INTERVAL
unset CODEX_SANDBOX
unset CODEX_SKIP_GIT_REPO_CHECK
unset CODEX_FULL_AUTO
unset CODEX_DANGEROUS
unset CODEX_PROFILE
unset BOT_MODE
unset BOT_WEBHOOK_URL
unset BOT_WEBHOOK_LISTEN
unset BOT_WEBHOOK_PORT
unset BOT_WEBHOOK_SECRET
unset BOT_ADMIN_USERS
unset BOT_PROJECTS
unset BOT_MODEL_PROFILES
unset BOT_DEFAULT_PROFILE
unset BOT_PUBLIC_WORKING_DIR
unset BOT_PUBLIC_MODEL_PROFILES
unset BOT_REGISTRY_URL
unset BOT_RATE_LIMIT_PER_MINUTE
unset BOT_RATE_LIMIT_PER_HOUR
unset BOT_COMPACT_MODE
unset BOT_SUMMARY_MODEL

export BOT_INSTANCE="$INSTANCE"
exec "$VENV/bin/python" -m app.main "$INSTANCE"
