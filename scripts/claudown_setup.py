#!/usr/bin/env python3
"""claudown installer - works on Windows, macOS and Linux (no bash needed).

    python scripts/claudown_setup.py                     install for you (~/.claude), DRY RUN
    python scripts/claudown_setup.py --threshold 90      custom threshold (percent)
    python scripts/claudown_setup.py --arm               install ARMED (DRY_RUN=false): really shuts down
    python scripts/claudown_setup.py --project PATH      install into a repo's .claude/ (Claude Code on the web)
    python scripts/claudown_setup.py --uninstall [--project PATH]

Your existing settings.json is backed up and merged, never replaced. A status
line you already had is kept and shown above the claudown line.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from . import claudown_common as c
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import claudown_common as c  # noqa: E402

SRC = Path(__file__).resolve().parent
OUR_SCRIPTS = ("statusline_sensor.py", "pretooluse_gate.py", "shutdown_orchestrator.py",
               "web_limit_watcher.py")
ENV_KEYS = ("SHUTDOWN_THRESHOLD", "DRY_RUN", "ACTION")


def is_ours(cmd: Any) -> bool:
    s = str(cmd or "").replace("\\", "/")
    return "claudown/" in s and any(name in s for name in OUR_SCRIPTS)


def strip_ours(hooks: Dict[str, Any]) -> Dict[str, Any]:
    for event in list(hooks):
        groups = []
        for g in hooks[event] or []:
            g = dict(g)
            g["hooks"] = [h for h in g.get("hooks", []) if not is_ours(h.get("command"))]
            if g["hooks"]:
                groups.append(g)
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    return hooks


def _win_short(path: str) -> str:
    """8.3 short path (no spaces) so the command works in Git Bash AND PowerShell."""
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(path, buf, 1024):  # type: ignore[attr-defined]
            return buf.value
    except Exception:
        pass
    return path


def shell_path(path: Path) -> str:
    p = str(path)
    if os.name == "nt":
        if " " in p:
            p = _win_short(p)
        p = p.replace("\\", "/")
        return f'"{p}"' if " " in p else p
    return shlex.quote(p)


def command_builder(project: bool, target: Path, python: str):
    if project:
        # Cloud sessions are Linux with python3; paths are relative to the repo.
        return lambda name: f'python3 "$CLAUDE_PROJECT_DIR/.claude/claudown/{name}"'
    py = shell_path(Path(python))
    return lambda name: f"{py} {shell_path(target / name)}"


def install_files(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for f in list(SRC.glob("*.py")) + list(SRC.glob("*.sh")):
        shutil.copy2(f, target / f.name)
        if os.name != "nt":
            os.chmod(target / f.name, 0o755)


def merge(settings: Path, target: Path, args: argparse.Namespace, project: bool) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    if settings.exists():
        try:
            data = json.loads(settings.read_text(encoding="utf-8") or "{}")
        except ValueError:
            raise SystemExit(f"{settings} is not valid JSON; fix it first (nothing was changed).")
        backup = settings.with_name(f"settings.json.bak.{int(time.time())}")
        shutil.copy2(settings, backup)
        print(f"Backed up your existing settings to {backup}")

    conf_path = target / "config.json"
    conf: Dict[str, Any] = c.read_json(conf_path) or {}
    hooks = strip_ours(data.get("hooks") or {})
    sl = data.get("statusLine")

    if args.uninstall:
        if isinstance(sl, dict) and is_ours(sl.get("command")):
            chained = conf.get("STATUSLINE_CHAIN_COMMAND")
            if chained:
                data["statusLine"] = {"type": "command", "command": chained}
            else:
                data.pop("statusLine", None)
        env = data.get("env") or {}
        for k in ENV_KEYS:
            env.pop(k, None)
        data["env"] = env
        if not env:
            data.pop("env")
        data["hooks"] = hooks
        if not hooks:
            data.pop("hooks")
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        if target.exists():
            shutil.rmtree(target)
        print("claudown removed. Its log and state files in the .claude folder were left for you.")
        return data

    q = command_builder(project, target, args.python)
    if isinstance(sl, dict) and sl.get("command") and not is_ours(sl.get("command")):
        conf["STATUSLINE_CHAIN_COMMAND"] = sl["command"]
        print(f"Kept your existing status line (shown above claudown's): {sl['command']}")
    data["statusLine"] = {"type": "command", "command": q("statusline_sensor.py"), "refreshInterval": 60}

    hooks.setdefault("PreToolUse", []).append(
        {"matcher": "*", "hooks": [{"type": "command", "command": q("pretooluse_gate.py"), "timeout": 30}]})
    hooks.setdefault("UserPromptSubmit", []).append(
        {"hooks": [{"type": "command", "command": q("pretooluse_gate.py"), "timeout": 30}]})
    hooks.setdefault("StopFailure", []).append(
        {"matcher": "rate_limit",
         "hooks": [{"type": "command", "command": q("shutdown_orchestrator.py"), "timeout": 60}]})
    if project:
        hooks.setdefault("SessionStart", []).append(
            {"hooks": [{"type": "command", "command": q("web_limit_watcher.py"), "timeout": 30}]})
    data["hooks"] = hooks

    env = data.setdefault("env", {})
    if args.threshold:
        env["SHUTDOWN_THRESHOLD"] = str(args.threshold)
    env.setdefault("SHUTDOWN_THRESHOLD", "95")
    env["DRY_RUN"] = "false" if args.arm else env.get("DRY_RUN", "true")
    env["ACTION"] = args.action or env.get("ACTION") or ("notify" if project else "auto")

    if project:
        print("Web setup: put WEBHOOK_URL and WEBHOOK_TOKEN in your cloud environment's "
              "environment variables (never commit them). See GETTING_STARTED.md, part 2C.")
    if conf:
        target.mkdir(parents=True, exist_ok=True)
        c.write_json_atomic(conf_path, conf)

    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Added claudown to {settings}")
    print(f"  threshold={env['SHUTDOWN_THRESHOLD']}%  DRY_RUN={env['DRY_RUN']}  ACTION={env['ACTION']}")
    return data


def _main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="claudown-setup", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", metavar="PATH", help="install into PATH/.claude (for Claude Code on the web)")
    ap.add_argument("--threshold", type=float, help="percent of the 5-hour window (default 95)")
    ap.add_argument("--arm", action="store_true", help="DRY_RUN=false: really shut down")
    ap.add_argument("--action", choices=["auto", "shutdown", "notify", "both", "none"])
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--python", default=sys.executable, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.threshold is not None and not (0 < args.threshold <= 100):
        ap.error("--threshold must be between 1 and 100")
    if args.threshold is not None:
        args.threshold = f"{args.threshold:g}"

    project = bool(args.project)
    if project:
        root = Path(args.project).expanduser().resolve()
        if not root.is_dir():
            print(f"Project folder not found: {root}", file=sys.stderr)
            return 1
        base = root / ".claude"
    else:
        base = c.claude_dir()
    target = base / "claudown"
    settings = base / "settings.json"
    base.mkdir(parents=True, exist_ok=True)

    if not args.uninstall:
        install_files(target)
    merge(settings, target, args, project)
    if args.uninstall:
        return 0

    print("\nSelf-test (dry run, nothing is executed):")
    env = dict(os.environ, DRY_RUN="true")
    subprocess.run([sys.executable, str(target / "shutdown_orchestrator.py"), "--test"], env=env)
    print()
    if args.arm:
        print("!! claudown is ARMED. At the threshold your computer WILL shut down without saving your work.")
    else:
        print("claudown is installed in DRY RUN mode: it only writes what it would do to "
              f"{c.log_path() if not project else '.claude/claudown.log'}. Re-run with --arm to enable it.")
    if project:
        print(f"Commit {target} and {settings} to the repository so web sessions pick them up.")
    print("Restart Claude Code (or open a new session) so the changes load.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    c.utf8_stdio()
    return _main(argv)


if __name__ == "__main__":
    sys.exit(main())
