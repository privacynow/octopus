#!/usr/bin/env bash
# Shared environment setup for run.sh and doctor.sh.
# Ensures provider CLIs are in PATH under systemd's minimal environment.
# Source this file, don't execute it.

export PATH="$HOME/.local/bin:$PATH"

export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
if [ -s "$NVM_DIR/nvm.sh" ]; then
    # shellcheck disable=SC1091
    source "$NVM_DIR/nvm.sh"
fi

unset_instance_config_env_overrides() {
    local name=""
    unset TELEGRAM_BOT_TOKEN
    unset BOT_ALLOW_OPEN
    unset BOT_ALLOWED_USERS
    unset BOT_PROVIDER
    unset OCTOPUS_DATABASE_URL
    unset BOT_DB_POOL_MIN_SIZE
    unset BOT_DB_POOL_MAX_SIZE
    unset BOT_DB_CONNECT_TIMEOUT
    unset BOT_MODEL
    unset BOT_WORKING_DIR
    unset BOT_EXTRA_DIRS
    unset BOT_DATA_DIR
    unset BOT_TIMEOUT_SECONDS
    unset BOT_APPROVAL_MODE
    unset BOT_ROLE
    unset BOT_SKILLS
    unset BOT_STREAM_UPDATE_INTERVAL
    unset BOT_TYPING_INTERVAL
    unset CODEX_SANDBOX
    unset CODEX_SKIP_GIT_REPO_CHECK
    unset CODEX_FULL_AUTO
    unset CODEX_DANGEROUS
    unset CODEX_PROFILE
    unset BOT_MODE
    unset BOT_WEBHOOK_URL
    unset BOT_WEBHOOK_LISTEN
    unset BOT_WEBHOOK_PORT
    unset BOT_WEBHOOK_SECRET
    unset BOT_ADMIN_USERS
    unset BOT_PROJECTS
    unset BOT_MODEL_PROFILES
    unset BOT_DEFAULT_PROFILE
    unset BOT_PUBLIC_WORKING_DIR
    unset BOT_PUBLIC_MODEL_PROFILES
    unset BOT_REGISTRY_URL
    unset BOT_AGENT_MODE
    unset BOT_AGENT_DISPLAY_NAME
    unset BOT_AGENT_SLUG
    unset BOT_AGENT_ROLE
    unset BOT_AGENT_TAGS
    unset BOT_AGENT_DESCRIPTION
    unset BOT_AGENT_REGISTRY_URL
    unset BOT_AGENT_REGISTRY_ENROLL_TOKEN
    unset BOT_AGENT_REGISTRY_SCOPE
    unset BOT_AGENT_POLL_INTERVAL_SECONDS
    unset BOT_RATE_LIMIT_PER_MINUTE
    unset BOT_RATE_LIMIT_PER_HOUR
    unset BOT_COMPACT_MODE
    unset BOT_SUMMARY_MODEL

    while IFS= read -r name; do
        [ -n "$name" ] && unset "$name"
    done < <(env | sed -n 's/^\(BOT_AGENT_REGISTRY_[0-9][0-9]*_[A-Z_]*\)=.*/\1/p')
}
