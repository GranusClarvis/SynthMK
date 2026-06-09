#!/usr/bin/env python3
"""SynthMK screenshot server — authenticated, listing-free, traversal-safe.

Replaces `python -m http.server` (which served the whole directory with an
index to anyone who could reach the port — security finding #2 in STATUS.md).

Design: failure screenshots can contain sensitive page content, but the link
in a Checkmk service must stay a plain clickable URL (no headers, no login).
So each PNG link carries a per-file token:

    http://node:9180/login-fail-step3.png?t=<hmac_sha256(key, filename)[:32]>

* the runner signs links with the same node-local key (SYNTHMK_SHOT_KEY_FILE,
  auto-generated 0600 at first start) when it renders a screenshot link
* a request without the exact token for that exact filename gets 403
* no directory listing, no path traversal (basename-only lookups), PNG only
* GET /healthz (no token) returns 200 "ok" — container/network healthcheck

Lab/dev escape hatch: SYNTHMK_SHOT_AUTH=off serves without tokens (still no
listing/traversal). The lab keeps auth ON to prove the flow end-to-end.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SHOT_DIR = Path(os.environ.get("SYNTHMK_SHOT_DIR", "/opt/synthmk/screenshots"))
PORT = int(os.environ.get("SYNTHMK_SHOT_PORT", "9180"))
AUTH = os.environ.get("SYNTHMK_SHOT_AUTH", "on").lower() != "off"
KEY_FILE = Path(os.environ.get("SYNTHMK_SHOT_KEY_FILE",
                               str(SHOT_DIR / ".synthmk_shot_key")))
TOKEN_LEN = 32  # hex chars of the HMAC kept in URLs (128 bits)


def load_or_create_key(path: Path = KEY_FILE) -> bytes:
    """Node-local signing key, created 0600 on first start."""
    if path.is_file():
        return path.read_bytes().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    return key


def sign(name: str, key: bytes) -> str:
    """Per-file URL token: HMAC(key, basename), truncated for URL hygiene."""
    return hmac.new(key, name.encode(), hashlib.sha256).hexdigest()[:TOKEN_LEN]


class ShotHandler(BaseHTTPRequestHandler):
    server_version = "SynthMKShots"
    key: bytes = b""

    def _deny(self, code: int, msg: str) -> None:
        body = msg.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        url = urlparse(self.path)
        if url.path == "/healthz":
            return self._deny(200, "ok")
        # basename-only: any path shape ("/../x", "//x", nested) collapses to
        # one filename looked up flat in SHOT_DIR — no traversal surface.
        name = os.path.basename(url.path)
        if not name or not name.endswith(".png"):
            return self._deny(404, "not found")
        target = SHOT_DIR / name
        if not target.is_file():
            return self._deny(404, "not found")
        if AUTH:
            token = (parse_qs(url.query).get("t") or [""])[0]
            if not hmac.compare_digest(token, sign(name, self.key)):
                return self._deny(403, "invalid or missing token")
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("shot-server: %s\n" % (fmt % args))


def main() -> int:
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    ShotHandler.key = load_or_create_key() if AUTH else b""
    mode = "token-auth" if AUTH else "OPEN (SYNTHMK_SHOT_AUTH=off)"
    print(f"shot-server: serving {SHOT_DIR} on :{PORT} [{mode}]", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), ShotHandler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
