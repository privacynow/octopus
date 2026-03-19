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

bot_registry_url() {
  read_bot_env_value BOT_AGENT_REGISTRY_URL "$(bot_env_file "$1")"
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
  docker compose -p octopus-registry ps --status running 2>/dev/null | grep -q registry
}

network_exists() {
  docker network inspect octopus-net >/dev/null 2>&1
}

ensure_deploy_dirs() {
  mkdir -p .deploy/bots .deploy/registry .deploy/provider-auth
}
