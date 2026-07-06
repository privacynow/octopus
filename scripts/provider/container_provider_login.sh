#!/usr/bin/env bash
# Run inside the bot container with bot-home volume mounted at /home/bot.
# Performs provider-specific interactive login then verifies the local CLI
# still works without doing a live provider runtime probe.
set -euo pipefail

provider="${BOT_PROVIDER:-claude}"

case "$provider" in
  codex)
    codex_login_args="login"
    if codex login --help 2>&1 | grep -q -- "--device-auth"; then
      codex_login_args="login --device-auth"
    fi
    cat <<'BANNER'
╔══════════════════════════════════════════════════════════════╗
║  ACTION REQUIRED — CODex LOGIN                              ║
║                                                              ║
║  The script runs the login command supported by this image.  ║
║  Follow the CLI instructions to complete sign-in.            ║
║  The command must return successfully before setup continues.║
║                                                              ║
║  Do not run the removed flag:  codex --login                 ║
╚══════════════════════════════════════════════════════════════╝
BANNER
    echo "Running: codex $codex_login_args"
    set +e
    # shellcheck disable=SC2086
    codex $codex_login_args
    exit_code=$?
    set -e
    if [ "$exit_code" -ne 0 ]; then
      echo "✗ Codex login command failed." >&2
      echo "  codex login exit code: $exit_code" >&2
      echo "  Run ./scripts/provider/provider_login.sh codex again after fixing the login error." >&2
      exit "$exit_code"
    fi
    if python -m app.provider_auth has-runtime-artifacts codex "${HOME:-/home/bot}"; then
      echo "✓ Codex authentication complete. Returning to setup..."
    else
      echo "✗ Codex authentication is still incomplete." >&2
      echo "  Complete Codex login, wait for the CLI to finish, then run ./octopus again." >&2
      echo "  codex login exit code: $exit_code" >&2
      exit 1
    fi
    ;;
  claude)
    cat <<'BANNER'
╔══════════════════════════════════════════════════════════════╗
║  ACTION REQUIRED — CLAUDE CLI LOGIN                         ║
║                                                              ║
║  The CLI will prompt for authentication automatically.       ║
║  Follow the browser link to sign in.                         ║
║                                                              ║
║  If already signed in, TYPE:  /exit   (or press Ctrl-D)      ║
║  to return to setup.                                         ║
╚══════════════════════════════════════════════════════════════╝
BANNER
    # Pre-create bind-mount targets so the copy-back after login has
    # a destination even if ensure_provider_auth_dir wasn't called.
    if [ -d /home/bot/.provider-auth ]; then
      python -m app.provider_auth ensure-shared-layout claude /home/bot/.provider-auth
    fi
    set +e
    claude
    exit_code=$?
    set -e
    # Claude CLI uses atomic writes (temp + rename) which replaces symlinks
    # with regular files in the container layer. Copy auth back to the bind
    # mount so credentials persist on the host after this container exits.
    if [ -d /home/bot/.provider-auth ]; then
      python -m app.provider_auth sync-runtime-to-shared claude "${HOME:-/home/bot}" /home/bot/.provider-auth || true
    fi
    if python -m app.provider_auth has-runtime-artifacts claude "${HOME:-/home/bot}"; then
      echo "✓ Claude authentication complete. Returning to setup..."
    else
      echo "✗ Claude authentication is still incomplete." >&2
      echo "  Inside Claude, run /login, complete browser auth, then /exit to return to setup." >&2
      echo "  claude exit code: $exit_code" >&2
      exit 1
    fi
    ;;
  *)
    echo "BOT_PROVIDER must be claude or codex, got: $provider" >&2
    exit 1
    ;;
esac

echo "Provider auth files saved."
echo "Octopus will run a live provider health check next."
