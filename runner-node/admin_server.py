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
import socket
import subprocess
import sys
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


# --- node state assembly ------------------------------------------------------

def parse_conf() -> list[dict]:
    entries = []
    if not CONF.is_file():
        return entries
    for raw in CONF.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            entries.append({"file": parts[0], "interval": int(parts[1]),
                            "checkmk_host": parts[2] if len(parts) > 2 else ""})
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
            [sys.executable, str(HOME / "runner" / "flow_lint.py"), tmp],
            capture_output=True, text=True, timeout=30)
        return proc.returncode == 0, proc.stdout.replace(tmp, "<flow>")
    finally:
        os.unlink(tmp)


def update_conf(flow_file: str, interval: int | None, host: str) -> None:
    """Add or update the schedule line for flow_file (interval None = remove)."""
    lines = CONF.read_text().splitlines() if CONF.is_file() else []
    kept = [ln for ln in lines
            if not (ln.split() and ln.split()[0] == flow_file)]
    if interval is not None:
        kept.append(f"{flow_file} {interval}" + (f" {host}" if host else ""))
    CONF.write_text("\n".join(kept) + "\n")


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

    def _authed(self) -> bool:
        return hmac.compare_digest(self._client_token(), TOKEN)

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
            tok = (parse_qs(url.query).get("token") or [""])[0]
            if hmac.compare_digest(tok, TOKEN):
                return self._send(200, b'{"ok": true}', "application/json", {
                    "Set-Cookie": "synthmk_admin=" + tok +
                                  "; HttpOnly; SameSite=Strict; Path=/",
                })
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
            return self._json(200, node_state())
        if url.path == "/api/flow":
            name = (parse_qs(url.query).get("file") or [""])[0]
            if not FLOW_NAME_RE.match(name):
                return self._json(400, {"error": "bad flow filename"})
            path = FLOWS_DIR / name
            if not path.is_file():
                return self._json(404, {"error": "not found"})
            return self._json(200, {"file": name, "yaml": path.read_text()})
        return self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if not self._authed() or not self._csrf_ok():
            return self._json(401, {"error": "auth required (token + X-SynthMK-Token header)"})

        if url.path == "/api/run":
            body = self._body()
            name = body.get("file", "")
            if not FLOW_NAME_RE.match(name):
                return self._json(400, {"error": "bad flow filename"})
            RUN_NOW_DIR.mkdir(parents=True, exist_ok=True)
            (RUN_NOW_DIR / name).touch()
            return self._json(200, {"ok": True, "queued": name})

        if url.path == "/api/flow":
            body = self._body()
            name = body.get("file", "")
            yaml_text = body.get("yaml", "")
            interval = body.get("interval")
            host = str(body.get("checkmk_host", "") or "")
            if not FLOW_NAME_RE.match(name):
                return self._json(400, {"error": "bad flow filename"})
            if not os.access(FLOWS_DIR, os.W_OK):
                return self._json(409, {"error": "flows directory is mounted read-only"})
            ok, report = lint_flow_text(yaml_text)
            if not ok:
                return self._json(422, {"error": "flow failed lint", "lint": report})
            (FLOWS_DIR / name).write_text(yaml_text)
            if interval is not None:
                try:
                    update_conf(name, int(interval), host)
                except Exception as exc:
                    return self._json(500, {"error": f"flow saved but schedule update failed: {exc}"})
            return self._json(200, {"ok": True, "lint": report})

        return self._json(404, {"error": "not found"})

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("admin-server: %s\n" % (fmt % args))


LOGIN_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>SynthMK Node — sign in</title><style>
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
</style></head><body>
<div class="top">
  <h1><b>SynthMK</b> runner node</h1>
  <div>
    <span class="pill" id="sched">scheduler: …</span>
    <span class="pill" id="ver"></span>
    <button onclick="newFlow()" class="primary" id="newbtn">+ New check</button>
  </div>
</div>
<table><thead><tr>
<th>Check</th><th>State</th><th>Duration</th><th>Steps</th><th>Every</th><th>Host</th><th>Last run</th><th></th>
</tr></thead><tbody id="rows"></tbody></table>

<div id="editor">
  <h2 id="etitle">Edit flow</h2>
  <div class="row">
    <label>File <input id="efile" size="24" placeholder="my-check.yaml"></label>
    <label>Interval (s) <input id="eint" size="6" value="300"></label>
    <label>Piggyback host <input id="ehost" size="16" placeholder="(optional)"></label>
  </div>
  <textarea id="eyaml" spellcheck="false"></textarea>
  <div class="row">
    <button class="primary" onclick="saveFlow()">Lint &amp; save</button>
    <button onclick="document.getElementById('editor').style.display='none'">Close</button>
    <span id="msg"></span>
  </div>
</div>

<script>
const TOKEN_HEADER = {};  // cookie carries auth; CSRF header injected below
let TOKEN = '';
function hdrs(){return {'Content-Type':'application/json','X-SynthMK-Token':TOKEN};}
const SN=['OK','WARN','CRIT','UNKNOWN'];
function badge(s){return '<span class="b b'+s+'">'+SN[s]+'</span>';}
function fmtAge(s){if(s==null)return '—';if(s<90)return s+'s ago';if(s<5400)return Math.round(s/60)+'m ago';return Math.round(s/3600)+'h ago';}
async function refresh(){
  const r=await fetch('/api/state');if(r.status===401){location.href='/login';return;}
  const st=await r.json();
  document.getElementById('ver').textContent='v'+st.version;
  if(st.scheduler){document.getElementById('sched').textContent='scheduler: '+st.scheduler.summary;}
  document.getElementById('newbtn').style.display=st.flows_dir_writable?'':'none';
  const rows=st.flows.map(f=>{
    const l=f.last||{};const stale=l._stale?' class="stale"':'';
    const steps=(l.steps||[]).map(s=>s.label.replace(/^step\\d+_/,'')+' '+s.ms+'ms').join(' → ');
    const shot=l.screenshot_url?' <a href="'+l.screenshot_url+'" target="_blank">📷</a>':'';
    return '<tr'+stale+'><td>'+(l.service||f.file)+shot+'</td><td>'+(l.status!=null?badge(l.status):'—')+
      '</td><td>'+(l.duration_ms!=null?l.duration_ms+'ms':'—')+'</td><td class="steps">'+steps+
      '</td><td>'+f.interval+'s</td><td>'+(f.checkmk_host||'—')+'</td><td>'+fmtAge(l._age_s)+
      '</td><td><button onclick="runNow(\\''+f.file+'\\')">Run now</button> '+
      '<button onclick="editFlow(\\''+f.file+'\\','+f.interval+',\\''+(f.checkmk_host||'')+'\\')">Edit</button></td></tr>';
  });
  document.getElementById('rows').innerHTML=rows.join('')||'<tr><td colspan="8">No checks configured.</td></tr>';
}
async function runNow(file){await fetch('/api/run',{method:'POST',headers:hdrs(),body:JSON.stringify({file})});setTimeout(refresh,1200);}
async function editFlow(file,interval,host){
  const r=await fetch('/api/flow?file='+encodeURIComponent(file));const d=await r.json();
  document.getElementById('etitle').textContent='Edit '+file;
  document.getElementById('efile').value=file;document.getElementById('eint').value=interval;
  document.getElementById('ehost').value=host;document.getElementById('eyaml').value=d.yaml||'';
  document.getElementById('msg').textContent='';document.getElementById('editor').style.display='block';
  window.scrollTo(0,document.body.scrollHeight);
}
function newFlow(){
  document.getElementById('etitle').textContent='New check';
  document.getElementById('efile').value='my-check.yaml';document.getElementById('eint').value='300';
  document.getElementById('ehost').value='';
  document.getElementById('eyaml').value='name: My Synthetic Check\\ntimeout_ms: 20000\\nwarn_ms: 5000\\ncrit_ms: 15000\\nscreenshot_on_failure: true\\nsteps:\\n  - action: open_url\\n    url: https://example.com\\n  - action: check_title\\n    contains: Example\\n';
  document.getElementById('msg').textContent='';document.getElementById('editor').style.display='block';
  window.scrollTo(0,document.body.scrollHeight);
}
async function saveFlow(){
  const body={file:document.getElementById('efile').value,
    yaml:document.getElementById('eyaml').value,
    interval:parseInt(document.getElementById('eint').value,10),
    checkmk_host:document.getElementById('ehost').value};
  const r=await fetch('/api/flow',{method:'POST',headers:hdrs(),body:JSON.stringify(body)});
  const d=await r.json();
  document.getElementById('msg').textContent=r.ok?('Saved ✓\\n'+(d.lint||'')):(d.error+'\\n'+(d.lint||''));
  if(r.ok)setTimeout(refresh,800);
}
// CSRF header needs the raw token (cookie is HttpOnly); the login page
// stores it in sessionStorage. Missing (e.g. new tab) -> re-login.
TOKEN=sessionStorage.getItem('synthmk_tok')||'';
if(!TOKEN){location.href='/login';}
refresh();setInterval(refresh,5000);
</script></body></html>"""


def main() -> int:
    RUN_NOW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"admin-server: dashboard on {BIND}:{PORT} "
          f"(flows {'rw' if os.access(FLOWS_DIR, os.W_OK) else 'ro'})", flush=True)
    ThreadingHTTPServer((BIND, PORT), AdminHandler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
