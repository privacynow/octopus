#!/usr/bin/env bash
# Operator-script contract tests: provider_login.sh, container_provider_login.sh,
# provider_status.sh, provider_logout.sh. Mocks docker/python/claude/codex to pin
# argv, env propagation, and failure output without using real Docker.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0
FAIL=0

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

cleanup() {
  if [ -n "$TEST_DIR" ] && [ -d "$TEST_DIR" ]; then
    rm -rf "$TEST_DIR"
  fi
  if [ -f "$REPO_DIR/.env.bot.docker_ops_backup" ]; then
    mv "$REPO_DIR/.env.bot.docker_ops_backup" "$REPO_DIR/.env.bot"
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
case "$1" in
  image)
    if [ "$2" = "inspect" ] && echo "$3" | grep -q '^telegram-agent-bot:'; then
      exit "${DOCKER_IMAGE_INSPECT_EXIT:-0}"
    fi
    ;;
esac
echo "$*" > "${RECORD_DOCKER_ARGS:?}"
printf 'BOT_PROVIDER=%s\n' "${BOT_PROVIDER:-}" >> "${RECORD_DOCKER_ENV:-/dev/null}"
exit 0
MOCK_DOCKER
chmod +x "$MOCK_BIN/docker"

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

# --- Tests that run host scripts (provider_login, provider_status, provider_logout) ---
# These need .env.bot in REPO_DIR and docker in PATH.

setup_env_bot() {
  local provider="${1:-claude}"
  if [ -f "$REPO_DIR/.env.bot" ]; then
    cp "$REPO_DIR/.env.bot" "$REPO_DIR/.env.bot.docker_ops_backup"
  fi
  {
    echo "TELEGRAM_BOT_TOKEN=123:fake"
    echo "BOT_PROVIDER=$provider"
    echo "BOT_ALLOW_OPEN=1"
  } > "$REPO_DIR/.env.bot"
}

echo "=== provider_login.sh: override arg is passed to Docker (image exists) ==="
setup_env_bot "claude"
DOCKER_IMAGE_INSPECT_EXIT=0
export DOCKER_IMAGE_INSPECT_EXIT
rm -f "$RECORD_DOCKER_ARGS" "$RECORD_DOCKER_ENV"
export PATH="$MOCK_BIN:$PATH"
"$REPO_DIR/scripts/provider_login.sh" codex >/dev/null 2>&1
docker_args="$(cat "$RECORD_DOCKER_ARGS" 2>/dev/null || true)"
docker_env="$(cat "$RECORD_DOCKER_ENV" 2>/dev/null || true)"
check_contains "compose run with profile and env-file" "$docker_args" "compose --profile bot run --rm --env-file .env.bot"
check_contains "override BOT_PROVIDER=codex in argv" "$docker_args" "BOT_PROVIDER=codex"
check_contains "shell env BOT_PROVIDER=codex for image selection" "$docker_env" "BOT_PROVIDER=codex"
check_contains "service and command" "$docker_args" "bot-provider sh /app/scripts/container_provider_login.sh"

echo
echo "=== provider_login.sh: fallback to .env.bot when no arg (image exists) ==="
setup_env_bot "codex"
rm -f "$RECORD_DOCKER_ARGS"
"$REPO_DIR/scripts/provider_login.sh" >/dev/null 2>&1
docker_args="$(cat "$RECORD_DOCKER_ARGS" 2>/dev/null || true)"
check_contains "fallback BOT_PROVIDER=codex from .env.bot" "$docker_args" "BOT_PROVIDER=codex"

echo
echo "=== provider_login.sh: fails with guided message when image missing ==="
setup_env_bot "codex"
DOCKER_IMAGE_INSPECT_EXIT=1
export DOCKER_IMAGE_INSPECT_EXIT
set +e
stderr="$("$REPO_DIR/scripts/provider_login.sh" codex 2>&1)"
exit_code=$?
set -e
check_exit "exit non-zero when image missing" "$exit_code" "1"
check_contains "stderr says image not found" "$stderr" "telegram-agent-bot:codex not found"
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
PATH="$MOCK_BIN:$PATH" BOT_PROVIDER=codex bash "$REPO_DIR/scripts/container_provider_login.sh" 2> "$stderr_file"
exit_code=$?
set -e
stderr="$(cat "$stderr_file")"
check_contains "stderr contains real doctor error" "$stderr" "DOCTOR_ERR: database not reachable"
check_contains "stderr contains follow-up message" "$stderr" "Provider health check failed (see above)"
check_exit "script exits non-zero on doctor failure" "$exit_code" "1"

echo
echo "=== container_provider_login.sh: codex path runs codex --login ==="
# Python that succeeds so script reaches success
printf '#!/bin/sh\nexit 0\n' > "$MOCK_BIN/python"
chmod +x "$MOCK_BIN/python"
rm -f "$RECORD_CODEX_ARGS" "$RECORD_CLAUDE_ARGS"
PATH="$MOCK_BIN:$PATH" BOT_PROVIDER=codex bash "$REPO_DIR/scripts/container_provider_login.sh" >/dev/null 2>&1
codex_args="$(cat "$RECORD_CODEX_ARGS" 2>/dev/null || true)"
check_contains "codex invoked with --login" "$codex_args" "--login"

echo
echo "=== container_provider_login.sh: claude path runs claude ==="
rm -f "$RECORD_CODEX_ARGS" "$RECORD_CLAUDE_ARGS"
PATH="$MOCK_BIN:$PATH" BOT_PROVIDER=claude bash "$REPO_DIR/scripts/container_provider_login.sh" >/dev/null 2>&1
claude_args="$(cat "$RECORD_CLAUDE_ARGS" 2>/dev/null || true)"
check_contains "claude invoked" "$claude_args" "claude"

echo
echo "=== provider_status.sh: compose run with --provider-health ==="
setup_env_bot "codex"
DOCKER_IMAGE_INSPECT_EXIT=0
export DOCKER_IMAGE_INSPECT_EXIT
rm -f "$RECORD_DOCKER_ARGS"
"$REPO_DIR/scripts/provider_status.sh" >/dev/null 2>&1
docker_args="$(cat "$RECORD_DOCKER_ARGS" 2>/dev/null || true)"
check_contains "compose run with profile and env-file" "$docker_args" "compose --profile bot run --rm --env-file .env.bot"
check_contains "bot-provider service (provider-only)" "$docker_args" "bot-provider"

echo "=== provider_status.sh: fails with rebuild message when image missing ==="
setup_env_bot "codex"
DOCKER_IMAGE_INSPECT_EXIT=1
export DOCKER_IMAGE_INSPECT_EXIT
set +e
stderr="$("$REPO_DIR/scripts/provider_status.sh" 2>&1)"
exit_code=$?
set -e
check_exit "exit non-zero when image missing" "$exit_code" "1"
check_contains "stderr says image not found" "$stderr" "telegram-agent-bot:codex not found"
check_contains "stderr tells user to rebuild" "$stderr" "build_bot_image.sh"

echo
echo "=== provider_logout.sh: compose run with bot and sh -c ==="
DOCKER_IMAGE_INSPECT_EXIT=0
export DOCKER_IMAGE_INSPECT_EXIT
setup_env_bot "codex"
rm -f "$RECORD_DOCKER_ARGS"
"$REPO_DIR/scripts/provider_logout.sh" >/dev/null 2>&1
docker_args="$(cat "$RECORD_DOCKER_ARGS" 2>/dev/null || true)"
check_contains "compose run with profile bot" "$docker_args" "compose --profile bot run --rm"
check_contains "sh -c" "$docker_args" "sh -c"
check_contains "home/bot" "$docker_args" "/home/bot"

echo "=== provider_logout.sh: fails with rebuild message when image missing ==="
DOCKER_IMAGE_INSPECT_EXIT=1
export DOCKER_IMAGE_INSPECT_EXIT
set +e
stderr="$("$REPO_DIR/scripts/provider_logout.sh" 2>&1)"
exit_code=$?
set -e
check_exit "exit non-zero when image missing" "$exit_code" "1"
check_contains "stderr says image not found" "$stderr" "telegram-agent-bot:codex not found"
check_contains "stderr tells user to rebuild" "$stderr" "build_bot_image.sh"

# --- Summary ---
echo
echo "========================================"
echo "  $PASS passed, $FAIL failed"
echo "========================================"
exit $((FAIL > 0 ? 1 : 0))
