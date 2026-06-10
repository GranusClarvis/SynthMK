#!/usr/bin/env python3
"""SynthMK Checkmk special agent (multi-node "locations").

Runs ON THE CHECKMK SERVER as a datasource program. Instead of every runner
node being polled as its own Checkmk host (agent over TCP 6556), this special
agent *pulls* flow results from one or more runner-node HTTP endpoints and
emits them as the agent output of a single configured host. That lets several
runners on different network segments — each reachable only from the Checkmk
server, not from each other — feed one site through one host definition.

Data path
---------
Each runner node exposes a read-only JSON results endpoint (admin_server.py
`/api/results`, token-protected). For every flow result the node reports, this
agent re-emits the node's native ``<<<synthmk:sep(0)>>>`` section — the exact
format the bundled check plugin (checkmk/plugin/agent_based/synthmk.py) already
parses — so no new check plugin is needed. A flow that names a ``checkmk_host``
is wrapped in that host's piggyback envelope, exactly as the node's own agent
would do; flows without one land on the special-agent host. Each node also
yields a ``SynthMK Node <name>`` connectivity service so an unreachable runner
is CRIT (visible) rather than silently absent.

CLI
---
    agent_synthmk --node URL[@TOKEN] [--node URL[@TOKEN] ...] [--timeout S]
                  [--insecure] [--config-file PATH|-]

``--config-file`` reads a JSON object ``{"nodes": [{"url", "token", "name",
"tls_verify"}], "timeout": S}`` (``-`` = stdin); this is how the Setup ruleset
hands configuration to the agent. ``--node`` flags are merged on top, so the
agent is also usable by hand for testing.

Exit code is always 0 (a Checkmk datasource program that exits non-zero is
treated as a hard datasource failure and suppresses *all* sections); per-node
errors surface as CRIT connectivity services instead.
"""
from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
import urllib.error
import urllib.request
from collections import OrderedDict
from typing import Any

SECTION_HEADER = "<<<synthmk:sep(0)>>>"
RESULTS_PATH = "/api/results"
DEFAULT_TIMEOUT = 30


def _node_entry(service: str, status: int, summary: str) -> dict[str, Any]:
    """A synthetic <<<synthmk>>> JSON entry the check plugin understands."""
    return {
        "service": service,
        "status": status,
        "duration_ms": 0,
        "warn_ms": None,
        "crit_ms": None,
        "summary": summary,
        "failed_step": None,
        "steps": [],
        "screenshot_url": None,
        "dynamic": False,
    }


def fetch_node(node: dict[str, Any], timeout: int) -> dict[str, Any]:
    """GET <url>/api/results from one runner node. Returns the parsed payload.

    Raises on any transport/parse error so the caller can render a CRIT
    connectivity service for the node.
    """
    url = node["url"].rstrip("/") + RESULTS_PATH
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    token = node.get("token")
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    ctx = None
    if url.lower().startswith("https"):
        ctx = ssl.create_default_context()
        if not node.get("tls_verify", True):
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        raw = resp.read().decode("utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("results endpoint did not return a JSON object")
    return payload


def collect(nodes: list[dict[str, Any]], timeout: int) -> "OrderedDict[str, list[dict]]":
    """Pull every node and bucket result entries by piggyback host.

    Key "" = the special-agent host itself (non-piggyback flows + node health).
    """
    by_host: "OrderedDict[str, list[dict]]" = OrderedDict()
    by_host.setdefault("", [])

    for node in nodes:
        name = node.get("name") or node["url"]
        try:
            payload = fetch_node(node, timeout)
        except urllib.error.HTTPError as exc:
            detail = "auth failed (check token)" if exc.code in (401, 403) else f"HTTP {exc.code}"
            by_host[""].append(_node_entry(f"SynthMK Node {name}", 2, f"unreachable: {detail}"))
            continue
        except (urllib.error.URLError, OSError, socket.timeout) as exc:
            reason = getattr(exc, "reason", exc)
            by_host[""].append(_node_entry(f"SynthMK Node {name}", 2, f"unreachable: {reason}"))
            continue
        except (ValueError, json.JSONDecodeError) as exc:
            by_host[""].append(_node_entry(f"SynthMK Node {name}", 3, f"bad response: {exc}"))
            continue

        results = payload.get("results") or []
        version = payload.get("version", "?")
        reported = payload.get("node") or name
        # Connectivity OK service for the node, on the special-agent host.
        by_host[""].append(_node_entry(
            f"SynthMK Node {name}", 0,
            f"connected to {reported} (v{version}), {len(results)} flow(s)"))

        for item in results:
            if not isinstance(item, dict):
                continue
            entry = item.get("entry")
            if not isinstance(entry, dict) or not entry.get("service"):
                continue
            host = str(item.get("piggyback_host", "") or "")
            by_host.setdefault(host, []).append(entry)

    return by_host


def render(by_host: "OrderedDict[str, list[dict]]") -> str:
    """Serialise the bucketed entries into Checkmk agent output."""
    lines: list[str] = []
    # Special-agent host first (empty key), then each piggyback host.
    for host, entries in by_host.items():
        if not entries:
            continue
        if host:
            lines.append(f"<<<<{host}>>>>")
            lines.append(SECTION_HEADER)
            for entry in entries:
                lines.append(json.dumps(entry, sort_keys=True))
            lines.append("<<<<>>>>")
        else:
            lines.append(SECTION_HEADER)
            for entry in entries:
                lines.append(json.dumps(entry, sort_keys=True))
    return "\n".join(lines) + ("\n" if lines else "")


def parse_nodes(args: argparse.Namespace) -> tuple[list[dict[str, Any]], int]:
    nodes: list[dict[str, Any]] = []
    timeout = args.timeout

    if args.config_file:
        text = sys.stdin.read() if args.config_file == "-" else open(args.config_file).read()
        cfg = json.loads(text)
        timeout = int(cfg.get("timeout", timeout))
        for n in cfg.get("nodes", []):
            nodes.append({
                "url": n["url"],
                "token": n.get("token") or None,
                "name": n.get("name") or None,
                "tls_verify": bool(n.get("tls_verify", not args.insecure)),
            })

    for spec in args.node or []:
        url, _, token = spec.partition("@")
        nodes.append({
            "url": url,
            "token": token or None,
            "name": None,
            "tls_verify": not args.insecure,
        })

    return nodes, timeout


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SynthMK multi-node special agent")
    ap.add_argument("--node", action="append", metavar="URL[@TOKEN]",
                    help="runner-node base URL (repeatable); token after '@'")
    ap.add_argument("--config-file", metavar="PATH",
                    help="JSON config ('-' = stdin) from the Setup ruleset")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                    help=f"per-node HTTP timeout in seconds (default {DEFAULT_TIMEOUT})")
    ap.add_argument("--insecure", action="store_true",
                    help="do not verify TLS certificates on https node URLs")
    args = ap.parse_args(argv)

    nodes, timeout = parse_nodes(args)
    if not nodes:
        sys.stderr.write("agent_synthmk: no nodes configured (use --node or --config-file)\n")
        # Still exit 0 so the datasource isn't marked hard-failed; emit nothing.
        return 0

    sys.stdout.write(render(collect(nodes, timeout)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
