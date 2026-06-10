# Installing SynthMK in a Checkmk home lab

SynthMK installs as a Checkmk **agent local-check**: the agent runs the check
each interval and renders each flow as a normal service. There is no server,
scheduler, or cloud backend.

## Prerequisites (on the monitored host)

- Checkmk agent installed (the host already reports to your Checkmk site).
- Python 3 with `pyyaml` and `playwright`, and a Chromium browser:
  ```bash
  pip install pyyaml playwright
  python3 -m playwright install chromium     # plus system libs on headless hosts
  ```

## Install

From a checkout of this repo on the host:

```bash
sudo ./install.sh
# installs payload to   /opt/synthmk
# installs local-check  /usr/lib/check_mk_agent/local/300/synthmk_check.sh
```

Override locations with env vars:

```bash
sudo SYNTHMK_HOME=/opt/synthmk \
     CMK_LOCAL_DIR=/usr/lib/check_mk_agent/local/60 \
     ./install.sh
```

Preview without changing anything:

```bash
./install.sh --dry-run
```

## Configure

Edit the top of `/opt/synthmk/checkmk/synthmk_check.sh` (or set env in the
agent's environment) to choose which flows run each interval:

```bash
SYNTHMK_FLOW_FILES="example-ok.yaml login.yaml"   # space-separated
SYNTHMK_DEMO_URL="https://your-app.local"          # {{ }} value(s)
```

Secrets stay out of the repo: flows reference `{{ ENV_NAME }}` and the runner
resolves them from the environment at run time (see `docs/flow-schema.md`).

## Verify

```bash
/usr/lib/check_mk_agent/local/300/synthmk_check.sh
# prints one Checkmk line per flow, e.g.
# 0 "Synthetic Example Check" duration=1200ms;3000;7000 OK - Flow completed successfully
```

Then run **service discovery** for the host on the Checkmk server. Each flow
becomes a service named by the flow's `name`, with `duration` graphed and
warn/crit thresholds applied automatically.

## Update

```bash
cd /path/to/SynthMK && git pull
sudo ./install.sh          # idempotent: overwrites payload + local-check in place
```

Installing a newer checkout over an older one is safe: `install.sh` recopies the
payload and the local-check. Your flow files in `/opt/synthmk/flows` are
overwritten by repo versions, so keep host-specific flows under version control
or a separate `SYNTHMK_FLOWS` directory.

## Uninstall

```bash
sudo ./install.sh --uninstall
# removes /opt/synthmk and the installed local-check
```

## Packaging (optional)

To build a redistributable package skeleton instead of installing in place:

```bash
make package      # -> dist/synthmk-<version>.mkp  (see packaging/README.md)
```
