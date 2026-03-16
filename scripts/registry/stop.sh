#!/usr/bin/env bash
# Stop the central registry service.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"

docker compose --project-directory . -p telegram-agent-registry -f infra/compose/docker-compose.yml --profile registry stop registry
