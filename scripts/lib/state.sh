#!/usr/bin/env bash
# Deployment state queries.

list_bot_slugs() {
  ls .deploy/bots/ 2>/dev/null || true
}

count_bots() {
  list_bot_slugs | wc -l | tr -d ' '
}

has_local_registry() {
  test -f .deploy/registry/.env
}

bot_env_file() {
  echo ".deploy/bots/$1/.env"
}

bot_display_name() {
  read_bot_env_value BOT_DISPLAY_NAME "$(bot_env_file "$1")"
}

bot_telegram_id() {
  read_bot_env_value BOT_TELEGRAM_ID "$(bot_env_file "$1")"
}

bot_telegram_username() {
  read_bot_env_value BOT_TELEGRAM_USERNAME "$(bot_env_file "$1")"
}

bot_registry_url() {
  local registry_id="" registry_url="" enroll_token="" registry_scope=""
  while IFS='|' read -r registry_id registry_url enroll_token registry_scope; do
    printf '%s\n' "$registry_url"
    return 0
  done < <(list_registry_connection_records "$(bot_env_file "$1")")
}

bot_registry_scope() {
  local registry_id="" registry_url="" enroll_token="" registry_scope=""
  while IFS='|' read -r registry_id registry_url enroll_token registry_scope; do
    printf '%s\n' "$registry_scope"
    return 0
  done < <(list_registry_connection_records "$(bot_env_file "$1")")
}

bot_registry_connection_count() {
  local slug="$1" count=0 registry_id="" registry_url="" enroll_token="" registry_scope=""
  while IFS='|' read -r registry_id registry_url enroll_token registry_scope; do
    [ -n "$registry_id" ] || continue
    count=$((count + 1))
  done < <(list_registry_connection_records "$(bot_env_file "$slug")")
  printf '%s\n' "$count"
}

bot_registry_connection_records() {
  list_registry_connection_records "$(bot_env_file "$1")"
}

bot_is_standalone() {
  local mode
  mode="$(read_bot_env_value BOT_AGENT_MODE "$(bot_env_file "$1")")"
  [ "$mode" = "standalone" ] || [ -z "$mode" ]
}

bot_is_registry() {
  [ "$(read_bot_env_value BOT_AGENT_MODE "$(bot_env_file "$1")")" = "registry" ]
}

bot_uses_local_reg() {
  [ "$(bot_registry_url "$1")" = "http://registry:8787" ]
}

bot_uses_remote_reg() {
  local url
  url="$(bot_registry_url "$1")"
  case "$url" in
    https://*) return 0 ;;
  esac
  return 1
}

bot_is_running() {
  docker compose -p "octopus-$1" ps --status running 2>/dev/null | grep -q bot
}

registry_is_running() {
  docker compose -p octopus-registry ps --status running service 2>/dev/null | grep -q service
}

network_exists() {
  docker network inspect octopus-net >/dev/null 2>&1
}

ensure_deploy_dirs() {
  mkdir -p .deploy/bots .deploy/registry .deploy/provider-auth .deploy/workspaces
}

# -- workspace state queries --------------------------------------------------

list_workspace_slugs() {
  local entry
  for entry in .deploy/workspaces/*/; do
    [ -d "$entry" ] || continue
    basename "$entry"
  done
}

count_workspaces() {
  list_workspace_slugs | wc -l | tr -d ' '
}

has_workspace() {
  test -f ".deploy/workspaces/$1/workspace.conf"
}

workspace_conf_file() {
  echo ".deploy/workspaces/$1/workspace.conf"
}

workspace_members_file() {
  echo ".deploy/workspaces/$1/members.txt"
}

read_workspace_conf_value() {
  local key="$1" file="$2"
  grep "^${key}=" "$file" 2>/dev/null | head -1 | sed "s/^${key}=//"
}

workspace_root() {
  read_workspace_conf_value WORKSPACE_ROOT "$(workspace_conf_file "$1")"
}

workspace_mount() {
  read_workspace_conf_value WORKSPACE_MOUNT "$(workspace_conf_file "$1")"
}

workspace_mode() {
  local mode
  mode="$(read_workspace_conf_value WORKSPACE_MODE "$(workspace_conf_file "$1")")"
  printf '%s\n' "${mode:-rw}"
}

workspace_members() {
  local file
  file="$(workspace_members_file "$1")"
  [ -f "$file" ] || return 0
  grep -v '^\s*$\|^\s*#' "$file" 2>/dev/null || true
}

bot_workspace_memberships() {
  local bot_slug="$1" ws_slug=""
  for ws_slug in $(list_workspace_slugs); do
    if grep -qx "$bot_slug" "$(workspace_members_file "$ws_slug")" 2>/dev/null; then
      printf '%s\n' "$ws_slug"
    fi
  done
}

bot_has_workspace() {
  [ -n "$(bot_workspace_memberships "$1")" ]
}

find_bot_slug_by_telegram_id() {
  local telegram_id="$1" slug=""
  [ -n "$telegram_id" ] || return 1
  for slug in $(list_bot_slugs); do
    if [ "$(bot_telegram_id "$slug")" = "$telegram_id" ]; then
      printf '%s\n' "$slug"
      return 0
    fi
  done
  return 1
}
