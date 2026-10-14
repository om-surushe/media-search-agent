#!/usr/bin/env bash
# Run Vite with HMR; API calls proxy to the project development backend.
set -euo pipefail

MSA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UI_DIR="$MSA_ROOT/src/msa_apps/ui"

if [[ ! -d "$UI_DIR/node_modules" ]]; then
  echo "UI dependencies missing. Run: npm --prefix src/msa_apps/ui ci" >&2
  exit 1
fi

export VITE_API_ORIGIN="${VITE_API_ORIGIN:-http://127.0.0.1:8500}"
exec npm --prefix "$UI_DIR" run dev -- --host 127.0.0.1
