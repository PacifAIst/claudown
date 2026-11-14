#!/usr/bin/env bash
# claudown CLI zero-token sensor (shell wrapper around statusline_sensor.py).
#
# As a Claude Code statusLine command, Claude Code pipes session JSON in and
# this forwards it to the Python sensor unchanged.
#
# Run it by hand in a terminal (`bash scripts/statusline_sensor.sh`) to see a
# demo: it feeds a fake "42 % used" reading into a THROWAWAY folder, so your
# real usage file is never touched.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PY=""
for cand in python3 python py; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
    PY="$cand"; break
  fi
done
if [ -z "$PY" ]; then
  echo "claudown: Python 3.8+ not found"
  exit 0  # never blank the status line with an error code
fi

if [ -t 0 ]; then
  DEMO_DIR="$(mktemp -d)"
  NOW="$(date +%s)"
  echo "Demo: sending a fake 42% reading (saved in $DEMO_DIR, not your real files)..."
  printf '{"session_id":"demo","rate_limits":{"five_hour":{"used_percentage":42,"resets_at":%s}}}' \
    "$((NOW + 3600))" | CLAUDE_CONFIG_DIR="$DEMO_DIR" "$PY" "$HERE/statusline_sensor.py"
  echo "If you see 'claudown ▸ 5h 42%' above, the sensor works."
  exit 0
fi

exec "$PY" "$HERE/statusline_sensor.py"
