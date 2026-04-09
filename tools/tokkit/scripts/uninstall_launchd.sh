#!/bin/zsh
set -euo pipefail

LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

for name in \
  "com.laoyao.tokkit.scan" \
  "com.laoyao.tokkit.daily-report" \
  "com.laoyao.tokkit.kaku-proxy" \
  "com.laoyao.tokstat.scan" \
  "com.laoyao.tokstat.daily-report" \
  "com.laoyao.tokstat.kaku-proxy"
do
  plist="$LAUNCH_AGENTS_DIR/$name.plist"
  launchctl unload "$plist" >/dev/null 2>&1 || true
  rm -f "$plist"
done

echo "Removed TokKit launchd jobs."
