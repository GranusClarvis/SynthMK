# SynthMK runner node

A single Docker appliance you host **inside the intranet range**. It runs your
browser flows against internal-only sites (sites Checkmk's own server may not be
able to reach), and exposes the results to Checkmk like any monitored host.

```
            intranet (no internet exposure)
   ┌───────────────┐        ┌──────────────────────────────┐
   │  Checkmk      │  6556  │  synthmk-runner (this node)   │
   │  server       │◀───────│   • scheduler runs flows      │──▶ http://intranet-wiki
   │  (Raw/CRE)    │  (TLS  │   • spool dir → agent output  │──▶ http://intranet-grafana
   └───────────────┘  opt.) │   • :9180 screenshots (auth)  │──▶ http://internal-app
                            └──────────────────────────────┘
```

## What's inside

| Component | File | Role |
|---|---|---|
| Agent transport | socat + `agent_output.sh` (lab) **or** official Checkmk agent over TLS (production, see below) | Answers Checkmk polls on `6556` with `<<<check_mk>>>` + fresh spool sections. |
| Scheduler | `scheduler.py` | Worker-pool scheduler (`SYNTHMK_MAX_CONCURRENCY`, default 4): per-flow intervals → Checkmk **spool dir**, startup stagger, overlap suppression, hard run timeout, warmup lines, screenshot pruning, and a **`SynthMK Scheduler` self-monitoring service** that WARNs when the node is oversubscribed. See [`../docs/scaling.md`](../docs/scaling.md). |
| Screenshot server | `shot_server.py` | Serves failure PNGs on `9180` with **per-file HMAC token URLs** (node-local key, auto-created 0600). No directory listing, no traversal, `/healthz` for container healthchecks. `SYNTHMK_SHOT_AUTH=off` only if you really want the old open behavior. |
| Schedule | `flows.conf` | `flow_file interval_s [checkmk_host]` per line — the scaling surface. Hot-reloaded on change. |
| Secrets | mounted file → `$SYNTHMK_SECRETS_FILE` | YAML mapping for `{{ secret.* }}` refs; chmod 600 on the host; the entrypoint stages a runner-owned copy so bind-mount ownership doesn't matter. Values are redacted from all output. |
| TLS upgrade | `register_agent.sh` | One command: downloads YOUR site's version-matched agent, installs it, registers `cmk-agent-ctl` (TLS). Then run with `SYNTHMK_AGENT_MODE=official`. |

Privilege model: the container may start as root (volume chown + official agent
daemon), but the **scheduler, browsers, and HTTP servers all run as the
unprivileged `pwuser`** — a compromised page never executes as root. Chromium
still runs `--no-sandbox` inside the container (standard for Chromium-in-Docker);
treat flow targets as trusted.

## Run it (production template)

Use [`compose.yaml`](compose.yaml) — it carries the hardened defaults (resource
limits sized to the concurrency, `no-new-privileges`, healthcheck, named
volumes):

```bash
cp runner-node/compose.yaml /srv/synthmk/compose.yaml   # edit the EDIT: lines
docker compose up -d
```

Or raw `docker run`:

```bash
docker build -f runner-node/Dockerfile -t synthmk-runner:$(cat VERSION) .
docker run -d --name synthmk-runner \
  -p 6556:6556 -p 9180:9180 \
  --memory 6g --cpus 4 --shm-size 1g --security-opt no-new-privileges \
  -v "$PWD/flows:/opt/synthmk/flows:ro" \
  -v "$PWD/runner-node/flows.conf:/opt/synthmk/runner-node/flows.conf:ro" \
  -v "$PWD/secrets.yaml:/run/synthmk/secrets.yaml:ro" \
  -e SYNTHMK_SECRETS_FILE=/run/synthmk/secrets.yaml \
  -e SYNTHMK_SHOT_BASE_URL="http://<this-node-lan-ip>:9180" \
  synthmk-runner:$(cat VERSION)
```

Then in Checkmk: add a host with the node's IP, monitored via **Checkmk agent
(TCP, port 6556)**, and run service discovery. Every configured flow is
discoverable immediately (warmup lines carry the real service names); each flow
becomes a service, plus the `SynthMK Scheduler` health service. A flow with a
`checkmk_host` lands under that target host (piggyback, below).

## Production transport: official agent over TLS

The socat transport is plaintext and unauthenticated — fine on a trusted lab
segment with `6556` firewalled to the Checkmk server, not fine beyond that.
Upgrade to the official, version-matched Checkmk agent + TLS controller
(verified against Checkmk Raw 2.3):

```bash
# 1. one-time registration (host must already exist in Checkmk):
docker exec -e CMK_PASSWORD=... synthmk-runner \
  bash /opt/synthmk/runner-node/register_agent.sh \
  --server cmk.example.lan:8000 --site mysite --user automation --host synthmk-runner

# 2. restart with the official transport (keep a volume on /var/lib/cmk-agent):
#    SYNTHMK_AGENT_MODE=official   (see compose.yaml)
```

The official agent serves the same spool dir natively, so scheduler output is
unchanged — only the transport hardens. (In containers the entrypoint provides
the agent socket via socat, replacing systemd socket activation.)

## Scaling

Add a flow file under `flows/` and a line to `flows.conf` (hot-reloaded).
`maxage` = `interval × 3`: if a flow stops producing, Checkmk marks the service
stale rather than showing stale-but-green. Capacity formula, knobs, and measured
60-flow results: [`../docs/scaling.md`](../docs/scaling.md).

## Piggyback (one node, many target hosts)

Set `checkmk_host:` in a flow (or the 3rd column in `flows.conf`) and the result
is wrapped in a Checkmk piggyback envelope, so the **monitored site appears as
its own Checkmk host** carrying the synthetic service — instead of every check
hanging off the runner node. Create those target hosts in Checkmk (no-IP /
no-agent is fine) to receive the piggyback data.

## Screenshots

On a failing step (with `screenshot_on_failure: true`) the runner saves a PNG
and the service line links it via `SYNTHMK_SHOT_BASE_URL`, including the
per-file access token. The link only renders if **"Escape HTML codes in service
output"** is **Off** for the runner host — scope that rule to this host only
(escaping-off is an XSS surface, Werk #6058; SynthMK output is always a single
sanitized line). **Credential flows:** screenshots taken after a
`sensitive: true` fill blank all form fields before capture; values from the
secrets file are additionally redacted from service output.

## Security summary

v0.3.0 closes the v0.2 must-fix set: authenticated screenshots, TLS agent path,
non-root browser execution, permission-checked secret store with output
redaction, resource limits in the shipped compose. Remaining residual risks and
operator duties: [`../docs/STATUS.md`](../docs/STATUS.md) §5.
