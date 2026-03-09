#!/usr/bin/env bash
# Tests for setup.sh — validates the wizard flow and generated configs.
# Uses a mock validate_token to avoid real credentials and live API calls.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_DIR="$HOME/.config/telegram-agent-bot"
PASS=0
FAIL=0

# Fake token that passes format validation but never hits the real API
FAKE_TOKEN="1234567890:AABBCCDDEEFFaabbccddeeff_0123456789"
FAKE_BOTNAME="test_mock_bot"

check() {
    local desc="$1" got="$2" want="$3"
    if [ "$got" = "$want" ]; then
        echo "  PASS  $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL  $desc (got: '$got', want: '$want')"
        FAIL=$((FAIL + 1))
    fi
}

check_contains() {
    local desc="$1" haystack="$2" needle="$3"
    if echo "$haystack" | grep -qF "$needle"; then
        echo "  PASS  $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL  $desc (missing: '$needle')"
        FAIL=$((FAIL + 1))
    fi
}

cleanup() {
    rm -f "$CONFIG_DIR/test-setup-"*.env
    rm -f "$REPO_DIR/.setup-test-patched.sh"
    # Stop any test services we may have started
    systemctl --user stop "telegram-agent-bot@test-setup-launch.service" 2>/dev/null || true
    systemctl --user disable "telegram-agent-bot@test-setup-launch.service" 2>/dev/null || true
}
trap cleanup EXIT

# --- Create patched setup.sh with mock validate_token ---
# Place it inside the repo so REPO_DIR resolves correctly.
PATCHED_SETUP="$REPO_DIR/.setup-test-patched.sh"

sed '/^validate_token() {$/,/^}$/c\
validate_token() {\
    local token="$1"\
    if ! [[ "$token" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then\
        echo "INVALID_FORMAT"\
        return\
    fi\
    if [ "$token" = "'"$FAKE_TOKEN"'" ]; then\
        echo "OK:'"$FAKE_BOTNAME"'"\
    else\
        echo "REJECTED"\
    fi\
}' "$REPO_DIR/setup.sh" > "$PATCHED_SETUP"
chmod +x "$PATCHED_SETUP"

# Also define the mock for direct unit tests
validate_token() {
    local token="$1"
    if ! [[ "$token" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then
        echo "INVALID_FORMAT"
        return
    fi
    if [ "$token" = "$FAKE_TOKEN" ]; then
        echo "OK:$FAKE_BOTNAME"
    else
        echo "REJECTED"
    fi
}

echo "=== Token validation (mock) ==="

result=$(validate_token "$FAKE_TOKEN")
check "valid token accepted" "$(echo "$result" | cut -d: -f1)" "OK"
check "valid token returns bot name" "$(echo "$result" | cut -d: -f2)" "$FAKE_BOTNAME"

result=$(validate_token "not-a-token")
check "garbage rejected" "$result" "INVALID_FORMAT"

result=$(validate_token "")
check "empty rejected" "$result" "INVALID_FORMAT"

result=$(validate_token "123:ABC_with spaces")
check "spaces rejected" "$result" "INVALID_FORMAT"

result=$(validate_token "123456:AABBCCDD_validformat")
check "unknown token rejected" "$result" "REJECTED"

echo
echo "=== Wizard: claude instance ==="

# Input: token, provider, model, allowed users, decline launch
cleanup
# Re-create patched setup since cleanup removes it
sed '/^validate_token() {$/,/^}$/c\
validate_token() {\
    local token="$1"\
    if ! [[ "$token" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then\
        echo "INVALID_FORMAT"\
        return\
    fi\
    if [ "$token" = "'"$FAKE_TOKEN"'" ]; then\
        echo "OK:'"$FAKE_BOTNAME"'"\
    else\
        echo "REJECTED"\
    fi\
}' "$REPO_DIR/setup.sh" > "$PATCHED_SETUP"
chmod +x "$PATCHED_SETUP"

output=$(echo -e "$FAKE_TOKEN\nclaude\nclaude-opus-4-6\n@alice,@bob\n\n\nn" | "$PATCHED_SETUP" test-setup-claude 2>&1)

check_contains "wizard shows BotFather link" "$output" "https://t.me/BotFather"
check_contains "wizard shows step-by-step" "$output" "/newbot"
check_contains "wizard validates token" "$output" "valid!"
check_contains "wizard shows bot name" "$output" "@${FAKE_BOTNAME}"

# Config summary
check_contains "summary shows instance" "$output" "Instance:       test-setup-claude"
check_contains "summary shows provider" "$output" "Provider:       claude"
check_contains "summary shows model" "$output" "Model:          claude-opus-4-6"
check_contains "summary shows users" "$output" "Allowed users:  @alice,@bob"
check_contains "summary shows timeout" "$output" "Timeout:        3600s"

# Decline launch shows manual steps
check_contains "shows manual launch" "$output" "Manual launch"
check_contains "shows doctor command" "$output" "doctor.sh test-setup-claude"

# Verify generated config
ENV_FILE="$CONFIG_DIR/test-setup-claude.env"
check "config file created" "$(test -f "$ENV_FILE" && echo yes)" "yes"

token_val=$(grep "^TELEGRAM_BOT_TOKEN=" "$ENV_FILE" | cut -d= -f2)
check "token written" "$token_val" "$FAKE_TOKEN"

provider_val=$(grep "^BOT_PROVIDER=" "$ENV_FILE" | cut -d= -f2)
check "provider is claude" "$provider_val" "claude"

model_val=$(grep "^BOT_MODEL=" "$ENV_FILE" | cut -d= -f2)
check "model is opus" "$model_val" "claude-opus-4-6"

users_val=$(grep "^BOT_ALLOWED_USERS=" "$ENV_FILE" | cut -d= -f2)
check "allowed users set" "$users_val" "@alice,@bob"

echo
echo "=== Wizard: codex instance ==="

# Input: token, provider, model, allowed users, decline launch
output=$(echo -e "$FAKE_TOKEN\ncodex\ngpt-5.4\n123456789\n\n\nn" | "$PATCHED_SETUP" test-setup-codex 2>&1)

ENV_FILE="$CONFIG_DIR/test-setup-codex.env"
check "codex config created" "$(test -f "$ENV_FILE" && echo yes)" "yes"

provider_val=$(grep "^BOT_PROVIDER=" "$ENV_FILE" | cut -d= -f2)
check "provider is codex" "$provider_val" "codex"

model_val=$(grep "^BOT_MODEL=" "$ENV_FILE" | cut -d= -f2)
check "model is gpt-5.4" "$model_val" "gpt-5.4"

users_val=$(grep "^BOT_ALLOWED_USERS=" "$ENV_FILE" | cut -d= -f2)
check "allowed users numeric" "$users_val" "123456789"

echo
echo "=== Wizard: existing config is not overwritten ==="

echo "# canary" >> "$CONFIG_DIR/test-setup-codex.env"
# Pipe "n" to decline launch/restart prompt
output=$(echo -e "n" | "$PATCHED_SETUP" test-setup-codex 2>&1)
check_contains "skips existing config" "$output" "already exists"
check_contains "shows existing config summary" "$output" "Current configuration"
check_contains "shows existing provider" "$output" "Provider:"
check "canary preserved" "$(grep -c canary "$CONFIG_DIR/test-setup-codex.env")" "1"

echo
echo "=== Wizard: claude defaults model when blank ==="

rm -f "$CONFIG_DIR/test-setup-default.env"
# Input: token, provider, blank model (defaults), allowed users, decline launch
output=$(echo -e "$FAKE_TOKEN\nclaude\n\n@user\n\n\nn" | "$PATCHED_SETUP" test-setup-default 2>&1)

ENV_FILE="$CONFIG_DIR/test-setup-default.env"
model_val=$(grep "^BOT_MODEL=" "$ENV_FILE" | cut -d= -f2)
check "default model is opus" "$model_val" "claude-opus-4-6"

echo
echo "=== Wizard: blank allowed users is ok ==="

rm -f "$CONFIG_DIR/test-setup-nouser.env"
# Input: token, provider, blank model, blank users, decline launch
output=$(echo -e "$FAKE_TOKEN\nclaude\n\n\n\n\nn" | "$PATCHED_SETUP" test-setup-nouser 2>&1)

ENV_FILE="$CONFIG_DIR/test-setup-nouser.env"
# When blank, the line keeps the inline comment from .env.example — just check no real value was set
users_line=$(grep "^BOT_ALLOWED_USERS=" "$ENV_FILE")
check "allowed users not populated" "$(echo "$users_line" | grep -cE '^BOT_ALLOWED_USERS=\s*(#|$)')" "1"
# Blank users should auto-enable open access so the bot can launch
open_val=$(grep "^BOT_ALLOW_OPEN=" "$ENV_FILE" | tail -1 | cut -d= -f2)
check "blank users enables open access" "$open_val" "1"

echo
echo "=== Wizard: accept launch ==="

rm -f "$CONFIG_DIR/test-setup-launch.env"
# Input: token, provider, model, allowed users, accept launch
output=$(echo -e "$FAKE_TOKEN\nclaude\nclaude-opus-4-6\n@testuser\n\n\ny" | "$PATCHED_SETUP" test-setup-launch 2>&1) || true

check_contains "runs health check" "$output" "health check"
# Systemd may not be available in test env — script should degrade gracefully.
# It should either attempt systemd install or show fallback run instructions.
if echo "$output" | grep -qF "systemd user services are not available"; then
    check_contains "shows fallback run command" "$output" "run.sh"
else
    check_contains "attempts systemd install" "$output" "systemd"
fi

# --- Summary ---
echo
echo "========================================"
echo "  $PASS passed, $FAIL failed"
echo "========================================"
exit $((FAIL > 0 ? 1 : 0))
