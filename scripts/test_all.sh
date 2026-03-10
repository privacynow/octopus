#!/usr/bin/env bash
# Run the full test suite: pytest (Python) + test_setup.sh (bash).
#
# Usage:
#   ./scripts/test_all.sh              # run everything
#   ./scripts/test_all.sh -n auto      # parallel via pytest-xdist
#   ./scripts/test_all.sh -k doctor    # only pytest tests matching "doctor"
#
# Any arguments are forwarded to pytest.
# When arguments are present, only pytest runs (bash tests are skipped)
# because flags like -k, -x, --lf, or path filters don't apply to bash tests.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

.venv/bin/python -m pytest "$@"

# Only run bash tests when no arguments were passed (full suite run).
if [ $# -eq 0 ]; then
    bash tests/test_setup.sh
fi
