#!/usr/bin/env bash
# Run the project API in the foreground with package-source reload. Restart after config changes.
set -euo pipefail

MSA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${MSA_DEV_VENV_DIR:-$MSA_ROOT/.venv}"
PYTHON="$VENV/bin/python"
UVICORN="$VENV/bin/uvicorn"

if [[ ! -x "$UVICORN" ]]; then
  echo "Missing backend environment at $VENV. Run: bash scripts/dev-setup.sh or set MSA_DEV_VENV_DIR." >&2
  exit 1
fi

# Do not accidentally load an installed-app config or data directory.
unset MSA_CONFIG_PATH MSA_DATA_DIR MSA_LOG_DIR MSA_CACHE_DIR MSA_VENV_DIR MSA_DEV_VENV_DIR
export MSA_ROOT MSA_DEV=1

read -r CONFIG_HOST CONFIG_PORT < <("$PYTHON" - "$MSA_ROOT/config.yaml" <<'PY'
import sys
import yaml
from pathlib import Path
config = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
api = config.get("api") or {}
print(api.get("host", "127.0.0.1"), api.get("port", 8500))
PY
)
HOST="${MSA_DEV_API_HOST:-$CONFIG_HOST}"
PORT="${MSA_DEV_API_PORT:-$CONFIG_PORT}"

cd "$MSA_ROOT"
exec "$UVICORN" msa_apps.search_api.app:app \
  --host "$HOST" --port "$PORT" \
  --reload \
  --reload-dir "$MSA_ROOT/src/msa_apps/search_api" \
  --reload-dir "$MSA_ROOT/src/msa_indexer" \
  --reload-dir "$MSA_ROOT/src/msa_query" \
  --reload-dir "$MSA_ROOT/src/msa_settings" \
  --reload-dir "$MSA_ROOT/src/msa_cli" \
  --reload-include '*.py' --reload-include '*.yaml'
