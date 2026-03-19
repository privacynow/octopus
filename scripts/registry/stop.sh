#!/usr/bin/env bash
# Stop the central registry service.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"

. "$REPO_DIR/scripts/lib/docker.sh"

registry_compose down --remove-orphans
