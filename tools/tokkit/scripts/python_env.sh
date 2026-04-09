#!/bin/zsh
set -euo pipefail

find_tokkit_python() {
  local candidate
  local version

  for candidate in \
    "${TOKKIT_PYTHON:-${TOKSTAT_PYTHON:-}}" \
    /opt/homebrew/bin/python3.14 \
    /opt/homebrew/bin/python3.13 \
    /opt/homebrew/bin/python3.12 \
    /opt/homebrew/bin/python3.11 \
    /opt/homebrew/bin/python3.10 \
    /opt/homebrew/bin/python3 \
    /usr/local/bin/python3.14 \
    /usr/local/bin/python3.13 \
    /usr/local/bin/python3.12 \
    /usr/local/bin/python3.11 \
    /usr/local/bin/python3.10 \
    /usr/local/bin/python3 \
    "$(command -v python3.14 2>/dev/null || true)" \
    "$(command -v python3.13 2>/dev/null || true)" \
    "$(command -v python3.12 2>/dev/null || true)" \
    "$(command -v python3.11 2>/dev/null || true)" \
    "$(command -v python3.10 2>/dev/null || true)" \
    "$(command -v python3 2>/dev/null || true)"
  do
    [[ -n "${candidate:-}" ]] || continue
    [[ -x "$candidate" ]] || continue
    version="$("$candidate" - <<'PY'
import sys
print(f"{sys.version_info[0]}.{sys.version_info[1]}")
PY
)"
    if [[ "$version" == 3.1[0-9] || "$version" == 4.* ]]; then
      echo "$candidate"
      return 0
    fi
  done

  echo "Unable to find Python 3.10+ for TokKit" >&2
  return 1
}

find_tokstat_python() {
  find_tokkit_python
}
