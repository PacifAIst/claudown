"""Shared helpers for claudown (config, paths, state, trigger lock, logging).

Zero-token by design: this module never imports an HTTP client, the Anthropic
SDK, or anything that opens a socket. Everything it knows comes from stdin,
environment variables and small JSON files under the Claude config directory.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

VERSION = "0.2.0"
NAME = "claudown"
WINDOW_SECONDS = 5 * 60 * 60  # Claude's rolling 5-hour usage window

DEFAULTS: Dict[str, str] = {
    "SHUTDOWN_THRESHOLD": "95",       # percent of the 5-hour window
    "WEEKLY_THRESHOLD": "95",         # percent of the 7-day window ("off" disables)
    "WRAP_UP": "true",                # let Claude save its work before the action
    "WRAP_UP_TOOL_CALLS": "5",        # tool calls Claude may still use to wrap up
    "WRAP_UP_MAX_SECONDS": "600",     # act at the latest this long after wrap-up starts
    "SLEEP_HOURS": "12",              # `--sleep` expires after this many hours
    "DRY_RUN": "true",                # armed ONLY when explicitly "false"
    "ACTION": "auto",                 # auto | shutdown | notify | both | none
    "BLOCK_TOOLS": "true",            # gate blocks tool calls/prompts at threshold
    "BACKSTOP_ENABLED": "true",       # StopFailure(rate_limit) triggers the action
    "SHUTDOWN_DELAY_SECONDS": "0",
    "SHUTDOWN_COMMAND": "",           # optional full override, e.g. "systemctl suspend"
    "WEBHOOK_URL": "",                # web surface: where the cloud watcher POSTs
    "WEBHOOK_TOKEN": "",              # shared secret checked by local_webhook_listener
    "WEBHOOK_FORMAT": "json",         # json | text (text suits ntfy-style endpoints)
    "WEB_POLL_SECONDS": "30",         # web_limit_watcher polling interval
    "SENSOR_STALE_SECONDS": "900",    # older sensor data -> use transcript sensor
    "TOKEN_BUDGET_5H": "",            # transcript sensor: weighted tokens = 100 %
    "CACHE_READ_WEIGHT": "0.1",       # transcript sensor: weight of cache-read tokens
    "STATUSLINE_CHAIN_COMMAND": "",   # optional: keep your previous status line
    "COMPUTER_USE_SHUTDOWN": "false", # optional macOS CLI path, see cli_computer_use_shutdown.py
}

TRUTHY = {"1", "true", "yes", "on", "y"}
FALSY = {"0", "false", "no", "off", "n"}


# --------------------------------------------------------------------------- paths
def claude_dir() -> Path:
    """Claude Code's config directory (honours CLAUDE_CONFIG_DIR)."""
    custom = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(custom).expanduser() if custom else Path.home() / ".claude"


def state_path() -> Path:
    return claude_dir() / "claudown_state.json"


def lock_path() -> Path:
    return claude_dir() / "claudown_trigger.json"


def log_path() -> Path:
    return claude_dir() / "claudown.log"


def disabled_flag_path() -> Path:
    return claude_dir() / "claudown.disabled"


def wrapup_path() -> Path:
    return claude_dir() / "claudown_wrapup.json"


def sleep_flag_path() -> Path:
    return claude_dir() / "claudown.sleep"


def install_dir() -> Path:
    return claude_dir() / "claudown"


def config_file_path() -> Path:
    return install_dir() / "config.json"


# -------------------------------------------------------------------------- config
_config_cache: Optional[Dict[str, Any]] = None


def _file_config() -> Dict[str, Any]:
    global _config_cache
    if _config_cache is None:
        _config_cache = {}
        candidates = [config_file_path()]
        project = os.environ.get("CLAUDE_PROJECT_DIR")
        if project:
            candidates.insert(0, Path(project) / ".claude" / "claudown" / "config.json")
        for path in candidates:
            data = read_json(path)
            if isinstance(data, dict):
                _config_cache = data
                break
    return _config_cache


def cfg(key: str) -> str:
    """Precedence: environment variable > config.json > built-in default."""
    if key in os.environ and os.environ[key] != "":
        return os.environ[key]
    val = _file_config().get(key)
    if val is not None and str(val) != "":
        return str(val).lower() if isinstance(val, bool) else str(val)
    return DEFAULTS.get(key, "")


def cfg_float(key: str) -> Optional[float]:
    try:
        return float(cfg(key))
    except (TypeError, ValueError):
        return None


def cfg_bool(key: str) -> bool:
    return cfg(key).strip().lower() in TRUTHY


def is_dry_run() -> bool:
    """Safe default: anything other than an explicit false value is a dry run."""
    return cfg("DRY_RUN").strip().lower() not in FALSY


def threshold() -> float:
    val = cfg_float("SHUTDOWN_THRESHOLD")
    if val is None or not (0 < val <= 100):
        return 95.0
    return val


def weekly_threshold() -> Optional[float]:
    """Weekly (7-day) threshold, or None when switched off ("off", "0", "false")."""
    raw = cfg("WEEKLY_THRESHOLD").strip().lower()
    if raw in FALSY or raw in ("", "none", "disabled"):
        return None
    val = cfg_float("WEEKLY_THRESHOLD")
    if val is None or not (0 < val <= 100):
        return 95.0
    return val


def is_remote() -> bool:
    """True inside Claude Code on the web (cloud VM)."""
    return os.environ.get("CLAUDE_CODE_REMOTE", "").lower() == "true"


def is_disabled() -> bool:
    return disabled_flag_path().exists() or os.environ.get("CLAUDOWN_DISABLE", "") in TRUTHY


# ---------------------------------------------------------------------------- I/O
def utf8_stdio() -> None:
    """Windows consoles and pipes default to a legacy code page; force UTF-8 so
    status text with symbols never crashes a hook."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def read_json(path: Path) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".claudown_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_stdin_json() -> Dict[str, Any]:
    try:
        raw = sys.stdin.read()
    except Exception:
        return {}
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [claudown] {message}\n"
    try:
        p = log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass


# --------------------------------------------------------------------------- state
def load_state() -> Dict[str, Any]:
    data = read_json(state_path())
    return data if isinstance(data, dict) else {}


def update_state(**fields: Any) -> None:
    """Merge a few keys into the state file (best effort)."""
    st = load_state()
    st.update(fields)
    try:
        write_json_atomic(state_path(), st)
    except OSError as exc:
        log(f"could not update state: {exc!r}")


def to_float(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def sensor_reading(now: Optional[float] = None) -> Tuple[Optional[float], Optional[float], str]:
    """Return (percent, resets_at, status) from the statusLine sensor's state file.

    status is one of: fresh, expired-window, stale, no-data.
    """
    now = time.time() if now is None else now
    st = load_state()
    pct = to_float(st.get("five_hour_pct"))
    resets_at = to_float(st.get("five_hour_resets_at"))
    updated = to_float(st.get("updated_at"))
    if pct is None or updated is None:
        return None, None, "no-data"
    if resets_at is not None and now >= resets_at:
        # The window the reading belonged to is over; usage has rolled back.
        return 0.0, None, "expired-window"
    stale_after = cfg_float("SENSOR_STALE_SECONDS") or 900.0
    if now - updated > stale_after:
        return pct, resets_at, "stale"
    return pct, resets_at, "fresh"


def _transcript_module():
    try:
        from . import vscode_transcript_sensor as mod  # installed as the claudown package
    except ImportError:
        import vscode_transcript_sensor as mod  # run from the scripts folder
    return mod


def effective_usage(now: Optional[float] = None) -> Dict[str, Any]:
    """Best local estimate of 5-hour usage. statusLine sensor first, transcripts second.

    Returns a dict: pct (float|None), resets_at (float|None), source (str).
    """
    now = time.time() if now is None else now
    pct, resets_at, status = sensor_reading(now)
    if status in ("fresh", "expired-window"):
        return {"pct": pct, "resets_at": resets_at, "source": f"statusline:{status}"}

    # statusLine silent or stale (the native VS Code panel never runs it): read transcripts.
    try:
        est = _transcript_module().estimate(now=now)
    except Exception as exc:  # never let the fallback crash a hook
        log(f"transcript sensor failed: {exc!r}")
        est = {"pct": None}
    if est.get("pct") is not None:
        return {
            "pct": est["pct"],
            "resets_at": est.get("resets_at"),
            "source": f"transcript:{est.get('basis', 'estimate')}",
        }
    if status == "stale" and pct is not None:
        # Stale but within its window: better than nothing, flagged as such.
        return {"pct": pct, "resets_at": resets_at, "source": "statusline:stale"}
    return {"pct": None, "resets_at": None, "source": f"unknown:{est.get('basis', 'no-data')}"}


def weekly_reading(now: Optional[float] = None) -> Dict[str, Any]:
    """7-day usage from the statusLine sensor (the only zero-token source for it).

    A stale weekly reading is still used: usage only grows inside a window, so an
    old value is a lower bound and acting on it can never be premature.
    """
    now = time.time() if now is None else now
    st = load_state()
    pct = to_float(st.get("seven_day_pct"))
    resets_at = to_float(st.get("seven_day_resets_at"))
    if pct is None:
        return {"pct": None, "resets_at": None, "source": "unknown:no-weekly-data"}
    if resets_at is not None and now >= resets_at:
        return {"pct": 0.0, "resets_at": None, "source": "statusline:expired-window"}
    return {"pct": pct, "resets_at": resets_at, "source": "statusline"}


def evaluate_limits(now: Optional[float] = None) -> Dict[str, Any]:
    """Check the 5-hour and weekly limits together.

    Returns five_hour / weekly readings plus, when a limit is reached:
    hit=True, kind ("5-hour" | "weekly"), pct, limit, resets_at, source and
    exhausted (True when the limit is already fully used, so there is no
    headroom left for a wrap-up).
    """
    now = time.time() if now is None else now
    five = effective_usage(now)
    week = weekly_reading(now)
    thr, wthr = threshold(), weekly_threshold()
    hits = []
    if five.get("pct") is not None and five["pct"] >= thr:
        hits.append(("5-hour", five, thr))
    if wthr is not None and week.get("pct") is not None and week["pct"] >= wthr:
        hits.append(("weekly", week, wthr))
    result: Dict[str, Any] = {"five_hour": five, "weekly": week, "threshold": thr,
                              "weekly_threshold": wthr, "hit": bool(hits)}
    if hits:
        # Report the limit that resets last: claudown must keep blocking until then.
        kind, reading, limit = max(hits, key=lambda h: h[1].get("resets_at") or 0.0)
        result.update(
            kind=kind, pct=reading["pct"], limit=limit, resets_at=reading.get("resets_at"),
            source=reading.get("source", "?"),
            exhausted=any(h[1]["pct"] >= 100 or "limit-message" in str(h[1].get("source"))
                          for h in hits),
        )
    return result


def sleep_active(now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """The sleep-mode flag if set and not expired, else None."""
    now = time.time() if now is None else now
    data = read_json(sleep_flag_path())
    if not isinstance(data, dict):
        return {"expires_at": None} if sleep_flag_path().exists() else None
    expires = to_float(data.get("expires_at"))
    if expires is not None and now >= expires:
        clear_file(sleep_flag_path())
        return None
    return data


def clear_file(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------- trigger lock
def active_lock(now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Return the trigger lock if it still covers the current window, else None."""
    now = time.time() if now is None else now
    data = read_json(lock_path())
    if not isinstance(data, dict):
        return None
    resets_at = to_float(data.get("window_resets_at"))
    triggered_at = to_float(data.get("triggered_at")) or 0.0
    if resets_at is not None:
        return data if now < resets_at else None
    return data if now - triggered_at < WINDOW_SECONDS else None


def acquire_lock(info: Dict[str, Any], now: Optional[float] = None) -> bool:
    """Atomically create the trigger lock. False if a live lock already exists."""
    now = time.time() if now is None else now
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and active_lock(now) is None:
        try:
            path.unlink()  # expired lock from a previous window
        except OSError:
            pass
    payload = dict(info)
    payload.setdefault("triggered_at", now)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    return True


def release_lock() -> bool:
    try:
        lock_path().unlink()
        return True
    except OSError:
        return False


def script_dir() -> Path:
    return Path(__file__).resolve().parent
