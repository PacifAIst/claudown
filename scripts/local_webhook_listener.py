#!/usr/bin/env python3
"""claudown LOCAL WEBHOOK LISTENER - run this on your laptop for Claude on the web.

A cloud VM cannot power off your machine, so on the web claudown's
web_limit_watcher.py POSTs a webhook instead. This listener receives it and
runs the normal local shutdown sequence, honouring DRY_RUN on THIS machine.

    python scripts/local_webhook_listener.py --token "<16+ random characters>"          # practice
    python scripts/local_webhook_listener.py --token "<16+ random characters>" --arm    # for real

The cloud cannot reach 127.0.0.1 on your laptop directly: expose the port
through a tunnel you control (for example Tailscale Funnel or Cloudflare
Tunnel) and use the tunnel's https URL as WEBHOOK_URL in the cloud session.

Requests must carry the shared secret (header X-Claudown-Token or a Bearer
token). Binds to 127.0.0.1 by default. Standard library only.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import List, Optional

try:
    from . import claudown_common as c
    from . import shutdown_orchestrator as orch
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import claudown_common as c  # noqa: E402
    import shutdown_orchestrator as orch  # noqa: E402

MAX_BODY = 16 * 1024
MIN_TOKEN = 16


def _bearer(value: Optional[str]) -> str:
    value = (value or "").strip()
    return value[7:].strip() if value.lower().startswith("bearer ") else ""


def token_ok(supplied: str, expected: str) -> bool:
    return bool(expected) and bool(supplied) and hmac.compare_digest(supplied.encode(), expected.encode())


def make_handler(expected_token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "claudown-listener"

        def _reply(self, code: int, text: str) -> None:
            body = text.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # health check, reveals nothing
            self._reply(200, "claudown listener up\n")

        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length > MAX_BODY:
                self._reply(413, "too large\n")
                return
            raw = self.rfile.read(length) if length > 0 else b""
            supplied = self.headers.get("X-Claudown-Token") or _bearer(self.headers.get("Authorization"))
            if not token_ok(supplied or "", expected_token):
                c.log("listener: rejected request with bad/missing token")
                self._reply(403, "forbidden\n")
                return
            try:
                data = json.loads(raw.decode("utf-8", "replace") or "{}")
                if not isinstance(data, dict):
                    data = {}
            except ValueError:
                data = {}
            pct = c.to_float(data.get("usage_pct"))
            reason = (f"web webhook (session {data.get('session_id', '?')}, "
                      f"{data.get('timestamp', '?')}): {data.get('reason', '')}")[:300]
            # Always a LOCAL shutdown here, whatever ACTION says on this machine.
            fired = orch.trigger(reason, pct, "web-webhook", c.to_float(data.get("resets_at")),
                                 action="shutdown", session_id=data.get("session_id"))
            self._reply(200, "fired\n" if fired else "already fired this window\n")

        def log_message(self, fmt: str, *args) -> None:  # route access log to claudown.log
            c.log("listener: " + (fmt % args))

    return Handler


def _main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8383)
    ap.add_argument("--token", default=c.cfg("WEBHOOK_TOKEN"),
                    help="shared secret (default: WEBHOOK_TOKEN from env or config.json)")
    ap.add_argument("--arm", action="store_true",
                    help="really shut down when a webhook arrives (sets DRY_RUN=false for this listener)")
    args = ap.parse_args(argv)
    if args.arm:
        os.environ["DRY_RUN"] = "false"
    token = (args.token or "").strip()
    if len(token) < MIN_TOKEN:
        print(f"Refusing to start: pass --token with at least {MIN_TOKEN} characters "
              "(the same value you set as WEBHOOK_TOKEN in the cloud session).", file=sys.stderr)
        return 1
    mode = "DRY RUN (will only log)" if c.is_dry_run() else "ARMED (will really shut down)"
    print(f"claudown listener on http://{args.host}:{args.port} - {mode}. Press Ctrl+C to stop.")
    try:
        HTTPServer((args.host, args.port), make_handler(token)).serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    c.utf8_stdio()
    return _main(argv)


if __name__ == "__main__":
    sys.exit(main())
