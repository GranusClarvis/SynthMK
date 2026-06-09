# SynthMK — Status, Test Evidence, Open Work & Security

**As of:** 2026-06-09 · **Version:** 0.2.0 · **Branch/commit:** `main` @ `bf344b5`
**Repo:** `git@github.com:GranusClarvis/SynthMK.git` (standalone)

This is the living "where things stand" doc. Roadmap tags below mirror the Clarvis
evolution queue (`PROJECT:SYNTHMK`) and the repo `TASKS.md`.

---

## 1. What SynthMK is

Readable YAML browser flow → Playwright runner → native Checkmk **local-check**
service. Lightweight, Raw/CRE-friendly alternative to Checkmk's enterprise
Synthetic Monitoring (Robotmk / Robot Framework). One **runner node** hosted
inside the intranet runs many flows against internal-only sites and reports to
Checkmk; Checkmk is the UI, scheduler-of-record, and alerting engine.

---

## 2. What was done in v0.2.0

- **Runner-node Docker appliance** (`runner-node/`): scheduler runs each flow on
  its own interval into the Checkmk **spool dir** (slow browser runs never block
  agent polls — the scaling mechanism), socat **agent transport** on `6556`,
  **screenshot HTTP server** on `9180`. Config via `flows.conf`
  (`flow_file interval_s [checkmk_host]`).
- **Piggyback** (`checkmk/piggyback_wrap.sh`, flow `checkmk_host:`): one runner →
  each monitored site appears as its **own Checkmk host**. Default = flat service
  on the runner.
- **Clickable failure screenshots**: `runner.py --screenshot-base-url` /
  `$SYNTHMK_SHOT_BASE_URL` → `<a href>` link to the node-served PNG.
- **Dynamic Checkmk state**: `state_mode: dynamic` / `--p-state` emits `P` and
  lets Checkmk threshold `duration`; failures stay an explicit digit.
- **Real, installable MKP** (`packaging/make_real_mkp.sh`, `make real-mkp`):
  genuine `info`+`info.json`+`agents.tar` via a running site's own `mkp` tool.
  `build_mkp.sh` remains the deterministic skeleton for CI checksums.
- **Self-hosted LAN lab** (`lab/`): Checkmk Raw + runner + internal-only nginx
  demo. Docs: `docs/lan-quickstart.md`, `docs/architecture.md`.
- **Positioning + hygiene**: README "vs Robotmk" section; recorder wording fixed;
  flow linter validates `state_mode`/`checkmk_host`; CI lints `lab/flows/`;
  `make` gains `real-mkp` / `runner-image` / `lab-up` / `lab-down`; VERSION 0.2.0.

---

## 3. What was tested (and the result)

Verified against **Checkmk Raw 2.3.0p48** (`cmk-mkp-tool 0.2.0`) in Docker:

| Test | Result |
|---|---|
| `make ci` (browser/Docker-free contract) | ✅ green — 27 contract checks, 6 flows lint clean, all 11 shell scripts shellcheck-clean, deterministic skeleton rebuild, secret scan, version consistency |
| Real Chromium runs a flow against the **internal-only** demo site | ✅ OK with real durations (~230–290 ms) |
| Service discovery in Checkmk | ✅ `Synthetic Intranet Home` (flat) + `Synthetic Account Overview` (piggyback) discovered |
| **Live OK** in Checkmk (both flat + piggyback host) | ✅ `state=0` via REST/livestatus |
| **Live CRIT** propagation (flat host) | ✅ `state=2`, message `Expected text … not found`, screenshot link in plugin output |
| CRIT + screenshot at runner/spool level (piggyback) | ✅ piggyback-wrapped CRIT section + PNG written |
| Screenshot served over HTTP | ✅ `GET /<file>.png → HTTP 200`, ~18 KB |
| Internal-only path | ✅ demo site reachable only from the runner (no published host port) |
| Real `.mkp` build + install | ✅ `make real-mkp` builds + installs on the site (11 files, "Enabled (active)"); idempotent across runs |

### Not yet tested / assumptions
- **Only Checkmk Raw 2.3** (and only the plaintext socat transport). Not tested on
  2.2 or against the TLS agent controller, CEE/bakery, or distributed sites.
- **Only Chromium.** Firefox/Edge untested.
- **`P`/dynamic state** unit-tested at the line level; not yet observed end-to-end
  driving WARN/CRIT inside Checkmk from duration alone.
- **Scale** is by design (spool dir, independent intervals) but not load-tested
  with dozens of concurrent long flows; no resource limits set (see security #6).
- Real-MKP build is **not byte-deterministic** (Checkmk's packer embeds
  timestamps) — expected; that's why `build_mkp.sh` stays the deterministic one.

---

## 4. Open work (mirrors queue `PROJECT:SYNTHMK`)

| Pri | Tag | Summary |
|---|---|---|
| P1 | `SYNTHMK_AGENT_TLS_REGISTRATION` | Bake version-matched official Checkmk agent + `cmk-agent-ctl` (TLS, registered) as the production transport; keep socat as lab fallback. |
| P1 | `SYNTHMK_SECRET_SOURCE` | File/vault-backed secret source for `{{ }}` so login creds aren't plain env (see security #2). |
| P2 | `SYNTHMK_FIRST_RUN_WARMUP` | First run emits UNKNOWN fallback name → bad early discovery; emit a discoverable "warming up" line under the intended service name. |
| P2 | `SYNTHMK_MULTINODE_SPECIAL_AGENT` | Multi-node "locations": a Checkmk special agent pulling results from several runner-node HTTP endpoints. |
| P2 | `SYNTHMK_REAL_MKP_CI` | Docker-gated CI job that builds + installs the real `.mkp` against an ephemeral Checkmk container. |
| P3 | `SYNTHMK_BROWSER_AND_STEPS_EXPANSION` | Firefox/Edge + new step types (select, network-idle, screenshot-always, visual diff). |

Other backlog (not yet ticketed): healthcheck for the appliance; per-flow
concurrency cap; structured per-step result drill-down; recorder selector-repair.

---

## 5. Security considerations

SynthMK is built for **trusted internal monitoring**, and several defaults trade
hardening for home-lab simplicity. The items below are the ones to fix before any
exposure beyond a trusted LAN segment.

| # | Severity | Issue | Mitigation / status |
|---|---|---|---|
| 1 | **High** | **Screenshots can capture secrets/PII.** A login flow that fails *after* filling credentials screenshots a page whose DOM may contain the typed password / session data / sensitive content. | Disable `screenshot_on_failure` for credential flows, or capture before sensitive input. **Open** — no redaction yet. |
| 2 | **High** | **Screenshot server is unauthenticated + open.** `python -m http.server` on `9180` serves the whole `screenshots/` dir with directory listing; anyone who can reach the node reads every screenshot (see #1). No TLS, no auth. | Bind to localhost + reverse-proxy with auth, or put `9180` on a restricted segment, or disable when unused. **Open.** Lab publishes `9180` to the host on purpose for the demo. |
| 3 | **High** | **Agent transport is plaintext + unauthenticated.** socat on `6556` returns agent output (incl. internal URLs, service structure) to *any* TCP client on the segment; no TLS, no registration. | `SYNTHMK_AGENT_TLS_REGISTRATION` (official agent + `cmk-agent-ctl` TLS). Until then, firewall `6556` to the Checkmk server only. **Open.** |
| 4 | **Medium** | **Secrets via env / `flows.conf`.** `{{ }}` resolves from environment only; creds live in env vars (visible in `/proc`, `docker inspect`) — no vault. | `.env`/`*.key`/`*credentials*` are gitignored and CI secret-scans tracked files. Proper fix = `SYNTHMK_SECRET_SOURCE`. **Open.** |
| 5 | **Medium** | **HTML-escaping disabled for screenshot links** is an XSS surface in the Checkmk GUI (Werk #6058; advisory SBA-ADV-20250729-01). | Scope the "Escape HTML codes in service output = Off" rule to the runner host(s) only; SynthMK emits a single sanitized one-line output containing only the link it generated. **Documented**, operator must scope. |
| 6 | **Medium** | **No resource limits / no run isolation.** Container has no CPU/mem limits; a runaway or flood of flows can exhaust the host; runner executes whatever URLs the flows name (internal SSRF-style reach is the *intended* feature but also the risk if flows are attacker-controlled). | Set compose `deploy.resources` / `--memory`; treat `flows/` + `flows.conf` as trusted, operator-only inputs (don't accept untrusted flow submissions). **Open.** |
| 7 | **Medium** | **Container runs as root; Chromium with `--no-sandbox`.** Needed for Chromium-in-Docker, but root + no-sandbox is risky if a flow ever visits an untrusted/compromised page (RCE surface in the browser). | Only point flows at trusted internal sites; consider a non-root user + seccomp; keep Playwright/Chromium patched. **Open.** |
| 8 | **Low** | **Lab uses a hardcoded admin password** (`synthmk-lab-admin`) and publishes the Checkmk UI on `8080`. | Lab/demo only — never reuse for a real site. Change `CMK_PASSWORD` and restrict ports for anything persistent. **Documented.** |
| 9 | **Low** | **Supply chain.** Appliance pulls `mcr.microsoft.com/playwright/python` + pins `playwright==1.49.0`; MKP ships runner code. | Pin/scan base image digests; review MKP contents (`mkp inspect`) before distributing. **Partial** (version pinned, not digest-pinned). |

**Net:** safe on a trusted LAN segment with `6556`/`9180` firewalled to the
Checkmk server and screenshots disabled for credential flows. Items #1–#3 are the
must-fix set before any wider exposure.

---

## 6. Operational notes / gotchas

- **Clean lab cycle:** `make lab-down && make lab-up`. Do **not** bring the lab up
  while git is rewriting the working tree — bind mounts go stale (empty `flows/`,
  nginx 403). Discover services **after** the first browser run completes (else
  discovery captures the `SynthMK <file>.yaml` UNKNOWN fallback names; re-discover
  to fix).
- **Screenshot links across the LAN:** set `SYNTHMK_SHOT_BASE_URL=http://<lan-ip>:9180`
  (compose default is `localhost`, only clickable on the lab host).
- **Real MKP** needs a running site: `make lab-up` then `make real-mkp`.
- **Enabled package removal** needs `mkp disable` before `mkp remove`.
