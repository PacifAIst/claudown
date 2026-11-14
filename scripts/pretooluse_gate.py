#!/usr/bin/env python3
"""claudown GATE - `PreToolUse` (and `UserPromptSubmit`) hook.

Works in the Claude Code CLI and in the VS Code extension (both run hooks).
Checks the 5-hour AND the weekly limit before every tool call:

* below both thresholds: allow (exit 0).
* a threshold reached, first time: start the WRAP-UP. The tool call is blocked
  (exit 2) and Claude is told to save its work with a few more tool calls, then
  end its turn. The computer goes off when Claude finishes (`Stop` hook), or at
  WRAP_UP_MAX_SECONDS at the latest. Work in progress isn't cut mid-step.
* during the wrap-up: allow up to WRAP_UP_TOOL_CALLS more calls, then block.
* limit already fully used (no headroom), or WRAP_UP=false: fire at once.
* after the action fired: keep blocking until the window resets.

Fail-open: if usage cannot be determined, the call is allowed and a clear
warning is logged (at most once an hour). No network, no SDK, no tokens.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict

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


def _usage(ev: Dict[str, Any]) -> str:
    return f"Claude {ev.get('kind', 'usage')} usage is {ev.get('pct', 0):.1f}% (limit {ev.get('limit', 0):.0f}%)"


def wrap_up_message(ev: Dict[str, Any], st: Dict[str, Any]) -> str:
    minutes = max(1, round(((c.to_float(st.get("deadline")) or time.time()) - time.time()) / 60))
    calls = int(st.get("grace_left") or 0)
    save = (f"You may use up to {calls} more tool calls, ONLY to save your work (for example: "
            "write a short progress note, or commit). " if calls else "")
    return (
        f"[claudown] {_usage(ev)}. Time to wrap up. {save}Don't start anything new. "
        "Then end your turn with a short summary of what's done and what's left. "
        f"When you finish (or in {minutes} min at most), claudown will {orch.action_text()}."
    )


def blocked_message(ev: Dict[str, Any], fired: bool) -> str:
    lock = c.active_lock() or {}
    mode = "DRY RUN - nothing was executed" if lock.get("dry_run", c.is_dry_run()) else lock.get("action", "")
    msg = (
        f"[claudown] Blocked: {_usage(ev)}, source {ev.get('source')}. "
        f"Action {'fired' if fired else 'already fired'}: {mode}. "
        "Stop here and wait for the limit to reset. To override: create the file "
        f"{c.disabled_flag_path()}."
    )
    if c.cfg_bool("COMPUTER_USE_SHUTDOWN") and orch.detect_os() == "macos" and not c.is_dry_run():
        msg += COMPUTER_USE_HINT
    return msg


def _main() -> int:
    hook = c.read_stdin_json()
    event = hook.get("hook_event_name", "PreToolUse")
    if c.is_disabled():
        return 0

    ev = c.evaluate_limits()
    if not ev["hit"]:
        if ev["five_hour"].get("pct") is None:
            _warn_unknown(ev["five_hour"].get("source", "unknown"))
        return 0

    session_id = hook.get("session_id")
    block = c.cfg_bool("BLOCK_TOOLS")

    if c.active_lock() is None and block and c.cfg_bool("WRAP_UP") and not ev.get("exhausted"):
        st = orch.wrap_up_state()
        if st is None:
            st = orch.start_wrap_up(ev, session_id)
            print(wrap_up_message(ev, st), file=sys.stderr)
            return 2
        if time.time() < (c.to_float(st.get("deadline")) or 0):
            if event == "PreToolUse" and orch.use_grace_call():
                return 0
            print("[claudown] Wrap-up tool calls used up. End your turn now with a short summary; "
                  f"claudown will {orch.action_text()} as soon as you do.", file=sys.stderr)
            return 2
        orch.finish_wrap_up("wrap-up time ran out")
        print(blocked_message(ev, True), file=sys.stderr)
        return 2

    reason = f"gate: {ev.get('kind')} usage {ev.get('pct', 0):.1f}% >= {ev.get('limit', 0):.0f}% ({event}:" \
             f"{hook.get('tool_name') or ('prompt' if event == 'UserPromptSubmit' else 'tool')})"
    fired = orch.trigger_limit(ev, reason, session_id)
    if not block:
        return 0
    print(blocked_message(ev, fired), file=sys.stderr)
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
