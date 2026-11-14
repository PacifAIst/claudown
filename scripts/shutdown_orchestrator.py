#!/usr/bin/env python3
"""claudown ORCHESTRATOR + BACKSTOP.

Two roles:

* Library: `trigger()` is called by the gate, the web watcher and the local
  webhook listener. It is idempotent (one action per 5-hour window, enforced by
  an atomic lock file) and picks the action:
  - local machine  -> cross-platform shutdown
  - Claude Code on the web (CLAUDE_CODE_REMOTE=true) -> webhook POST, because a
    cloud VM cannot power off your laptop.
* Hook: as a `StopFailure` hook with matcher "rate_limit" it reads the hook
  JSON on stdin and fires the action as a last resort, after the limit is hit.
  This is the backstop, not the sensor.

DRY_RUN is the default: commands are logged, never executed, until you set
DRY_RUN=false. Failures are logged and the script exits 0 (never crashes a hook).

The only network call anywhere in claudown is the optional webhook to an
endpoint YOU configure (WEBHOOK_URL). Nothing ever contacts Anthropic.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    from . import claudown_common as c
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import claudown_common as c  # noqa: E402

Command = Union[List[str], str]


# ------------------------------------------------------------------ commands
def detect_os() -> str:
    name = platform.system().lower()
    if name.startswith("win") or os.name == "nt":
        return "windows"
    if name == "darwin":
        return "macos"
    return "linux"


def shutdown_candidates(os_name: Optional[str] = None, delay: int = 0) -> List[Command]:
    """Commands to try in order. The first is the canonical one; the rest are
    fallbacks that avoid needing passwordless sudo."""
    os_name = os_name or detect_os()
    override = c.cfg("SHUTDOWN_COMMAND").strip()
    if override:
        # Windows: hand the raw string to CreateProcess, which understands
        # quoted paths with spaces. POSIX: split it like a shell would.
        return [override] if os_name == "windows" else [shlex.split(override)]
    if os_name == "windows":
        return [["shutdown", "/s", "/t", str(max(0, delay))]]
    if os_name == "macos":
        return [
            ["sudo", "-n", "shutdown", "-h", "now"],
            ["osascript", "-e", 'tell application "System Events" to shut down'],
        ]
    return [
        ["sudo", "-n", "systemctl", "poweroff"],
        ["systemctl", "poweroff"],  # works without sudo on most polkit desktops
    ]


def show(cmd: Command) -> str:
    return cmd if isinstance(cmd, str) else " ".join(cmd)


def resolve_action() -> str:
    action = c.cfg("ACTION").strip().lower() or "auto"
    if action == "auto":
        return "notify" if c.is_remote() else "shutdown"
    if action not in {"shutdown", "notify", "both", "none"}:
        c.log(f"unknown ACTION={action!r}; falling back to auto")
        return "notify" if c.is_remote() else "shutdown"
    return action


# ------------------------------------------------------------------ actions
def run_shutdown(reason: str, dry_run: Optional[bool] = None) -> bool:
    dry_run = c.is_dry_run() if dry_run is None else dry_run
    delay = int(c.cfg_float("SHUTDOWN_DELAY_SECONDS") or 0)
    os_name = detect_os()
    cands = shutdown_candidates(os_name, delay)

    if dry_run:
        for i, cmd in enumerate(cands):
            label = "would execute" if i == 0 else "fallback would be"
            msg = f"DRY_RUN: {label}: {show(cmd)} (os={os_name}, delay={delay}s, reason={reason})"
            c.log(msg)
            print(msg, file=sys.stderr)
        return True

    local_alert(f"claudown: shutting down in {delay}s - {reason}")
    if delay > 0 and os_name != "windows":
        # Detach a sleeper so the hook returns immediately.
        return _spawn_detached([sys.executable, str(Path(__file__).resolve()), "--execute-shutdown",
                                "--after", str(delay)])
    return execute_candidates(cands)


def execute_candidates(cands: List[Command]) -> bool:
    for cmd in cands:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except FileNotFoundError:
            c.log(f"shutdown command not found: {show(cmd)}")
            continue
        except subprocess.TimeoutExpired:
            c.log(f"shutdown command timed out: {show(cmd)}")
            continue
        except Exception as exc:
            c.log(f"shutdown command error {show(cmd)}: {exc!r}")
            continue
        if res.returncode == 0:
            c.log(f"shutdown issued: {show(cmd)}")
            return True
        c.log(f"shutdown failed rc={res.returncode}: {show(cmd)} :: {(res.stderr or '').strip()[:300]}")
    c.log("all shutdown commands failed; exiting gracefully (see README > Troubleshooting)")
    return False


def _spawn_detached(cmd: List[str]) -> bool:
    try:
        kwargs: Dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                                  "stderr": subprocess.DEVNULL}
        if os.name == "nt":
            kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_GROUP
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(cmd, **kwargs)
        return True
    except Exception as exc:
        c.log(f"could not spawn detached process: {exc!r}")
        return False


def local_alert(text: str) -> None:
    """Best-effort desktop notification. Silent on failure."""
    os_name = detect_os()
    cmds = {
        "linux": [["notify-send", "-u", "critical", "claudown", text]],
        "macos": [["osascript", "-e", f'display notification {json.dumps(text)} with title "claudown"']],
        "windows": [["msg", "*", text]],
    }.get(os_name, [])
    for cmd in cmds:
        try:
            subprocess.run(cmd, capture_output=True, timeout=5)
        except Exception:
            pass


def send_notification(payload: Dict[str, Any], dry_run: Optional[bool] = None) -> bool:
    """POST to the user's own webhook. The ONLY network call in claudown."""
    dry_run = c.is_dry_run() if dry_run is None else dry_run
    url = c.cfg("WEBHOOK_URL").strip()
    if not url:
        c.log("notify requested but WEBHOOK_URL is empty; nothing sent")
        return False
    if not url.lower().startswith(("https://", "http://")):
        c.log("WEBHOOK_URL must be http(s); nothing sent")
        return False
    fmt = c.cfg("WEBHOOK_FORMAT").strip().lower()
    if fmt == "text":
        body = (f"claudown: Claude 5-hour usage at {payload.get('usage_pct')}% "
                f"(threshold {payload.get('threshold')}%). {payload.get('reason')}").encode()
        ctype = "text/plain; charset=utf-8"
    else:
        body = json.dumps(payload).encode()
        ctype = "application/json"
    if dry_run:
        msg = f"DRY_RUN: would POST {len(body)} bytes ({ctype}) to {url}"
        c.log(msg)
        print(msg, file=sys.stderr)
        return True

    import urllib.request  # imported lazily: only reached for a real webhook send

    headers = {"Content-Type": ctype, "User-Agent": f"claudown/{c.VERSION}", "Title": "claudown"}
    token = c.cfg("WEBHOOK_TOKEN").strip()
    if token:
        headers["X-Claudown-Token"] = token
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            c.log(f"webhook sent: HTTP {resp.status}")
            return 200 <= resp.status < 300
    except Exception as exc:
        c.log(f"webhook failed: {exc!r}")
        return False


# ------------------------------------------------------------------ trigger
def trigger(reason: str, pct: Optional[float], source: str,
            resets_at: Optional[float] = None, now: Optional[float] = None,
            action: Optional[str] = None, session_id: Optional[str] = None) -> bool:
    """Fire the configured action once per window. Returns True if it fired now."""
    now = time.time() if now is None else now
    action = action or resolve_action()
    dry_run = c.is_dry_run()
    session_id = session_id or c.load_state().get("session_id")
    info = {
        "triggered_at": now,
        "window_resets_at": resets_at,
        "pct": pct,
        "source": source,
        "reason": reason,
        "action": action,
        "dry_run": dry_run,
        "host_remote": c.is_remote(),
    }
    if not c.acquire_lock(info, now):
        c.log(f"already triggered this window; not firing again ({reason})")
        return False

    c.log(f"TRIGGER: {reason} | pct={pct} source={source} action={action} dry_run={dry_run}")
    payload = {
        "event": "claudown.threshold_reached",
        "session_id": session_id,
        "timestamp": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "usage_pct": None if pct is None else round(pct, 1),
        "threshold": c.threshold(),
        "reason": reason,
        "source": source,
        "resets_at": resets_at,
        "remote": c.is_remote(),
        "host": platform.node(),
    }
    if action in ("notify", "both"):
        send_notification(payload, dry_run)
    if action in ("shutdown", "both"):
        run_shutdown(reason, dry_run)
    if action == "none":
        c.log("ACTION=none: gate blocks only, no shutdown/notification")
    return True


# ------------------------------------------------------------------ hook / CLI
def handle_stop_failure(hook: Dict[str, Any]) -> int:
    err = str(hook.get("error") or "").lower()
    if err != "rate_limit":
        return 0  # the settings matcher should already filter, but be defensive
    if not c.cfg_bool("BACKSTOP_ENABLED") or c.is_disabled():
        c.log("backstop: rate_limit seen but backstop disabled")
        return 0
    detail = hook.get("error_details") or hook.get("last_assistant_message") or ""
    reading = c.effective_usage()
    trigger(f"backstop: StopFailure rate_limit ({str(detail)[:120]})", 100.0,
            "stopfailure", reading.get("resets_at"), session_id=hook.get("session_id"))
    return 0


def status() -> Dict[str, Any]:
    reading = c.effective_usage()
    return {
        "version": c.VERSION,
        "os": detect_os(),
        "remote": c.is_remote(),
        "dry_run": c.is_dry_run(),
        "disabled": c.is_disabled(),
        "threshold": c.threshold(),
        "action": resolve_action(),
        "usage": reading,
        "state_file": str(c.state_path()),
        "log_file": str(c.log_path()),
        "lock": c.active_lock(),
        "shutdown_commands": [show(x) for x in shutdown_candidates()],
    }


def _main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="claudown",
                                 description="claudown shutdown orchestrator / StopFailure backstop")
    ap.add_argument("--status", action="store_true", help="print current state as JSON")
    ap.add_argument("--test", action="store_true", help="dry-run the full trigger path (ignores lock)")
    ap.add_argument("--trigger", action="store_true", help="fire the configured action now")
    ap.add_argument("--reset", action="store_true", help="clear the trigger lock")
    ap.add_argument("--version", action="version", version=f"claudown {c.VERSION}")
    ap.add_argument("--execute-shutdown", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--after", type=float, default=0, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.execute_shutdown:
        if args.after > 0:
            time.sleep(args.after)
        execute_candidates(shutdown_candidates(delay=0))
        return 0
    if args.status:
        print(json.dumps(status(), indent=2, default=str))
        return 0
    if args.reset:
        print("lock cleared" if c.release_lock() else "no lock to clear")
        return 0
    if args.test:
        os.environ["DRY_RUN"] = "true"
        r = c.effective_usage()
        run_shutdown("manual --test")
        if resolve_action() in ("notify", "both"):
            send_notification({"event": "claudown.test", "usage_pct": r.get("pct")}, True)
        return 0
    if args.trigger:
        r = c.effective_usage()
        fired = trigger("manual --trigger", r.get("pct"), "cli", r.get("resets_at"))
        print("fired" if fired else "already triggered this window (use --reset)")
        return 0

    # Default: invoked as a StopFailure hook with JSON on stdin.
    hook = c.read_stdin_json()
    if hook.get("hook_event_name") in (None, "StopFailure"):
        return handle_stop_failure(hook)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    c.utf8_stdio()
    try:
        return _main(argv)
    except SystemExit:
        raise
    except Exception as exc:
        c.log(f"orchestrator crashed: {exc!r}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
