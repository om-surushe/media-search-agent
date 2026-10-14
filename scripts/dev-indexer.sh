#!/usr/bin/env bash
# Run one indexing pass in the project venv; output stays in this terminal.
set -euo pipefail

MSA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${MSA_DEV_VENV_DIR:-$MSA_ROOT/.venv}"
CLI="$VENV/bin/msa"

if [[ ! -x "$CLI" ]]; then
  echo "Missing CLI environment at $VENV. Run: bash scripts/dev-setup.sh or set MSA_DEV_VENV_DIR." >&2
  exit 1
fi

unset MSA_CONFIG_PATH MSA_DATA_DIR MSA_LOG_DIR MSA_CACHE_DIR MSA_VENV_DIR MSA_DEV_VENV_DIR
export MSA_DEV=1
exec "$CLI" index run "$@"
