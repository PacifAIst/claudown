#!/usr/bin/env python3
"""claudown SENSOR - Claude Code CLI `statusLine` command.

Claude Code pipes session JSON to this script on stdin after each assistant
message. For Pro/Max/Ultra subscribers that JSON carries
`rate_limits.five_hour.used_percentage`; we copy it (and friends) into
~/.claude/claudown_state.json and print a one-line status. The status line is
generated locally by the CLI and costs zero tokens; this script makes no
network calls at all.

Note: the native VS Code panel never runs statusLine. There, the gate falls
back to vscode_transcript_sensor.py automatically.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from . import claudown_common as c
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import claudown_common as c  # noqa: E402


def _window(data: dict, name: str):
    win = (data.get("rate_limits") or {}).get(name) or {}
    if not isinstance(win, dict):
        return None, None
    return c.to_float(win.get("used_percentage")), c.to_float(win.get("resets_at"))


def update_state(data: dict, now: float) -> dict:
    """Merge the new reading into the state file and return the merged state."""
    state = c.load_state()
    five_pct, five_reset = _window(data, "five_hour")
    week_pct, week_reset = _window(data, "seven_day")

    state["sensor_seen_at"] = now
    state["sensor"] = "statusline"
    state["version"] = c.VERSION
    if data.get("session_id"):
        state["session_id"] = data["session_id"]
    if data.get("transcript_path"):
        state["transcript_path"] = data["transcript_path"]
    if data.get("version"):
        state["claude_code_version"] = data["version"]

    if five_pct is not None:
        state["five_hour_pct"] = five_pct
        state["five_hour_resets_at"] = five_reset
        state["updated_at"] = now
        state["source"] = "statusline"
        state["rate_limits_present"] = True
    else:
        # rate_limits is absent before the first API response, or for accounts that
        # are not Pro/Max/Ultra. Keep the previous reading; the gate checks freshness.
        state["rate_limits_present"] = False
    if week_pct is not None:
        state["seven_day_pct"] = week_pct
        state["seven_day_resets_at"] = week_reset

    c.write_json_atomic(c.state_path(), state)
    return state


def render(state: dict, now: float) -> str:
    thr = c.threshold()
    pct = c.to_float(state.get("five_hour_pct"))
    if c.is_disabled():
        return "claudown ⏸ disabled"
    if pct is None or state.get("updated_at") is None:
        return "claudown ▸ 5h: waiting for data"
    resets = c.to_float(state.get("five_hour_resets_at"))
    if resets is not None and now >= resets:
        return "claudown ▸ 5h: window reset"
    color = "\033[32m"
    if pct >= thr:
        color = "\033[31m"
    elif pct >= thr * 0.8:
        color = "\033[33m"
    reset_txt = ""
    if resets:
        reset_txt = " · resets " + datetime.fromtimestamp(resets).strftime("%H:%M")
    mode = " · DRY RUN" if c.is_dry_run() else " · ARMED"
    return f"{color}claudown ▸ 5h {pct:.0f}%\033[0m / gate {thr:.0f}%{reset_txt}{mode}"


def chained_output(raw: str) -> str:
    cmd = c.cfg("STATUSLINE_CHAIN_COMMAND").strip()
    if not cmd:
        return ""
    try:
        out = subprocess.run(cmd, shell=True, input=raw, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=5)
        return (out.stdout or "").rstrip("\n")
    except Exception:
        return ""


def _main() -> int:
    raw = ""
    try:
        raw = sys.stdin.read()
    except Exception:
        pass
    try:
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            data = {}
    except ValueError:
        data = {}

    now = time.time()
    try:
        state = update_state(data, now) if data else c.load_state()
    except Exception as exc:
        c.log(f"sensor could not write state: {exc!r}")
        state = c.load_state()

    line = render(state, now)
    chained = chained_output(raw)
    print(f"{chained}\n{line}" if chained else line)
    return 0  # a non-zero exit would blank the status line


def main() -> int:
    c.utf8_stdio()
    try:
        return _main()
    except Exception as exc:  # never break the user's status line
        c.log(f"sensor crashed: {exc!r}")
        print("claudown ▸ sensor error (see ~/.claude/claudown.log)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
