#!/usr/bin/env python3
"""claudown VS CODE SENSOR - read 5-hour usage from local transcript files.

The native VS Code extension runs hooks but never runs `statusLine`, so the
CLI sensor is silent there. This sensor reads the .jsonl transcripts Claude
Code already writes under ~/.claude/projects/ and:

1. Rebuilds the current 5-hour block (starts at the hour of the first message
   after a gap of 5 h or more, like Claude's own window).
2. Flags the block as 100 % if a "usage limit reached" API error appears in it.
3. Otherwise, if TOKEN_BUDGET_5H is set, estimates percent = weighted tokens /
   budget. Run `vscode_transcript_sensor.py --calibrate --write` once from the
   CLI (where the real statusLine sensor works) to derive a budget for your plan.
4. If none of that is possible it logs a clear WARNING and reports "unknown".
   It never guesses.

The gate calls `estimate()` on demand. `--watch` additionally polls on a timer
and writes the result to the same claudown_state.json (transcript_* keys), which
the optional VS Code bridge extension reads to show a status bar item.

Purely local file reads: no SDK, no HTTP, no tokens.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from . import claudown_common as c
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import claudown_common as c  # noqa: E402

LIMIT_RE = re.compile(
    r"(usage limit reached|limit reached|rate[ _-]?limit|5-hour limit|too many requests)",
    re.IGNORECASE,
)
LOOKBACK_SECONDS = 2 * c.WINDOW_SECONDS  # enough history to locate the block start


def _parse_ts(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value) / (1000.0 if value > 1e12 else 1.0)
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _text_of(message: Dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    parts: List[str] = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
    return " ".join(parts)


def iter_events(projects_dir: Path, since: float) -> Iterable[Dict[str, Any]]:
    """Yield usage and limit events from transcripts modified after `since`."""
    if not projects_dir.is_dir():
        return
    for path in projects_dir.rglob("*.jsonl"):
        try:
            if path.stat().st_mtime < since:
                continue
            fh = open(path, "r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"assistant"' not in line and "isApiErrorMessage" not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict) or rec.get("type") != "assistant":
                    continue
                ts = _parse_ts(rec.get("timestamp"))
                if ts is None or ts < since:
                    continue
                msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
                if rec.get("isApiErrorMessage") or rec.get("error"):
                    text = _text_of(msg) + " " + str(rec.get("error") or "")
                    if LIMIT_RE.search(text):
                        yield {"kind": "limit", "ts": ts, "text": text.strip()}
                    continue
                usage = msg.get("usage")
                if isinstance(usage, dict):
                    key = msg.get("id") or rec.get("requestId") or rec.get("uuid")
                    yield {"kind": "usage", "ts": ts, "usage": usage, "key": key}


def weighted_tokens(usage: Dict[str, Any], cache_read_weight: float) -> float:
    def n(k: str) -> float:
        return c.to_float(usage.get(k)) or 0.0

    return (
        n("input_tokens")
        + n("output_tokens")
        + n("cache_creation_input_tokens")
        + cache_read_weight * n("cache_read_input_tokens")
    )


def current_block(timestamps: List[float], now: float) -> Optional[Tuple[float, float]]:
    """Return (start, end) of the 5-hour block containing `now`, if any."""
    block: Optional[Tuple[float, float]] = None
    for ts in sorted(timestamps):
        if block is None or ts >= block[1]:
            start = ts - (ts % 3600)  # floor to the hour, as Claude's window does
            block = (start, start + c.WINDOW_SECONDS)
    if block and block[0] <= now < block[1]:
        return block
    return None


def scan(now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else now
    projects = c.claude_dir() / "projects"
    crw = c.cfg_float("CACHE_READ_WEIGHT")
    crw = 0.1 if crw is None else crw

    usage_by_key: Dict[Any, Tuple[float, float]] = {}
    anon: List[Tuple[float, float]] = []
    limits: List[float] = []
    for ev in iter_events(projects, now - LOOKBACK_SECONDS):
        if ev["kind"] == "limit":
            limits.append(ev["ts"])
            continue
        tok = weighted_tokens(ev["usage"], crw)
        if ev["key"]:
            # Streaming writes several lines per message; keep the largest reading.
            prev = usage_by_key.get(ev["key"])
            if prev is None or tok > prev[1]:
                usage_by_key[ev["key"]] = (ev["ts"], tok)
        else:
            anon.append((ev["ts"], tok))

    events = list(usage_by_key.values()) + anon
    block = current_block([t for t, _ in events] + limits, now)
    if block is None:
        return {"block": None, "tokens": 0.0, "limit_hit": False, "messages": 0}
    start, end = block
    in_block = [(t, k) for t, k in events if start <= t < end]
    return {
        "block": block,
        "tokens": sum(k for _, k in in_block),
        "messages": len(in_block),
        "limit_hit": any(start <= t < end for t in limits),
    }


def estimate(now: Optional[float] = None) -> Dict[str, Any]:
    """Return {'pct', 'resets_at', 'basis', 'tokens'}; pct is None when unknown."""
    now = time.time() if now is None else now
    s = scan(now)
    if s["block"] is None:
        # No activity in the last 5 h: the window is fresh. Only meaningful if
        # transcripts exist at all; otherwise we genuinely do not know.
        if (c.claude_dir() / "projects").is_dir():
            return {"pct": 0.0, "resets_at": None, "basis": "idle", "tokens": 0.0}
        return {"pct": None, "basis": "no-transcripts"}
    resets_at = s["block"][1]
    if s["limit_hit"]:
        return {"pct": 100.0, "resets_at": resets_at, "basis": "limit-message", "tokens": s["tokens"]}
    budget = c.cfg_float("TOKEN_BUDGET_5H")
    if budget and budget > 0:
        pct = min(100.0, 100.0 * s["tokens"] / budget)
        return {"pct": pct, "resets_at": resets_at, "basis": "token-budget", "tokens": s["tokens"]}
    return {"pct": None, "resets_at": resets_at, "basis": "no-budget", "tokens": s["tokens"]}


WARNINGS = {
    "no-budget": "transcripts found but TOKEN_BUDGET_5H is not set, so there is nothing to "
                 "compare them against. Run this script with --calibrate --write once (see "
                 "GETTING_STARTED.md). Not guessing.",
    "no-transcripts": f"no transcripts found under {c.claude_dir() / 'projects'}. Has Claude "
                      "Code been used on this computer yet? Not guessing.",
}


def write_reading(est: Dict[str, Any], now: float) -> None:
    """Store the transcript reading next to (not over) the statusLine reading."""
    c.update_state(
        transcript_pct=est.get("pct"),
        transcript_basis=est.get("basis"),
        transcript_resets_at=est.get("resets_at"),
        transcript_updated_at=now,
    )
    warning = WARNINGS.get(str(est.get("basis")))
    if warning:
        st = c.load_state()
        last = c.to_float(st.get("transcript_last_warning")) or 0.0
        if now - last >= 3600:
            c.log("WARNING vscode transcript sensor: " + warning)
            c.update_state(transcript_last_warning=now)


def calibrate(now: Optional[float] = None) -> Dict[str, Any]:
    """Derive TOKEN_BUDGET_5H from a fresh statusLine reading plus transcripts."""
    now = time.time() if now is None else now
    pct, _, status = c.sensor_reading(now)
    s = scan(now)
    result: Dict[str, Any] = {"sensor_pct": pct, "sensor_status": status, "tokens": s["tokens"]}
    if status != "fresh" or not pct or pct < 5:
        result["error"] = (
            "Need a fresh statusLine reading of at least 5 %. Use Claude Code in a "
            "terminal for a while (with the claudown status line), then run this again."
        )
        return result
    result["suggested_budget"] = int(s["tokens"] * 100.0 / pct)
    return result


def _main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--calibrate", action="store_true", help="suggest TOKEN_BUDGET_5H")
    ap.add_argument("--write", action="store_true",
                    help="with --calibrate: save it to config.json; otherwise save the reading to the state file")
    ap.add_argument("--watch", type=float, metavar="SECONDS", nargs="?", const=60.0,
                    help="poll every SECONDS (default 60) and write each reading to the state file")
    args = ap.parse_args(argv)

    if args.calibrate:
        res = calibrate()
        print(json.dumps(res, indent=2))
        if args.write and "suggested_budget" in res:
            path = c.config_file_path()
            conf = c.read_json(path) or {}
            conf["TOKEN_BUDGET_5H"] = str(res["suggested_budget"])
            c.write_json_atomic(path, conf)
            print(f"Saved TOKEN_BUDGET_5H={res['suggested_budget']} to {path}")
        return 0 if "suggested_budget" in res else 1

    if args.watch:
        interval = max(5.0, args.watch)
        print(f"claudown transcript sensor: polling every {interval:.0f}s. Ctrl+C to stop.")
        try:
            while True:
                now = time.time()
                est = estimate(now)
                write_reading(est, now)
                pct = est.get("pct")
                shown = "unknown" if pct is None else f"{pct:.0f}%"
                print(f"{time.strftime('%H:%M:%S')} 5h usage {shown} ({est.get('basis')})", flush=True)
                time.sleep(interval)
        except KeyboardInterrupt:
            return 0

    now = time.time()
    est = estimate(now)
    if args.write:
        write_reading(est, now)
    print(json.dumps(est, indent=2))
    warning = WARNINGS.get(str(est.get("basis")))
    if warning:
        print("WARNING: " + warning, file=sys.stderr)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    c.utf8_stdio()
    return _main(argv)


if __name__ == "__main__":
    sys.exit(main())
