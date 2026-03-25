#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_REPO="${1:-/Users/tinker/octopus}"
BACKUP_ROOT="${2:-/Users/tinker/output/bots/telegram-agent-bot/.tmp/octopus-refresh-backups}"
RUN_PYTHON="${RUN_PYTHON:-/Users/tinker/output/bots/telegram-agent-bot/.venv/bin/python}"
RUN_ID="$(date +%s)"
BACKUP_DIR="${BACKUP_ROOT}/${RUN_ID}"
DEPLOY_BACKUP_DIR="${BACKUP_DIR}/.deploy"

octopus_cmd() {
  (
    cd "${SOURCE_REPO}"
    PYTHONPATH="${SOURCE_REPO}" "${RUN_PYTHON}" -m app.octopus_cli "$@"
  )
}

collect_bot_env_files() {
  find "${DEPLOY_BACKUP_DIR}/bots" -mindepth 2 -maxdepth 2 -name '.env' | sort
}

collect_providers() {
  collect_bot_env_files | while IFS= read -r env_file; do
    [ -n "${env_file}" ] || continue
    awk -F= '/^BOT_PROVIDER=/{print $2}' "${env_file}"
  done | sort -u
}

if [ ! -d "${SOURCE_REPO}" ]; then
  echo "Missing source repo: ${SOURCE_REPO}" >&2
  exit 1
fi

if [ ! -x "${RUN_PYTHON}" ]; then
  echo "Missing Python runtime: ${RUN_PYTHON}" >&2
  exit 1
fi

if [ ! -d "${SOURCE_REPO}/.deploy" ]; then
  echo "Missing source deploy dir: ${SOURCE_REPO}/.deploy" >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}"
echo "Backup directory: ${BACKUP_DIR}"

"${SCRIPT_DIR}/backup_octopus_deploy.sh" --source "${SOURCE_REPO}" --target "${BACKUP_DIR}"

echo "Pulling latest code in ${SOURCE_REPO}"
git -C "${SOURCE_REPO}" pull --ff-only

echo "Running octopus clean"
printf 'yes\n' | octopus_cmd clean

echo "Restoring backed up deploy state"
mkdir -p "${SOURCE_REPO}/.deploy"
rsync -a --delete "${DEPLOY_BACKUP_DIR}/" "${SOURCE_REPO}/.deploy/"

echo "Starting fresh registry and bots"
octopus_cmd start --yes
octopus_cmd connect --yes

EXPECTED_BOTS="$(collect_bot_env_files | sed '/^$/d' | wc -l | tr -d ' ')"
if [ "${EXPECTED_BOTS}" -eq 0 ]; then
  echo "No bots found in backup deploy state" >&2
  exit 1
fi

REGISTRY_ENV="${SOURCE_REPO}/.deploy/registry/.env"
REGISTRY_PORT="$(awk -F= '/^REGISTRY_PORT=/{print $2}' "${REGISTRY_ENV}" | tail -n 1)"
REGISTRY_HOST="$(awk -F= '/^REGISTRY_BIND_HOST=/{print $2}' "${REGISTRY_ENV}" | tail -n 1)"
if [ -z "${REGISTRY_HOST}" ]; then
  REGISTRY_HOST="127.0.0.1"
fi
if [ -z "${REGISTRY_PORT}" ]; then
  REGISTRY_PORT="8787"
fi
REGISTRY_URL="http://${REGISTRY_HOST}:${REGISTRY_PORT}"

echo "Waiting for registry health at ${REGISTRY_URL}"
for _ in {1..30}; do
  if curl -fsS "${REGISTRY_URL}/healthz" >/dev/null; then
    break
  fi
  sleep 2
done
curl -fsS "${REGISTRY_URL}/healthz" >/dev/null

echo "Waiting for bot registry connections"
for _ in {1..30}; do
  STATUS="$(octopus_cmd status)"
  CONNECTED_COUNT="$(printf '%s\n' "${STATUS}" | grep -c 'state: connected' || true)"
  if [ "${CONNECTED_COUNT}" -ge "${EXPECTED_BOTS}" ]; then
    break
  fi
  sleep 2
done

STATUS="$(octopus_cmd status)"
printf '%s\n' "${STATUS}"

CONNECTED_COUNT="$(printf '%s\n' "${STATUS}" | grep -c 'state: connected' || true)"
if [ "${CONNECTED_COUNT}" -lt "${EXPECTED_BOTS}" ]; then
  echo "Expected ${EXPECTED_BOTS} connected bots after restore/start, found ${CONNECTED_COUNT}" >&2
  exit 1
fi

collect_providers | while IFS= read -r provider; do
  [ -n "${provider}" ] || continue
  docker image inspect "octopus-agent:${provider}" >/dev/null
done
docker image inspect "octopus-registry-service:latest" >/dev/null

echo "Refresh complete."
echo "Saved deploy snapshot: ${DEPLOY_BACKUP_DIR}"
