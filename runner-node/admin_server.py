#!/usr/bin/env python3
"""SynthMK node management dashboard.

A small, token-protected web UI + JSON API served by the runner node
(default :9181) to manage the node's synthetic checks without SSH:

  * overview table: every configured check with live state, duration,
    last-run age, schedule, target host — parsed from the same spool files
    the Checkmk agent serves (native JSON sections), so it shows EXACTLY
    what Checkmk will see next poll
  * run-now per check (drops a trigger the scheduler picks up within a tick)
  * view any flow's YAML; create/edit flows + schedule entries when the
    flows volume is mounted writable (read-only mounts degrade gracefully
    to a view-only dashboard); every save is linted first — invalid flows
    are rejected with the linter's messages, never written half-broken
  * tokenized links to failure screenshots

Security model: every request (UI and API) requires the admin token
(`$SYNTHMK_ADMIN_TOKEN`, or auto-generated 0600 at
$SYNTHMK_ADMIN_TOKEN_FILE on first start — printed once to the log).
The login form stores it in a SameSite=Strict cookie; API calls may send
`Authorization: Bearer <token>` instead. State-changing requests must also
carry the token in the X-SynthMK-Token header (CSRF guard). Comparisons are
constant-time. Bind/port via SYNTHMK_ADMIN_BIND / SYNTHMK_ADMIN_PORT.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets as pysecrets
import select
import socket
import subprocess
import sys
import threading
import time
from http import cookies as http_cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOME = Path(os.environ.get("SYNTHMK_HOME", "/opt/synthmk"))
FLOWS_DIR = Path(os.environ.get("SYNTHMK_FLOWS", HOME / "flows"))
CONF = Path(os.environ.get("SYNTHMK_FLOWS_CONF", HOME / "runner-node" / "flows.conf"))
SPOOL = Path(os.environ.get("SYNTHMK_SPOOL", "/var/lib/check_mk_agent/spool"))
RUN_NOW_DIR = Path(os.environ.get("SYNTHMK_RUN_NOW_DIR", "/tmp/synthmk-run-now"))
PORT = int(os.environ.get("SYNTHMK_ADMIN_PORT", "9181"))
BIND = os.environ.get("SYNTHMK_ADMIN_BIND", "0.0.0.0")
TOKEN_FILE = Path(os.environ.get("SYNTHMK_ADMIN_TOKEN_FILE", "/run/synthmk-admin-token"))
VERSION = (HOME / "VERSION").read_text().strip() if (HOME / "VERSION").is_file() else "dev"

FLOW_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.ya?ml$")

# Optional HTTPS for the dashboard itself: point both at PEM files and the
# server binds TLS. (The agent transport has its own TLS via cmk-agent-ctl;
# this covers the operator's browser session on :9181.)
TLS_CERT = os.environ.get("SYNTHMK_ADMIN_TLS_CERT", "").strip()
TLS_KEY = os.environ.get("SYNTHMK_ADMIN_TLS_KEY", "").strip()

# Failed-login throttle: after LOCKOUT_AFTER consecutive failures from one
# address, /api/login from it is refused for LOCKOUT_SECS. The token is
# high-entropy, so this is about audit noise and brute-force hygiene, not a
# load-bearing defense; any successful login clears the counter.
LOCKOUT_AFTER = int(os.environ.get("SYNTHMK_LOGIN_LOCKOUT_AFTER", "5"))
LOCKOUT_SECS = int(os.environ.get("SYNTHMK_LOGIN_LOCKOUT_SECS", "60"))
_FAILED_LOGINS: dict[str, list] = {}  # ip -> [count, locked_until_epoch]
_FAILED_LOCK = threading.Lock()


def login_locked(ip: str) -> bool:
    with _FAILED_LOCK:
        entry = _FAILED_LOGINS.get(ip)
        return bool(entry) and time.time() < entry[1]


def login_failed(ip: str) -> None:
    with _FAILED_LOCK:
        entry = _FAILED_LOGINS.setdefault(ip, [0, 0.0])
        entry[0] += 1
        if entry[0] >= LOCKOUT_AFTER:
            entry[1] = time.time() + LOCKOUT_SECS
            entry[0] = 0


def login_succeeded(ip: str) -> None:
    with _FAILED_LOCK:
        _FAILED_LOGINS.pop(ip, None)


def load_token() -> str:
    tok = os.environ.get("SYNTHMK_ADMIN_TOKEN", "").strip()
    if tok:
        return tok
    if TOKEN_FILE.is_file():
        return TOKEN_FILE.read_text().strip()
    tok = pysecrets.token_urlsafe(24)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, tok.encode())
    finally:
        os.close(fd)
    print(f"admin-server: generated admin token (also in {TOKEN_FILE}): {tok}", flush=True)
    return tok


TOKEN = load_token()

# Optional read-only token for the multi-node special agent's pull endpoint
# (/api/results). The Checkmk server only needs to *read* results, so hand it
# this scoped token instead of the full admin token. When unset, the admin
# token still works (so /api/results is reachable out of the box).
RESULTS_TOKEN = os.environ.get("SYNTHMK_RESULTS_TOKEN", "").strip()

# Optional read-only dashboard role: a viewer token sees the live table, flow
# YAML and history but every state-changing request is refused. Hand this to
# the on-call folks who need eyes, not write access.
VIEWER_TOKEN = os.environ.get("SYNTHMK_VIEWER_TOKEN", "").strip()

# Append-only audit trail of every state-changing dashboard action (and every
# login attempt): one JSON object per line. Ship it to your SIEM by tailing
# the file; the dashboard exposes the last entries at /api/audit (admin only).
AUDIT_FILE = Path(os.environ.get("SYNTHMK_AUDIT_LOG", "/var/log/synthmk-audit.log"))
_AUDIT_LOCK = threading.Lock()


def audit(role: str, ip: str, action: str, target: str = "", ok: bool = True) -> None:
    entry = json.dumps({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "ip": ip, "role": role or "unauthenticated",
        "action": action, "target": target, "ok": bool(ok),
    }, sort_keys=True)
    try:
        with _AUDIT_LOCK:
            with open(AUDIT_FILE, "a") as fh:
                fh.write(entry + "\n")
    except OSError:
        sys.stderr.write(f"admin-server: audit log unwritable: {AUDIT_FILE}\n")


def audit_tail(n: int = 100) -> list[dict]:
    if not AUDIT_FILE.is_file():
        return []
    entries = []
    for line in AUDIT_FILE.read_text().splitlines()[-n:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


# Flow version history: every dashboard save snapshots the previous content,
# so a bad edit is one click from undone. Plain files, newest-first, capped.
HISTORY_KEEP = int(os.environ.get("SYNTHMK_HISTORY_KEEP", "10"))


def history_dir() -> Path:
    return FLOWS_DIR / ".history"


def snapshot_flow(name: str) -> None:
    src = FLOWS_DIR / name
    if not src.is_file():
        return
    hdir = history_dir()
    hdir.mkdir(exist_ok=True)
    ts = int(time.time())
    while (hdir / f"{name}.{ts}").exists():
        ts += 1  # two snapshots in one second must not overwrite each other
    (hdir / f"{name}.{ts}").write_text(src.read_text())
    for _, old in _versions_of(name)[HISTORY_KEEP:]:
        old.unlink(missing_ok=True)


def _versions_of(name: str) -> list[tuple[int, Path]]:
    """(ts, path) snapshots for a flow, newest first."""
    if not history_dir().is_dir():
        return []
    found = []
    for p in history_dir().glob(f"{name}.*"):
        ts = p.name.rsplit(".", 1)[-1]
        if ts.isdigit():
            found.append((int(ts), p))
    return sorted(found, reverse=True)


def flow_history(name: str) -> list[dict]:
    return [{"ts": ts,
             "saved": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
             "bytes": p.stat().st_size}
            for ts, p in _versions_of(name)]


# --- node state assembly ------------------------------------------------------

PAUSED_PREFIX = "#PAUSED "


def _parse_conf_line(line: str) -> dict | None:
    parts = line.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return None
    host, tags = "", []
    for tok in parts[2:]:
        if tok.startswith("tags="):
            tags = [t for t in tok[len("tags="):].split(",") if t]
        elif not host:
            host = tok
    return {"file": parts[0], "interval": int(parts[1]),
            "checkmk_host": host, "tags": tags}


def parse_conf() -> list[dict]:
    """Schedule entries, including paused ones.

    A paused check keeps its line, prefixed `#PAUSED ` — a comment to the
    scheduler (which therefore skips it with zero special-casing), structured
    state to the dashboard (which can resume it with the schedule intact).
    """
    entries = []
    if not CONF.is_file():
        return entries
    for raw in CONF.read_text().splitlines():
        line = raw.strip()
        paused = line.startswith(PAUSED_PREFIX)
        if paused:
            line = line[len(PAUSED_PREFIX):].strip()
        elif not line or line.startswith("#"):
            continue
        entry = _parse_conf_line(line)
        if entry:
            entry["paused"] = paused
            entries.append(entry)
    return entries


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def last_results() -> dict[str, dict]:
    """flow file -> latest result, parsed from the native spool sections."""
    results: dict[str, dict] = {}
    if not SPOOL.is_dir():
        return results
    for f in SPOOL.iterdir():
        m = re.match(r"^(\d+)_synthmk_(.+)$", f.name)
        if not m:
            continue
        maxage, flow_id = int(m.group(1)), m.group(2)
        try:
            age = time.time() - f.stat().st_mtime
            for line in f.read_text().splitlines():
                line = line.strip()
                if not line.startswith("{"):
                    continue
                entry = json.loads(line)
                entry["_age_s"] = int(age)
                entry["_stale"] = age > maxage
                results[flow_id] = entry
        except Exception:
            continue
    return results


def node_state() -> dict:
    conf = parse_conf()
    spool = last_results()
    flows = []
    for e in conf:
        last = spool.get(slug(e["file"]))
        flows.append({**e, "last": last})
    sched = None
    for f in SPOOL.glob("*_synthmk_scheduler"):
        try:
            for line in f.read_text().splitlines():
                if line.strip().startswith("{"):
                    sched = json.loads(line)
        except Exception:
            pass
    return {
        "version": VERSION,
        "flows_dir_writable": os.access(FLOWS_DIR, os.W_OK),
        "conf_writable": os.access(CONF, os.W_OK) if CONF.exists() else os.access(CONF.parent, os.W_OK),
        "scheduler": sched,
        "flows": flows,
    }


def results_payload() -> dict:
    """Read-only result feed for the multi-node special agent (/api/results).

    Each result carries its native <<<synthmk>>> entry (exactly what the
    bundled check plugin parses) plus the piggyback host the flow targets, so
    the special agent on the Checkmk server can re-emit it under the right host
    without re-deriving anything. The scheduler self-service is included too.
    """
    conf = parse_conf()
    host_by_flow = {slug(e["file"]): e.get("checkmk_host", "") for e in conf}
    spool = last_results()
    results = []
    for flow_id, entry in spool.items():
        results.append({
            "piggyback_host": host_by_flow.get(flow_id, ""),
            "entry": entry,
        })
    return {
        "version": VERSION,
        "node": socket.gethostname(),
        "count": len(results),
        "results": results,
    }


def lint_flow_text(text: str) -> tuple[bool, str]:
    """Validate candidate YAML with the repo linter before any write."""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tf:
        tf.write(text)
        tmp = tf.name
    try:
        proc = subprocess.run(
            [sys.executable, str(HOME / "runner" / "flow_lint.py"),
             "--base-dir", str(FLOWS_DIR), tmp],
            capture_output=True, text=True, timeout=30)
        return proc.returncode == 0, proc.stdout.replace(tmp, "<flow>")
    finally:
        os.unlink(tmp)


def _is_entry_for(line: str, flow_file: str) -> bool:
    stripped = line.strip()
    if stripped.startswith(PAUSED_PREFIX):
        stripped = stripped[len(PAUSED_PREFIX):].strip()
    parts = stripped.split()
    return bool(parts) and parts[0] == flow_file


def update_conf(flow_file: str, interval: int | None, host: str,
                tags: list[str] | None = None, paused: bool = False) -> None:
    """Add or update the schedule line for flow_file (interval None = remove)."""
    lines = CONF.read_text().splitlines() if CONF.is_file() else []
    kept = [ln for ln in lines if not _is_entry_for(ln, flow_file)]
    if interval is not None:
        line = f"{flow_file} {interval}"
        if host:
            line += f" {host}"
        if tags:
            line += " tags=" + ",".join(t.strip() for t in tags if t.strip())
        if paused:
            line = PAUSED_PREFIX + line
        kept.append(line)
    CONF.write_text("\n".join(kept) + "\n")


def set_paused(flow_file: str, paused: bool) -> bool:
    """Flip the paused marker, preserving interval/host/tags. False = no entry."""
    for entry in parse_conf():
        if entry["file"] == flow_file:
            update_conf(flow_file, entry["interval"], entry["checkmk_host"],
                        entry["tags"], paused)
            return True
    return False


# --- visual step builder session -----------------------------------------------

class BuilderSession:
    """Owns the builder_session.py worker (one live Playwright page).

    One session per node — the builder is an authoring tool for the operator
    at the dashboard, not a multi-user service. All access is serialized; an
    idle session is reaped so a forgotten tab can't pin a headless browser.
    """

    IDLE_TIMEOUT_S = int(os.environ.get("SYNTHMK_BUILDER_IDLE_S", "600"))

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._last = 0.0

    def _read_line(self, timeout_s: float) -> str | None:
        assert self._proc is not None
        ready, _, _ = select.select([self._proc.stdout], [], [], timeout_s)
        return self._proc.stdout.readline() if ready else None

    def _stop_locked(self) -> None:
        if self._proc is not None:
            try:
                self._proc.kill()
                self._proc.wait(timeout=5)
            except Exception:
                pass
            self._proc = None

    def _spawn_locked(self) -> None:
        self._proc = subprocess.Popen(
            [sys.executable, str(HOME / "runner-node" / "builder_session.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1)
        line = self._read_line(60)
        if not line or not json.loads(line).get("ready"):
            self._stop_locked()
            raise RuntimeError("builder worker failed to start")

    def request(self, payload: dict, timeout_s: float = 60) -> dict:
        with self._lock:
            now = time.time()
            if self._proc is not None and (
                    self._proc.poll() is not None
                    or now - self._last > self.IDLE_TIMEOUT_S):
                self._stop_locked()
            if self._proc is None:
                if payload.get("cmd") != "start":
                    return {"ok": False,
                            "error": "no active builder session; open a page first"}
                try:
                    self._spawn_locked()
                except Exception as exc:
                    return {"ok": False, "error": f"could not start builder: {exc}"}
            self._last = now
            try:
                self._proc.stdin.write(json.dumps(payload) + "\n")
                self._proc.stdin.flush()
                line = self._read_line(timeout_s)
            except Exception as exc:
                self._stop_locked()
                return {"ok": False, "error": f"builder session died: {exc}"}
            if line is None:
                self._stop_locked()
                return {"ok": False, "error": "builder timed out; the session was reset"}
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                self._stop_locked()
                return {"ok": False, "error": "builder protocol error; the session was reset"}

    def stop(self) -> dict:
        with self._lock:
            if self._proc is not None:
                try:
                    self._proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
                    self._proc.stdin.flush()
                    self._proc.wait(timeout=5)
                except Exception:
                    pass
                self._stop_locked()
            return {"ok": True}


BUILDER = BuilderSession()


# --- HTTP ----------------------------------------------------------------------

class AdminHandler(BaseHTTPRequestHandler):
    server_version = "SynthMKAdmin"

    # -- helpers --
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if ctype.startswith("text/html"):
            # The dashboard is self-contained: inline CSS/JS, data: screenshots
            # from the builder, same-origin fetches. Lock everything else out.
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; img-src 'self' data:; "
                "connect-src 'self'; form-action 'self'; frame-ancestors 'none'")
            self.send_header("X-Frame-Options", "DENY")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload) -> None:
        self._send(code, json.dumps(payload).encode(), "application/json")

    def _client_token(self) -> str:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:].strip()
        cookie = http_cookies.SimpleCookie(self.headers.get("Cookie", ""))
        if "synthmk_admin" in cookie:
            return cookie["synthmk_admin"].value
        return ""

    def _role(self) -> str:
        tok = self._client_token()
        if tok and hmac.compare_digest(tok, TOKEN):
            return "admin"
        if VIEWER_TOKEN and tok and hmac.compare_digest(tok, VIEWER_TOKEN):
            return "viewer"
        return ""

    def _authed(self) -> bool:
        return self._role() != ""

    def _ip(self) -> str:
        return self.client_address[0] if self.client_address else "?"

    def _results_authed(self) -> bool:
        # /api/results accepts the scoped read-only token or the admin token.
        tok = self._client_token()
        if not tok:
            tok = (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
        if RESULTS_TOKEN and hmac.compare_digest(tok, RESULTS_TOKEN):
            return True
        return hmac.compare_digest(tok, TOKEN)

    def _csrf_ok(self) -> bool:
        # State-changing requests must repeat the token in a custom header —
        # a cross-site form can carry the cookie but not this header.
        return hmac.compare_digest(self.headers.get("X-SynthMK-Token", ""), TOKEN)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length)) if length else {}
        except Exception:
            return {}

    # -- routes --
    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path == "/healthz":
            return self._send(200, b"ok", "text/plain")
        if url.path == "/login":
            return self._send(200, LOGIN_HTML.encode(), "text/html; charset=utf-8")
        if url.path == "/api/login":
            ip = self._ip()
            if login_locked(ip):
                audit("", ip, "login_locked", ok=False)
                return self._json(429, {"ok": False,
                                        "error": "too many failed attempts; wait a minute"})
            tok = (parse_qs(url.query).get("token") or [""])[0]
            ok_admin = hmac.compare_digest(tok, TOKEN)
            ok_viewer = bool(VIEWER_TOKEN) and hmac.compare_digest(tok, VIEWER_TOKEN)
            if ok_admin or ok_viewer:
                login_succeeded(ip)
                audit("admin" if ok_admin else "viewer", ip, "login")
                cookie = ("synthmk_admin=" + tok +
                          "; HttpOnly; SameSite=Strict; Path=/")
                if TLS_CERT:
                    cookie += "; Secure"
                return self._send(200, b'{"ok": true}', "application/json",
                                  {"Set-Cookie": cookie})
            login_failed(ip)
            audit("", ip, "login", ok=False)
            return self._json(403, {"ok": False, "error": "bad token"})
        if url.path == "/api/results":
            # Read-only feed for the multi-node special agent (separate token).
            if not self._results_authed():
                return self._json(401, {"error": "auth required"})
            return self._json(200, results_payload())
        if not self._authed():
            if url.path == "/":
                return self._send(302, b"", "text/plain", {"Location": "/login"})
            return self._json(401, {"error": "auth required"})

        if url.path == "/":
            return self._send(200, DASH_HTML.encode(), "text/html; charset=utf-8")
        if url.path == "/api/state":
            state = node_state()
            state["role"] = self._role()
            return self._json(200, state)
        if url.path == "/api/flow":
            name = (parse_qs(url.query).get("file") or [""])[0]
            if not FLOW_NAME_RE.match(name):
                return self._json(400, {"error": "bad flow filename"})
            path = FLOWS_DIR / name
            if not path.is_file():
                return self._json(404, {"error": "not found"})
            return self._json(200, {"file": name, "yaml": path.read_text()})
        if url.path == "/api/flow/history":
            name = (parse_qs(url.query).get("file") or [""])[0]
            if not FLOW_NAME_RE.match(name):
                return self._json(400, {"error": "bad flow filename"})
            return self._json(200, {"file": name, "versions": flow_history(name)})
        if url.path == "/api/flow/version":
            q = parse_qs(url.query)
            name = (q.get("file") or [""])[0]
            ts = (q.get("ts") or [""])[0]
            if not FLOW_NAME_RE.match(name) or not ts.isdigit():
                return self._json(400, {"error": "bad file or ts"})
            path = history_dir() / f"{name}.{ts}"
            if not path.is_file():
                return self._json(404, {"error": "version not found"})
            return self._json(200, {"file": name, "ts": int(ts),
                                    "yaml": path.read_text()})
        if url.path == "/api/audit":
            if self._role() != "admin":
                return self._json(403, {"error": "admin token required"})
            n = (parse_qs(url.query).get("n") or ["100"])[0]
            n = max(1, min(int(n), 1000)) if n.isdigit() else 100
            return self._json(200, {"entries": audit_tail(n)})
        if url.path == "/api/builder/shot":
            if self._role() != "admin":
                return self._json(403, {"error": "admin token required"})
            return self._json(200, BUILDER.request({"cmd": "shot"}))
        return self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        # Every state change requires the ADMIN token (viewers are read-only)
        # plus the CSRF header.
        if self._role() != "admin" or not self._csrf_ok():
            return self._json(401, {"error": "admin token required (+ X-SynthMK-Token header)"})

        if url.path == "/api/builder/start":
            target = str(self._body().get("url", "")).strip()
            if not target.startswith(("http://", "https://")):
                return self._json(400, {"error": "url must start with http:// or https://"})
            audit("admin", self._ip(), "builder_start", target)
            return self._json(200, BUILDER.request({"cmd": "start", "url": target}, 90))

        if url.path == "/api/builder/pick":
            body = self._body()
            try:
                x, y = int(body.get("x")), int(body.get("y"))
            except (TypeError, ValueError):
                return self._json(400, {"error": "x and y must be integers"})
            return self._json(200, BUILDER.request({"cmd": "pick", "x": x, "y": y}, 30))

        if url.path == "/api/builder/step":
            step = self._body().get("step")
            if not isinstance(step, dict) or not step.get("action"):
                return self._json(400, {"error": "step must be an object with an action"})
            return self._json(200, BUILDER.request({"cmd": "step", "step": step}, 60))

        if url.path == "/api/builder/stop":
            audit("admin", self._ip(), "builder_stop")
            return self._json(200, BUILDER.stop())

        if url.path == "/api/import/devtools":
            # Chrome DevTools Recorder JSON -> flow YAML, straight into the
            # editor. Same converter as runner/import_devtools.py.
            recording = self._body().get("recording")
            if not isinstance(recording, dict):
                return self._json(400, {"error": "recording must be the parsed "
                                                 "DevTools JSON object"})
            sys.path.insert(0, str(HOME / "runner"))
            try:
                import import_devtools
                flow, notes = import_devtools.convert(recording)
                if not flow["steps"]:
                    return self._json(422, {"error": "recording produced no usable steps",
                                            "notes": notes})
                text = import_devtools.to_yaml(flow)
            except Exception as exc:
                return self._json(500, {"error": f"import failed: {exc}"})
            audit("admin", self._ip(), "import_devtools", flow.get("name", ""))
            return self._json(200, {"ok": True, "yaml": text,
                                    "name": flow.get("name", ""), "notes": notes})

        if url.path == "/api/run":
            body = self._body()
            name = body.get("file", "")
            if not FLOW_NAME_RE.match(name):
                return self._json(400, {"error": "bad flow filename"})
            RUN_NOW_DIR.mkdir(parents=True, exist_ok=True)
            (RUN_NOW_DIR / name).touch()
            audit("admin", self._ip(), "run_now", name)
            return self._json(200, {"ok": True, "queued": name})

        if url.path == "/api/pause":
            body = self._body()
            name = body.get("file", "")
            paused = bool(body.get("paused"))
            if not FLOW_NAME_RE.match(name):
                return self._json(400, {"error": "bad flow filename"})
            if not (CONF.is_file() and os.access(CONF, os.W_OK)):
                return self._json(409, {"error": "flows.conf is not writable"})
            if not set_paused(name, paused):
                return self._json(404, {"error": "no schedule entry for that flow"})
            audit("admin", self._ip(), "pause" if paused else "resume", name)
            return self._json(200, {"ok": True, "file": name, "paused": paused})

        if url.path == "/api/flow":
            body = self._body()
            name = body.get("file", "")
            yaml_text = body.get("yaml", "")
            interval = body.get("interval")
            host = str(body.get("checkmk_host", "") or "")
            raw_tags = body.get("tags", [])
            if isinstance(raw_tags, str):
                raw_tags = [t for t in raw_tags.split(",")]
            tags = [t.strip() for t in raw_tags if str(t).strip()]
            if not FLOW_NAME_RE.match(name):
                return self._json(400, {"error": "bad flow filename"})
            if not os.access(FLOWS_DIR, os.W_OK):
                return self._json(409, {"error": "flows directory is mounted read-only"})
            ok, report = lint_flow_text(yaml_text)
            if not ok:
                audit("admin", self._ip(), "flow_save", name, ok=False)
                return self._json(422, {"error": "flow failed lint", "lint": report})
            snapshot_flow(name)  # previous content -> .history (rollback point)
            (FLOWS_DIR / name).write_text(yaml_text)
            audit("admin", self._ip(), "flow_save", name)
            if interval is not None:
                try:
                    was_paused = any(e["file"] == name and e["paused"]
                                     for e in parse_conf())
                    update_conf(name, int(interval), host, tags, was_paused)
                except Exception as exc:
                    return self._json(500, {"error": f"flow saved but schedule update failed: {exc}"})
            return self._json(200, {"ok": True, "lint": report})

        if url.path == "/api/flow/rollback":
            body = self._body()
            name = body.get("file", "")
            ts = str(body.get("ts", ""))
            if not FLOW_NAME_RE.match(name) or not ts.isdigit():
                return self._json(400, {"error": "bad file or ts"})
            if not os.access(FLOWS_DIR, os.W_OK):
                return self._json(409, {"error": "flows directory is mounted read-only"})
            src = history_dir() / f"{name}.{ts}"
            if not src.is_file():
                return self._json(404, {"error": "version not found"})
            text = src.read_text()
            ok, report = lint_flow_text(text)
            if not ok:
                return self._json(422, {"error": "stored version no longer lints "
                                                 "(engine moved on?)", "lint": report})
            snapshot_flow(name)
            (FLOWS_DIR / name).write_text(text)
            audit("admin", self._ip(), "flow_rollback", f"{name}@{ts}")
            return self._json(200, {"ok": True, "file": name, "restored": int(ts)})

        return self._json(404, {"error": "not found"})

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("admin-server: %s\n" % (fmt % args))


LOGIN_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>SynthMK Node: sign in</title><style>
body{font:15px system-ui,sans-serif;background:#0f172a;color:#e2e8f0;display:grid;place-items:center;height:100vh;margin:0}
form{background:#1e293b;padding:2rem;border-radius:12px;width:22rem;box-shadow:0 8px 40px rgba(0,0,0,.4)}
h1{font-size:1.1rem;color:#2dd4bf;margin:0 0 1rem}
input{width:100%;box-sizing:border-box;padding:.6rem;border-radius:8px;border:1px solid #334155;background:#020617;color:#e2e8f0}
button{margin-top:1rem;width:100%;padding:.6rem;border:0;border-radius:8px;background:#2dd4bf;color:#0f172a;font-weight:600;cursor:pointer}
p.err{color:#f87171;font-size:.85rem;min-height:1.2em}</style></head><body>
<form onsubmit="login(event)"><h1>SynthMK runner node</h1>
<input id="tok" type="password" placeholder="Admin token" autofocus>
<button>Sign in</button><p class="err" id="err"></p>
<script>async function login(e){e.preventDefault();
const t=document.getElementById('tok').value;
const r=await fetch('/api/login?token='+encodeURIComponent(t));
if(r.ok){sessionStorage.setItem('synthmk_tok',t);location.href='/';}
else{document.getElementById('err').textContent='Invalid token';}}</script>
</form></body></html>"""


DASH_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SynthMK Node</title><style>
:root{--bg:#0f172a;--card:#1e293b;--line:#334155;--text:#e2e8f0;--dim:#94a3b8;--teal:#2dd4bf;--red:#f87171;--amber:#fbbf24}
*{box-sizing:border-box}body{font:14px system-ui,sans-serif;background:var(--bg);color:var(--text);margin:0;padding:2rem}
h1{font-size:1.3rem;margin:0}h1 b{color:var(--teal)}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:1.2rem}
.pill{font-size:.78rem;color:var(--dim);background:var(--card);padding:.35rem .7rem;border-radius:99px;border:1px solid var(--line)}
table{width:100%;border-collapse:collapse;background:var(--card);border-radius:12px;overflow:hidden}
th,td{padding:.65rem .9rem;text-align:left;border-bottom:1px solid var(--line);font-size:.86rem}
th{color:var(--dim);font-weight:500;font-size:.74rem;text-transform:uppercase;letter-spacing:.05em}
tr:last-child td{border-bottom:0}
.b{display:inline-block;padding:.15rem .55rem;border-radius:99px;font-size:.74rem;font-weight:600}
.b0{background:rgba(45,212,191,.15);color:var(--teal)}.b1{background:rgba(251,191,36,.15);color:var(--amber)}
.b2{background:rgba(248,113,113,.18);color:var(--red)}.b3{background:rgba(148,163,184,.15);color:var(--dim)}
.stale{opacity:.55}
.tag{display:inline-block;font-size:.68rem;color:var(--dim);border:1px solid var(--line);border-radius:99px;padding:.05rem .45rem;margin-left:.35rem}
.paused td{opacity:.6}
button{padding:.32rem .7rem;border-radius:7px;border:1px solid var(--line);background:#0f172a;color:var(--text);cursor:pointer;font-size:.78rem}
button:hover{border-color:var(--teal);color:var(--teal)}
a{color:var(--teal)}
#editor{display:none;margin-top:1.4rem;background:var(--card);border-radius:12px;padding:1.2rem}
#editor h2{margin:0 0 .8rem;font-size:1rem;color:var(--teal)}
textarea{width:100%;height:300px;background:#020617;color:#cbd5e1;border:1px solid var(--line);border-radius:8px;font:12px ui-monospace,monospace;padding:.8rem}
.row{display:flex;gap:.8rem;margin:.8rem 0;align-items:center;flex-wrap:wrap}
.row input{background:#020617;color:var(--text);border:1px solid var(--line);border-radius:7px;padding:.4rem .6rem}
#msg{font-size:.82rem;white-space:pre-wrap;color:var(--dim)}
.steps{color:var(--dim);font-size:.76rem}
.primary{background:var(--teal);color:#0f172a;border-color:var(--teal);font-weight:600}
#builder{display:none;margin-top:1.4rem;background:var(--card);border-radius:12px;padding:1.2rem}
#builder h2{margin:0 0 .8rem;font-size:1rem;color:var(--teal)}
.bwrap{display:flex;gap:1rem;align-items:flex-start;flex-wrap:wrap}
.bshot{flex:1 1 540px;min-width:380px}
.bshot img{width:100%;border:1px solid var(--line);border-radius:8px;cursor:crosshair;display:block}
.bshot .burl{font-size:.74rem;color:var(--dim);margin-top:.3rem;word-break:break-all}
.bpanel{flex:1 1 300px;min-width:280px;max-width:430px}
.bcard{background:#0f172a;border:1px solid var(--line);border-radius:9px;padding:.8rem;margin-bottom:.8rem}
.bcard h3{margin:0 0 .5rem;font-size:.82rem;color:var(--teal)}
.bcard label{display:block;font-size:.78rem;color:var(--dim);margin:.45rem 0 .15rem}
.bcard input[type=text],.bcard select{width:100%;box-sizing:border-box;background:#020617;color:var(--text);border:1px solid var(--line);border-radius:7px;padding:.38rem .5rem;font-size:.8rem}
.bcand{font:11px ui-monospace,monospace;display:flex;gap:.4rem;align-items:center;margin:.2rem 0;word-break:break-all}
.bsteps{list-style:none;margin:.4rem 0 0;padding:0;font-size:.78rem}
.bsteps li{display:flex;justify-content:space-between;gap:.5rem;border-bottom:1px solid var(--line);padding:.3rem .1rem;font-family:ui-monospace,monospace}
.bsteps li:last-child{border-bottom:0}
.bsteps .ok{color:var(--teal)}.bsteps .err{color:var(--red)}
.bsteps button{padding:.05rem .4rem;font-size:.7rem}
#bstatus{font-size:.8rem;color:var(--dim);white-space:pre-wrap}
.bhint{font-size:.78rem;color:var(--dim)}
.qa{display:flex;gap:.4rem;flex-wrap:wrap;margin-top:.4rem}
.qa button{font-size:.72rem;padding:.25rem .5rem}
</style></head><body>
<div class="top">
  <h1><b>SynthMK</b> runner node</h1>
  <div>
    <span class="pill" id="sched">scheduler: …</span>
    <span class="pill" id="ver"></span>
    <button onclick="toggleBuilder()" id="builderbtn">Step builder</button>
    <button onclick="document.getElementById('importfile').click()" id="importbtn">Import recording</button>
    <input type="file" id="importfile" accept=".json,application/json" style="display:none" onchange="importRecording(this)">
    <button onclick="newFlow()" class="primary" id="newbtn">+ New check</button>
  </div>
</div>
<table><thead><tr>
<th>Check</th><th>State</th><th>Duration</th><th>Steps</th><th>Every</th><th>Host</th><th>Last run</th><th></th>
</tr></thead><tbody id="rows"></tbody></table>

<div id="builder">
  <h2>Visual step builder</h2>
  <div class="row">
    <input id="burl" size="42" placeholder="https://portal.example/login" value="https://">
    <button class="primary" onclick="bOpen()">Open page</button>
    <button onclick="bReplay()" id="breplay">Replay steps</button>
    <button onclick="bStop()">Stop session</button>
    <span id="bstatus"></span>
  </div>
  <div class="bwrap">
    <div class="bshot">
      <img id="bshot" alt="page preview" onclick="bPick(event)" style="display:none">
      <div class="burl" id="bpageurl"></div>
    </div>
    <div class="bpanel">
      <div class="bcard" id="belem">
        <h3>Element</h3>
        <div class="bhint">Open a page, then click an element in the preview.
        Like Chrome inspect, but every click builds a monitored step.</div>
      </div>
      <div class="bcard">
        <h3>Page checks</h3>
        <div class="qa">
          <button onclick="bQuick('check_title')">Assert title</button>
          <button onclick="bQuick('check_url')">Assert URL</button>
          <button onclick="bQuick('check_text')">Assert text…</button>
          <button onclick="bQuick('press_enter')">Press Enter</button>
          <button onclick="bQuick('wait_idle')">Wait network idle</button>
          <button onclick="bQuick('screenshot')">Screenshot</button>
        </div>
      </div>
      <div class="bcard">
        <h3>Steps <span class="bhint" id="bcount"></span></h3>
        <ol class="bsteps" id="bsteplist"></ol>
        <div class="row" style="margin-bottom:0">
          <input id="bname" size="22" placeholder="Flow name" value="My Recorded Journey">
          <button class="primary" onclick="bExport()">Open in editor</button>
        </div>
        <div class="bhint">Removing a step does not undo it in the live page.
        Use Replay steps to re-run the list from the start URL.</div>
      </div>
    </div>
  </div>
</div>

<div id="editor">
  <h2 id="etitle">Edit flow</h2>
  <div class="row">
    <label>File <input id="efile" size="24" placeholder="my-check.yaml"></label>
    <label>Interval (s) <input id="eint" size="6" value="300"></label>
    <label>Piggyback host <input id="ehost" size="16" placeholder="(optional)"></label>
    <label>Tags <input id="etags" size="16" placeholder="payments,critical"></label>
  </div>
  <textarea id="eyaml" spellcheck="false"></textarea>
  <div class="row">
    <button class="primary" onclick="saveFlow()">Lint &amp; save</button>
    <button onclick="document.getElementById('editor').style.display='none'">Close</button>
    <span id="msg"></span>
  </div>
  <div class="row" id="histrow" style="display:none">
    <label>History <select id="ehist"></select></label>
    <button onclick="loadVersion()">View version</button>
    <button onclick="rollbackVersion()">Roll back to it</button>
    <span class="bhint">Every save keeps the previous version; roll back re-lints first.</span>
  </div>
</div>

<script>
const TOKEN_HEADER = {};  // cookie carries auth; CSRF header injected below
let TOKEN = '';
function hdrs(){return {'Content-Type':'application/json','X-SynthMK-Token':TOKEN};}
const SN=['OK','WARN','CRIT','UNKNOWN'];
function badge(s){return '<span class="b b'+s+'">'+SN[s]+'</span>';}
function fmtAge(s){if(s==null)return '—';if(s<90)return s+'s ago';if(s<5400)return Math.round(s/60)+'m ago';return Math.round(s/3600)+'h ago';}
let ROLE='admin',FLOWS=[];
async function refresh(){
  const r=await fetch('/api/state');if(r.status===401){location.href='/login';return;}
  const st=await r.json();ROLE=st.role||'admin';FLOWS=st.flows;
  document.getElementById('ver').textContent='v'+st.version+(ROLE==='viewer'?' · read-only':'');
  if(st.scheduler){document.getElementById('sched').textContent='scheduler: '+st.scheduler.summary;}
  const canWrite=st.flows_dir_writable&&ROLE==='admin';
  document.getElementById('newbtn').style.display=canWrite?'':'none';
  document.getElementById('builderbtn').style.display=ROLE==='admin'?'':'none';
  document.getElementById('importbtn').style.display=canWrite?'':'none';
  const rows=st.flows.map((f,i)=>{
    const l=f.last||{};const cls=(f.paused?' class="paused"':(l._stale?' class="stale"':''));
    const steps=(l.steps||[]).map(s=>s.label.replace(/^step\\d+_/,'')+' '+s.ms+'ms').join(' → ');
    const shot=l.screenshot_url?' <a href="'+l.screenshot_url+'" target="_blank">📷</a>':'';
    const tags=(f.tags||[]).map(t=>'<span class="tag">'+t+'</span>').join('');
    const state=f.paused?'<span class="b b3">PAUSED</span>':(l.status!=null?badge(l.status):'—');
    const acts=ROLE!=='admin'?'':
      '<button onclick="runNow('+i+')">Run now</button> '+
      '<button onclick="editFlow('+i+')">Edit</button> '+
      '<button onclick="pauseFlow('+i+')">'+(f.paused?'Resume':'Pause')+'</button>';
    return '<tr'+cls+'><td>'+(l.service||f.file)+tags+shot+'</td><td>'+state+
      '</td><td>'+(l.duration_ms!=null?l.duration_ms+'ms':'—')+'</td><td class="steps">'+steps+
      '</td><td>'+f.interval+'s</td><td>'+(f.checkmk_host||'—')+'</td><td>'+fmtAge(l._age_s)+
      '</td><td>'+acts+'</td></tr>';
  });
  document.getElementById('rows').innerHTML=rows.join('')||'<tr><td colspan="8">No checks configured.</td></tr>';
}
async function runNow(i){await fetch('/api/run',{method:'POST',headers:hdrs(),body:JSON.stringify({file:FLOWS[i].file})});setTimeout(refresh,1200);}
async function pauseFlow(i){
  await fetch('/api/pause',{method:'POST',headers:hdrs(),
    body:JSON.stringify({file:FLOWS[i].file,paused:!FLOWS[i].paused})});
  setTimeout(refresh,400);
}
async function editFlow(i){
  const f=FLOWS[i];
  const r=await fetch('/api/flow?file='+encodeURIComponent(f.file));const d=await r.json();
  document.getElementById('etitle').textContent='Edit '+f.file;
  document.getElementById('efile').value=f.file;document.getElementById('eint').value=f.interval;
  document.getElementById('ehost').value=f.checkmk_host||'';
  document.getElementById('etags').value=(f.tags||[]).join(',');
  document.getElementById('eyaml').value=d.yaml||'';
  document.getElementById('msg').textContent='';document.getElementById('editor').style.display='block';
  loadHistory(f.file);
  window.scrollTo(0,document.body.scrollHeight);
}
async function loadHistory(file){
  const row=document.getElementById('histrow');
  const r=await fetch('/api/flow/history?file='+encodeURIComponent(file));
  const d=await r.json();
  if(!d.versions||!d.versions.length){row.style.display='none';return;}
  document.getElementById('ehist').innerHTML=d.versions.map(v=>
    '<option value="'+v.ts+'">'+v.saved+' ('+v.bytes+' B)</option>').join('');
  row.style.display='flex';
}
async function loadVersion(){
  const file=document.getElementById('efile').value,ts=document.getElementById('ehist').value;
  const r=await fetch('/api/flow/version?file='+encodeURIComponent(file)+'&ts='+ts);
  const d=await r.json();
  if(d.yaml!=null){document.getElementById('eyaml').value=d.yaml;
    document.getElementById('msg').textContent='Viewing version '+ts+' (not saved).';}
}
async function rollbackVersion(){
  const file=document.getElementById('efile').value,ts=document.getElementById('ehist').value;
  const r=await fetch('/api/flow/rollback',{method:'POST',headers:hdrs(),
    body:JSON.stringify({file,ts})});
  const d=await r.json();
  document.getElementById('msg').textContent=r.ok?'Rolled back ✓':(d.error||'rollback failed');
  if(r.ok){editFlowByName(file);setTimeout(refresh,500);}
}
function editFlowByName(file){
  const i=FLOWS.findIndex(f=>f.file===file);
  if(i>=0)editFlow(i);
}
async function importRecording(input){
  const f=input.files[0];input.value='';
  if(!f)return;
  let rec;
  try{rec=JSON.parse(await f.text());}
  catch(e){alert('Not valid JSON: '+e.message);return;}
  const r=await fetch('/api/import/devtools',{method:'POST',headers:hdrs(),
    body:JSON.stringify({recording:rec})});
  const d=await r.json();
  if(!r.ok){alert(d.error||'import failed');return;}
  const slug=(d.name||'imported-check').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'')||'imported-check';
  document.getElementById('etitle').textContent='Imported recording: '+(d.name||f.name);
  document.getElementById('efile').value=slug+'.yaml';
  document.getElementById('eint').value='300';
  document.getElementById('ehost').value='';document.getElementById('etags').value='';
  document.getElementById('histrow').style.display='none';
  document.getElementById('eyaml').value=d.yaml;
  document.getElementById('msg').textContent=(d.notes&&d.notes.length?('Importer notes:\\n- '+d.notes.join('\\n- ')+'\\n'):'')+'Review, then Lint & save.';
  document.getElementById('editor').style.display='block';
  window.scrollTo(0,document.body.scrollHeight);
}
function newFlow(){
  document.getElementById('etitle').textContent='New check';
  document.getElementById('efile').value='my-check.yaml';document.getElementById('eint').value='300';
  document.getElementById('ehost').value='';document.getElementById('etags').value='';
  document.getElementById('histrow').style.display='none';
  document.getElementById('eyaml').value='name: My Synthetic Check\\ntimeout_ms: 20000\\nwarn_ms: 5000\\ncrit_ms: 15000\\nscreenshot_on_failure: true\\nsteps:\\n  - action: open_url\\n    url: https://example.com\\n  - action: check_title\\n    contains: Example\\n';
  document.getElementById('msg').textContent='';document.getElementById('editor').style.display='block';
  window.scrollTo(0,document.body.scrollHeight);
}
async function saveFlow(){
  const body={file:document.getElementById('efile').value,
    yaml:document.getElementById('eyaml').value,
    interval:parseInt(document.getElementById('eint').value,10),
    checkmk_host:document.getElementById('ehost').value,
    tags:document.getElementById('etags').value};
  const r=await fetch('/api/flow',{method:'POST',headers:hdrs(),body:JSON.stringify(body)});
  const d=await r.json();
  document.getElementById('msg').textContent=r.ok?('Saved ✓\\n'+(d.lint||'')):(d.error+'\\n'+(d.lint||''));
  if(r.ok)setTimeout(refresh,800);
}
// ---------- visual step builder ----------
let bSteps=[];        // {step:{...}, label:string, tested:bool}
let bStartUrl='';
let bElem=null;       // last picked element info

function toggleBuilder(){
  const b=document.getElementById('builder');
  b.style.display=b.style.display==='block'?'none':'block';
  if(b.style.display==='block')window.scrollTo(0,b.offsetTop-10);
}
function bStatus(t,isErr){const s=document.getElementById('bstatus');
  s.textContent=t;s.style.color=isErr?'var(--red)':'var(--dim)';}
function bShowShot(d){
  if(!d.png)return;
  const img=document.getElementById('bshot');
  img.src='data:image/png;base64,'+d.png;img.style.display='block';
  document.getElementById('bpageurl').textContent=(d.title?d.title+' · ':'')+(d.url||'');
}
async function bApi(path,body){
  const r=await fetch(path,{method:'POST',headers:hdrs(),body:JSON.stringify(body||{})});
  return await r.json();
}
async function bOpen(){
  const u=document.getElementById('burl').value.trim();
  if(!u.startsWith('http')){bStatus('URL must start with http(s)://',true);return;}
  bStatus('Opening page…');
  const d=await bApi('/api/builder/start',{url:u});
  if(d.ok===false){bStatus(d.error,true);return;}
  bStartUrl=u;bShowShot(d);bStatus('Page open. Click an element to build a step.');
  if(!bSteps.length){bSteps.push({step:{action:'open_url',url:u},label:'open_url '+u,tested:true});bRenderSteps();}
}
async function bStop(){
  await bApi('/api/builder/stop',{});
  document.getElementById('bshot').style.display='none';
  bStatus('Session stopped.');
}
function bScaleCoords(ev){
  const img=ev.target,r=img.getBoundingClientRect();
  return {x:Math.round((ev.clientX-r.left)*(img.naturalWidth/r.width)),
          y:Math.round((ev.clientY-r.top)*(img.naturalHeight/r.height))};
}
async function bPick(ev){
  const pt=bScaleCoords(ev);
  bStatus('Inspecting element…');
  const d=await bApi('/api/builder/pick',pt);
  if(d.ok===false){bStatus(d.error,true);return;}
  bShowShot(d);bElem=d.element;bRenderElem();bStatus('');
}
function bDefaultAction(e){
  if(e.isPassword||e.isInput)return 'fill';
  if(e.isSelect)return 'select_option';
  if(e.isCheckbox)return 'check_checkbox';
  if(e.tag==='a'||e.tag==='button'||['button','submit'].includes(e.type))return 'click';
  if(e.text)return 'check_visible_text';
  return 'click';
}
const B_ACTIONS=['click','fill','select_option','hover','check_visible_text',
  'check_text_absent','wait_for_element','check_element_count',
  'check_element_attribute','check_checkbox','scroll_into_view'];
function bRenderElem(){
  const e=bElem,el=document.getElementById('belem');
  const cands=e.candidates.map((c,i)=>
    `<div class="bcand"><input type="checkbox" id="bc${i}" ${i<2?'checked':''}><label for="bc${i}" style="display:inline;margin:0">${bEsc(c)}</label></div>`).join('');
  const opts=B_ACTIONS.map(a=>`<option ${a===bDefaultAction(e)?'selected':''}>${a}</option>`).join('');
  el.innerHTML=`<h3>Element &lt;${e.tag}${e.type?' type='+e.type:''}&gt;</h3>`+
    (e.text?`<div class="bhint">“${bEsc(e.text.slice(0,60))}”</div>`:'')+
    `<label>Selector ladder (checked = used, in order)</label>${cands}`+
    `<label>Action</label><select id="bact" onchange="bRenderFields()">${opts}</select>`+
    `<div id="bfields"></div>`+
    `<div class="row" style="margin-bottom:0"><button class="primary" onclick="bAddStep()">Add &amp; test step</button></div>`;
  bRenderFields();
}
function bRenderFields(){
  const e=bElem,a=document.getElementById('bact').value,f=document.getElementById('bfields');
  let h='';
  if(a==='fill'){
    const v=e.isPassword?'{{ secret.password }}':(e.text||'');
    h+=`<label>Value</label><input type="text" id="bval" value="${bEsc(v)}">`+
       `<label><input type="checkbox" id="bsens" ${e.isPassword?'checked':''} style="width:auto"> sensitive (mask in screenshots, redact in output)</label>`+
       (e.isPassword?'<div class="bhint">Password detected: the value stays a secret reference; put the real value in the node’s secrets file.</div>':'');
  }else if(a==='select_option'){
    const o=(e.options||[]).map(x=>`<option value="${bEsc(x.value)}">${bEsc(x.label||x.value)}</option>`).join('');
    h+=`<label>Option</label>`+(o?`<select id="bval">${o}</select>`:`<input type="text" id="bval">`);
  }else if(a==='check_visible_text'||a==='check_text_absent'){
    h+=`<label>Text</label><input type="text" id="bval" value="${bEsc(e.text||'')}">`;
  }else if(a==='check_element_count'){
    h+=`<label>Minimum count</label><input type="text" id="bval" value="1">`;
  }else if(a==='check_element_attribute'){
    h+=`<label>Attribute</label><input type="text" id="battr" value="${e.href?'href':''}">`+
       `<label>Contains (empty = just present)</label><input type="text" id="bval" value="${bEsc(e.href||'')}">`;
  }else if(a==='check_checkbox'){
    h+=`<label><input type="checkbox" id="bval" ${e.checked?'checked':''} style="width:auto"> expected checked</label>`;
  }
  f.innerHTML=h;
}
function bSelectedLadder(){
  const sel=[];
  bElem.candidates.forEach((c,i)=>{const cb=document.getElementById('bc'+i);if(cb&&cb.checked)sel.push(c);});
  return sel.length?(sel.length===1?sel[0]:sel):bElem.candidates[0];
}
function bStepLabel(st){
  let l=st.action;
  if(st.selector)l+=' '+(Array.isArray(st.selector)?st.selector[0]:st.selector);
  if(st.text)l+=' “'+st.text.slice(0,24)+'”';
  if(st.url)l+=' '+st.url;if(st.key)l+=' '+st.key;
  return l;
}
async function bAddStep(){
  const a=document.getElementById('bact').value;
  const st={action:a};
  const needsSel=!['check_visible_text','check_text_absent'].includes(a);
  if(needsSel)st.selector=bSelectedLadder();
  const val=document.getElementById('bval');
  if(a==='fill'){st.value=val.value;if(document.getElementById('bsens').checked)st.sensitive=true;}
  else if(a==='select_option')st.value=val.value;
  else if(a==='check_visible_text'||a==='check_text_absent')st.text=val.value;
  else if(a==='check_element_count')st.min=parseInt(val.value,10)||1;
  else if(a==='check_element_attribute'){st.attribute=document.getElementById('battr').value;
    if(val.value)st.contains=val.value;}
  else if(a==='check_checkbox')st.checked=val.checked;
  await bRunAndRecord(st);
}
async function bQuick(kind){
  let st=null;
  if(kind==='check_title'){const t=prompt('Title must contain:',
    (document.getElementById('bpageurl').textContent.split(' · ')[0]||'').trim());
    if(t===null)return;st={action:'check_title',contains:t};}
  else if(kind==='check_url'){const u=prompt('URL must contain:','/');
    if(u===null)return;st={action:'check_url',contains:u};}
  else if(kind==='check_text'){const t=prompt('Page must show text:','');
    if(!t)return;st={action:'check_visible_text',text:t};}
  else if(kind==='press_enter')st={action:'press',key:'Enter'};
  else if(kind==='wait_idle')st={action:'wait_for_network_idle'};
  else if(kind==='screenshot')st={action:'screenshot',name:'evidence'};
  if(st)await bRunAndRecord(st);
}
async function bRunAndRecord(st){
  bStatus('Testing step on the live page…');
  const d=await bApi('/api/builder/step',{step:st});
  bShowShot(d);
  if(d.ok===false){bStatus('Step failed: '+d.error+'. Not added.',true);return;}
  bSteps.push({step:st,label:bStepLabel(st),tested:true});
  bRenderSteps();bStatus('Step added ✓');
  document.getElementById('belem').innerHTML='<h3>Element</h3><div class="bhint">Click the next element in the preview.</div>';
}
function bRenderSteps(){
  const ol=document.getElementById('bsteplist');
  ol.innerHTML=bSteps.map((s,i)=>
    `<li><span class="${s.tested?'ok':''}">${i}. ${bEsc(s.label)}</span>`+
    `<button onclick="bSteps.splice(${i},1);bRenderSteps()">✕</button></li>`).join('');
  document.getElementById('bcount').textContent=bSteps.length?('('+bSteps.length+')'):'';
}
async function bReplay(){
  if(!bSteps.length||bSteps[0].step.action!=='open_url'){bStatus('Nothing to replay.',true);return;}
  bStatus('Replaying…');
  let d=await bApi('/api/builder/start',{url:bSteps[0].step.url});
  if(d.ok===false){bStatus(d.error,true);return;}
  for(let i=1;i<bSteps.length;i++){
    d=await bApi('/api/builder/step',{step:bSteps[i].step});
    if(d.ok===false){bShowShot(d);bStatus('Replay failed at step '+i+': '+d.error,true);return;}
  }
  bShowShot(d);bStatus('Replay OK: '+bSteps.length+' steps ✓');
}
function bEsc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function yScalar(v){
  if(typeof v==='number'||typeof v==='boolean')return String(v);
  return JSON.stringify(String(v)); // JSON string == valid YAML double-quoted scalar
}
function bYaml(){
  const name=document.getElementById('bname').value.trim()||'My Recorded Journey';
  let y='name: '+yScalar(name)+'\\ntimeout_ms: 30000\\nwarn_ms: 8000\\ncrit_ms: 20000\\nscreenshot_on_failure: true\\nsteps:\\n';
  const ORDER=['action','selector','url','key','value','sensitive','text','contains','attribute','equals','min','checked','ms','name','full_page'];
  for(const s of bSteps){
    let first=true;
    for(const k of ORDER){
      if(!(k in s.step))continue;
      const v=s.step[k];
      const pre=first?'  - ':'    ';first=false;
      if(Array.isArray(v)){
        y+=pre+k+':\\n';
        for(const it of v)y+='      - '+yScalar(it)+'\\n';
      }else{
        y+=pre+k+': '+yScalar(v)+'\\n';
      }
    }
  }
  return y;
}
function bExport(){
  const name=document.getElementById('bname').value.trim()||'my-journey';
  const slug=name.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'')||'my-journey';
  document.getElementById('etitle').textContent='New check (from step builder)';
  document.getElementById('efile').value=slug+'.yaml';
  document.getElementById('eint').value='300';
  document.getElementById('ehost').value='';
  document.getElementById('eyaml').value=bYaml();
  document.getElementById('msg').textContent='Review, then Lint & save.';
  document.getElementById('editor').style.display='block';
  window.scrollTo(0,document.body.scrollHeight);
}

// CSRF header needs the raw token (cookie is HttpOnly); the login page
// stores it in sessionStorage. Missing (e.g. new tab) -> re-login.
TOKEN=sessionStorage.getItem('synthmk_tok')||'';
if(!TOKEN){location.href='/login';}
refresh();setInterval(refresh,5000);
</script></body></html>"""


def main() -> int:
    RUN_NOW_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((BIND, PORT), AdminHandler)
    scheme = "http"
    if TLS_CERT and TLS_KEY:
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(TLS_CERT, TLS_KEY)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        scheme = "https"
    print(f"admin-server: dashboard on {scheme}://{BIND}:{PORT} "
          f"(flows {'rw' if os.access(FLOWS_DIR, os.W_OK) else 'ro'})", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
