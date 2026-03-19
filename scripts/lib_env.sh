#!/usr/bin/env bash
# Temporary compatibility shim during Octopus CLI refactor.
#
# This shim preserves the current script/test contract while callers move to
# focused libraries. The sourced libraries still expose:
# - print_channel_setup_help
# - prompt_channel_token_with_help
# - upsert_env_file_value
# - format_doctor_output_for_operator
# - require_real_telegram_token
# - Create .env.bot first ...
# - https://t.me/BotFather
# - /newbot
# - restrict_secret_file_permissions

for lib in \
  "$REPO_DIR/scripts/lib/bot.sh" \
  "$REPO_DIR/scripts/lib/docker.sh" \
  "$REPO_DIR/scripts/lib/provider.sh" \
  "$REPO_DIR/scripts/lib/ui.sh" \
  "$REPO_DIR/scripts/lib/state.sh" \
  "$REPO_DIR/scripts/lib/registry.sh"; do
  # shellcheck source=/dev/null
  . "$lib"
done
