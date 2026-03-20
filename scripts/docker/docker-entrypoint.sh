#!/bin/sh
set -e

if [ -d /home/bot/.provider-auth ]; then
  provider="${BOT_PROVIDER:-claude}"
  case "$provider" in
    claude)
      ln -sfn /home/bot/.provider-auth/.claude /home/bot/.claude
      ln -sfn /home/bot/.provider-auth/.claude.json /home/bot/.claude.json
      ;;
    codex)
      ln -sfn /home/bot/.provider-auth/.codex /home/bot/.codex
      ;;
  esac
fi

mkdir -p /home/bot/data
chown -R 1000:1000 /home/bot/data 2>/dev/null || true
chown -h 1000:1000 /home/bot/.claude /home/bot/.claude.json /home/bot/.codex 2>/dev/null || true

exec gosu bot "$@"
