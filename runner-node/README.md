# SynthMK runner node

A single Docker appliance you host **inside the intranet range**. It runs your
browser flows against internal-only sites (sites Checkmk's own server may not be
able to reach), and exposes the results to Checkmk like any monitored host.

```
            intranet (no internet exposure)
   ┌───────────────┐        ┌──────────────────────────────┐
   │  Checkmk      │  6556  │  synthmk-runner (this node)   │
   │  server       │◀───────│   • scheduler runs flows      │──▶ http://intranet-wiki
   │  (Raw/CRE)    │        │   • spool dir → agent output  │──▶ http://intranet-grafana
   └───────────────┘        │   • :9180 serves screenshots  │──▶ http://internal-app
                            └──────────────────────────────┘
```

## What's inside

| Component | File | Role |
|---|---|---|
| Agent transport | `agent_output.sh` + socat | Answers Checkmk polls on `6556`; emits `<<<check_mk>>>` + fresh spool sections. |
| Scheduler | `synthmk-scheduler.sh` | Runs each flow on its own interval → Checkmk **spool dir** (slow checks never block fast ones). Prunes old screenshots. |
| Screenshot server | `python -m http.server` | Serves `screenshots/` on `9180` so failing services can link the PNG. |
| Schedule | `flows.conf` | `flow_file interval_s [checkmk_host]` per line — the scaling surface. |

## Run it

```bash
# build (context = repo root)
docker build -f runner-node/Dockerfile -t synthmk-runner:0.2.0 .

docker run -d --name synthmk-runner \
  -p 6556:6556 -p 9180:9180 \
  -v "$PWD/flows:/opt/synthmk/flows:ro" \
  -v "$PWD/runner-node/flows.conf:/opt/synthmk/runner-node/flows.conf:ro" \
  -e SYNTHMK_SHOT_BASE_URL="http://<this-node-lan-ip>:9180" \
  synthmk-runner:0.2.0
```

Then in Checkmk: add a host with the node's IP, monitored via **Checkmk agent
(TCP, port 6556)**, and run service discovery. Each flow becomes a service; a
flow with a `checkmk_host` lands under that target host (see piggyback below).

## Scaling

Add a flow file under `flows/` and a line to `flows.conf`. The scheduler runs
each flow independently on its interval and publishes atomically to the spool
dir, so adding long or numerous checks never delays collection. `maxage` is set
to `interval × 3`: if a flow stops producing, Checkmk marks the service stale
rather than showing a stale-but-green result.

## Piggyback (one node, many target hosts)

Set `checkmk_host:` in a flow (or the 3rd column in `flows.conf`) and the result
is wrapped in a Checkmk piggyback envelope, so the **monitored site appears as
its own Checkmk host** carrying the synthetic service — instead of every check
hanging off the runner node. Create those target hosts in Checkmk (IP can be a
dummy / no direct checks) to receive the piggyback data.

## Screenshots

On a failing step (with `screenshot_on_failure: true`) the runner saves a PNG to
`screenshots/` and the service line links it via `SYNTHMK_SHOT_BASE_URL`. The
link only renders if **Setup → … → "Escape HTML codes in service output"** is
**Off** for the runner host. Scope that rule to this host only — disabling HTML
escaping broadly is an XSS surface (Werk #6058). SynthMK output is always a
single sanitized line containing only the link it generated.

## Production hardening: the real Checkmk agent

The bundled socat transport is dependency-free and version-agnostic, ideal for
the LAN lab and most home setups. For TLS-encrypted, registered agent comms,
install the **version-matched** official Checkmk agent in the image and register
the controller instead:

```bash
# inside the image / a derived image, with the agent .deb from YOUR site:
dpkg -i check-mk-agent_<ver>.deb
cmk-agent-ctl register --server <cmk-host> --site <site> \
    --user automation --password <secret> --hostname synthmk-runner
```

Keep the scheduler + spool dir exactly as-is; the official agent reads the same
spool directory, so only the transport changes.
