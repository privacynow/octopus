#!/usr/bin/env bash
# Start the central registry service for same-host Docker use.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"

. "$REPO_DIR/scripts/lib/state.sh"
. "$REPO_DIR/scripts/lib/docker.sh"
. "$REPO_DIR/scripts/lib/registry.sh"

ensure_deploy_dirs
ensure_local_registry

ENV_FILE=".deploy/registry/.env"
set -a
. "$ENV_FILE"
set +a

echo "Registry UI: http://localhost:${REGISTRY_PORT:-8787}/ui"
echo "Registry secrets are stored in $ENV_FILE (keep this file private)."
