#!/usr/bin/env bash
# Friendly setup wrapper.
# Usage: ./setup.sh [instance_name]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTANCE="${1:-}"
CONFIG_DIR="$HOME/.config/telegram-agent-bot"

# --- helpers ---

# Safely set a key=value in an env file without sed injection.
# Handles both uncommented (KEY=...) and commented (# KEY=...) lines.
set_env_value() {
    local file="$1" key="$2" value="$3"
    local tmpfile="${file}.tmp.$$"
    local found=0
    while IFS= read -r line || [ -n "$line" ]; do
        if [[ "$line" =~ ^[[:space:]]*#?[[:space:]]*"$key"= ]]; then
            echo "${key}=${value}"
            found=1
        else
            echo "$line"
        fi
    done < "$file" > "$tmpfile"
    if [ "$found" -eq 0 ]; then
        echo "${key}=${value}" >> "$tmpfile"
    fi
    mv "$tmpfile" "$file"
}

validate_token() {
    local token="$1"
    # Quick format check: digits:alphanumeric
    if ! [[ "$token" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then
        echo "INVALID_FORMAT"
        return
    fi
    # Call Telegram API to verify
    local response
    response=$(curl -sf --max-time 10 "https://api.telegram.org/bot${token}/getMe" 2>/dev/null) || {
        echo "API_ERROR"
        return
    }
    local ok
    ok=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ok',''))" 2>/dev/null)
    if [ "$ok" = "True" ]; then
        local botname
        botname=$(echo "$response" | python3 -c "import sys,json; r=json.load(sys.stdin)['result']; print(r.get('username',''))" 2>/dev/null)
        echo "OK:$botname"
    else
        echo "REJECTED"
    fi
}

show_config() {
    local env_file="$1" instance="$2"
    echo "  Instance:       $instance"
    echo "  Config file:    $env_file"
    echo "  Bot:            @${BOTNAME:-unknown}"

    local val
    val=$(grep "^BOT_PROVIDER=" "$env_file" | cut -d= -f2 | awk '{print $1}')
    echo "  Provider:       ${val:-claude}"

    val=$(grep "^BOT_MODEL=" "$env_file" 2>/dev/null | cut -d= -f2 | awk '{print $1}') || true
    echo "  Model:          ${val:-(provider default)}"

    val=$(grep "^BOT_ALLOWED_USERS=" "$env_file" 2>/dev/null | cut -d= -f2 | awk '{print $1}') || true
    if [ -n "$val" ] && [ "$val" != "#" ]; then
        echo "  Allowed users:  $val"
    else
        echo "  Allowed users:  (not set — configure before use)"
    fi

    val=$(grep "^BOT_ROLE=" "$env_file" 2>/dev/null | cut -d= -f2- | sed 's/^"//;s/"$//') || true
    echo "  Role:           ${val:-(none)}"

    val=$(grep "^BOT_SKILLS=" "$env_file" 2>/dev/null | cut -d= -f2 | awk '{print $1}') || true
    echo "  Skills:         ${val:-(none)}"

    val=$(grep "^BOT_TIMEOUT_SECONDS=" "$env_file" 2>/dev/null | cut -d= -f2 | awk '{print $1}') || true
    echo "  Timeout:        ${val:-300}s"

    val=$(grep "^BOT_WORKING_DIR=" "$env_file" 2>/dev/null | cut -d= -f2 | awk '{print $1}') || true
    echo "  Working dir:    ${val:-\$HOME}"
}

has_systemd_user() {
    systemctl --user status >/dev/null 2>&1
}

install_systemd() {
    local repo_dir="$1" instance="$2"
    if ! has_systemd_user; then
        echo "systemd user services are not available on this system."
        echo "You can run the bot directly instead:"
        echo "  ./scripts/run.sh $instance"
        return 1
    fi
    mkdir -p "$HOME/.config/systemd/user"
    sed "s|REPO_DIR|$repo_dir|g" "$repo_dir/deploy/telegram-agent-bot@.service" \
        > "$HOME/.config/systemd/user/telegram-agent-bot@.service"
    systemctl --user daemon-reload
    systemctl --user enable --now "telegram-agent-bot@${instance}.service"
}

# --- main ---

echo "=== Telegram Agent Bot Setup ==="
echo

# Step 0: prompt for instance name if not given
if [ -z "$INSTANCE" ]; then
    read -rp "Instance name (e.g. my-claude, my-codex): " INSTANCE
    if [ -z "$INSTANCE" ]; then
        echo "Instance name is required." >&2
        exit 1
    fi
fi

ENV_FILE="$CONFIG_DIR/$INSTANCE.env"
BOTNAME=""

# Step 1: bootstrap (stdin closed so pip doesn't eat our interactive input)
BOT_SETUP_RUNNING=1 "$REPO_DIR/scripts/bootstrap.sh" < /dev/null

# Step 2: create instance env if needed
mkdir -p "$CONFIG_DIR"
if [ -f "$ENV_FILE" ]; then
    echo "Instance '$INSTANCE' already exists."
    echo

    # Resolve bot name from existing token
    existing_token=$(grep "^TELEGRAM_BOT_TOKEN=" "$ENV_FILE" | cut -d= -f2 | awk '{print $1}') || true
    if [ -n "$existing_token" ]; then
        result=$(validate_token "$existing_token") || true
        case "$result" in
            OK:*) BOTNAME="${result#OK:}" ;;
        esac
    fi

    echo "=== Current configuration ==="
    echo
    show_config "$ENV_FILE" "$INSTANCE"
    echo
    echo "  Edit config: \$EDITOR $ENV_FILE"

    # Check if already running
    if systemctl --user is-active --quiet "telegram-agent-bot@${INSTANCE}.service" 2>/dev/null; then
        echo
        echo "This bot is currently running."
        read -rp "Restart it? [Y/n]: " RESTART || true
        RESTART="${RESTART:-y}"
        if [[ "$RESTART" =~ ^[Yy]$ ]]; then
            systemctl --user restart "telegram-agent-bot@${INSTANCE}.service"
            sleep 2
            if systemctl --user is-active --quiet "telegram-agent-bot@${INSTANCE}.service"; then
                echo "Restarted! Bot: @${BOTNAME:-your bot}"
            else
                echo "Restart may have failed. Check with:"
                echo "  journalctl --user -u telegram-agent-bot@${INSTANCE}.service -f"
            fi
        fi
    else
        echo
        read -rp "Launch this bot as a service? [Y/n]: " LAUNCH || true
        LAUNCH="${LAUNCH:-y}"
        if [[ "$LAUNCH" =~ ^[Yy]$ ]]; then
            echo
            echo "Running health check..."
            if "$REPO_DIR/scripts/doctor.sh" "$INSTANCE"; then
                echo
                echo "Installing systemd service..."
                if install_systemd "$REPO_DIR" "$INSTANCE"; then
                    echo
                    sleep 2
                    if systemctl --user is-active --quiet "telegram-agent-bot@${INSTANCE}.service"; then
                        echo "Bot is running! Send a message to @${BOTNAME:-your bot} on Telegram."
                    else
                        echo "Service started but may have issues. Check with:"
                        echo "  journalctl --user -u telegram-agent-bot@${INSTANCE}.service -f"
                    fi
                fi
            else
                echo
                echo "Health check failed. Fix the issues above, then try again."
            fi
        fi
    fi
else
    cp "$REPO_DIR/.env.example" "$ENV_FILE"
    echo "Created instance config: $ENV_FILE"
    echo

    # --- Bot token ---
    echo "You need a Telegram bot token from @BotFather."
    echo
    echo "  Step 1: Open BotFather in Telegram:"
    echo "          https://t.me/BotFather"
    echo
    echo "  Step 2: Send:    /newbot"
    echo "  Step 3: Type a display name, e.g.:  My Claude Agent"
    echo "  Step 4: Type a username (must end in 'bot'), e.g.:  my_claude_agent_bot"
    echo "  Step 5: BotFather replies with your token. Copy it."
    echo

    while true; do
        read -rp "Paste your bot token here: " BOT_TOKEN
        if [ -z "$BOT_TOKEN" ]; then
            echo "  Token is required. Try again."
            continue
        fi

        echo -n "  Validating... "
        result=$(validate_token "$BOT_TOKEN")
        case "$result" in
            OK:*)
                BOTNAME="${result#OK:}"
                echo "valid! Bot: @${BOTNAME}"
                set_env_value "$ENV_FILE" "TELEGRAM_BOT_TOKEN" "$BOT_TOKEN"
                break
                ;;
            INVALID_FORMAT)
                echo "token format looks wrong (expected digits:letters)."
                echo "  Double-check you copied the full token from BotFather."
                ;;
            API_ERROR)
                echo "could not reach Telegram API."
                echo "  Check your internet connection and try again."
                ;;
            REJECTED)
                echo "Telegram rejected this token."
                echo "  It may be revoked or mistyped. Try again."
                ;;
        esac
    done

    # --- Provider ---
    echo
    while true; do
        echo "Provider options: claude, codex"
        read -rp "Provider [claude]: " PROVIDER
        PROVIDER="${PROVIDER:-claude}"
        if [ "$PROVIDER" = "claude" ] || [ "$PROVIDER" = "codex" ]; then
            break
        fi
        echo "  Invalid provider '$PROVIDER'. Must be 'claude' or 'codex'."
    done
    set_env_value "$ENV_FILE" "BOT_PROVIDER" "$PROVIDER"

    # Prune provider-irrelevant config sections
    if [ "$PROVIDER" = "claude" ]; then
        # Remove Codex-specific lines
        tmpfile="${ENV_FILE}.tmp.$$"
        grep -v '^# === Codex-specific' "$ENV_FILE" | grep -v '^# CODEX_' > "$tmpfile"
        mv "$tmpfile" "$ENV_FILE"
    fi

    # --- Model ---
    echo
    if [ "$PROVIDER" = "claude" ]; then
        echo "Model examples: claude-opus-4-6, claude-sonnet-4-6"
        read -rp "Model [claude-opus-4-6]: " MODEL
        MODEL="${MODEL:-claude-opus-4-6}"
    else
        echo "Model examples: gpt-5.4, o3"
        read -rp "Model [provider default]: " MODEL
    fi
    if [ -n "$MODEL" ]; then
        set_env_value "$ENV_FILE" "BOT_MODEL" "$MODEL"
    fi

    # --- Allowed users ---
    echo
    echo "Who can use this bot? Enter Telegram @usernames and/or numeric IDs."
    echo "  Don't know your ID? Leave blank for now — the bot will start in"
    echo "  open-access mode so you can send /id to discover your ID,"
    echo "  then add it to the config and restart."
    echo "  Example: @myusername or @alice,@bob,123456789"
    read -rp "Allowed users [leave blank for open access]: " ALLOWED
    if [ -n "$ALLOWED" ]; then
        set_env_value "$ENV_FILE" "BOT_ALLOWED_USERS" "$ALLOWED"
    else
        # Enable open access so the bot can launch without users configured.
        # The user can /id themselves, add their ID, and disable open access later.
        set_env_value "$ENV_FILE" "BOT_ALLOW_OPEN" "1"
    fi

    # --- Role ---
    echo
    echo "Give the bot a role/persona (optional). Examples:"
    echo "  Senior Python engineer"
    echo "  DevOps specialist managing Kubernetes clusters"
    echo "  For long descriptions, create ${CONFIG_DIR}/${INSTANCE}.role.md"
    read -rp "Role [none]: " BOT_ROLE_INPUT
    if [ -n "$BOT_ROLE_INPUT" ]; then
        # Reject " and \ — direct to role.md for complex roles
        if [[ "$BOT_ROLE_INPUT" == *'"'* ]] || [[ "$BOT_ROLE_INPUT" == *'\\'* ]]; then
            echo "  Role contains \" or \\. Use ${CONFIG_DIR}/${INSTANCE}.role.md instead."
        else
            set_env_value "$ENV_FILE" "BOT_ROLE" "\"${BOT_ROLE_INPUT}\""
        fi
    fi

    # --- Default skills ---
    echo
    echo "Default skills for new conversations (comma-separated, optional)."
    echo "  Available: code-review, testing, debugging, devops,"
    echo "             documentation, security, refactoring, architecture"
    echo "  Users can change active skills per chat via /skills."
    read -rp "Default skills [none]: " BOT_SKILLS_INPUT
    if [ -n "$BOT_SKILLS_INPUT" ]; then
        set_env_value "$ENV_FILE" "BOT_SKILLS" "$BOT_SKILLS_INPUT"
    fi

    # --- Show config summary ---
    echo
    echo "=== Your bot configuration ==="
    echo
    show_config "$ENV_FILE" "$INSTANCE"
    echo
    echo "  Config file: $ENV_FILE"
    echo "  Edit anytime: \$EDITOR $ENV_FILE"

    # --- Offer to launch ---
    echo
    read -rp "Launch this bot now as a service? [Y/n]: " LAUNCH || true
    LAUNCH="${LAUNCH:-y}"
    if [[ "$LAUNCH" =~ ^[Yy]$ ]]; then
        echo
        echo "Running health check..."
        if "$REPO_DIR/scripts/doctor.sh" "$INSTANCE"; then
            echo
            echo "Installing systemd service..."
            if install_systemd "$REPO_DIR" "$INSTANCE"; then
                echo
                sleep 2
                if systemctl --user is-active --quiet "telegram-agent-bot@${INSTANCE}.service"; then
                    echo "Bot is running! Send a message to @${BOTNAME:-your bot} on Telegram."
                else
                    echo "Service started but may have issues. Check with:"
                    echo "  journalctl --user -u telegram-agent-bot@${INSTANCE}.service -f"
                fi
            fi
        else
            echo
            echo "Health check failed. Fix the issues above, then launch manually:"
            echo "  ./scripts/run.sh $INSTANCE"
        fi
    else
        echo
        echo "=== Manual launch ==="
        echo "  ./scripts/doctor.sh $INSTANCE"
        echo "  ./scripts/run.sh $INSTANCE"
        echo
        echo "Or as a systemd service:"
        echo "  mkdir -p ~/.config/systemd/user"
        echo "  sed \"s|REPO_DIR|$REPO_DIR|g\" deploy/telegram-agent-bot@.service \\"
        echo "    > ~/.config/systemd/user/telegram-agent-bot@.service"
        echo "  systemctl --user daemon-reload"
        echo "  systemctl --user enable --now telegram-agent-bot@$INSTANCE.service"
    fi
fi
