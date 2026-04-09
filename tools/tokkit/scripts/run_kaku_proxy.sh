#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT_DIR/scripts/python_env.sh"
PYTHON_BIN="$(find_tokkit_python)"
TOKKIT_HOME="${TOKKIT_HOME:-${TOKSTAT_HOME:-$([[ -d "$HOME/.tokkit" || ! -d "$HOME/.tokstat" ]] && echo "$HOME/.tokkit" || echo "$HOME/.tokstat")}}"
DB_PATH="${TOKKIT_DB_PATH:-${TOKSTAT_DB_PATH:-$TOKKIT_HOME/usage.sqlite}}"
TIMEZONE="${TOKKIT_TIMEZONE:-${TOKSTAT_TIMEZONE:-Asia/Shanghai}}"
PORT="${TOKKIT_KAKU_PROXY_PORT:-${TOKSTAT_KAKU_PROXY_PORT:-8765}}"
HOST="${TOKKIT_KAKU_PROXY_HOST:-${TOKSTAT_KAKU_PROXY_HOST:-127.0.0.1}}"
UPSTREAM_BASE_URL="${TOKKIT_KAKU_UPSTREAM_BASE_URL:-${TOKSTAT_KAKU_UPSTREAM_BASE_URL:-}}"

if [[ -z "$UPSTREAM_BASE_URL" ]]; then
  echo "TOKKIT_KAKU_UPSTREAM_BASE_URL is required" >&2
  exit 1
fi

mkdir -p "$(dirname "$DB_PATH")"

PYTHONPATH="$ROOT_DIR/src" \
"$PYTHON_BIN" -m tokkit.cli \
  --db "$DB_PATH" \
  --timezone "$TIMEZONE" \
  serve-proxy \
  --host "$HOST" \
  --port "$PORT" \
  --upstream-base-url "$UPSTREAM_BASE_URL"
