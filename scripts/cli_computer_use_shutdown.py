#!/usr/bin/env python3
"""claudown OPTIONAL COMPUTER-USE PATH (Claude Code CLI on macOS only).

Claude Code ships a built-in `computer-use` MCP server (research preview). It
is OFF by default and can only be switched on by you, inside an interactive
session, with `/mcp`. Requirements (per Claude Code docs):

* macOS only (not Linux, not Windows)
* a claude.ai Pro, Max or Ultra plan (NOT Team or Enterprise), logged in with
  claude.ai (not an API key, Bedrock or Vertex)
* Claude Code v2.1.85 or later, interactive session (it does not work with `claude -p`)

Because it can't be switched on or driven from a script, this file does NOT
start Claude or spend tokens. It:

  --check    (default) reports whether this computer looks eligible
  --enable   if eligible, sets COMPUTER_USE_SHUTDOWN=true in claudown's config.
             When the gate then blocks at the threshold (and DRY_RUN=false),
             its block message also asks Claude to shut the Mac down with the
             computer-use tool. That costs a few tokens, so it's opt-in.
  --disable  turns it back off

This is never the primary path. The normal hook path (gate + shutdown command)
always runs first and works without it. If computer-use isn't available,
Claude simply ignores the request. Detection stays zero-token either way.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from . import claudown_common as c
    from . import shutdown_orchestrator as orch
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import claudown_common as c  # noqa: E402
    import shutdown_orchestrator as orch  # noqa: E402

MIN_VERSION: Tuple[int, int, int] = (2, 1, 85)

STEPS = """\
To finish turning it on (one time, inside Claude Code):
  1. Start Claude Code in a terminal:  claude
  2. Type  /mcp  and press Enter.
  3. Pick  computer-use  from the list and choose  Enable.
  4. The first time it's used, macOS asks for Accessibility and Screen
     Recording permission. Allow both in System Settings > Privacy & Security.
If computer-use is not in the /mcp list, your plan or computer is not eligible.
claudown keeps working through the normal shutdown command; nothing breaks."""


def claude_version() -> Optional[Tuple[int, int, int]]:
    exe = shutil.which("claude")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return None
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", out or "")
    return tuple(int(x) for x in m.groups()) if m else None  # type: ignore[return-value]


def eligibility(os_name: Optional[str] = None) -> Dict[str, Any]:
    os_name = os_name or orch.detect_os()
    report: Dict[str, Any] = {"os": os_name, "checks": {}, "eligible": False}
    checks = report["checks"]
    checks["macos"] = os_name == "macos"
    if not checks["macos"]:
        report["reason"] = "computer-use in the Claude Code CLI is macOS only"
        return report

    ver = claude_version()
    checks["claude_version"] = ".".join(map(str, ver)) if ver else None
    checks["version_ok"] = bool(ver and ver >= MIN_VERSION)

    # Zero-token plan hint: Claude Code only sends rate_limits to the status line
    # for claude.ai Pro/Max/Ultra subscribers, so the sensor has seen it -> subscriber.
    seen = c.load_state().get("rate_limits_present")
    checks["subscriber_plan_seen"] = seen  # True, False, or None (sensor never ran)

    if not checks["version_ok"]:
        report["reason"] = "Claude Code not found or older than 2.1.85 (update it first)"
    elif seen is False:
        report["reason"] = ("the status line never received rate-limit data: this looks like an "
                            "API-key, Team or Enterprise login, which can't use computer-use")
    else:
        report["eligible"] = True
        report["reason"] = ("looks eligible" if seen else
                            "probably eligible (plan unknown until the claudown status line has run)")
    return report


def set_flag(value: bool) -> Path:
    path = c.config_file_path()
    conf = c.read_json(path) or {}
    conf["COMPUTER_USE_SHUTDOWN"] = "true" if value else "false"
    c.write_json_atomic(path, conf)
    return path


def _main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="report eligibility (default)")
    g.add_argument("--enable", action="store_true", help="opt in, if eligible")
    g.add_argument("--disable", action="store_true", help="opt out")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    if args.disable:
        print(f"Computer-use shutdown turned off ({set_flag(False)}).")
        return 0

    report = eligibility()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"computer-use eligibility: {'YES' if report['eligible'] else 'NO'} - {report['reason']}")

    if not report["eligible"]:
        # Fall back silently: the hook path keeps working, nothing to configure.
        if args.enable:
            print("Not enabled. claudown will keep using the normal shutdown command.")
        return 0
    if args.enable:
        print(f"Saved COMPUTER_USE_SHUTDOWN=true in {set_flag(True)}.")
        print(STEPS)
    elif not args.json:
        print("Run again with --enable to opt in.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    c.utf8_stdio()
    return _main(argv)


if __name__ == "__main__":
    sys.exit(main())
