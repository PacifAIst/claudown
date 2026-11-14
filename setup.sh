#!/usr/bin/env bash
# claudown installer for macOS / Linux / Git Bash. All the work happens in
# scripts/claudown_setup.py, which you can also run directly on any OS:
#
#   ./setup.sh                      install for your user (~/.claude), DRY RUN
#   ./setup.sh --threshold 90       custom threshold (percent of the 5-hour window)
#   ./setup.sh --arm                install ARMED (DRY_RUN=false) - really shuts down
#   ./setup.sh --project /path/repo install into a repo's .claude/ (Claude Code on the web)
#   ./setup.sh --uninstall [--project /path/repo]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PY=""
for cand in python3 python py; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
    PY="$cand"; break
  fi
done
[[ -z "$PY" ]] && { echo "claudown needs Python 3.8+ (https://www.python.org/downloads/)." >&2; exit 1; }

exec "$PY" "$HERE/scripts/claudown_setup.py" "$@"
