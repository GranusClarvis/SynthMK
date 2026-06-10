#!/usr/bin/env python3
"""Contract test for the SynthMK multi-node special agent.

Spins up two in-process HTTP servers that mimic runner-node /api/results
endpoints (different "network segments"), runs agent_synthmk against both, and
asserts that BOTH nodes report through the one special-agent host — the task's
acceptance criterion. Also feeds the agent's output through the real check
plugin's parse_synthmk to prove the wire format is exactly what Checkmk parses.

Run:  python3 checkmk/special/test_agent_synthmk.py   (exit 0 = all passed)
Browser-free, stdlib only — safe for CI.
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import agent_synthmk as A  # noqa: E402

# The real check plugin parser, to prove the emitted section is consumable.
PLUGIN = HERE.parent / "plugin" / "agent_based" / "synthmk.py"


def _entry(service, status=0, **kw):
    e = {
        "service": service, "status": status, "duration_ms": 1234,
        "warn_ms": 5000, "crit_ms": 15000, "summary": f"{service} ok",
        "failed_step": None, "steps": [], "screenshot_url": None,
        "dynamic": False,
    }
    e.update(kw)
    return e


def make_node_server(payload: dict, token: str | None):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silence
            pass

        def do_GET(self):
            if not self.path.startswith("/api/results"):
                self.send_response(404)
                self.end_headers()
                return
            if token is not None:
                got = self.headers.get("Authorization", "")
                if got != f"Bearer {token}":
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b'{"error":"auth"}')
                    return
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def load_parse_synthmk():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_synthmk_plugin_stub", PLUGIN)
    # The plugin imports cmk.agent_based.v2 (absent off-server). Stub it so we
    # can exercise the pure parse_function without a Checkmk install.
    if "cmk.agent_based.v2" not in sys.modules:
        import types

        class _Stub:  # permissive: callable, indexable, attr-able
            def __init__(self, *a, **k):
                pass

            def __call__(self, *a, **k):
                return self

            def __getattr__(self, _):
                return _Stub()

        fake = types.ModuleType("cmk.agent_based.v2")
        for n in ("AgentSection", "CheckPlugin", "CheckResult", "DiscoveryResult",
                  "Metric", "Result", "Service", "State", "check_levels", "render"):
            setattr(fake, n, _Stub())
        sys.modules.setdefault("cmk", types.ModuleType("cmk"))
        sys.modules.setdefault("cmk.agent_based", types.ModuleType("cmk.agent_based"))
        sys.modules["cmk.agent_based.v2"] = fake
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.parse_synthmk


def main() -> int:
    # Node A (segment 1): one direct flow + one piggyback flow, token-protected.
    node_a = {
        "version": "0.4.0", "node": "runner-a", "results": [
            {"piggyback_host": "", "entry": _entry("Wiki Login")},
            {"piggyback_host": "intranet-grafana", "entry": _entry("Grafana Home", status=1)},
        ],
    }
    # Node B (segment 2): one piggyback flow, no token.
    node_b = {
        "version": "0.4.0", "node": "runner-b", "results": [
            {"piggyback_host": "internal-app", "entry": _entry("App Smoke", status=2)},
        ],
    }

    srv_a, url_a = make_node_server(node_a, token="secret-a")
    srv_b, url_b = make_node_server(node_b, token=None)
    try:
        nodes = [
            {"url": url_a, "token": "secret-a", "name": "alpha", "tls_verify": True},
            {"url": url_b, "token": None, "name": "beta", "tls_verify": True},
        ]
        out = A.render(A.collect(nodes, timeout=5))
    finally:
        srv_a.shutdown()
        srv_b.shutdown()

    print("---- agent output ----")
    print(out)
    print("----------------------")

    # 1. Both nodes' connectivity services land on the special-agent host.
    assert '"SynthMK Node alpha"' in out, "node alpha health missing"
    assert '"SynthMK Node beta"' in out, "node beta health missing"
    assert "connected to runner-a" in out and "connected to runner-b" in out

    # 2. Piggyback envelopes route flows to their target hosts.
    assert "<<<<intranet-grafana>>>>" in out, "grafana piggyback missing"
    assert "<<<<internal-app>>>>" in out, "app piggyback missing"
    assert "<<<<>>>>" in out, "piggyback envelope not closed"

    # 3. The non-piggyback flow + node health sit under the special-agent host
    #    (a bare section with no <<<<host>>>> envelope before it).
    first = out.split("\n", 1)[0]
    assert first == A.SECTION_HEADER, f"expected bare section first, got {first!r}"

    # 4. The emitted sections parse with the REAL check plugin parser.
    parse_synthmk = load_parse_synthmk()
    services = set()
    for block in out.split("<<<synthmk:sep(0)>>>"):
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("{"):
                parsed = parse_synthmk([[line]])
                services.update(parsed.keys())
    for expected in ("Wiki Login", "Grafana Home", "App Smoke",
                     "SynthMK Node alpha", "SynthMK Node beta"):
        assert expected in services, f"plugin did not parse service {expected!r}"

    # 5. An unreachable node becomes a CRIT connectivity service (not silence).
    bad = A.render(A.collect(
        [{"url": "http://127.0.0.1:1", "token": None, "name": "down", "tls_verify": True}],
        timeout=2))
    assert '"SynthMK Node down"' in bad and '"status": 2' in bad, \
        "unreachable node not reported CRIT"

    # 6. Wrong token => the node is CRIT auth-failed, not a crash.
    srv_c, url_c = make_node_server(node_a, token="right")
    try:
        bad_auth = A.render(A.collect(
            [{"url": url_c, "token": "wrong", "name": "authfail", "tls_verify": True}],
            timeout=5))
    finally:
        srv_c.shutdown()
    assert "auth failed" in bad_auth, "bad token not surfaced as auth failure"

    print("ALL PASSED: two runner nodes report through one special-agent host.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
