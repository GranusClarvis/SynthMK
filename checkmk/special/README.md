# SynthMK multi-node special agent

Pull synthetic-flow results from **several runner nodes on different network
segments** into **one** Checkmk host. Where the per-node agent transport (TCP
6556) needs the Checkmk server to reach each runner as its own host, the
special agent inverts that: it runs on the Checkmk server and *pulls* each
node's HTTP results endpoint, so nodes that can't see each other — and need not
be reachable as agents — share a single host definition ("locations").

```
                         Checkmk server
                   ┌───────────────────────────┐
   segment A  ◀────│  agent_synthmk (datasource)│────▶ GET nodeA/api/results
   runner-a        │   one configured host      │
   segment B  ◀────│   piggyback → target hosts │────▶ GET nodeB/api/results
   runner-b        └───────────────────────────┘
```

## Pieces

| File | Role |
|---|---|
| `agent_synthmk.py` | The datasource program. Pulls each node, re-emits its native `<<<synthmk:sep(0)>>>` sections, piggybacking flows to their target hosts. Install as `agents/special/agent_synthmk` in the site. |
| `../plugin/rulesets/special_agent_synthmk.py` | Setup GUI: the node list (URL + read token + name). |
| `../plugin/server_side_calls/synthmk.py` | Translates that rule into the agent command line. |
| node side: `runner-node/admin_server.py` `/api/results` | Read-only JSON feed each node exposes. Auth: `SYNTHMK_RESULTS_TOKEN` (scoped) or the admin token. |

The bundled check plugin (`../plugin/agent_based/synthmk.py`) is **unchanged** —
the special agent emits exactly the section it already parses, so every flow
becomes the same first-class service whether the node is polled directly or
pulled here.

## On each runner node

Expose the results endpoint (the admin server already serves it):

```bash
# scoped read-only token for the Checkmk server (recommended)
export SYNTHMK_RESULTS_TOKEN="$(openssl rand -hex 24)"
# admin_server.py is already started by the appliance entrypoint on :9181
curl -s -H "Authorization: Bearer $SYNTHMK_RESULTS_TOKEN" \
     http://NODE:9181/api/results | jq .
```

## On the Checkmk server

Manual test of the agent:

```bash
agents/special/agent_synthmk \
  --node http://10.20.0.5:9181@TOKEN_A \
  --node http://10.30.0.9:9181@TOKEN_B \
  --timeout 30
```

Then in Setup → add a host (no IP / no agent needed), and apply the rule
**"SynthMK runner nodes (multi-node locations)"** to it, listing both nodes.
Run service discovery: each node yields a `SynthMK Node <name>` connectivity
service plus every flow it reports. Flows with a `checkmk_host` land on that
target host via piggyback; the rest land on this host.

## Failure behavior

- An **unreachable** node → `SynthMK Node <name>` goes **CRIT** ("unreachable:
  …"), never silently disappears.
- A **bad/missing token** → CRIT ("unreachable: auth failed (check token)").
- The agent **always exits 0** so one dead node can't suppress the others'
  sections (a non-zero datasource program blanks the whole host).

## Test

```bash
python3 checkmk/special/test_agent_synthmk.py   # browser-free, stdlib only
```

Two in-process fake nodes verify the acceptance criterion (two runners → one
host), piggyback routing, the CRIT-on-unreachable path, and that the output
parses with the real check plugin's `parse_synthmk`.
