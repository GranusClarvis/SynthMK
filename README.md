# SynthMK

Checkmk synthetic monitoring addon for browser-recorded website flows.

SynthMK's first target is deliberately small:

1. Record or define a readable browser flow.
2. Run it with a Chrome/Playwright-based runner.
3. Emit Checkmk-compatible service output.
4. Show the result as a normal Checkmk service.

The product direction is simplicity first. Users should not need to write
Playwright or Selenium code for common checks.

## MVP Components

- `flows/` - readable YAML flow examples (`example-ok.yaml`, `example-fail.yaml`)
  plus a bundled local `demo/` page so the runner has a stable, login-free target.
- `runner/` - Playwright-based synthetic runner (`runner.py`) emitting Checkmk
  local-check output, a browser-free contract test (`test_contract.py`), and a
  smoke script (`smoke_test.sh`).
- `checkmk/` - Checkmk local-check/addon skeleton (`synthmk_check.sh` + README).
- `extension/` - Chrome recorder placeholder (deferred; see `extension/README.md`).
- `docs/` - GOAT reference audit, flow schema, home-lab/demo, product roadmap.

## Quick start

```bash
pip install playwright pyyaml && python3 -m playwright install chromium
python3 runner/test_contract.py          # validate output contract (no browser)
export SYNTHMK_DEMO_URL="file://$PWD/flows/demo/index.html"
python3 runner/runner.py flows/example-ok.yaml    # -> 0 "..." OK - ...
python3 runner/runner.py flows/example-fail.yaml  # -> 2 "..." CRIT - Expected text 'Dashboard' not found
```

See [`docs/home-lab.md`](docs/home-lab.md) for the full Checkmk wiring walkthrough.

## Install / package

```bash
make validate            # contract test + recorder-export contract check (no browser)
sudo ./install.sh        # install to /opt/synthmk + agent local-check dir
sudo ./install.sh --uninstall
make package             # build dist/synthmk-<version>.mkp skeleton (deterministic)
```

See [`INSTALL.md`](INSTALL.md) for the home-lab install/update/uninstall path and
[`packaging/README.md`](packaging/README.md) for the MKP skeleton layout.

## Reference

GOAT is a reference point, not the final architecture. Useful concepts include
its Chrome recorder event capture, selector generation, recorded step model, and
Playwright runner behavior. SynthMK keeps the Checkmk user flow as the center of
gravity.

