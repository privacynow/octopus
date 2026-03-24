#!/usr/bin/env bash
# Provider auth helpers.
#
# Slice 3 integration probe notes (2026-03-19):
# - Claude Code v2.1.79 first launch created /home/bot/.claude and /home/bot/.claude.json
#   during onboarding/login prompting. No /home/bot/.config/Claude or
#   /home/bot/.local/share/Claude paths were created in the probe.
# - Codex CLI v0.116.0 device-auth first launch created /home/bot/.codex
#   during login prompting. No /home/bot/.config/openai path was created in the probe.
# - The shared auth layout therefore mirrors the observed live paths instead of
#   carrying forward older .config-based assumptions.

ensure_provider_auth_dir() {
  local provider="$1"
  local auth_dir=".deploy/provider-auth/$provider"
  mkdir -p "$auth_dir"
  chmod 700 "$auth_dir"
  case "$provider" in
    claude)
      mkdir -p "$auth_dir/.claude"
      [ -f "$auth_dir/.claude.json" ] || : > "$auth_dir/.claude.json"
      ;;
    codex)
      mkdir -p "$auth_dir/.codex"
      ;;
    *)
      echo "Unsupported provider '$provider'" >&2
      return 1
      ;;
  esac
}

claude_auth_artifacts_exist() {
  local auth_root="${1:-.deploy/provider-auth/claude}"
  if [ -f "$auth_root/.claude.json" ] && [ -s "$auth_root/.claude.json" ]; then
    return 0
  fi
  if [ -d "$auth_root/.claude" ] && find "$auth_root/.claude" -mindepth 1 -type f -size +0c -print -quit 2>/dev/null | grep -q .; then
    return 0
  fi
  return 1
}

provider_auth_hint() {
  local provider="$1"
  test -f ".deploy/provider-auth/$provider/.authed"
}

update_provider_auth_hint() {
  local provider="$1" success="$2"
  ensure_provider_auth_dir "$provider" >/dev/null
  if [ "$success" = "true" ]; then
    touch ".deploy/provider-auth/$provider/.authed"
  else
    rm -f ".deploy/provider-auth/$provider/.authed"
  fi
}

provider_has_auth_files() {
  # Fast local check: do provider-specific auth artifacts exist on disk?
  # Must check for artifacts that are ONLY created by a successful login,
  # not the empty bootstrap files/directories pre-created by ensure_provider_auth_dir().
  local provider="$1"
  case "$provider" in
    claude)
      claude_auth_artifacts_exist ".deploy/provider-auth/claude"
      ;;
    codex)
      # auth.json is only created by codex login, never by bootstrap.
      [ -f ".deploy/provider-auth/codex/.codex/auth.json" ]
      ;;
    *)
      return 1
      ;;
  esac
}

provider_is_authed() {
  # Full check: run the provider health command inside a container.
  # This includes both auth verification and API ping. Use
  # provider_has_auth_files() for fast checks that don't need the API.
  local provider="$1"
  local exit_code=0
  ensure_provider_auth_dir "$provider"
  check_provider_image "$provider" >/dev/null
  if provider_compose "$provider" run --rm bot-provider </dev/null >/dev/null 2>&1; then
    exit_code=0
  else
    exit_code=$?
  fi
  if [ "$exit_code" -eq 0 ]; then
    update_provider_auth_hint "$provider" "true"
  else
    update_provider_auth_hint "$provider" "false"
  fi
  return "$exit_code"
}
