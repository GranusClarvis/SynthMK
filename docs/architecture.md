# SynthMK Architecture

SynthMK turns a readable browser flow into a native Checkmk service. v0.2.0 adds
a **runner-node appliance** so one host inside the intranet can run many checks
against internal-only sites and report them to Checkmk.

## Components

```
  authoring                runner node (intranet)                 Checkmk server
 ┌──────────┐   flows/   ┌───────────────────────────────┐  6556  ┌────────────┐
 │ recorder │──────────▶ │ synthmk-scheduler             │◀───────│  agent     │
 │  (MV3)   │  YAML      │  • runs each flow on interval  │  pull  │  transport │
 └──────────┘            │  • runner.py → Checkmk line    │        │  parses    │
 ┌──────────┐            │  • piggyback_wrap (target host)│        │  sections  │
 │ hand-    │──────────▶ │  • writes spool dir            │        └─────┬──────┘
 │ written  │            │ agent_output.sh (socat :6556)  │              │
 └──────────┘            │ http.server :9180 (screenshots)│        ┌─────▼──────┐
                         └───────────────────────────────┘        │  services  │
                                  │  reaches                       │  + graphs  │
                                  ▼                                └────────────┘
                       internal-only sites (no internet exposure)
```

## Data flow

1. **Flow** (YAML) describes a journey + assertions (`docs/flow-schema.md`).
2. **`runner/runner.py`** executes it with Playwright/Chromium and prints exactly
   one Checkmk local-check line (`<status> "name" perfdata STATE - summary`).
3. **`runner-node/synthmk-scheduler.sh`** runs each flow on its own interval,
   wraps the line via **`checkmk/piggyback_wrap.sh`** (adding `<<<local>>>` and,
   when `checkmk_host` is set, a `<<<<host>>>>` piggyback envelope), and publishes
   it atomically to the Checkmk **spool directory**.
4. **`runner-node/agent_output.sh`** (served by socat on 6556) answers each
   Checkmk poll with `<<<check_mk>>>` + the fresh spool sections.
5. **Checkmk** discovers and renders each flow as a service, graphs `duration`,
   and applies warn/crit.

## Why the spool dir (scaling)

Running flows inline in the agent poll would serialize slow browser runs behind
collection and make many checks impossible. The scheduler executes flows
independently and only *publishes* finished results; the agent transport just
concatenates what's fresh. So:

- Adding a check = adding a flow file + a `flows.conf` line. No coupling between
  checks; a 30 s flow and a 2 s flow don't interfere.
- `maxage = interval × 3`: if a flow stops producing, its section ages out and
  Checkmk marks the service **stale** rather than showing a stale-green result.

## Attribution: flat vs piggyback

- **Flat** (default): the flow becomes a service of the runner-node host.
- **Piggyback** (`checkmk_host:` / `flows.conf` 3rd column): the result is
  attributed to the named host, so each monitored site appears as its **own
  Checkmk host**. One runner, many target hosts — the home-lab equivalent of
  synthetic-monitoring "locations".

## Screenshots

`screenshot_on_failure: true` saves a PNG to `screenshots/` on a failing step.
The node serves that directory over HTTP (`:9180`); the failing service line
embeds `<a href="$SYNTHMK_SHOT_BASE_URL/<file>">screenshot</a>`. Checkmk core has
no native image attachment (only the enterprise Robotmk add-on does), so a link
to a node-hosted file is the portable path. The link renders only with **"Escape
HTML codes in service output" = Off**, scoped to the runner host (escaping-off is
an XSS surface — Werk #6058; SynthMK output is always one sanitized line).

## Transport options

- **Lab / home (default):** dependency-free socat + `agent_output.sh` over
  plaintext 6556.
- **Production:** install the version-matched official Checkmk agent and register
  `cmk-agent-ctl` (TLS). The scheduler + spool dir are unchanged; only the
  transport differs. See `runner-node/README.md`.

## Deliberately out of scope

No central coordinator/admin-suite (rejected from GOAT — see
`docs/goat-reference-audit.md`), no encrypted secret store, no multi-node fleet /
special-agent HTTP mode (documented future path), no raw-Playwright script mode.
Checkmk remains the UI and the scheduler of record.
