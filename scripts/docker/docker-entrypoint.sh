#!/bin/sh
set -e

if [ -d /home/bot/.provider-auth ]; then
  provider="${BOT_PROVIDER:-claude}"
  case "$provider" in
    claude)
      # Force-replace any local Claude paths before linking them into the
      # shared provider-auth mount. `ln -sfn` does not replace a real
      # directory, which can leave `/home/bot/.claude` shadowing the mount.
      rm -rf /home/bot/.claude
      rm -f /home/bot/.claude.json
      ln -sfn /home/bot/.provider-auth/.claude /home/bot/.claude
      ln -sfn /home/bot/.provider-auth/.claude.json /home/bot/.claude.json
      ;;
    codex)
      # Use CODEX_HOME env var instead of symlink — the codex CLI
      # conflicts with symlinked ~/.codex (EEXIST on directory ops).
      mkdir -p /home/bot/.provider-auth/.codex
      export CODEX_HOME="/home/bot/.provider-auth/.codex"
      ;;
  esac
fi

mkdir -p /home/bot/data
chown -R 1000:1000 /home/bot/data 2>/dev/null || true
chown -h 1000:1000 /home/bot/.claude /home/bot/.claude.json /home/bot/.codex 2>/dev/null || true

exec gosu bot "$@"
