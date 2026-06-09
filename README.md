# SynthMK

Checkmk synthetic monitoring addon for browser-recorded website flows.

SynthMK's first target is deliberately small:

1. Record or define a readable browser flow.
2. Run it with a Chrome/Playwright-based runner.
3. Emit Checkmk-compatible service output.
4. Show the result as a normal Checkmk service.

The product direction is simplicity first. Users should not need to write
Playwright or Selenium code for common checks.

## Why SynthMK (vs Checkmk's own Synthetic Monitoring)

Checkmk 2.3 ships an official **Synthetic Monitoring** add-on built on
**Robotmk / Robot Framework** — powerful, enterprise-grade, and the right choice
if you already live in Robot Framework or run a commercial Checkmk edition.

SynthMK aims at the gap underneath it:

| | Checkmk Synthetic Monitoring (Robotmk) | **SynthMK** |
|---|---|---|
| Engine | Robot Framework | Playwright (direct) |
| Authoring | RF keyword DSL / `.robot` | readable YAML + Chrome recorder |
| Edition | enterprise / commercial | works on **Raw/CRE (free)** |
| Integration | deep (bakery, dedicated services) | agent **local check** (drop-in) |
| Footprint | a platform | one script + one container |

If you run **Checkmk Raw at home** and want *"is my login flow still working?"*
as a normal service — without Robot Framework or a paid tier — that's SynthMK.

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
```

`make package` builds the byte-deterministic skeleton (for CI). `make real-mkp`
produces the genuine Checkmk-Exchange-installable `.mkp` (info + info.json +
member tarballs) using the lab Checkmk container — bring it up first
(`cd lab && docker compose up -d checkmk`). Verified against Checkmk Raw 2.3.

`make ci` is the single contract GitHub Actions and autonomous agents both run
(see [`scripts/ci.sh`](scripts/ci.sh) and [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

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

