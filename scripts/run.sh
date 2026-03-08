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

export BOT_INSTANCE="$INSTANCE"
exec "$VENV/bin/python" -m app.main "$INSTANCE"
