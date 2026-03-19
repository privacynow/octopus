#!/usr/bin/env bash
# Operator-script contract tests: provider_login.sh, container_provider_login.sh,
# provider_status.sh, provider_logout.sh. Mocks docker/python/claude/codex to pin
# argv, env propagation, and failure output without using real Docker.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0
FAIL=0
HAD_ENV_BOT=0
ENV_BOT_BACKED_UP=0

# Temp dir for mock binaries and record files
TEST_DIR=""
RECORD_DOCKER_ARGS=""
RECORD_CODEX_ARGS=""
RECORD_CLAUDE_ARGS=""

check_contains() {
  local desc="$1" haystack="$2" needle="$3"
  if echo "$haystack" | grep -qF -e "$needle"; then
    echo "  PASS  $desc"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  $desc (missing: '$needle')"
    FAIL=$((FAIL + 1))
  fi
}

check_exit() {
  local desc="$1" got="$2" want="$3"
  if [ "$got" = "$want" ]; then
    echo "  PASS  $desc"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  $desc (exit: $got, want: $want)"
    FAIL=$((FAIL + 1))
  fi
}

check_not_contains() {
  local desc="$1" haystack="$2" needle="$3"
  if echo "$haystack" | grep -qF -e "$needle"; then
    echo "  FAIL  $desc (unexpected: '$needle')"
    FAIL=$((FAIL + 1))
  else
    echo "  PASS  $desc"
    PASS=$((PASS + 1))
  fi
}

check_file_missing() {
  local desc="$1" path="$2"
  if [ ! -e "$path" ]; then
    echo "  PASS  $desc"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  $desc (found: $path)"
    FAIL=$((FAIL + 1))
  fi
}

cleanup() {
  if [ -n "$TEST_DIR" ] && [ -d "$TEST_DIR" ]; then
    rm -rf "$TEST_DIR"
  fi
  if [ -f "$REPO_DIR/.env.bot.docker_ops_backup" ]; then
    mv "$REPO_DIR/.env.bot.docker_ops_backup" "$REPO_DIR/.env.bot"
  elif [ "$HAD_ENV_BOT" = "0" ]; then
    rm -f "$REPO_DIR/.env.bot"
  fi
}
trap cleanup EXIT

TEST_DIR="$(mktemp -d)"
RECORD_DOCKER_ARGS="$TEST_DIR/docker_args"
RECORD_DOCKER_ENV="$TEST_DIR/docker_env"
RECORD_CODEX_ARGS="$TEST_DIR/codex_args"
RECORD_CLAUDE_ARGS="$TEST_DIR/claude_args"

# --- Mock binaries (prepend to PATH) ---
MOCK_BIN="$TEST_DIR/bin"
mkdir -p "$MOCK_BIN"

# docker: "image inspect ..." exits with DOCKER_IMAGE_INSPECT_EXIT; else record argv and env (BOT_PROVIDER for image-selection test)
cat > "$MOCK_BIN/docker" << 'MOCK_DOCKER'
#!/bin/sh
printf '%s\n' "$*" >> "${RECORD_DOCKER_ARGS:?}"
printf 'BOT_PROVIDER=%s\n' "${BOT_PROVIDER:-}" >> "${RECORD_DOCKER_ENV:-/dev/null}"
case "$1" in
  image)
    if [ "$2" = "inspect" ] && echo "$3" | grep -q '^octopus-agent:'; then
      exit "${DOCKER_IMAGE_INSPECT_EXIT:-0}"
    fi
    ;;
  compose)
    case "$*" in
      *" ps -a --format {{.Status}} bot"*)
        printf '%s\n' "${MOCK_DOCKER_PS_STATUS:-}"
        exit 0
        ;;
      *" ps -a --format {{.Service}} {{.Status}} bot-webhook bot-worker"*)
        printf '%s\n' "${MOCK_DOCKER_SHARED_PS_STATUS:-}"
        exit 0
        ;;
      *" run --rm bot python -m app.main --doctor"*)
        printf '%s\n' "${MOCK_DOCKER_RUN_DOCTOR_STDOUT:-}"
        exit "${MOCK_DOCKER_RUN_DOCTOR_EXIT:-0}"
        ;;
      *" run --rm bot-webhook python -m app.main --doctor"*)
        printf '%s\n' "${MOCK_DOCKER_RUN_DOCTOR_STDOUT:-}"
        exit "${MOCK_DOCKER_RUN_DOCTOR_EXIT:-0}"
        ;;
      *" logs "*)
        printf '%s\n' "${MOCK_DOCKER_LOGS_STDERR:-}" >&2
        exit 0
        ;;
    esac
    ;;
esac
exit 0
MOCK_DOCKER
chmod +x "$MOCK_BIN/docker"

cat > "$MOCK_BIN/sleep" << 'MOCK_SLEEP'
#!/bin/sh
exit 0
MOCK_SLEEP
chmod +x "$MOCK_BIN/sleep"

# codex: record "codex $argv", exit 0
cat > "$MOCK_BIN/codex" << 'MOCK_CODEX'
#!/bin/sh
echo "codex $*" >> "${RECORD_CODEX_ARGS:?}"
exit 0
MOCK_CODEX
chmod +x "$MOCK_BIN/codex"

# claude: record "claude $argv", exit 0
cat > "$MOCK_BIN/claude" << 'MOCK_CLAUDE'
#!/bin/sh
echo "claude $*" >> "${RECORD_CLAUDE_ARGS:?}"
exit 0
MOCK_CLAUDE
chmod +x "$MOCK_BIN/claude"

# python: optional; for doctor-failure test we need stderr + exit 1
# We'll create a per-test python wrapper below.
export MOCK_PYTHON_STDERR=""
export MOCK_PYTHON_EXIT="0"

python_mock_script() {
  cat << MOCK_PYTHON
#!/bin/sh
printf '%s\n' "\$MOCK_PYTHON_STDERR" >&2
exit \$MOCK_PYTHON_EXIT
MOCK_PYTHON
}

# Ensure RECORD_* and MOCK_* are exported for the mock scripts (they run in subshells)
export RECORD_DOCKER_ARGS RECORD_DOCKER_ENV RECORD_CODEX_ARGS RECORD_CLAUDE_ARGS
export MOCK_PYTHON_STDERR MOCK_PYTHON_EXIT
export DOCKER_IMAGE_INSPECT_EXIT
export MOCK_DOCKER_PS_STATUS MOCK_DOCKER_SHARED_PS_STATUS MOCK_DOCKER_RUN_DOCTOR_STDOUT MOCK_DOCKER_RUN_DOCTOR_EXIT MOCK_DOCKER_LOGS_STDERR

# --- Tests that run host scripts (provider_login, provider_status, provider_logout) ---
# These need .env.bot in REPO_DIR and docker in PATH.

setup_env_bot() {
  local provider="${1:-claude}"
  local token="${2:-123:fake}"
  if [ -f "$REPO_DIR/.env.bot" ] && [ "$ENV_BOT_BACKED_UP" = "0" ]; then
    HAD_ENV_BOT=1
    cp "$REPO_DIR/.env.bot" "$REPO_DIR/.env.bot.docker_ops_backup"
    ENV_BOT_BACKED_UP=1
  else
    HAD_ENV_BOT="${HAD_ENV_BOT:-0}"
  fi
  {
    echo "TELEGRAM_BOT_TOKEN=$token"
    echo "BOT_PROVIDER=$provider"
    echo "BOT_ALLOW_OPEN=1"
  } > "$REPO_DIR/.env.bot"
}

echo "=== start_instance.sh: rejects placeholder Telegram token before Docker ==="
setup_env_bot "codex" "123:fake"
rm -f "$RECORD_DOCKER_ARGS"
set +e
stderr="$("$REPO_DIR/scripts/app/start_instance.sh" 2>&1)"
exit_code=$?
set -e
check_exit "exit non-zero on placeholder token" "$exit_code" "1"
check_contains "stderr says placeholder token" "$stderr" "still a placeholder"
check_contains "stderr tells operator to use BotFather" "$stderr" "@BotFather"
check_file_missing "docker compose is not invoked on placeholder token" "$RECORD_DOCKER_ARGS"

echo
echo "=== start_instance.sh: proceeds when Telegram token looks real ==="
setup_env_bot "codex" "123456:real-looking-token"
rm -f "$RECORD_DOCKER_ARGS"
PATH="$MOCK_BIN:$PATH" "$REPO_DIR/scripts/app/start_instance.sh" >/dev/null 2>&1
docker_args="$(cat "$RECORD_DOCKER_ARGS" 2>/dev/null || true)"
check_contains "compose up with env-file for bot start" "$docker_args" "compose --project-directory . -f infra/compose/docker-compose.yml --profile bot --env-file .env.bot up -d bot"

echo
echo "=== guided_start.sh: rejects placeholder token before Step 1 ==="
setup_env_bot "codex" "123:fake"
rm -f "$RECORD_DOCKER_ARGS"
set +e
guided_out="$(PATH="$MOCK_BIN:$PATH" "$REPO_DIR/scripts/app/guided_start.sh" 2>&1)"
guided_exit=$?
set -e
check_exit "guided_start exits non-zero on placeholder token" "$guided_exit" "1"
check_contains "guided_start reports placeholder token" "$guided_out" "still a placeholder"
check_not_contains "guided_start does not continue to Step 1" "$guided_out" "Step 1/3"
check_file_missing "guided_start does not invoke docker on placeholder token" "$RECORD_DOCKER_ARGS"

echo
echo "=== guided_start.sh: startup failure runs doctor instead of dumping logs ==="
setup_env_bot "codex" "123456:real-looking-token"
MOCK_DOCKER_PS_STATUS="Exited (1) 2 seconds ago"
MOCK_DOCKER_RUN_DOCTOR_STDOUT="  FAIL: Telegram rejected TELEGRAM_BOT_TOKEN in .env.bot. Update it with a valid token from @BotFather and restart."
MOCK_DOCKER_RUN_DOCTOR_EXIT="1"
MOCK_DOCKER_LOGS_STDERR='RAW TRACEBACK SHOULD NOT BE PRINTED'
export MOCK_DOCKER_PS_STATUS MOCK_DOCKER_RUN_DOCTOR_STDOUT MOCK_DOCKER_RUN_DOCTOR_EXIT MOCK_DOCKER_LOGS_STDERR
rm -f "$RECORD_DOCKER_ARGS"
set +e
guided_out="$(PATH="$MOCK_BIN:$PATH" "$REPO_DIR/scripts/app/guided_start.sh" 2>&1)"
guided_exit=$?
set -e
check_exit "guided_start exits non-zero on failed startup" "$guided_exit" "1"
check_contains "guided_start explains health check rerun" "$guided_out" "Running full app health check for a clearer diagnosis"
check_contains "guided_start includes doctor output" "$guided_out" "Telegram rejected TELEGRAM_BOT_TOKEN"
check_contains "guided_start points to logs command" "$guided_out" "logs_instance.sh"
check_not_contains "guided_start does not dump raw last logs banner" "$guided_out" "Last logs:"
check_not_contains "guided_start does not print raw docker logs by default" "$guided_out" "RAW TRACEBACK SHOULD NOT BE PRINTED"
docker_args="$(cat "$RECORD_DOCKER_ARGS" 2>/dev/null || true)"
check_contains "guided_start runs full doctor after startup failure" "$docker_args" "run --rm bot python -m app.main --doctor"
MOCK_DOCKER_PS_STATUS=""
MOCK_DOCKER_RUN_DOCTOR_STDOUT=""
MOCK_DOCKER_RUN_DOCTOR_EXIT="0"
MOCK_DOCKER_LOGS_STDERR=""
export MOCK_DOCKER_PS_STATUS MOCK_DOCKER_RUN_DOCTOR_STDOUT MOCK_DOCKER_RUN_DOCTOR_EXIT MOCK_DOCKER_LOGS_STDERR

echo
echo "=== shared_start.sh: rejects placeholder token before webhook or Docker ==="
setup_env_bot "codex" "123:fake"
{
  echo "BOT_WEBHOOK_URL=https://example.invalid/hook"
  echo "BOT_AGENT_MODE=standalone"
} >> "$REPO_DIR/.env.bot"
rm -f "$RECORD_DOCKER_ARGS"
set +e
shared_out="$(PATH="$MOCK_BIN:$PATH" "$REPO_DIR/scripts/app/shared_start.sh" 2>&1)"
shared_exit=$?
set -e
check_exit "shared_start exits non-zero on placeholder token" "$shared_exit" "1"
check_contains "shared_start reports placeholder token" "$shared_out" "still a placeholder"
check_file_missing "shared_start does not invoke docker on placeholder token" "$RECORD_DOCKER_ARGS"

echo "=== provider_login.sh: override arg is passed to Docker (image exists) ==="
setup_env_bot "claude"
DOCKER_IMAGE_INSPECT_EXIT=0
export DOCKER_IMAGE_INSPECT_EXIT
rm -f "$RECORD_DOCKER_ARGS" "$RECORD_DOCKER_ENV"
export PATH="$MOCK_BIN:$PATH"
"$REPO_DIR/scripts/provider/provider_login.sh" codex >/dev/null 2>&1
docker_args="$(cat "$RECORD_DOCKER_ARGS" 2>/dev/null || true)"
docker_env="$(cat "$RECORD_DOCKER_ENV" 2>/dev/null || true)"
check_contains "compose run with project dir, compose file, profile and env-file" "$docker_args" "compose --project-directory . -f infra/compose/docker-compose.yml --profile bot --env-file .env.bot run --rm"
check_contains "override BOT_PROVIDER=codex in argv" "$docker_args" "BOT_PROVIDER=codex"
check_contains "shell env BOT_PROVIDER=codex for image selection" "$docker_env" "BOT_PROVIDER=codex"
check_contains "service and command" "$docker_args" "bot-provider sh /app/scripts/provider/container_provider_login.sh"

echo
echo "=== provider_login.sh: fallback to .env.bot when no arg (image exists) ==="
setup_env_bot "codex"
rm -f "$RECORD_DOCKER_ARGS"
"$REPO_DIR/scripts/provider/provider_login.sh" >/dev/null 2>&1
docker_args="$(cat "$RECORD_DOCKER_ARGS" 2>/dev/null || true)"
check_contains "fallback BOT_PROVIDER=codex from .env.bot" "$docker_args" "BOT_PROVIDER=codex"

echo
echo "=== provider_login.sh: fails with guided message when image missing ==="
setup_env_bot "codex"
DOCKER_IMAGE_INSPECT_EXIT=1
export DOCKER_IMAGE_INSPECT_EXIT
set +e
stderr="$("$REPO_DIR/scripts/provider/provider_login.sh" codex 2>&1)"
exit_code=$?
set -e
check_exit "exit non-zero when image missing" "$exit_code" "1"
check_contains "stderr says image not found" "$stderr" "octopus-agent:codex not found"
check_contains "stderr tells user to rebuild" "$stderr" "build_bot_image.sh codex"

echo
echo "=== container_provider_login.sh: doctor failure output preserved ==="
# Fake python that prints recognizable stderr and exits 1
MOCK_PYTHON_STDERR="DOCTOR_ERR: database not reachable"
MOCK_PYTHON_EXIT="1"
export MOCK_PYTHON_STDERR MOCK_PYTHON_EXIT
printf '#!/bin/sh\nprintf "%%s\n" "$MOCK_PYTHON_STDERR" >&2\nexit %s\n' "$MOCK_PYTHON_EXIT" > "$MOCK_BIN/python"
chmod +x "$MOCK_BIN/python"
rm -f "$RECORD_CODEX_ARGS"
stderr_file="$TEST_DIR/doctor_stderr"
set +e
PATH="$MOCK_BIN:$PATH" BOT_PROVIDER=codex bash "$REPO_DIR/scripts/provider/container_provider_login.sh" 2> "$stderr_file"
exit_code=$?
set -e
stderr="$(cat "$stderr_file")"
check_contains "stderr contains real doctor error" "$stderr" "DOCTOR_ERR: database not reachable"
check_contains "stderr contains follow-up message" "$stderr" "Provider health check failed (see above)"
check_exit "script exits non-zero on doctor failure" "$exit_code" "1"

echo
echo "=== container_provider_login.sh: codex path runs codex login --device-auth ==="
# Python that succeeds so script reaches success
printf '#!/bin/sh\nexit 0\n' > "$MOCK_BIN/python"
chmod +x "$MOCK_BIN/python"
rm -f "$RECORD_CODEX_ARGS" "$RECORD_CLAUDE_ARGS"
PATH="$MOCK_BIN:$PATH" BOT_PROVIDER=codex bash "$REPO_DIR/scripts/provider/container_provider_login.sh" >/dev/null 2>&1
codex_args="$(cat "$RECORD_CODEX_ARGS" 2>/dev/null || true)"
check_contains "codex invoked with login" "$codex_args" "login"
check_contains "codex invoked with device auth" "$codex_args" "--device-auth"

echo
echo "=== container_provider_login.sh: non-zero provider exit still reaches health check ==="
cat > "$MOCK_BIN/codex" << 'MOCK_CODEX_FAIL'
#!/bin/sh
echo "codex $*" >> "${RECORD_CODEX_ARGS:?}"
exit 7
MOCK_CODEX_FAIL
chmod +x "$MOCK_BIN/codex"
printf '#!/bin/sh\nexit 0\n' > "$MOCK_BIN/python"
chmod +x "$MOCK_BIN/python"
rm -f "$RECORD_CODEX_ARGS"
set +e
stdout="$(PATH="$MOCK_BIN:$PATH" BOT_PROVIDER=codex bash "$REPO_DIR/scripts/provider/container_provider_login.sh" 2>&1)"
exit_code=$?
set -e
check_exit "script continues after non-zero provider exit when health check succeeds" "$exit_code" "0"
check_contains "warns about provider exit code" "$stdout" "exit code 7"
check_contains "still runs health success path" "$stdout" "Provider login and health check succeeded."
cat > "$MOCK_BIN/codex" << 'MOCK_CODEX'
#!/bin/sh
echo "codex $*" >> "${RECORD_CODEX_ARGS:?}"
exit 0
MOCK_CODEX
chmod +x "$MOCK_BIN/codex"

echo
echo "=== container_provider_login.sh: claude path runs claude ==="
rm -f "$RECORD_CODEX_ARGS" "$RECORD_CLAUDE_ARGS"
PATH="$MOCK_BIN:$PATH" BOT_PROVIDER=claude bash "$REPO_DIR/scripts/provider/container_provider_login.sh" >/dev/null 2>&1
claude_args="$(cat "$RECORD_CLAUDE_ARGS" 2>/dev/null || true)"
check_contains "claude invoked" "$claude_args" "claude"

echo
echo "=== provider_status.sh: compose run with --provider-health ==="
setup_env_bot "codex"
DOCKER_IMAGE_INSPECT_EXIT=0
export DOCKER_IMAGE_INSPECT_EXIT
rm -f "$RECORD_DOCKER_ARGS"
"$REPO_DIR/scripts/provider/provider_status.sh" >/dev/null 2>&1
docker_args="$(cat "$RECORD_DOCKER_ARGS" 2>/dev/null || true)"
check_contains "compose run with project dir, compose file, profile and env-file" "$docker_args" "compose --project-directory . -f infra/compose/docker-compose.yml --profile bot --env-file .env.bot run --rm"
check_contains "bot-provider service (provider-only)" "$docker_args" "bot-provider"

echo "=== provider_status.sh: fails with rebuild message when image missing ==="
setup_env_bot "codex"
DOCKER_IMAGE_INSPECT_EXIT=1
export DOCKER_IMAGE_INSPECT_EXIT
set +e
stderr="$("$REPO_DIR/scripts/provider/provider_status.sh" 2>&1)"
exit_code=$?
set -e
check_exit "exit non-zero when image missing" "$exit_code" "1"
check_contains "stderr says image not found" "$stderr" "octopus-agent:codex not found"
check_contains "stderr tells user to rebuild" "$stderr" "build_bot_image.sh"

echo
echo "=== provider_logout.sh: compose run with bot and sh -c ==="
DOCKER_IMAGE_INSPECT_EXIT=0
export DOCKER_IMAGE_INSPECT_EXIT
setup_env_bot "codex"
rm -f "$RECORD_DOCKER_ARGS"
"$REPO_DIR/scripts/provider/provider_logout.sh" >/dev/null 2>&1
docker_args="$(cat "$RECORD_DOCKER_ARGS" 2>/dev/null || true)"
check_contains "compose run with project dir, compose file, profile and env-file" "$docker_args" "compose --project-directory . -f infra/compose/docker-compose.yml --profile bot --env-file .env.bot run --rm"
check_contains "sh -c" "$docker_args" "sh -c"
check_contains "home/bot" "$docker_args" "/home/bot"

echo "=== provider_logout.sh: fails with rebuild message when image missing ==="
DOCKER_IMAGE_INSPECT_EXIT=1
export DOCKER_IMAGE_INSPECT_EXIT
set +e
stderr="$("$REPO_DIR/scripts/provider/provider_logout.sh" 2>&1)"
exit_code=$?
set -e
check_exit "exit non-zero when image missing" "$exit_code" "1"
check_contains "stderr says image not found" "$stderr" "octopus-agent:codex not found"
check_contains "stderr tells user to rebuild" "$stderr" "build_bot_image.sh"

# --- Summary ---
echo
echo "========================================"
echo "  $PASS passed, $FAIL failed"
echo "========================================"
exit $((FAIL > 0 ? 1 : 0))
