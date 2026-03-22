#!/usr/bin/env bash
# Registry lifecycle helpers.

pick_available_port() {
  local port="${1:-8787}"
  while lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 || \
        docker ps --format '{{.Ports}}' 2>/dev/null | grep -q ":${port}->"; do
    port=$((port + 1))
  done
  echo "$port"
}

REGISTRY_WAS_CREATED=0

ensure_local_registry() {
  REGISTRY_WAS_CREATED=0
  if registry_is_running; then
    return 0
  fi
  if has_local_registry; then
    registry_compose up -d --remove-orphans service
    return $?
  fi

  local port enroll_token ui_token
  REGISTRY_WAS_CREATED=1
  port="$(pick_available_port 8787)"
  enroll_token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  ui_token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"

  mkdir -p .deploy/registry
  cat > .deploy/registry/.env <<EOF
REGISTRY_ENROLL_TOKEN=${enroll_token}
REGISTRY_UI_TOKEN=${ui_token}
REGISTRY_BIND_HOST=127.0.0.1
REGISTRY_PORT=${port}
REGISTRY_ALLOW_HTTP=1
EOF
  chmod 600 .deploy/registry/.env
  registry_compose up -d --remove-orphans service
}
