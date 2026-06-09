# SynthMK Checkmk Integration

SynthMK plugs into Checkmk as a **local check** — the simplest, most portable
integration point. No MKP packaging, no special-agent, no API server.

## How it works

The Checkmk agent runs every executable in its `local/` directory each interval
and forwards each stdout line as a service result. SynthMK's runner already
emits that exact format:

```text
<status> "<service>" duration=<ms>ms;<warn>;<crit> <STATE> - <summary>
```

So `checkmk/synthmk_check.sh` just loops over your configured flows, calls
`runner/runner.py`, and prints the lines. **The runner output is the protocol** —
no parsing layer.

## Install

```bash
# on the monitored host
cp -r synthmk /opt/synthmk
cp /opt/synthmk/checkmk/synthmk_check.sh /usr/lib/check_mk_agent/local/300/synthmk_check.sh
chmod +x /usr/lib/check_mk_agent/local/300/synthmk_check.sh
```

`300/` = run every 300 seconds. Use the bare `local/` directory for the agent's
default interval.

## Configure

Environment (or edit the top of `synthmk_check.sh`):

| Var | Default | Meaning |
|---|---|---|
| `SYNTHMK_HOME` | `/opt/synthmk` | Repo root on the host. |
| `SYNTHMK_PYTHON` | `python3` | Python with playwright+pyyaml. |
| `SYNTHMK_FLOWS` | `$SYNTHMK_HOME/flows` | Flow directory. |
| `SYNTHMK_FLOW_FILES` | `example-ok.yaml` | Space-separated flows to run each interval. |
| `SYNTHMK_DEMO_URL` | `file://.../demo/index.html` | Demo target / `{{ }}` value. |

## Verify

```bash
/usr/lib/check_mk_agent/local/300/synthmk_check.sh
# should print one Checkmk line per flow
```

Then run service discovery on the Checkmk server for the host. Each flow becomes
a service (named by the flow's `name`), with `duration` graphed and warn/crit
thresholds applied automatically.

## Failure behavior

If the runner can't launch a browser or a flow file is malformed, it prints a
single `3 ... UNKNOWN - ...` line rather than crashing, so the service reports
UNKNOWN instead of disappearing. A failed assertion prints `2 ... CRIT - <reason>`.
