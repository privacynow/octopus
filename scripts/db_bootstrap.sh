#!/usr/bin/env bash
# First-time DB creation: create schema namespace and apply all repo SQL.
# Requires BOT_DATABASE_URL. See docs/PHASE12-OPERATIONAL-CONTRACT.md.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-$REPO_DIR/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
    PYTHON=python3
fi
cd "$REPO_DIR"
"$PYTHON" -m app.db.cli bootstrap
