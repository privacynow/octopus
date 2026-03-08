#!/usr/bin/env bash
# Run health checks for a given instance.
# Usage: ./scripts/doctor.sh <instance>
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
exec "$VENV/bin/python" -m app.main "$INSTANCE" --doctor
