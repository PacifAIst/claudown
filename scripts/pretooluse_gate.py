#!/usr/bin/env python3
"""claudown GATE - `PreToolUse` (and `UserPromptSubmit`) hook.

Works in the Claude Code CLI and in the VS Code extension (both run hooks).
Reads the sensor's state file, or the transcript sensor when the statusLine
sensor is silent. At or above SHUTDOWN_THRESHOLD it:

1. blocks the tool call / prompt with exit code 2 (stops further token spend), and
2. fires the shutdown or webhook sequence exactly once per 5-hour window.

Fail-open: if usage cannot be determined, the call is allowed and a clear
warning is logged (at most once an hour). No network, no SDK, no tokens.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

try:
    from . import claudown_common as c
    from . import shutdown_orchestrator as orch
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import claudown_common as c  # noqa: E402
    import shutdown_orchestrator as orch  # noqa: E402

_WARN_EVERY = 3600.0

COMPUTER_USE_HINT = (
    " Optional computer-use shutdown is enabled: if the computer-use tool is available "
    "in this session, use it now to open the Apple menu and choose Shut Down. If it is "
    "not available, do nothing else."
)


def _warn_unknown(source: str) -> None:
    """Log 'usage unknown' at most once per hour (typical VS Code statusLine gap)."""
    st = c.load_state()
    last = c.to_float(st.get("last_unknown_warning")) or 0.0
    now = time.time()
    if now - last < _WARN_EVERY:
        return
    c.log(
        f"WARNING usage unknown ({source}): the statusLine sensor is not running (normal in "
        "the VS Code panel) and the transcript sensor has no TOKEN_BUDGET_5H to compare "
        "against, so claudown is NOT guessing. Tool calls are allowed. Fix: see "
        "GETTING_STARTED.md > Troubleshooting."
    )
    st["last_unknown_warning"] = now
    try:
        c.write_json_atomic(c.state_path(), st)
    except OSError:
        pass


def _main() -> int:
    hook = c.read_stdin_json()
    event = hook.get("hook_event_name", "PreToolUse")
    if c.is_disabled():
        return 0

    reading = c.effective_usage()
    pct = reading.get("pct")
    if pct is None:
        _warn_unknown(reading.get("source", "unknown"))
        return 0

    thr = c.threshold()
    if pct < thr:
        return 0

    tool = hook.get("tool_name") or ("prompt" if event == "UserPromptSubmit" else "tool")
    fired = orch.trigger(
        reason=f"gate: 5-hour usage {pct:.1f}% >= {thr:.0f}% ({event}:{tool})",
        pct=pct,
        source=reading.get("source", "?"),
        resets_at=reading.get("resets_at"),
        session_id=hook.get("session_id"),
    )

    if not c.cfg_bool("BLOCK_TOOLS"):
        return 0
    lock = c.active_lock() or {}
    mode = "DRY RUN - nothing was executed" if lock.get("dry_run", c.is_dry_run()) else lock.get("action", "")
    msg = (
        f"[claudown] Blocked: Claude 5-hour usage is {pct:.1f}% (threshold {thr:.0f}%, "
        f"source {reading.get('source')}). Action {'fired' if fired else 'already fired'}: {mode}. "
        "Stop here and wait for the window to reset. To override: create the file "
        f"{c.disabled_flag_path()}."
    )
    if c.cfg_bool("COMPUTER_USE_SHUTDOWN") and orch.detect_os() == "macos" and not c.is_dry_run():
        msg += COMPUTER_USE_HINT
    print(msg, file=sys.stderr)
    return 2  # exit 2 = block (PreToolUse: deny tool; UserPromptSubmit: reject prompt)


def main() -> int:
    c.utf8_stdio()
    try:
        return _main()
    except Exception as exc:
        c.log(f"gate crashed (failing open): {exc!r}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
