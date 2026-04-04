#!/usr/bin/env bash
# Initialize the current Postgres schema. Requires OCTOPUS_DATABASE_URL.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="${PYTHON:-$REPO_DIR/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
    PYTHON=python3
fi
cd "$REPO_DIR"
"$PYTHON" -m app.db.cli init
