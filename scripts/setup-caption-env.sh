#!/usr/bin/env bash
# Create the isolated Apple Silicon MLX caption-worker environment.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/versions.env"
UV_BIN="${UV_BIN:-$HOME/.local/bin/uv}"
VENV="$ROOT/.venv-caption"
LOCK="$ROOT/requirements-caption-macos-arm64.lock"

if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo "The MLX caption worker requires macOS on Apple Silicon." >&2
  exit 1
fi
MACOS_MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
if [[ "$MACOS_MAJOR" -lt 14 ]]; then
  echo "The pinned MLX caption worker requires macOS 14 or later." >&2
  exit 1
fi
if [[ ! -x "$UV_BIN" ]]; then
  echo "uv not found at $UV_BIN; run bash scripts/dev-setup.sh first." >&2
  exit 1
fi
if [[ ! -f "$LOCK" ]]; then
  echo "Caption dependency lock missing: $LOCK" >&2
  echo "Generate it with ./scripts/lock-macos-arm64.sh" >&2
  exit 1
fi

if [[ -x "$VENV/bin/python" ]]; then
  VENV_PYTHON_VERSION="$($VENV/bin/python -c 'import platform; print(platform.python_version())')"
  if [[ "$VENV_PYTHON_VERSION" != "$PYTHON_VERSION" ]]; then
    echo "Caption venv uses Python $VENV_PYTHON_VERSION, expected $PYTHON_VERSION." >&2
    echo "Remove only $VENV and rerun this script to rebuild it." >&2
    exit 1
  fi
else
  "$UV_BIN" venv "$VENV" --python "$PYTHON_VERSION"
fi

"$UV_BIN" pip sync --python "$VENV/bin/python" "$LOCK"
printf 'Caption environment ready. In the backend terminal, set:\n'
printf 'export MSA_CAPTION_PYTHON="%s/bin/python"\n' "$VENV"
printf 'export MSA_CAPTION_CACHE_DIR="%s/models/caption-hub"\n' "$ROOT"
