#!/usr/bin/env bash
set -euo pipefail

MSA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$MSA_ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "Missing Python environment at $MSA_ROOT/.venv. Run: bash scripts/dev-setup.sh" >&2
  exit 1
fi

cd "$MSA_ROOT"
export PYTHONPATH="$MSA_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" -c 'from msa_cli.cli import main; main()' index run \
  --media-source-override "${1:-$MSA_ROOT/data/sample_photos}"
