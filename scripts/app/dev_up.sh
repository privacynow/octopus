#!/usr/bin/env bash
# Local Runtime requires Postgres.
# Run ./scripts/db/dev_up_postgres.sh first, then ./octopus.
set -euo pipefail

echo "Start Postgres first: ./scripts/db/dev_up_postgres.sh"
echo "Then run the stack: ./octopus"
