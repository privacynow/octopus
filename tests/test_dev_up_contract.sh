#!/usr/bin/env bash
# Contract tests for dev_up.sh: update-first branching, bootstrap only on missing-schema,
# other failures surface and stop. Mocks docker so we never touch real Compose.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0
FAIL=0
TEST_DIR=""
RECORD_DOCKER_INVOCATIONS=""
RECORD_BOOTSTRAP_CALLED=""

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

check_not_contains() {
  local desc="$1" haystack="$2" needle="$3"
  if ! echo "$haystack" | grep -qF -e "$needle"; then
    echo "  PASS  $desc"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  $desc (should not contain: '$needle')"
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

check_file_exists() {
  local desc="$1" path="$2"
  if [ -f "$path" ]; then
    echo "  PASS  $desc"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  $desc (file missing: $path)"
    FAIL=$((FAIL + 1))
  fi
}

check_file_missing() {
  local desc="$1" path="$2"
  if [ ! -f "$path" ]; then
    echo "  PASS  $desc"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  $desc (file should be missing: $path)"
    FAIL=$((FAIL + 1))
  fi
}

cleanup() {
  if [ -n "$TEST_DIR" ] && [ -d "$TEST_DIR" ]; then
    rm -rf "$TEST_DIR"
  fi
  if [ -f "$REPO_DIR/.env.bot.dev_up_test_backup" ]; then
    mv "$REPO_DIR/.env.bot.dev_up_test_backup" "$REPO_DIR/.env.bot"
  elif [ -f "$REPO_DIR/.env.bot" ]; then
    rm -f "$REPO_DIR/.env.bot"
  fi
}
trap cleanup EXIT

TEST_DIR="$(mktemp -d)"
RECORD_DOCKER_INVOCATIONS="$TEST_DIR/docker_invocations"
RECORD_BOOTSTRAP_CALLED="$TEST_DIR/bootstrap_called"
MOCK_BIN="$TEST_DIR/bin"
mkdir -p "$MOCK_BIN"

# Mock docker: record every invocation; for db-update return configured exit code and output;
# for db-bootstrap record that it was called; otherwise succeed (postgres up, pg_isready, db-doctor).
cat > "$MOCK_BIN/docker" << 'MOCKDOCKER'
#!/bin/sh
echo "$*" >> "${RECORD_DOCKER_INVOCATIONS:?}"
case "$*" in
  *db-update*)
    printf '%s' "${DEV_UP_MOCK_UPDATE_OUT:-Update complete.}"
    exit "${DEV_UP_MOCK_UPDATE_RC:-0}"
    ;;
  *db-bootstrap*)
    touch "${RECORD_BOOTSTRAP_CALLED:?}"
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
MOCKDOCKER
chmod +x "$MOCK_BIN/docker"

export RECORD_DOCKER_INVOCATIONS RECORD_BOOTSTRAP_CALLED
export PATH="$MOCK_BIN:$PATH"

# Required so dev_up.sh does not wait 30 seconds in the pg_isready loop
export DEV_UP_SLEEP=0
# Override sleep to no-op in test so we don't wait
if type sleep 2>/dev/null | grep -q builtin; then
  sleep() { return 0; }
  export -f sleep 2>/dev/null || true
fi
# Actually the script calls sleep 1 in the loop; the mock pg_isready succeeds on first call so we only do one sleep. So one second. We could mock sleep too.
sleep_mock() { return 0; }
export -f sleep_mock 2>/dev/null || true
# Simpler: don't override sleep; the test will take 1 second per run. Or we could add a mock for "compose exec" to succeed immediately. Our mock already returns 0 for everything except db-update. So the first "compose exec postgres pg_isready" gets exit 0. So we only go through the loop once, then one "sleep 1". So 1 second. Acceptable. If we want to avoid sleep we could add a "sleep" mock in MOCK_BIN that does nothing. Let me add it.
cat > "$MOCK_BIN/sleep" << 'MOCKSLEEP'
#!/bin/sh
exit 0
MOCKSLEEP
chmod +x "$MOCK_BIN/sleep"
# But the script invokes "sleep" - is it via PATH? Usually yes. So PATH has MOCK_BIN first, so our sleep will be used. Good.

# Run dev_up.sh with given mock update exit code and stdout (passed to child so mock sees them).
run_dev_up() {
  local want_rc="$1" want_out="$2"
  rm -f "$RECORD_BOOTSTRAP_CALLED"
  : > "$RECORD_DOCKER_INVOCATIONS"
  set +e
  DEV_UP_MOCK_UPDATE_RC="$want_rc" DEV_UP_MOCK_UPDATE_OUT="$want_out" \
    "$REPO_DIR/scripts/dev_up.sh" > "$TEST_DIR/dev_up_stdout" 2> "$TEST_DIR/dev_up_stderr"
  echo $?
  set -e
}

# --- 1. Update succeeds: no bootstrap, doctor called ---
echo "=== dev_up: update succeeds -> no bootstrap, doctor called ==="
exitcode=$(run_dev_up 0 "Update complete.")
check_exit "dev_up exits 0 when update succeeds" "$exitcode" "0"
check_file_missing "bootstrap not called" "$RECORD_BOOTSTRAP_CALLED"
invocations=$(cat "$RECORD_DOCKER_INVOCATIONS")
check_contains "db-doctor was run" "$invocations" "db-doctor"
check_not_contains "db-bootstrap was not run" "$invocations" "db-bootstrap"
check_contains "Running DB update (existing schema)" "$(cat "$TEST_DIR/dev_up_stdout")" "Running DB update (existing schema)"
check_contains "dev_up mentions guided_start for full path" "$(cat "$TEST_DIR/dev_up_stdout")" "guided_start"

# --- 2. Update fails with missing-schema message -> bootstrap and doctor ---
echo ""
echo "=== dev_up: update fails with missing-schema -> bootstrap and doctor ==="
exitcode=$(run_dev_up 1 "Schema or schema_migrations table missing. Run DB bootstrap first (scripts/db_bootstrap.sh or python -m app.db.cli bootstrap).")
check_exit "dev_up exits 0 when missing-schema then bootstrap" "$exitcode" "0"
check_file_exists "bootstrap was called" "$RECORD_BOOTSTRAP_CALLED"
invocations=$(cat "$RECORD_DOCKER_INVOCATIONS")
check_contains "db-bootstrap was run" "$invocations" "db-bootstrap"
check_contains "db-doctor was run after bootstrap" "$invocations" "db-doctor"
check_contains "Schema missing; running DB bootstrap" "$(cat "$TEST_DIR/dev_up_stdout")" "Schema missing; running DB bootstrap"

# --- 3. Update fails with other error (e.g. connectivity) -> no bootstrap, exit non-zero ---
echo ""
echo "=== dev_up: update fails with other error -> no bootstrap, exit non-zero ==="
rm -f "$RECORD_BOOTSTRAP_CALLED"
exitcode=$(run_dev_up 1 "Database error: connection refused")
check_exit "dev_up exits non-zero on other update failure" "$exitcode" "1"
check_file_missing "bootstrap not called on other failure" "$RECORD_BOOTSTRAP_CALLED"
stderr=$(cat "$TEST_DIR/dev_up_stderr")
check_contains "stderr says not a fresh database" "$stderr" "This does not look like a fresh database"
check_contains "stderr shows real error" "$stderr" "connection refused"
check_contains "stderr hints rerun dev_up" "$stderr" "rerun ./scripts/dev_up.sh"

# --- 4. Update fails with schema-drift style error -> no bootstrap ---
echo ""
echo "=== dev_up: update fails (schema drift style) -> no bootstrap ==="
rm -f "$RECORD_BOOTSTRAP_CALLED"
exitcode=$(run_dev_up 1 "FAIL: Applying 0002_foo.sql: relation \"x\" does not exist")
check_exit "dev_up exits non-zero on drift-style failure" "$exitcode" "1"
check_file_missing "bootstrap not called on drift failure" "$RECORD_BOOTSTRAP_CALLED"

# --- 5. guided_start.sh propagates dev_up.sh failure (does not continue to image step) ---
echo ""
echo "=== guided_start.sh: propagates dev_up failure, does not continue to Step 2 ==="
if [ -f "$REPO_DIR/.env.bot" ]; then
  cp "$REPO_DIR/.env.bot" "$REPO_DIR/.env.bot.dev_up_test_backup"
fi
printf 'TELEGRAM_BOT_TOKEN=x\nBOT_PROVIDER=claude\nBOT_ALLOWED_USERS=1\n' > "$REPO_DIR/.env.bot"
set +e
DEV_UP_MOCK_UPDATE_RC=1 DEV_UP_MOCK_UPDATE_OUT="Database error: connection refused" \
  PATH="$MOCK_BIN:$PATH" "$REPO_DIR/scripts/guided_start.sh" \
  > "$TEST_DIR/guided_stdout" 2> "$TEST_DIR/guided_stderr"
guided_exit=$?
set -e
check_exit "guided_start exits non-zero when dev_up fails" "$guided_exit" "1"
guided_out=$(cat "$TEST_DIR/guided_stdout" "$TEST_DIR/guided_stderr")
check_contains "guided_start shows DB update failure" "$guided_out" "This does not look like a fresh database"
check_not_contains "guided_start does not continue to image step" "$guided_out" "Step 2/4"

# --- Summary ---
echo ""
echo "========================================"
echo "  $PASS passed, $FAIL failed"
echo "========================================"
exit $((FAIL > 0 ? 1 : 0))
