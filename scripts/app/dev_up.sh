#!/usr/bin/env bash
# Local Runtime (default): no database to start. Bot uses SQLite in BOT_DATA_DIR.
# Run ./octopus to build, provider login, and start the bot.
# For optional Postgres: ./scripts/db/dev_up_postgres.sh then set BOT_DATABASE_URL in the bot env file.
set -euo pipefail

echo "Local Runtime is the default; no database to start."
echo "To run the bot: ./octopus"
echo "Optional Postgres: ./scripts/db/dev_up_postgres.sh then set BOT_DATABASE_URL in the bot env file."
