#!/usr/bin/env python3
"""HTTP contract tests for the node management dashboard (admin_server.py).

Boots the real server on a loopback port with temp state and exercises the
full management surface browser-free: auth + roles, flow save with lint gate,
version history + rollback, pause/resume, run-now, and the audit trail.
(The builder endpoints need Playwright and are covered by the lab e2e.)

Run:  python3 runner-node/test_admin_contract.py   (exit 0 = all passed)
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

ADMIN_TOK = "test-admin-token"
VIEWER_TOK = "test-viewer-token"

PASS = 0
FAILS = []


def check(label, cond):
    global PASS
    if cond:
        PASS += 1
        print(f"  ok   - {label}")
    else:
        FAILS.append(label)
        print(f"  FAIL - {label}")


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def req(port, path, method="GET", body=None, token=None, csrf=False):
    """Return (status, parsed json or text)."""
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    if csrf:
        r.add_header("X-SynthMK-Token", token or "")
    if data is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            raw = resp.read().decode()
            code = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        code = e.code
    try:
        return code, json.loads(raw)
    except json.JSONDecodeError:
        return code, raw


FLOW_V1 = "name: T1\nsteps:\n  - action: open_url\n    url: https://one\n"
FLOW_V2 = "name: T2\nsteps:\n  - action: open_url\n    url: https://two\n"


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        flows = tdp / "flows"
        flows.mkdir()
        conf = tdp / "flows.conf"
        conf.write_text("")
        (tdp / "spool").mkdir()
        port = free_port()
        env = dict(os.environ,
                   SYNTHMK_HOME=str(ROOT),
                   SYNTHMK_FLOWS=str(flows),
                   SYNTHMK_FLOWS_CONF=str(conf),
                   SYNTHMK_SPOOL=str(tdp / "spool"),
                   SYNTHMK_RUN_NOW_DIR=str(tdp / "run-now"),
                   SYNTHMK_ADMIN_PORT=str(port),
                   SYNTHMK_ADMIN_BIND="127.0.0.1",
                   SYNTHMK_ADMIN_TOKEN=ADMIN_TOK,
                   SYNTHMK_VIEWER_TOKEN=VIEWER_TOK,
                   SYNTHMK_AUDIT_LOG=str(tdp / "audit.log"),
                   SYNTHMK_ADMIN_TOKEN_FILE=str(tdp / "token"))
        proc = subprocess.Popen([sys.executable, str(HERE / "admin_server.py")],
                                env=env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                try:
                    socket.create_connection(("127.0.0.1", port), 0.2).close()
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                check("server came up", False)
                return 1

            print("== auth & roles ==")
            code, _ = req(port, "/api/state")
            check("unauthenticated state is 401", code == 401)
            code, _ = req(port, "/api/login?token=wrong")
            check("bad login is 403", code == 403)
            code, d = req(port, "/api/state", token=ADMIN_TOK)
            check("admin state ok with role", code == 200 and d.get("role") == "admin")
            code, d = req(port, "/api/state", token=VIEWER_TOK)
            check("viewer state ok with role", code == 200 and d.get("role") == "viewer")
            code, _ = req(port, "/api/run", "POST", {"file": "x.yaml"},
                          token=VIEWER_TOK, csrf=True)
            check("viewer cannot POST (read-only role)", code == 401)
            code, _ = req(port, "/api/run", "POST", {"file": "x.yaml"},
                          token=ADMIN_TOK)
            check("admin POST without CSRF header refused", code == 401)

            print("== flow save, lint gate, history, rollback ==")
            code, d = req(port, "/api/flow", "POST",
                          {"file": "t.yaml", "yaml": FLOW_V1, "interval": 120,
                           "checkmk_host": "app-host", "tags": "payments,critical"},
                          token=ADMIN_TOK, csrf=True)
            check("valid flow saves", code == 200 and d.get("ok"))
            check("flow file written", (flows / "t.yaml").read_text() == FLOW_V1)
            line = conf.read_text().strip()
            check("conf line carries host and tags",
                  line == "t.yaml 120 app-host tags=payments,critical")

            code, d = req(port, "/api/flow", "POST",
                          {"file": "t.yaml", "yaml": "steps: []\n"},
                          token=ADMIN_TOK, csrf=True)
            check("invalid flow rejected by lint gate (422)", code == 422)
            check("rejected save did not touch the file",
                  (flows / "t.yaml").read_text() == FLOW_V1)

            time.sleep(1.1)  # distinct history timestamps
            code, d = req(port, "/api/flow", "POST",
                          {"file": "t.yaml", "yaml": FLOW_V2, "interval": 120,
                           "checkmk_host": "app-host", "tags": ["payments"]},
                          token=ADMIN_TOK, csrf=True)
            check("second save ok", code == 200)
            code, d = req(port, "/api/flow/history?file=t.yaml", token=VIEWER_TOK)
            check("history lists the prior version",
                  code == 200 and len(d.get("versions", [])) == 1)
            ts = d["versions"][0]["ts"]
            code, d = req(port, f"/api/flow/version?file=t.yaml&ts={ts}",
                          token=VIEWER_TOK)
            check("stored version is the v1 content", d.get("yaml") == FLOW_V1)
            code, d = req(port, "/api/flow/rollback", "POST",
                          {"file": "t.yaml", "ts": str(ts)},
                          token=ADMIN_TOK, csrf=True)
            check("rollback succeeds", code == 200 and d.get("ok"))
            check("rollback restored v1", (flows / "t.yaml").read_text() == FLOW_V1)
            code, d = req(port, "/api/flow/history?file=t.yaml", token=ADMIN_TOK)
            check("rollback snapshotted v2 too",
                  code == 200 and len(d.get("versions", [])) == 2)

            print("== pause / resume ==")
            code, d = req(port, "/api/pause", "POST",
                          {"file": "t.yaml", "paused": True},
                          token=ADMIN_TOK, csrf=True)
            check("pause ok", code == 200 and d.get("paused") is True)
            check("conf line gains #PAUSED with schedule intact",
                  conf.read_text().strip()
                  == "#PAUSED t.yaml 120 app-host tags=payments")
            code, d = req(port, "/api/state", token=ADMIN_TOK)
            flow = d["flows"][0]
            check("state reports paused + tags",
                  flow["paused"] is True and flow["tags"] == ["payments"])
            code, d = req(port, "/api/pause", "POST",
                          {"file": "t.yaml", "paused": False},
                          token=ADMIN_TOK, csrf=True)
            check("resume restores the active line",
                  conf.read_text().strip() == "t.yaml 120 app-host tags=payments")
            code, _ = req(port, "/api/pause", "POST",
                          {"file": "ghost.yaml", "paused": True},
                          token=ADMIN_TOK, csrf=True)
            check("pausing an unscheduled flow is 404", code == 404)

            print("== run-now + audit trail ==")
            code, d = req(port, "/api/run", "POST", {"file": "t.yaml"},
                          token=ADMIN_TOK, csrf=True)
            check("run-now queues a trigger", code == 200
                  and (tdp / "run-now" / "t.yaml").is_file())
            code, d = req(port, "/api/audit", token=ADMIN_TOK)
            actions = [e["action"] for e in d.get("entries", [])]
            check("audit captured the session's actions",
                  {"flow_save", "flow_rollback", "pause", "resume",
                   "run_now"}.issubset(set(actions)))
            failed_login = [e for e in d["entries"]
                            if e["action"] == "login" and not e["ok"]]
            check("audit captured the failed login", len(failed_login) >= 1)
            code, _ = req(port, "/api/audit", token=VIEWER_TOK)
            check("audit is admin-only", code == 403)
        finally:
            proc.kill()
            proc.wait(timeout=5)

    print(f"\n{PASS} checks passed, {len(FAILS)} failed.")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
