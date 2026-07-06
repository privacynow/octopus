#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"

provider="${1:-${BOT_PROVIDER:-}}"
case "$provider" in
  claude|codex) ;;
  *)
    echo "Usage: ./scripts/provider/provider_login.sh <claude|codex>" >&2
    exit 1
    ;;
esac

auth_dir=".deploy/provider-auth/$provider"
python3 -m app.provider_auth ensure-shared-layout "$provider" "$auth_dir"

if ! docker image inspect "octopus-agent:$provider" >/dev/null 2>&1; then
  echo "Image octopus-agent:$provider not found. Run ./octopus redeploy bots or ./scripts/provider/build_bot_image.sh $provider first." >&2
  exit 1
fi

if ! docker network inspect octopus-net >/dev/null 2>&1; then
  docker network create octopus-net >/dev/null
fi

echo "Provider login (BOT_PROVIDER=$provider). Uses shared provider auth under .deploy/provider-auth/$provider."
if [ "$provider" = "codex" ]; then
  codex_home="$REPO_DIR/$auth_dir/.codex"
  mkdir -p "$codex_home"
  chmod 700 "$codex_home"
  if ! command -v codex >/dev/null 2>&1; then
    echo "Codex CLI was not found on this host." >&2
    echo "Install the Codex CLI on the host, then rerun:" >&2
    echo "  ./scripts/provider/provider_login.sh codex" >&2
    echo "Octopus stores Codex auth for bots in:" >&2
    echo "  $codex_home" >&2
    exit 127
  fi
  cat <<BANNER
╔══════════════════════════════════════════════════════════════╗
║  ACTION REQUIRED — CODEX LOGIN                              ║
║                                                              ║
║  The script runs host-side Codex login using Octopus' shared ║
║  provider auth directory. If a browser opens a localhost     ║
║  callback URL, it must reach this host terminal.             ║
║                                                              ║
║  Do not run the removed flag:  codex --login                 ║
╚══════════════════════════════════════════════════════════════╝
BANNER
  echo "Running: CODEX_HOME=$codex_home codex login"
  set +e
  CODEX_HOME="$codex_home" codex login
  exit_code=$?
  set -e
  if [ "$exit_code" -ne 0 ]; then
    echo "✗ Codex login command failed." >&2
    echo "  codex login exit code: $exit_code" >&2
    echo "  Run ./scripts/provider/provider_login.sh codex again after fixing the login error." >&2
    exit "$exit_code"
  fi
  if CODEX_HOME="$codex_home" python3 -m app.provider_auth has-runtime-artifacts codex "$HOME"; then
    echo "✓ Codex authentication files were saved for Octopus."
  else
    echo "✗ Codex authentication is still incomplete." >&2
    echo "  The login command returned success, but no Codex auth.json was written under:" >&2
    echo "  $codex_home" >&2
    exit 1
  fi
else
  OCTOPUS_NETWORK="octopus-net" \
  BOT_PROVIDER="$provider" \
  OCTOPUS_RUNTIME_IMAGE="octopus-agent:$provider" \
  PROVIDER_AUTH_DIR="$auth_dir" \
  BOT_ENV_FILE="/dev/null" \
  REGISTRY_ENROLL_TOKEN="${REGISTRY_ENROLL_TOKEN:-placeholder-registry-enroll}" \
  REGISTRY_UI_TOKEN="${REGISTRY_UI_TOKEN:-placeholder-registry-ui}" \
  docker compose \
    --project-directory . \
    -p "octopus-auth-${provider}" \
    -f infra/compose/docker-compose.yml \
    --profile bot \
    run --rm bot-provider sh /app/scripts/provider/container_provider_login.sh
fi

echo "Running live provider health check..."
"$REPO_DIR/scripts/provider/provider_status.sh" "$provider"
