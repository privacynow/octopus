#!/usr/bin/env bash
# Run the full test suite: pytest (Python) + current bash smoke tests.
#
# Usage:
#   ./scripts/test/test_all.sh              # run everything in parallel
#   OCTOPUS_TEST_WORKERS=auto ./scripts/test/test_all.sh
#   OCTOPUS_TEST_WORKERS=0 ./scripts/test/test_all.sh   # disable xdist
#   ./scripts/test/test_all.sh -k doctor    # only pytest tests matching "doctor"
#
# Any arguments are forwarded to pytest.
# When arguments are present, only pytest runs (bash tests are skipped)
# because flags like -k, -x, --lf, or path filters don't apply to bash tests.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"

if [ $# -eq 0 ]; then
    workers="${OCTOPUS_TEST_WORKERS:-$(.venv/bin/python -c 'import os; print(min(max(os.cpu_count() or 2, 2), 20))')}"
    durations="${OCTOPUS_TEST_DURATIONS:-50}"
    if [ "$workers" = "0" ] || [ "$workers" = "false" ] || [ "$workers" = "off" ]; then
        .venv/bin/python -m pytest -q --tb=short --durations="$durations"
    else
        .venv/bin/python -m pytest -q -n "$workers" --dist load --tb=short --durations="$durations"
    fi
else
    .venv/bin/python -m pytest "$@"
fi

# Only run bash tests when no arguments were passed (full suite run).
if [ $# -eq 0 ]; then
    bash tests/test_setup.sh
fi
