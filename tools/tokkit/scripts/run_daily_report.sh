#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT_DIR/scripts/python_env.sh"
PYTHON_BIN="$(find_tokkit_python)"
TOKKIT_HOME="${TOKKIT_HOME:-${TOKSTAT_HOME:-$([[ -d "$HOME/.tokkit" || ! -d "$HOME/.tokstat" ]] && echo "$HOME/.tokkit" || echo "$HOME/.tokstat")}}"
DB_PATH="${TOKKIT_DB_PATH:-${TOKSTAT_DB_PATH:-$TOKKIT_HOME/usage.sqlite}}"
TIMEZONE="${TOKKIT_TIMEZONE:-${TOKSTAT_TIMEZONE:-Asia/Shanghai}}"
REPORT_DIR="${TOKKIT_REPORT_DIR:-${TOKSTAT_REPORT_DIR:-$TOKKIT_HOME/reports}}"

mkdir -p "$REPORT_DIR"

REPORT_DATE="$(
  TIMEZONE="$TIMEZONE" "$PYTHON_BIN" - <<'PY'
from datetime import datetime, timedelta
from os import environ
from zoneinfo import ZoneInfo

tz = ZoneInfo(environ["TIMEZONE"])
print((datetime.now(tz).date() - timedelta(days=1)).isoformat())
PY
)"

PYTHONPATH="$ROOT_DIR/src" \
"$PYTHON_BIN" -m tokkit.cli \
  --db "$DB_PATH" \
  --timezone "$TIMEZONE" \
  report-daily \
  --date yesterday \
  --output "$REPORT_DIR/$REPORT_DATE.txt"
