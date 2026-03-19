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
  (
    umask 077
    cat > "$ENV_FILE" <<EOF
REGISTRY_BIND_HOST=127.0.0.1
REGISTRY_PORT=8787
REGISTRY_ALLOW_HTTP=1
REGISTRY_ENROLL_TOKEN=$enroll_token
REGISTRY_UI_TOKEN=$ui_token
EOF
  )
  chmod 600 "$ENV_FILE"
  echo "Created $ENV_FILE with local registry tokens."
fi

chmod 600 "$ENV_FILE"

set -a
. "$ENV_FILE"
set +a

docker compose --project-directory . -p telegram-agent-registry -f infra/compose/docker-compose.yml --profile registry up -d registry
echo "Registry UI: http://localhost:${REGISTRY_PORT:-8787}/ui"
echo "Registry secrets are stored in $ENV_FILE (keep this file private)."
