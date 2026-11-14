#!/usr/bin/env python3
"""claudown ORCHESTRATOR: wrap-up, sleep mode, shutdown and backstop.

Roles:

* Library: `trigger()` fires the action exactly once per window (atomic lock):
  - local machine  -> cross-platform shutdown
  - Claude Code on the web (CLAUDE_CODE_REMOTE=true) -> webhook POST, because a
    cloud VM cannot power off your laptop.
  `start_wrap_up()` / `finish_wrap_up()` add a grace phase first, so Claude can
  save its work and finish its turn before the computer goes off.
* `Stop` hook: when Claude finishes its turn it completes a pending wrap-up, or,
  in sleep mode (`--sleep`), powers off because the job is done.
* `StopFailure` hook (matcher "rate_limit"): last-resort backstop after the
  limit was actually hit. Fires immediately. This is not the sensor.

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


def action_text(action: Optional[str] = None) -> str:
    """Plain-English description of what will happen, for messages to Claude/users."""
    if c.is_dry_run():
        return "log what it would do (DRY RUN: nothing is actually turned off)"
    action = action or resolve_action()
    return {
        "shutdown": "shut down this computer",
        "notify": "send the shutdown webhook to your laptop",
        "both": "send the webhook and shut down this computer",
        "none": "keep blocking (no shutdown configured)",
    }.get(action, "shut down this computer")


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
        body = (f"claudown: {payload.get('limit', 'usage')} limit reached "
                f"({payload.get('usage_pct')}%). {payload.get('reason')}").encode()
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
            action: Optional[str] = None, session_id: Optional[str] = None,
            limit: Optional[str] = None) -> bool:
    """Fire the action once per window. Returns True if it fired now."""
    now = time.time() if now is None else now
    action = action or resolve_action()
    if c.is_remote() and action in ("shutdown", "both"):
        c.log("cloud session: a shutdown here would only stop the cloud VM; sending the webhook instead")
        action = "notify"
    dry_run = c.is_dry_run()
    session_id = session_id or c.load_state().get("session_id")
    info = {
        "triggered_at": now,
        "window_resets_at": resets_at,
        "pct": pct,
        "limit": limit,
        "source": source,
        "reason": reason,
        "action": action,
        "dry_run": dry_run,
        "host_remote": c.is_remote(),
    }
    if not c.acquire_lock(info, now):
        c.log(f"already triggered this window; not firing again ({reason})")
        return False

    # This firing ends any wrap-up and any sleep request: never fire twice after a reboot.
    c.clear_file(c.wrapup_path())
    c.clear_file(c.sleep_flag_path())

    c.log(f"TRIGGER: {reason} | pct={pct} limit={limit} source={source} action={action} dry_run={dry_run}")
    payload = {
        "event": "claudown.threshold_reached",
        "session_id": session_id,
        "timestamp": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "limit": limit,
        "usage_pct": None if pct is None else round(pct, 1),
        "threshold": c.threshold(),
        "weekly_threshold": c.weekly_threshold(),
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


def trigger_limit(ev: Dict[str, Any], reason: str, session_id: Optional[str] = None,
                  action: Optional[str] = None) -> bool:
    """trigger() for an evaluate_limits() result."""
    return trigger(reason, ev.get("pct"), ev.get("source", "?"), ev.get("resets_at"),
                   action=action, session_id=session_id, limit=ev.get("kind"))


# ------------------------------------------------------------------ wrap-up
def wrap_up_state() -> Optional[Dict[str, Any]]:
    data = c.read_json(c.wrapup_path())
    return data if isinstance(data, dict) else None


def start_wrap_up(ev: Dict[str, Any], session_id: Optional[str] = None,
                  now: Optional[float] = None) -> Dict[str, Any]:
    """Begin the grace phase (once). Returns the wrap-up record."""
    now = time.time() if now is None else now
    max_s = max(5.0, c.cfg_float("WRAP_UP_MAX_SECONDS") or 600.0)
    grace = int(c.cfg_float("WRAP_UP_TOOL_CALLS") or 0)
    record = {
        "started_at": now, "deadline": now + max_s, "grace_left": max(0, grace),
        "kind": ev.get("kind"), "pct": ev.get("pct"), "limit": ev.get("limit"),
        "resets_at": ev.get("resets_at"), "source": ev.get("source"), "session_id": session_id,
    }
    path = c.wrapup_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return wrap_up_state() or record  # another hook started it a moment ago
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, sort_keys=True)
    c.log(f"WRAP-UP started: {ev.get('kind')} usage {ev.get('pct')}% >= {ev.get('limit')}% "
          f"({grace} tool calls, {int(max_s)}s max)")
    # Safety net: act at the deadline even if Claude never ends its turn.
    _spawn_detached([sys.executable, str(Path(__file__).resolve()), "--wrap-up-deadline", repr(now)])
    return record


def use_grace_call() -> bool:
    """Spend one wrap-up tool call. True if one was left."""
    st = wrap_up_state()
    if not st or int(st.get("grace_left") or 0) <= 0:
        return False
    st["grace_left"] = int(st["grace_left"]) - 1
    try:
        c.write_json_atomic(c.wrapup_path(), st)
    except OSError:
        pass
    return True


def finish_wrap_up(why: str) -> bool:
    """Run the action for a pending wrap-up. Returns True if it fired now."""
    st = wrap_up_state()
    if not st:
        return False
    fired = trigger(
        reason=f"{st.get('kind', 'usage')} limit {st.get('pct')}% >= {st.get('limit')}%: {why}",
        pct=c.to_float(st.get("pct")), source=str(st.get("source") or "?"),
        resets_at=c.to_float(st.get("resets_at")), session_id=st.get("session_id"),
        limit=st.get("kind"),
    )
    c.clear_file(c.wrapup_path())
    return fired


def wait_for_deadline(started: float) -> int:
    """Detached safety timer started by start_wrap_up()."""
    st = wrap_up_state()
    if not st or c.to_float(st.get("started_at")) != started:
        return 0
    remaining = (c.to_float(st.get("deadline")) or time.time()) - time.time()
    if remaining > 0:
        time.sleep(remaining)
    st = wrap_up_state()
    if st and c.to_float(st.get("started_at")) == started:
        finish_wrap_up("wrap-up time ran out")
    return 0


# ------------------------------------------------------------------ sleep mode
def set_sleep(hours: Optional[float] = None) -> Dict[str, Any]:
    hours = hours if hours and hours > 0 else (c.cfg_float("SLEEP_HOURS") or 12.0)
    now = time.time()
    data = {"created_at": now, "expires_at": now + hours * 3600}
    c.write_json_atomic(c.sleep_flag_path(), data)
    c.log(f"SLEEP mode on for up to {hours:g} h: claudown will act when Claude finishes its turn")
    return data


# ------------------------------------------------------------------ hooks
def handle_stop(hook: Dict[str, Any]) -> int:
    """`Stop` hook: Claude finished its turn."""
    if c.is_disabled():
        return 0
    if wrap_up_state():
        finish_wrap_up("Claude finished wrapping up")
        return 0
    if c.sleep_active():
        ev = c.evaluate_limits()
        pct = ev["five_hour"].get("pct")
        trigger("sleep mode: Claude finished its work", pct, "sleep",
                resets_at=time.time() + 120, session_id=hook.get("session_id"), limit="sleep")
    return 0


def handle_stop_failure(hook: Dict[str, Any]) -> int:
    err = str(hook.get("error") or "").lower()
    if err != "rate_limit":
        return 0  # the settings matcher should already filter, but be defensive
    if not c.cfg_bool("BACKSTOP_ENABLED") or c.is_disabled():
        c.log("backstop: rate_limit seen but backstop disabled")
        return 0
    detail = hook.get("error_details") or hook.get("last_assistant_message") or ""
    ev = c.evaluate_limits()
    resets = ev.get("resets_at") or ev["five_hour"].get("resets_at")
    trigger(f"backstop: StopFailure rate_limit ({str(detail)[:120]})", 100.0,
            "stopfailure", resets, session_id=hook.get("session_id"), limit="rate_limit")
    return 0


def status() -> Dict[str, Any]:
    ev = c.evaluate_limits()
    return {
        "version": c.VERSION,
        "os": detect_os(),
        "remote": c.is_remote(),
        "dry_run": c.is_dry_run(),
        "disabled": c.is_disabled(),
        "threshold_5h": ev["threshold"],
        "threshold_weekly": ev["weekly_threshold"],
        "action": resolve_action(),
        "usage_5h": ev["five_hour"],
        "usage_weekly": ev["weekly"],
        "limit_reached": ev.get("kind"),
        "wrap_up": wrap_up_state(),
        "sleep_mode": c.sleep_active(),
        "state_file": str(c.state_path()),
        "log_file": str(c.log_path()),
        "lock": c.active_lock(),
        "shutdown_commands": [show(x) for x in shutdown_candidates()],
    }


def _main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="claudown",
                                 description="claudown orchestrator: status, sleep mode, tests, hooks")
    ap.add_argument("--status", action="store_true", help="print current state as JSON")
    ap.add_argument("--sleep", type=float, nargs="?", const=0.0, metavar="HOURS",
                    help="sleep mode: act as soon as Claude finishes its current turn "
                         "(expires after HOURS, default SLEEP_HOURS=12)")
    ap.add_argument("--wake", action="store_true", help="cancel sleep mode")
    ap.add_argument("--test", action="store_true", help="dry-run the full trigger path (ignores lock)")
    ap.add_argument("--trigger", action="store_true", help="fire the configured action now")
    ap.add_argument("--reset", action="store_true", help="clear the trigger lock and any wrap-up")
    ap.add_argument("--version", action="version", version=f"claudown {c.VERSION}")
    ap.add_argument("--execute-shutdown", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--after", type=float, default=0, help=argparse.SUPPRESS)
    ap.add_argument("--wrap-up-deadline", type=float, default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.execute_shutdown:
        if args.after > 0:
            time.sleep(args.after)
        execute_candidates(shutdown_candidates(delay=0))
        return 0
    if args.wrap_up_deadline is not None:
        return wait_for_deadline(args.wrap_up_deadline)
    if args.status:
        print(json.dumps(status(), indent=2, default=str))
        return 0
    if args.sleep is not None:
        data = set_sleep(args.sleep)
        until = datetime.fromtimestamp(data["expires_at"]).strftime("%Y-%m-%d %H:%M")
        print(f"Sleep mode ON (until {until}). When Claude finishes its current task, "
              f"claudown will {action_text()}. Cancel with --wake.")
        return 0
    if args.wake:
        had = c.sleep_flag_path().exists()
        c.clear_file(c.sleep_flag_path())
        print("Sleep mode OFF." if had else "Sleep mode was not on.")
        return 0
    if args.reset:
        c.clear_file(c.wrapup_path())
        print("lock cleared" if c.release_lock() else "no lock to clear")
        return 0
    if args.test:
        os.environ["DRY_RUN"] = "true"
        ev = c.evaluate_limits()
        run_shutdown("manual --test")
        if resolve_action() in ("notify", "both"):
            send_notification({"event": "claudown.test", "usage_pct": ev["five_hour"].get("pct")}, True)
        return 0
    if args.trigger:
        ev = c.evaluate_limits()
        fired = trigger("manual --trigger", ev["five_hour"].get("pct"), "cli",
                        ev.get("resets_at") or ev["five_hour"].get("resets_at"), limit="manual")
        print("fired" if fired else "already triggered this window (use --reset)")
        return 0

    # Default: invoked as a hook with JSON on stdin.
    hook = c.read_stdin_json()
    event = hook.get("hook_event_name")
    if event == "Stop":
        return handle_stop(hook)
    if event in (None, "StopFailure"):
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
