#!/usr/bin/env bash
# First-time schema bootstrap for an existing Postgres database.
# Requires BOT_DATABASE_URL. See README.md.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-$REPO_DIR/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
    PYTHON=python3
fi
cd "$REPO_DIR"
"$PYTHON" -m app.db.cli bootstrap
