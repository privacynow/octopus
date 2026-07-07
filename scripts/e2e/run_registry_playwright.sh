#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PLAYWRIGHT_DIR="${REPO_DIR}/.tmp/playwright"
PLAYWRIGHT_VERSION="${PLAYWRIGHT_VERSION:-1.59.1}"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-${REPO_DIR}/.tmp/ms-playwright}"

if [ "$#" -eq 0 ]; then
  set -- "${REPO_DIR}/tests/e2e/playwright/auto-protocol-ui.spec.js"
fi

if [ "${PLAYWRIGHT_DRY_RUN:-0}" = "1" ]; then
  printf '%s\n' "${PLAYWRIGHT_DIR}/node_modules/.bin/playwright test $* --config=${REPO_DIR}/tests/e2e/playwright.config.js"
  exit 0
fi

mkdir -p "${PLAYWRIGHT_DIR}"

if [ ! -x "${PLAYWRIGHT_DIR}/node_modules/.bin/playwright" ]; then
  npm install --prefix "${PLAYWRIGHT_DIR}" --no-save "@playwright/test@${PLAYWRIGHT_VERSION}"
fi

PLAYWRIGHT_BIN="${PLAYWRIGHT_DIR}/node_modules/.bin/playwright"

if [ "${PLAYWRIGHT_SKIP_BROWSER_INSTALL:-0}" != "1" ]; then
  if [ "${CI:-}" = "true" ]; then
    "${PLAYWRIGHT_BIN}" install --with-deps chromium
  else
    "${PLAYWRIGHT_BIN}" install chromium
  fi
fi

exec "${PLAYWRIGHT_BIN}" test "$@" --config="${REPO_DIR}/tests/e2e/playwright.config.js"
