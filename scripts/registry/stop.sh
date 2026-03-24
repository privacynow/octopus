#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
exec "$REPO_DIR/octopus" stop registry --yes

