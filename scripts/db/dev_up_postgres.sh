#!/usr/bin/env bash
# Start Postgres, run DB init and doctor for the standard runtime.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"

echo "Starting Postgres..."
docker compose --project-directory . -f infra/compose/docker-compose.yml up -d postgres

echo "Building runtime image for DB tools..."
docker build -f infra/docker/Dockerfile.registry -t octopus-registry-service:latest .

echo "Waiting for Postgres to be ready..."
for i in $(seq 1 30); do
  if docker compose --project-directory . -f infra/compose/docker-compose.yml exec postgres pg_isready -U bot -d bot 2>/dev/null; then
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "Postgres did not become ready in time." >&2
    exit 1
  fi
  sleep 1
done

echo "Running DB init..."
OCTOPUS_RUNTIME_IMAGE=octopus-registry-service:latest docker compose --project-directory . -f infra/compose/docker-compose.yml --profile tools run --rm db-init
echo "Running DB doctor..."
OCTOPUS_RUNTIME_IMAGE=octopus-registry-service:latest docker compose --project-directory . -f infra/compose/docker-compose.yml --profile tools run --rm db-doctor

echo "Postgres stack ready. Set OCTOPUS_DATABASE_URL=postgresql://bot:bot@postgres:5432/bot in the bot env file."
echo "To run the bot: ./octopus"
