#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT_DIR/scripts/python_env.sh"
PYTHON_BIN="$(find_tokkit_python)"
TOKKIT_HOME="${TOKKIT_HOME:-${TOKSTAT_HOME:-$([[ -d "$HOME/.tokkit" || ! -d "$HOME/.tokstat" ]] && echo "$HOME/.tokkit" || echo "$HOME/.tokstat")}}"
DB_PATH="${TOKKIT_DB_PATH:-${TOKSTAT_DB_PATH:-$TOKKIT_HOME/usage.sqlite}}"
TIMEZONE="${TOKKIT_TIMEZONE:-${TOKSTAT_TIMEZONE:-Asia/Shanghai}}"
SCAN_MODE="${TOKKIT_SCAN_MODE:-${TOKSTAT_SCAN_MODE:-all}}"

mkdir -p "$(dirname "$DB_PATH")"

case "$SCAN_MODE" in
  codex)
    PYTHONPATH="$ROOT_DIR/src" \
    "$PYTHON_BIN" -m tokkit.cli \
      --db "$DB_PATH" \
      --timezone "$TIMEZONE" \
      scan-codex
    ;;
  warp)
    PYTHONPATH="$ROOT_DIR/src" \
    "$PYTHON_BIN" -m tokkit.cli \
      --db "$DB_PATH" \
      --timezone "$TIMEZONE" \
      scan-warp
    ;;
  all)
    PYTHONPATH="$ROOT_DIR/src" \
    "$PYTHON_BIN" -m tokkit.cli \
      --db "$DB_PATH" \
      --timezone "$TIMEZONE" \
      scan-all
    ;;
  *)
    echo "Unsupported TOKKIT_SCAN_MODE: $SCAN_MODE" >&2
    exit 1
    ;;
esac
