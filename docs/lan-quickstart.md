# SynthMK LAN quick start (full end-to-end)

Stand up **Checkmk Raw (free)**, the **SynthMK runner node**, and an
**internal-only demo site** on one machine, then watch a synthetic check go
green → red with a failure screenshot — exactly the loop you'll run in your LAN.

Everything is in [`lab/docker-compose.yml`](../lab/docker-compose.yml). You need
Docker + the compose plugin.

## 1. Bring up the stack

```bash
cd lab
docker compose up -d --build      # builds the runner image, pulls Checkmk + nginx
```

- Checkmk UI: <http://localhost:8080/cmk/>
- Screenshot server: `http://localhost:9180/<file>.png?t=<token>` — served by
  the runner node with **per-file token auth** (links in Checkmk carry their
  token automatically; bare URLs get 403, there is no directory listing).
- `intranet-demo` has **no published ports** — only the runner can reach it,
  which is the point: it stands in for an internal-only site.
- Login credentials for the demo's login journey come from
  [`lab/secrets.yaml`](../lab/secrets.yaml) (lab-only values), mounted into the
  node and referenced by the flow as `{{ secret.portal_user }}` /
  `{{ secret.portal_password }}` — the production secret path, demonstrated.

Get the admin password (set to `synthmk-lab-admin` by the compose env, but verify):

```bash
docker compose logs checkmk | grep -i password   # cmkadmin / synthmk-lab-admin
```

Log in as `cmkadmin`.

## 2. Add the runner node as a host

In the Checkmk UI: **Setup → Hosts → Add host**

- **Hostname:** `synthmk-runner`
- **IPv4 address:** `synthmk-runner` (compose DNS resolves it on the lab network)
- **Monitoring agents → Checkmk agent:** *API integrations if configured, else
  Checkmk agent* (the default; it connects to TCP `6556`, which the node answers).

Save → **Save & run service discovery**. You'll see the synthetic services:

- `Synthetic Intranet Home` — a **flat** service on the runner node.
- `SynthMK Scheduler` — the node's self-monitoring service (WARNs if the node
  is oversubscribed and flows go overdue).

Every configured flow is discoverable immediately — the node publishes a
"warming up" placeholder under each flow's real service name at startup.

Then **Setup → Hosts → Add host** again for the piggyback target:

- **Hostname:** `intranet-demo`  (must match the flow's `checkmk_host`)
- **IPv4 address:** `intranet-demo`
- **Checkmk agent:** *No API integrations, no Checkmk agent* (it receives only
  piggyback data from the runner — it isn't polled directly).

Run discovery on `intranet-demo` → `Synthetic Account Overview` **and**
`Synthetic Portal Login` (the 10-step login journey with secrets) appear
**under their own host**. One runner, results attributed per target site.

> First poll can take a minute. **Activate changes** after adding hosts, and use
> the host's *Service discovery* page to accept the new services.

## 3. Enable the screenshot link (one rule)

Checkmk escapes HTML by default, so the screenshot link shows as text until you
allow it — **scoped to the runner host only**:

**Setup → Service monitoring rules → "Escape HTML codes in service output"** →
*Add rule* → set to **Do not escape**, condition **Host = synthmk-runner**
(and `intranet-demo` if you want links on the piggyback service). Activate changes.

> Escaping-off is an XSS surface (Werk #6058); keep this rule scoped to the
> SynthMK hosts. SynthMK only ever emits a single sanitized line containing the
> link it generated.

## 4. Break it → watch CRIT + screenshot

Edit the demo site (served live from the mount):

```bash
# remove the asserted text
sed -i 's/Account Overview/Account Overhauled/' intranet-demo/html/index.html
```

Within ~30 s (the lab interval) the `Synthetic Account Overview` service on
`intranet-demo` goes **CRIT** — `Expected text 'Account Overview' not found` — and
its **Details** show a clickable **screenshot** link opening the captured PNG
from `http://localhost:9180/...`.

Restore it:

```bash
sed -i 's/Account Overhauled/Account Overview/' intranet-demo/html/index.html
```

## 5. Prove the internal-only path (optional)

```bash
curl -sS http://localhost:8080/cmk/ -o /dev/null && echo "Checkmk reachable"
curl -sS --max-time 3 http://localhost:INTRANET 2>&1 || echo "intranet-demo NOT reachable from host (correct)"
# but the runner can reach it:
docker compose exec synthmk-runner python3 -c "import urllib.request as u; print(u.urlopen('http://intranet-demo/').status)"
```

The site is reachable **only** from inside the lab network — same as a real
intranet app the Checkmk server might not reach but the runner node can.

## 6. Add your own checks (scaling)

1. Drop a flow YAML into `lab/flows/` (see [`flow-schema.md`](flow-schema.md)).
2. Add a line to `lab/flows.conf`: `my-flow.yaml  300  [checkmk_host]`.
3. `docker compose restart synthmk-runner` → discover the new service.

Each flow runs on its own interval; slow checks never block fast ones — the
worker pool, capacity formula, and a measured 60-flow run are in
[`scaling.md`](scaling.md). For production (TLS agent transport, resource
limits, secrets): [`../runner-node/README.md`](../runner-node/README.md) and
[`../runner-node/compose.yaml`](../runner-node/compose.yaml).

## Tear down

```bash
docker compose down -v        # -v also removes the Checkmk data volume
```
