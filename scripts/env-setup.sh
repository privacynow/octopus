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
