#!/usr/bin/env python3
"""claudown WEB WATCHER - runs INSIDE a Claude Code on the web cloud session.

A cloud VM cannot power off your laptop, so this watcher NEVER runs a shutdown
command. It polls the session's local state (statusLine reading, or transcripts)
and, when usage crosses SHUTDOWN_THRESHOLD (5-hour) or WEEKLY_THRESHOLD
(7-day), and after the wrap-up (see pretooluse_gate.py), sends one HTTP POST to the webhook
YOU configured (WEBHOOK_URL) with the session ID, a timestamp and the usage
percentage. Run local_webhook_listener.py on your laptop to turn that POST into
a real shutdown.

Usage
    web_limit_watcher.py            SessionStart hook: starts a background poller, returns at once
    web_limit_watcher.py --loop     the poller itself (stops after 12 hours)
    web_limit_watcher.py --once     one check, then exit (good for testing)

Outside a cloud session (CLAUDE_CODE_REMOTE is not "true") it does nothing
unless you pass --force. Detection reads only local files; the webhook POST is
the only network call, and DRY_RUN=true (the default) only logs it.

Note: if Computer Use is enabled in a cloud session, Claude can see the limit
on screen, but it still cannot power off your local machine. Only this
webhook-plus-listener bridge can.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from . import claudown_common as c
    from . import shutdown_orchestrator as orch
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import claudown_common as c  # noqa: E402
    import shutdown_orchestrator as orch  # noqa: E402

MAX_LIFETIME = 12 * 3600


def pid_path() -> Path:
    return c.claude_dir() / "claudown_web_watcher.pid"


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return False  # cloud sessions are Linux; on Windows just allow a new poller
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def check(session_id: Optional[str] = None) -> Dict[str, Any]:
    """One poll. Fires the webhook (once per window) at or above the threshold."""
    if c.is_disabled():
        return {"fired": False, "why": "disabled"}
    ev = c.evaluate_limits()
    pct = ev["five_hour"].get("pct")
    c.update_state(web_watcher_checked_at=time.time(), web_watcher_pct=pct,
                   web_watcher_weekly_pct=ev["weekly"].get("pct"))
    if not ev["hit"]:
        if pct is None:
            return {"fired": False, "why": f"usage unknown ({ev['five_hour'].get('source')})"}
        return {"fired": False, "why": f"{pct:.1f}% < {ev['threshold']:.0f}%"}

    if c.active_lock() is None and c.cfg_bool("WRAP_UP") and not ev.get("exhausted"):
        st = orch.wrap_up_state()
        if st is None:
            orch.start_wrap_up(ev, session_id)  # the gate/Stop hook or the deadline finish it
            return {"fired": False, "why": f"{ev['kind']} limit reached - wrap-up started"}
        if time.time() < (c.to_float(st.get("deadline")) or 0):
            return {"fired": False, "why": "wrap-up in progress"}
        fired = orch.finish_wrap_up("wrap-up time ran out")
        return {"fired": fired, "why": "wrap-up time ran out"}

    fired = orch.trigger_limit(
        ev, f"web watcher: {ev['kind']} usage {ev['pct']:.1f}% >= {ev['limit']:.0f}%",
        session_id=session_id, action="notify",  # never a shutdown inside the cloud VM
    )
    return {"fired": fired, "why": f"{ev['kind']} limit reached" if fired else "already fired this window"}


def loop(session_id: Optional[str]) -> int:
    interval = max(5.0, c.cfg_float("WEB_POLL_SECONDS") or 30.0)
    started = time.time()
    try:
        pid_path().write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass
    c.log(f"web watcher started (pid {os.getpid()}, every {interval:.0f}s)")
    try:
        while time.time() - started < MAX_LIFETIME:
            try:
                check(session_id)
            except Exception as exc:
                c.log(f"web watcher check failed: {exc!r}")
            time.sleep(interval)
    finally:
        try:
            pid_path().unlink()
        except OSError:
            pass
    return 0


def start_background(session_id: Optional[str]) -> int:
    try:
        pid = int(pid_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid = 0
    if _alive(pid):
        return 0
    cmd = [sys.executable, str(Path(__file__).resolve()), "--loop"]
    if session_id:
        cmd += ["--session-id", str(session_id)]
    orch._spawn_detached(cmd)
    return 0


def _main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--loop", action="store_true", help="run the poller in the foreground")
    ap.add_argument("--once", action="store_true", help="check once and exit")
    ap.add_argument("--force", action="store_true", help="run even outside a cloud session")
    ap.add_argument("--session-id", default=None)
    args = ap.parse_args(argv)

    if not (c.is_remote() or args.force):
        return 0  # local machine: the CLI/VS Code gate handles everything

    session_id = args.session_id
    if args.once:
        res = check(session_id)
        print(f"claudown web watcher: {res['why']}" + (" - webhook fired" if res["fired"] else ""))
        return 0
    if args.loop:
        return loop(session_id)

    # SessionStart hook: hook JSON on stdin carries the session id.
    hook = c.read_stdin_json()
    return start_background(session_id or hook.get("session_id"))


def main(argv: Optional[List[str]] = None) -> int:
    c.utf8_stdio()
    try:
        return _main(argv)
    except SystemExit:
        raise
    except Exception as exc:
        c.log(f"web watcher crashed: {exc!r}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
