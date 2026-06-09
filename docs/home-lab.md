# Home-Lab Setup & End-to-End Demo

This walks the full SynthMK loop on a single home-lab host:
**readable flow → Playwright runner → Checkmk-compatible output → Checkmk service.**

## 1. Prerequisites

- Python 3.10+ with PyYAML and Playwright:
  ```bash
  pip install playwright pyyaml
  python3 -m playwright install chromium      # downloads Chromium
  python3 -m playwright install-deps chromium  # system X libs (needs root)
  ```
  > The bundled Chromium needs system libraries (`libatk`, `libXdamage`, …).
  > On a normal home-lab host `install-deps` provides them. In a locked-down
  > sandbox without those libs, the runner **fails open to a Checkmk UNKNOWN
  > line** instead of crashing — the service simply reports UNKNOWN.
- A Checkmk site with the agent installed (Raw/CRE is fine).

## 2. Validate the output contract (no browser needed)

```bash
python3 runner/test_contract.py
```

Exercises the Checkmk line format, warn/crit escalation, assertion messages, and
`{{ }}` substitution deterministically. Expected: `12 checks passed, 0 failed.`

## 3. Run a flow locally

```bash
export SYNTHMK_DEMO_URL="file://$PWD/flows/demo/index.html"
export DEMO_USER=demo DEMO_PASS=demo

python3 runner/runner.py flows/example-ok.yaml
# -> 0 "Synthetic Example Check" duration=1187ms;3000;7000 OK - Flow completed successfully

python3 runner/runner.py flows/example-fail.yaml
# -> 2 "Synthetic Dashboard Check" duration=842ms;3000;7000 CRIT - Expected text 'Dashboard' not found
```

The OK flow signs into the bundled demo page and asserts the dashboard panel
appears; the failing flow asserts text that does not exist, producing a clear
CRIT. (Durations are illustrative.) Run both at once with:

```bash
bash runner/smoke_test.sh
```

## 4. Wire into Checkmk

1. Copy the repo to the monitored host, e.g. `/opt/synthmk`.
2. Install the local check:
   ```bash
   cp checkmk/synthmk_check.sh /usr/lib/check_mk_agent/local/300/synthmk_check.sh
   chmod +x /usr/lib/check_mk_agent/local/300/synthmk_check.sh
   ```
   The `300/` directory runs it every 300s; use the bare `local/` dir for the
   default interval.
3. Point it at your flows (env or edit the script):
   ```bash
   export SYNTHMK_HOME=/opt/synthmk
   export SYNTHMK_FLOW_FILES="example-ok.yaml my-login.yaml"
   ```
4. On the Checkmk server: **Setup → Hosts → service discovery** for the host.
   The runner's stdout line *is* the local-check protocol, so each flow shows up
   as a service named after the flow's `name`, with `duration` as a graphable
   metric and warn/crit thresholds already attached.

## 5. What "done" looks like

A Checkmk service that goes **OK / WARN / CRIT** based on whether your real
browser journey still works, with the failure reason in the service summary —
no Playwright code written, no dashboard to maintain. That is the entire MVP
promise. Next steps (recorder, secret store, premium tiers) are in
[product-roadmap.md](product-roadmap.md).
