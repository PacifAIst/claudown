"""claudown test-suite: zero tokens, zero network, zero real shutdowns.

Every script runs as a real subprocess (exactly as Claude Code would run it) with:
* an isolated CLAUDE_CONFIG_DIR / HOME in a temp folder,
* DRY_RUN=true (or a harmless SHUTDOWN_COMMAND override when testing armed mode),
* a sitecustomize.py that makes ANY socket connection fail and leaves a marker,
  so a single network attempt anywhere fails the suite.

Run:  python -m pytest -q
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

FORBIDDEN_MODULES = {"anthropic", "requests", "httpx", "aiohttp", "urllib", "urllib3",
                     "http", "socket", "ssl", "websocket", "websockets"}
ZERO_NETWORK_SCRIPTS = ["claudown_common.py", "statusline_sensor.py", "pretooluse_gate.py",
                        "vscode_transcript_sensor.py", "web_limit_watcher.py",
                        "cli_computer_use_shutdown.py", "claudown_setup.py"]


def src(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


# ----------------------------------------------------------------- fixtures
@pytest.fixture()
def sandbox(tmp_path):
    home = tmp_path / "home"
    cdir = home / ".claude"
    cdir.mkdir(parents=True)
    guard = tmp_path / "guard"
    guard.mkdir()
    marker = tmp_path / "NETWORK_ATTEMPTED"
    (guard / "sitecustomize.py").write_text(textwrap.dedent(f"""
        import socket
        _MARK = {str(marker)!r}
        def _deny(*a, **k):
            open(_MARK, "a").write("connect attempted\\n")
            raise OSError("claudown test guard: network disabled")
        socket.socket.connect = _deny
        socket.socket.connect_ex = _deny
        socket.create_connection = _deny
        socket.getaddrinfo = _deny
    """), encoding="utf-8")
    env = {k: v for k, v in os.environ.items()
           if k not in {"CLAUDE_CODE_REMOTE", "CLAUDE_PROJECT_DIR", "SHUTDOWN_COMMAND",
                        "WEBHOOK_URL", "WEBHOOK_TOKEN", "ACTION", "TOKEN_BUDGET_5H",
                        "COMPUTER_USE_SHUTDOWN", "CLAUDOWN_DISABLE"}}
    env.update({
        "HOME": str(home), "USERPROFILE": str(home), "CLAUDE_CONFIG_DIR": str(cdir),
        "PYTHONPATH": str(guard), "DRY_RUN": "true", "SHUTDOWN_THRESHOLD": "95",
        "PYTHONDONTWRITEBYTECODE": "1",
    })

    class Box:
        pass

    box = Box()
    box.home, box.cdir, box.env, box.marker, box.tmp = home, cdir, env, marker, tmp_path

    def run(script, payload=None, args=(), extra_env=None, script_dir=SCRIPTS):
        e = dict(env)
        e.update(extra_env or {})
        inp = payload if isinstance(payload, str) else json.dumps(payload or {})
        return subprocess.run([sys.executable, str(Path(script_dir) / script), *args], input=inp,
                              capture_output=True, text=True, encoding="utf-8", env=e, timeout=60)

    def log():
        p = cdir / "claudown.log"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def write_state(pct, resets_in=3600, age=0, **extra):
        now = time.time()
        data = {"five_hour_pct": pct, "five_hour_resets_at": now + resets_in,
                "updated_at": now - age, "sensor_seen_at": now - age}
        data.update(extra)
        (cdir / "claudown_state.json").write_text(json.dumps(data), encoding="utf-8")

    def state():
        return json.loads((cdir / "claudown_state.json").read_text(encoding="utf-8"))

    box.run, box.log, box.write_state, box.state = run, log, write_state, state
    yield box
    assert not marker.exists(), "a script attempted a network connection"


def statusline_payload(pct=42.0, resets_in=3600):
    return {
        "session_id": "test-session", "transcript_path": "/tmp/t.jsonl",
        "model": {"id": "claude-opus-5-5", "display_name": "Opus"},
        "workspace": {"current_dir": "/tmp"}, "version": "2.1.300",
        "rate_limits": {"five_hour": {"used_percentage": pct, "resets_at": int(time.time() + resets_in)},
                        "seven_day": {"used_percentage": 10.0, "resets_at": int(time.time() + 86400)}},
    }


# ------------------------------------------------------------ static checks
@pytest.mark.parametrize("name", ZERO_NETWORK_SCRIPTS)
def test_detection_scripts_import_no_network_or_sdk(name):
    tree = ast.parse(src(name))
    for node in ast.walk(tree):
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods = [node.module]
        for m in mods:
            assert m.split(".")[0] not in FORBIDDEN_MODULES, f"{name} imports {m}"


def test_no_script_uses_anthropic_sdk_or_api():
    for py in SCRIPTS.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert "import anthropic" not in text and "from anthropic" not in text, py.name
        assert "api.anthropic.com" not in text, py.name


def test_orchestrator_network_is_lazy_and_webhook_only():
    tree = ast.parse(src("shutdown_orchestrator.py"))
    for node in tree.body:  # module-level imports only
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for n in names:
                assert n.split(".")[0] not in FORBIDDEN_MODULES
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "send_notification")
    assert any(isinstance(n, ast.Import) and n.names[0].name == "urllib.request" for n in ast.walk(fn))


def test_computer_use_script_never_starts_claude_sessions():
    # It may run `claude --version`; it must never run a prompt (-p) or the SDK.
    text = src("cli_computer_use_shutdown.py")
    assert '"-p"' not in text and "'-p'" not in text and "--print" not in text


def test_shutdown_commands_match_spec_per_os(monkeypatch):
    monkeypatch.delenv("SHUTDOWN_COMMAND", raising=False)
    import shutdown_orchestrator as orch

    assert orch.shutdown_candidates("windows")[0] == ["shutdown", "/s", "/t", "0"]
    assert orch.shutdown_candidates("macos")[0] == ["sudo", "-n", "shutdown", "-h", "now"]
    assert orch.shutdown_candidates("linux")[0] == ["sudo", "-n", "systemctl", "poweroff"]


def test_shutdown_override_keeps_windows_paths_with_spaces(monkeypatch):
    import shutdown_orchestrator as orch

    cmd = r'"C:\Program Files\Python\python.exe" -c "pass"'
    monkeypatch.setenv("SHUTDOWN_COMMAND", cmd)
    assert orch.shutdown_candidates("windows") == [cmd]
    assert orch.shutdown_candidates("linux") == [[r"C:\Program Files\Python\python.exe", "-c", "pass"]]


def test_package_imports_work_when_installed_as_claudown(tmp_path):
    pkg = tmp_path / "claudown"
    shutil.copytree(SCRIPTS, pkg, ignore=shutil.ignore_patterns("__pycache__"))
    code = ("import claudown.pretooluse_gate as g, claudown.shutdown_orchestrator as o, "
            "claudown.web_limit_watcher, claudown.local_webhook_listener, "
            "claudown.cli_computer_use_shutdown, claudown.claudown_setup, claudown.statusline_sensor; "
            "assert g.c.__name__ == 'claudown.claudown_common', g.c.__name__; "
            "assert o.c is g.c; print('ok')")
    r = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=60)
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr


def test_pyproject_entry_points_exist():
    tomllib = pytest.importorskip("tomllib")
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    proj = data["project"]
    assert proj["name"] == "claudown" and proj["version"] == "0.1.0"
    targets = proj["scripts"]
    assert targets["claudown"] == "claudown.shutdown_orchestrator:main"
    assert targets["claudown-gate"] == "claudown.pretooluse_gate:main"
    for spec in targets.values():
        module, func = spec.split(":")
        tree = ast.parse(src(module.split(".")[1] + ".py"))
        assert any(isinstance(n, ast.FunctionDef) and n.name == func for n in tree.body), spec


# --------------------------------------------------------------- sensor
def test_sensor_writes_state_and_prints_status(sandbox):
    r = sandbox.run("statusline_sensor.py", statusline_payload(42.0))
    assert r.returncode == 0, r.stderr
    assert "42%" in r.stdout and "DRY RUN" in r.stdout
    st = sandbox.state()
    assert st["five_hour_pct"] == 42.0 and st["seven_day_pct"] == 10.0
    assert st["session_id"] == "test-session" and st["rate_limits_present"] is True


def test_sensor_keeps_last_reading_when_rate_limits_absent(sandbox):
    sandbox.run("statusline_sensor.py", statusline_payload(55.0))
    p = statusline_payload()
    del p["rate_limits"]
    r = sandbox.run("statusline_sensor.py", p)
    assert r.returncode == 0
    st = sandbox.state()
    assert st["five_hour_pct"] == 55.0 and st["rate_limits_present"] is False


def test_sensor_survives_garbage_input(sandbox):
    r = sandbox.run("statusline_sensor.py", "not json at all")
    assert r.returncode == 0 and "claudown" in r.stdout


@pytest.mark.skipif(shutil.which("bash") is None or os.name == "nt", reason="needs POSIX bash")
def test_sensor_shell_wrapper_forwards_stdin(sandbox):
    r = subprocess.run(["bash", str(SCRIPTS / "statusline_sensor.sh")],
                       input=json.dumps(statusline_payload(33.0)), capture_output=True,
                       text=True, env=sandbox.env, timeout=60)
    assert r.returncode == 0 and "33%" in r.stdout
    assert sandbox.state()["five_hour_pct"] == 33.0


# ----------------------------------------------------------------- gate
def test_gate_allows_below_threshold(sandbox):
    sandbox.write_state(50.0)
    r = sandbox.run("pretooluse_gate.py", {"hook_event_name": "PreToolUse", "tool_name": "Bash"})
    assert r.returncode == 0
    assert not (sandbox.cdir / "claudown_trigger.json").exists()


def test_gate_blocks_dry_runs_and_is_idempotent(sandbox):
    sandbox.write_state(96.5)
    hook = {"hook_event_name": "PreToolUse", "tool_name": "Bash"}
    r1 = sandbox.run("pretooluse_gate.py", hook)
    assert r1.returncode == 2, r1.stderr
    assert "Blocked" in r1.stderr and "DRY RUN" in r1.stderr
    log = sandbox.log()
    assert "DRY_RUN: would execute" in log
    assert (sandbox.cdir / "claudown_trigger.json").exists()

    r2 = sandbox.run("pretooluse_gate.py", hook)
    r3 = sandbox.run("pretooluse_gate.py", {"hook_event_name": "UserPromptSubmit", "prompt": "hi"})
    assert r2.returncode == 2 and r3.returncode == 2  # still blocking...
    log = sandbox.log()
    assert log.count("TRIGGER:") == 1                  # ...but fired only once
    assert "already triggered" in log


def test_gate_ignores_reading_from_expired_window(sandbox):
    sandbox.write_state(99.0, resets_in=-10)
    r = sandbox.run("pretooluse_gate.py", {"hook_event_name": "PreToolUse"})
    assert r.returncode == 0


def test_gate_fails_open_with_clear_warning_when_usage_unknown(sandbox):
    r = sandbox.run("pretooluse_gate.py", {"hook_event_name": "PreToolUse"})
    assert r.returncode == 0
    assert "WARNING usage unknown" in sandbox.log() and "NOT guessing" in sandbox.log()


def test_disable_flag_bypasses_gate(sandbox):
    sandbox.write_state(99.0)
    (sandbox.cdir / "claudown.disabled").touch()
    r = sandbox.run("pretooluse_gate.py", {"hook_event_name": "PreToolUse"})
    assert r.returncode == 0 and "TRIGGER" not in sandbox.log()


def test_custom_threshold(sandbox):
    sandbox.write_state(85.0)
    r = sandbox.run("pretooluse_gate.py", {"hook_event_name": "PreToolUse"},
                    extra_env={"SHUTDOWN_THRESHOLD": "80"})
    assert r.returncode == 2


def test_computer_use_hint_absent_by_default(sandbox):
    sandbox.write_state(99.0)
    r = sandbox.run("pretooluse_gate.py", {"hook_event_name": "PreToolUse"},
                    extra_env={"DRY_RUN": "false", "SHUTDOWN_COMMAND": "/nonexistent/x"})
    assert r.returncode == 2 and "computer-use" not in r.stderr


# ------------------------------------------------------------- backstop
def test_backstop_fires_on_rate_limit_only(sandbox):
    other = {"hook_event_name": "StopFailure", "error": "overloaded"}
    assert sandbox.run("shutdown_orchestrator.py", other).returncode == 0
    assert "TRIGGER" not in sandbox.log()

    hit = {"hook_event_name": "StopFailure", "error": "rate_limit",
           "error_details": "429 Too Many Requests", "last_assistant_message": "API Error: Rate limit reached"}
    r = sandbox.run("shutdown_orchestrator.py", hit)
    assert r.returncode == 0
    assert "backstop" in sandbox.log() and "DRY_RUN: would execute" in sandbox.log()


def test_backstop_skips_if_gate_already_fired(sandbox):
    sandbox.write_state(97.0)
    sandbox.run("pretooluse_gate.py", {"hook_event_name": "PreToolUse"})
    sandbox.run("shutdown_orchestrator.py", {"hook_event_name": "StopFailure", "error": "rate_limit"})
    assert sandbox.log().count("TRIGGER:") == 1


# --------------------------------------------------------- armed / failure
def test_armed_mode_executes_command_override(sandbox):
    done = sandbox.tmp / "shutdown_ran"
    cmd = f'"{sys.executable}" -c "open(r\'{done}\', \'w\').close()"'
    sandbox.write_state(99.0)
    r = sandbox.run("pretooluse_gate.py", {"hook_event_name": "PreToolUse"},
                    extra_env={"DRY_RUN": "false", "SHUTDOWN_COMMAND": cmd})
    assert r.returncode == 2
    assert done.exists(), sandbox.log()
    assert "shutdown issued" in sandbox.log()


def test_failed_shutdown_exits_gracefully(sandbox):
    sandbox.write_state(99.0)
    r = sandbox.run("pretooluse_gate.py", {"hook_event_name": "PreToolUse"},
                    extra_env={"DRY_RUN": "false", "SHUTDOWN_COMMAND": "/nonexistent/claudown-shutdown"})
    assert r.returncode == 2  # still blocks the tool call
    assert "all shutdown commands failed" in sandbox.log()


# ------------------------------------------------------------------ web
WEB_ENV = {"CLAUDE_CODE_REMOTE": "true", "WEBHOOK_URL": "https://hooks.example.invalid/claudown"}


def test_web_gate_notifies_instead_of_shutdown(sandbox):
    sandbox.write_state(98.0)
    r = sandbox.run("pretooluse_gate.py", {"hook_event_name": "PreToolUse"}, extra_env=WEB_ENV)
    assert r.returncode == 2
    log = sandbox.log()
    assert "DRY_RUN: would POST" in log
    assert "would execute" not in log  # no shutdown inside the cloud VM


def test_web_watcher_posts_once_and_never_shuts_down(sandbox):
    sandbox.write_state(97.0)
    env = dict(WEB_ENV, ACTION="shutdown")  # even if misconfigured, the watcher only notifies
    r = sandbox.run("web_limit_watcher.py", args=["--once"], extra_env=env)
    assert r.returncode == 0 and "webhook fired" in r.stdout
    r = sandbox.run("web_limit_watcher.py", args=["--once"], extra_env=env)
    assert "already fired" in r.stdout
    log = sandbox.log()
    assert log.count("DRY_RUN: would POST") == 1 and "would execute" not in log


def test_web_watcher_below_threshold_and_outside_cloud(sandbox):
    sandbox.write_state(40.0)
    r = sandbox.run("web_limit_watcher.py", args=["--once"], extra_env=WEB_ENV)
    assert "40.0% < 95%" in r.stdout
    sandbox.write_state(99.0)
    r = sandbox.run("web_limit_watcher.py", args=["--once"])  # not a cloud session
    assert r.returncode == 0 and r.stdout == "" and "TRIGGER" not in sandbox.log()


def test_webhook_payload_has_session_timestamp_and_usage(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("DRY_RUN", "true")
    import claudown_common as c
    import shutdown_orchestrator as orch

    c._config_cache = None
    sent = {}
    monkeypatch.setattr(orch, "send_notification", lambda p, d=None: sent.update(p) or True)
    assert orch.trigger("t", 96.04, "test", action="notify", session_id="sess-1")
    assert sent["session_id"] == "sess-1" and sent["usage_pct"] == 96.0
    assert sent["timestamp"].endswith("+00:00") and "token" not in sent


def test_listener_token_checks():
    import local_webhook_listener as lis

    assert lis.token_ok("a" * 20, "a" * 20)
    assert not lis.token_ok("", "a" * 20) and not lis.token_ok("b" * 20, "a" * 20)
    assert not lis.token_ok("x", "")
    assert lis._bearer("Bearer abc") == "abc"


def test_listener_refuses_short_token(sandbox):
    r = sandbox.run("local_webhook_listener.py", args=["--token", "short"])
    assert r.returncode == 1 and "at least 16" in r.stderr
    r = sandbox.run("local_webhook_listener.py", args=["--token", "short", "--arm"])
    assert r.returncode == 1  # --arm never bypasses the token check
    r = sandbox.run("local_webhook_listener.py", args=["--help"])
    assert "--arm" in r.stdout


# ------------------------------------------------------- computer use
def test_computer_use_not_offered_off_macos():
    import cli_computer_use_shutdown as cu

    for os_name in ("windows", "linux"):
        rep = cu.eligibility(os_name)
        assert rep["eligible"] is False and "macOS only" in rep["reason"]


@pytest.mark.skipif(sys.platform == "darwin", reason="checks the non-macOS fallback")
def test_computer_use_enable_falls_back_silently_off_macos(sandbox):
    r = sandbox.run("cli_computer_use_shutdown.py", args=["--enable"])
    assert r.returncode == 0 and "NO" in r.stdout
    assert not (sandbox.cdir / "claudown" / "config.json").exists()


# ---------------------------------------------------- transcript sensor
def _transcript(cdir, lines):
    d = cdir / "projects" / "-home-user-proj"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "session.jsonl", "w", encoding="utf-8") as fh:
        for rec in lines:
            fh.write(json.dumps(rec) + "\n")


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(ts))


def test_transcript_sensor_detects_limit_message(sandbox):
    now = time.time()
    _transcript(sandbox.cdir, [
        {"type": "assistant", "timestamp": _iso(now - 600),
         "message": {"id": "m1", "usage": {"input_tokens": 10, "output_tokens": 10}}},
        {"type": "assistant", "timestamp": _iso(now - 60), "isApiErrorMessage": True,
         "message": {"content": [{"type": "text", "text": "Claude usage limit reached. Resets 5pm"}]}},
    ])
    r = sandbox.run("pretooluse_gate.py", {"hook_event_name": "PreToolUse"})
    assert r.returncode == 2 and "transcript:limit-message" in r.stderr


def test_transcript_sensor_budget_estimate_and_dedupe(sandbox):
    now = time.time()
    usage = {"input_tokens": 1000, "output_tokens": 9000,
             "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    _transcript(sandbox.cdir, [
        # same message streamed twice -> counted once
        {"type": "assistant", "timestamp": _iso(now - 300), "message": {"id": "a", "usage": usage}},
        {"type": "assistant", "timestamp": _iso(now - 299), "message": {"id": "a", "usage": usage}},
        {"type": "assistant", "timestamp": _iso(now - 200), "message": {"id": "b", "usage": usage}},
    ])
    env = {"TOKEN_BUDGET_5H": "21000"}  # 20000 / 21000 = 95.2 %
    r = sandbox.run("pretooluse_gate.py", {"hook_event_name": "PreToolUse"}, extra_env=env)
    assert r.returncode == 2 and "transcript:token-budget" in r.stderr

    env = {"TOKEN_BUDGET_5H": "100000"}  # 20 %
    (sandbox.cdir / "claudown_trigger.json").unlink()
    r = sandbox.run("pretooluse_gate.py", {"hook_event_name": "PreToolUse"}, extra_env=env)
    assert r.returncode == 0


def test_transcript_sensor_warns_and_does_not_guess_without_budget(sandbox):
    now = time.time()
    _transcript(sandbox.cdir, [
        {"type": "assistant", "timestamp": _iso(now - 100),
         "message": {"id": "x", "usage": {"input_tokens": 0, "output_tokens": 50000}}},
    ])
    r = sandbox.run("vscode_transcript_sensor.py", args=["--write"])
    assert r.returncode == 0 and json.loads(r.stdout)["pct"] is None
    assert "WARNING" in r.stderr and "Not guessing" in sandbox.log()
    st = sandbox.state()
    assert st["transcript_pct"] is None and st["transcript_basis"] == "no-budget"
    assert "five_hour_pct" not in st  # never overwrites the statusLine reading


def test_stale_sensor_falls_back_to_transcripts(sandbox):
    sandbox.write_state(99.0, age=7200)  # sensor silent for 2 h (VS Code case)
    (sandbox.cdir / "projects").mkdir()   # transcripts exist, no activity -> idle
    r = sandbox.run("pretooluse_gate.py", {"hook_event_name": "PreToolUse"})
    assert r.returncode == 0


def test_calibration_suggests_budget(sandbox):
    now = time.time()
    _transcript(sandbox.cdir, [
        {"type": "assistant", "timestamp": _iso(now - 100),
         "message": {"id": "x", "usage": {"input_tokens": 0, "output_tokens": 50000}}},
    ])
    sandbox.write_state(25.0)
    r = sandbox.run("vscode_transcript_sensor.py", args=["--calibrate"])
    assert r.returncode == 0, r.stdout
    assert json.loads(r.stdout)["suggested_budget"] == 200000


# ------------------------------------------------------------- CLI + setup
def test_orchestrator_status_and_test_cli(sandbox):
    r = sandbox.run("shutdown_orchestrator.py", args=["--status"])
    st = json.loads(r.stdout)
    assert st["dry_run"] is True and st["threshold"] == 95.0
    r = sandbox.run("shutdown_orchestrator.py", args=["--test"])
    assert r.returncode == 0 and "DRY_RUN" in r.stderr


def _hook_cmds(data, event):
    return [h["command"] for g in data["hooks"].get(event, []) for h in g["hooks"]]


def test_setup_merges_and_uninstalls_cleanly(sandbox):
    settings = sandbox.cdir / "settings.json"
    chain = f'"{sys.executable}" -c "print(\'mine\')"' if os.name == "nt" else "echo mine"
    settings.write_text(json.dumps({
        "statusLine": {"type": "command", "command": chain},
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo keep"}]}]},
        "model": "opus"}), encoding="utf-8")
    r = sandbox.run("claudown_setup.py", args=["--threshold", "90"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert "claudown/statusline_sensor.py" in data["statusLine"]["command"]
    assert "\\" not in data["statusLine"]["command"]  # Git Bash eats backslashes
    assert data["env"]["SHUTDOWN_THRESHOLD"] == "90" and data["env"]["DRY_RUN"] == "true"
    assert data["model"] == "opus"
    cmds = _hook_cmds(data, "PreToolUse")
    assert "echo keep" in cmds and any("pretooluse_gate.py" in x for x in cmds)
    assert "StopFailure" in data["hooks"] and "SessionStart" not in data["hooks"]
    conf = json.loads((sandbox.cdir / "claudown" / "config.json").read_text(encoding="utf-8"))
    assert conf["STATUSLINE_CHAIN_COMMAND"] == chain

    # the installed sensor runs and shows the chained status line too
    r = sandbox.run("statusline_sensor.py", statusline_payload(10), script_dir=sandbox.cdir / "claudown")
    assert "mine" in r.stdout and "claudown" in r.stdout, r.stderr

    # idempotent re-run: no duplicate hooks
    sandbox.run("claudown_setup.py")
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert sum("pretooluse_gate.py" in x for x in _hook_cmds(data, "PreToolUse")) == 1

    r = sandbox.run("claudown_setup.py", args=["--uninstall"])
    assert r.returncode == 0, r.stderr
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == chain
    assert "StopFailure" not in data.get("hooks", {})
    assert _hook_cmds(data, "PreToolUse") == ["echo keep"]
    assert not (sandbox.cdir / "claudown").exists()


def test_setup_project_mode_for_web(sandbox):
    repo = sandbox.tmp / "repo"
    repo.mkdir()
    r = sandbox.run("claudown_setup.py", args=["--project", str(repo)])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert data["env"]["ACTION"] == "notify"
    assert any("web_limit_watcher.py" in x for x in _hook_cmds(data, "SessionStart"))
    assert all("$CLAUDE_PROJECT_DIR" in x for x in _hook_cmds(data, "PreToolUse"))
    assert (repo / ".claude" / "claudown" / "web_limit_watcher.py").exists()
    assert not (repo / ".claude" / "claudown" / "config.json").exists()  # no secrets in the repo
