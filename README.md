# SynthMK

**Website & docs: https://granusclarvis.github.io/SynthMK-Web/ · Downloads: [GitHub Releases](https://github.com/GranusClarvis/SynthMK/releases)**

Checkmk synthetic monitoring addon for browser journeys — record, build, or
script a flow; a hardened runner node executes it on schedule; the result is a
normal Checkmk service with graphs, thresholds, and failure screenshots.

**Four ways to author a check** (simplicity first — nobody is forced to code,
nobody is capped by YAML either):

1. **Record** — browser extension (Chrome/Edge/Firefox) records clicks/typing
   into readable YAML; passwords become secret references automatically.
2. **Import** — every Chrome has a recorder built in (F12 → Recorder); convert
   its JSON export with `runner/import_devtools.py`. No extension needed.
3. **Build visually** — the node dashboard's **step builder**: click elements
   on a live page preview (Chrome-inspect style), pick the action, every step
   is tested live as you add it, export to the lint-gated editor.
4. **Write** — readable YAML flows (with selector fallback ladders, sub-flow
   `include`, TOTP/MFA secrets), or full **Playwright Python script checks**
   for power users (trust-gated, off by default).

## Why SynthMK (vs Checkmk's own Synthetic Monitoring)

Checkmk 2.3 ships an official **Synthetic Monitoring** add-on built on
**Robotmk / Robot Framework** — powerful, enterprise-grade, and the right choice
if you already live in Robot Framework or run a commercial Checkmk edition.

SynthMK aims at the gap underneath it:

| | Checkmk Synthetic Monitoring (Robotmk) | **SynthMK** |
|---|---|---|
| Engine | Robot Framework | Playwright (direct) |
| Authoring | RF keyword DSL / `.robot` + RCC/CSM CLI | recorder, DevTools import, visual step builder, YAML, or Playwright Python |
| Edition | Pro/Ultimate + per-test subscription | works on **Raw/CRE (free)**, MIT |
| Credentials | secret env vars (plaintext in agent config) | node-local 0600 secrets file, `{{ secret.NAME }}` + `{{ totp.NAME }}` MFA, output-redacted |
| Integration depth | bakery + dedicated services | **native check plugin**: Setup ruleset, unit-aware graphs, perf-o-meter, per-step metrics |
| Check management | bakery rules + .robot redeploys | **web dashboard** on the node: live states, run-now, pause/resume, tags, version history + rollback, audit log, lint-gated editor |
| Footprint | 4–8 cores / 8–16 GB per test host | one container + one MKP + one extension |

If you run **Checkmk Raw** and want *"is my login flow still working?"* as a
normal service — without Robot Framework or a paid tier — that's SynthMK.
v0.5.0 adds the authoring & operations layer on top of the v0.3 hardening:
selector fallback ladders, sub-flows, TOTP/MFA, the visual step builder, the
DevTools importer, script checks, and dashboard management (pause/tags/
history/audit/viewer role) — all contract- and e2e-tested. Test evidence:
[`docs/STATUS.md`](docs/STATUS.md) · capacity math: [`docs/scaling.md`](docs/scaling.md)
· how we compare: [`docs/competitive-landscape.md`](docs/competitive-landscape.md).

## MVP Components

- `flows/` - readable YAML flow examples (`example-ok.yaml`, `example-fail.yaml`)
  plus a bundled local `demo/` page so the runner has a stable, login-free target.
- `runner/` - Playwright-based synthetic runner (`runner.py`) emitting Checkmk
  local-check output, a browser-free contract test (`test_contract.py`), and a
  smoke script (`smoke_test.sh`).
- `checkmk/` - Checkmk local-check wrapper + piggyback wrapper (`synthmk_check.sh`,
  `piggyback_wrap.sh` + README).
- `extension/` - Chrome MV3 recorder (record → export YAML; see `extension/README.md`).
- `runner-node/` - the Docker **runner-node appliance** (scheduler + agent
  transport + screenshot server) you host inside the intranet.
- `lab/` - one-command **self-hosted Checkmk Raw + runner + internal demo site**
  for full LAN end-to-end testing (`docs/lan-quickstart.md`).
- `docs/` - architecture, GOAT reference audit, flow schema, home-lab/demo,
  LAN quick start, product roadmap, and **`docs/STATUS.md`** (status, test
  evidence, open work, and the **security review**).

## Quick start

```bash
pip install playwright pyyaml && python3 -m playwright install chromium
python3 runner/test_contract.py          # validate output contract (no browser)
export SYNTHMK_DEMO_URL="file://$PWD/flows/demo/index.html"
python3 runner/runner.py flows/example-ok.yaml    # -> 0 "..." OK - ...
python3 runner/runner.py flows/example-fail.yaml  # -> 2 "..." CRIT - Expected text 'Dashboard' not found
```

See [`docs/home-lab.md`](docs/home-lab.md) for the full Checkmk wiring walkthrough.

## Run it in your LAN (runner node + self-hosted Checkmk)

Host **one runner node** inside the intranet range; it reaches internal-only
sites, runs many flows on their own intervals, serves failure screenshots, and
reports to Checkmk like any host. To try the whole thing end-to-end on one
machine — self-hosted Checkmk Raw + the runner + an internal demo site:

```bash
cd lab && docker compose up -d --build      # Checkmk UI: http://localhost:8080/cmk/
```

Walkthrough (add host → discovery → break site → CRIT + screenshot):
[`docs/lan-quickstart.md`](docs/lan-quickstart.md). Architecture + scaling +
piggyback + screenshots: [`docs/architecture.md`](docs/architecture.md). The
appliance itself: [`runner-node/README.md`](runner-node/README.md).

## Install / package

```bash
make ci                  # full release contract (validate + syntax + determinism + secrets + version)
make validate            # contract test + recorder-export contract check (no browser)
sudo ./install.sh        # install to /opt/synthmk + agent local-check dir
sudo ./install.sh --uninstall
make package             # deterministic dist/synthmk-<version>.mkp *skeleton* (CI checksum)
make real-mkp            # REAL installable .mkp via a running Checkmk site's own mkp tool
make real-mkp-ci         # ephemeral Checkmk: build + `mkp add`/`enable` the .mkp (Docker)
```

`make package` builds the byte-deterministic skeleton (for CI). `make real-mkp`
produces the genuine Checkmk-Exchange-installable `.mkp` (info + info.json +
member tarballs) using the lab Checkmk container — bring it up first
(`cd lab && docker compose up -d checkmk`). Verified against Checkmk Raw 2.3.

`make ci` is the single browser/Docker-free contract GitHub Actions and
autonomous agents both run (see [`scripts/ci.sh`](scripts/ci.sh) and
[`.github/workflows/ci.yml`](.github/workflows/ci.yml)). A **separate optional**
job, [`.github/workflows/real-mkp.yml`](.github/workflows/real-mkp.yml)
(`make real-mkp-ci` / [`scripts/ci_real_mkp.sh`](scripts/ci_real_mkp.sh)), is
Docker-gated: it spins up an ephemeral Checkmk Raw site, runs `make real-mkp`,
then proves the built artifact `mkp add` + `mkp enable`s and lists the shipped
files. It never gates the fast `ci` workflow.

See [`INSTALL.md`](INSTALL.md) for the home-lab install/update/uninstall path,
[`packaging/README.md`](packaging/README.md) for the MKP layout,
[`RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md) for cutting a release, and
[`CHANGELOG.md`](CHANGELOG.md) for the version history.

## Reference

GOAT is a reference point, not the final architecture. Useful concepts include
its Chrome recorder event capture, selector generation, recorded step model, and
Playwright runner behavior. SynthMK keeps the Checkmk user flow as the center of
gravity. SynthMK adopts a remote **runner-node appliance** (the "run checks from
inside the intranet" idea) but Checkmk-native — agent + spool dir + piggyback —
explicitly rejecting GOAT's central admin-suite coordinator. See
[`docs/architecture.md`](docs/architecture.md) and
[`docs/goat-reference-audit.md`](docs/goat-reference-audit.md).

