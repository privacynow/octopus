#!/usr/bin/env bash
# Create virtualenv and install dependencies.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [ -d "$REPO_DIR/.venv" ]; then
    echo "Virtualenv already exists."
    # Always refresh dependencies in case requirements.txt changed
    "$REPO_DIR/.venv/bin/pip" install -r "$REPO_DIR/requirements.txt" -q
else
    echo "Creating virtualenv..."
    python3 -m venv "$REPO_DIR/.venv"
    "$REPO_DIR/.venv/bin/pip" install --upgrade pip -q
    "$REPO_DIR/.venv/bin/pip" install -r "$REPO_DIR/requirements.txt" -q
    echo "Dependencies installed."
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
