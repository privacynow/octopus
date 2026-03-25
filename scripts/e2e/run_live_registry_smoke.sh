#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$REPO_DIR/.venv/bin/python}"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Missing Python runtime at $PYTHON_BIN" >&2
  exit 1
fi

exec "$PYTHON_BIN" -m tests.e2e.live_registry_harness "$@"
