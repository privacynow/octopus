#!/usr/bin/env bash
# Create virtualenv and install dependencies from requirements.txt.
# Run this after git pull so the venv has the latest dependencies (e.g. python-statemachine).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_DIR/.venv"
PIP="$VENV/bin/pip"
PYTHON="$VENV/bin/python"

if [ -d "$VENV" ]; then
    echo "Virtualenv already exists. Refreshing dependencies from requirements.txt..."
    "$PIP" install -r "$REPO_DIR/requirements.txt" -q
else
    echo "Creating virtualenv..."
    python3 -m venv "$VENV"
    "$PIP" install --upgrade pip -q
    "$PIP" install -r "$REPO_DIR/requirements.txt" -q
    echo "Dependencies installed."
fi

# Smoke test: ensure app imports (catches missing deps like python-statemachine)
if ! "$PYTHON" -c "import app.main"; then
    echo "Dependency check failed. Run: $PIP install -r $REPO_DIR/requirements.txt" >&2
    exit 1
fi

# Install dev/test dependencies only when run standalone (not from setup.sh).
if [ -z "${BOT_SETUP_RUNNING:-}" ]; then
    "$REPO_DIR/.venv/bin/pip" install -r "$REPO_DIR/requirements-dev.txt" -q
fi

# Only show next-steps when run standalone (not from setup.sh)
if [ -z "${BOT_SETUP_RUNNING:-}" ]; then
    echo
    echo "Next: run ./setup.sh to configure an instance."
fi
