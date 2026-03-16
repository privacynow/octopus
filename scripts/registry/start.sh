#!/usr/bin/env bash
# Start the central registry service for same-host Docker use.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"

ENV_FILE=".env.registry"
if [ ! -f "$ENV_FILE" ]; then
  enroll_token="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(24))
PY
)"
  ui_token="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(24))
PY
)"
  cat > "$ENV_FILE" <<EOF
REGISTRY_PORT=8787
REGISTRY_ENROLL_TOKEN=$enroll_token
REGISTRY_UI_TOKEN=$ui_token
EOF
  echo "Created $ENV_FILE with local registry tokens."
fi

set -a
. "$ENV_FILE"
set +a

docker compose --project-directory . -p telegram-agent-registry -f infra/compose/docker-compose.yml --profile registry up -d registry
echo "Registry started: http://localhost:${REGISTRY_PORT:-8787}/ui?token=${REGISTRY_UI_TOKEN}"
echo "Enrollment token is stored in $ENV_FILE."
