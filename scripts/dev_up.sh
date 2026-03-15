#!/usr/bin/env bash
# Local Runtime (default): no database to start. Bot uses SQLite in BOT_DATA_DIR.
# Run ./scripts/guided_start.sh to build, provider login, and start the bot.
# For optional Postgres: ./scripts/dev_up_postgres.sh then set BOT_DATABASE_URL in .env.bot.
set -euo pipefail

echo "Local Runtime is the default; no database to start."
echo "To run the bot: ./scripts/guided_start.sh"
echo "Optional Postgres: ./scripts/dev_up_postgres.sh then set BOT_DATABASE_URL in .env.bot."
