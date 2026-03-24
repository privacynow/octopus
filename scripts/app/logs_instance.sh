#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SLUG="${1:-}"
[ -n "$SLUG" ] || {
  echo "Usage: ./scripts/app/logs_instance.sh <slug>" >&2
  exit 1
}

exec "$REPO_DIR/octopus" logs "$SLUG" --follow

