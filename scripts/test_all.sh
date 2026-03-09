#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

for test_file in tests/test_*.py; do
    .venv/bin/python "$test_file"
done

bash tests/test_setup.sh
