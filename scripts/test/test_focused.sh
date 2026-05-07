#!/usr/bin/env bash
# Focused local test tiers. These are intentionally smaller than test_all.sh
# and are meant for iteration before the final full-suite gate.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"

tier="${1:-unit-fast}"
shift || true

case "$tier" in
  unit-fast)
    .venv/bin/python -m pytest -q \
      tests/test_protocol_engine.py \
      tests/test_registry_management_protocol.py \
      tests/test_artifact_runtime.py \
      "$@"
    ;;
  registry-contract)
    .venv/bin/python -m pytest -q \
      tests/test_protocols.py \
      tests/test_registry_service.py \
      tests/test_registry_sdk_contract.py \
      "$@"
    ;;
  bot-runtime-focused)
    .venv/bin/python -m pytest -q \
      tests/test_artifact_runtime.py \
      tests/test_registry_management_protocol.py \
      tests/test_runtime_dispatch_boundary.py \
      "$@"
    ;;
  browser-focused)
    .venv/bin/python -m pytest -q \
      tests/test_registry_ui_contract.py \
      tests/test_registry_ui_kit_contract.py \
      "$@"
    ;;
  integration-focused)
    .venv/bin/python -m pytest -q \
      tests/test_protocols.py \
      tests/test_protocol_telegram.py \
      tests/test_registry_service.py \
      "$@"
    ;;
  full)
    bash scripts/test/test_all.sh "$@"
    ;;
  *)
    echo "Unknown focused test tier: $tier" >&2
    echo "Expected one of: unit-fast, registry-contract, bot-runtime-focused, browser-focused, integration-focused, full" >&2
    exit 2
    ;;
esac
