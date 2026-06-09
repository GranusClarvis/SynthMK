# SynthMK Flow Schema

A flow is a readable YAML file describing a browser journey and its assertions.
It is a human-authorable projection of GOAT's `RecordedStep` model
(see [goat-reference-audit.md](goat-reference-audit.md)). Users write flows, not
Playwright code.

## Top-level fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `name` | string | yes | Checkmk service name (quoted in output). |
| `start_url` | string | no | Documentary start URL; the first `open_url` step does the real navigation. |
| `timeout_ms` | int | no (30000) | Default per-step timeout. |
| `warn_ms` | int | no | Total-duration WARN threshold → Checkmk perfdata `;warn`. |
| `crit_ms` | int | no | Total-duration CRIT threshold → Checkmk perfdata `;crit`. |
| `browser` | string | no (`chrome`) | Target browser; MVP runs Chromium. |
| `screenshot_on_failure` | bool | no (false) | On a failing step, capture `screenshots/<flow>-fail-step<N>.png` and cite it in the output line (a clickable link when a screenshot base URL is configured — see below). |
| `state_mode` | string | no (`digit`) | `digit` = runner computes the state (authoritative failure message); `dynamic` = emit a `P` state on success and let Checkmk threshold `duration` from `warn_ms`/`crit_ms`. |
| `checkmk_host` | string | no | Piggyback target: attribute the result to this Checkmk host (the monitored site appears as its own host) instead of the runner node. Consumed by the runner-node scheduler / `checkmk/piggyback_wrap.sh`, not `runner.py`. |
| `steps` | list | yes | Ordered steps (below). |

## Step actions

Interaction steps:

| `action` | Fields | Behavior |
|---|---|---|
| `open_url` | `url` | `page.goto(url, wait_until=domcontentloaded)`. |
| `click` | `selector` | `page.click(selector)`. |
| `fill` | `selector`, `value` | `page.fill(selector, value)`. `value` supports `{{ }}`. |
| `wait_for_element` | `selector`, `timeout_ms?` | Wait until selector is visible; clear failure if not. |

Assertion steps (failure ends the flow CRIT with a clear message):

| `action` | Fields | Failure message |
|---|---|---|
| `check_visible_text` | `text` | `Expected text '<text>' not found` |
| `check_title` | `contains` | `Expected title to contain '<x>', got '<actual>'` |
| `check_url` | `contains` | `Expected URL to contain '<x>', got '<actual>'` |

Per-step `timeout_ms` overrides the flow default.

## Value substitution

Any `value`/`url` may contain `{{ NAME }}` placeholders, resolved from
environment variables at run time (GOAT-style, but env-backed — no secret store).
Unknown placeholders resolve to empty string. Keep credentials in env / Checkmk's
own secret mechanism; never commit them (`.env`, `*.key`, `*credentials*` are
gitignored).

## Output contract

The runner emits exactly one Checkmk local-check line:

```text
<status> "<name>" duration=<ms>ms;<warn>;<crit> <STATE> - <summary>
```

- `status`/`STATE`: `0/OK`, `1/WARN`, `2/CRIT`, `3/UNKNOWN`.
- A failed assertion → `2 ... CRIT - <clear message>`.
- A passing flow over `warn_ms`/`crit_ms` → `1/WARN` or `2/CRIT` on duration.
- Browser/schema errors fail **open** to `3/UNKNOWN` (never a traceback, never
  multi-line) so the Checkmk service never goes silent.

### Dynamic state (`state_mode: dynamic`)

With `state_mode: dynamic` (or `runner.py --p-state`) a *passing* flow emits a
`P` marker instead of a digit and lets Checkmk compute the state from the
duration thresholds:

```text
P "<name>" duration=<ms>ms;<warn>;<crit> <summary>
```

A real failure still emits an explicit `2/CRIT` (or `3/UNKNOWN`) so the failure
message is never silently downgraded by a missing threshold. Default stays
`digit` (the runner is authoritative).

### Screenshot links

When the runner is given a screenshot base URL (`--screenshot-base-url` or
`$SYNTHMK_SHOT_BASE_URL`) and a step fails with `screenshot_on_failure: true`,
the failing line ends with a clickable link instead of a bare path:

```text
2 "<name>" duration=... CRIT - <message> <a href="http://<runner>:9180/<flow>-fail-step<N>.png">screenshot</a>
```

The runner-node appliance serves the `screenshots/` directory over HTTP for
exactly this. The link only renders in the Checkmk GUI if **"Escape HTML codes
in service output"** is turned **Off** for the runner host (scope it narrowly —
escaping-off is an XSS surface; SynthMK's output is always a single sanitized
line). Without a base URL the line keeps the plain `(screenshot: <path>)` form.

### Piggyback (`checkmk_host`)

By default a flow becomes a service of the runner node. Set `checkmk_host:` and
the runner-node scheduler wraps the result in a Checkmk piggyback envelope
(`checkmk/piggyback_wrap.sh`) so the **monitored site appears as its own Checkmk
host** carrying the synthetic service — one runner, many target hosts.

## Examples

- [`flows/example-ok.yaml`](../flows/example-ok.yaml) — passing journey.
- [`flows/example-fail.yaml`](../flows/example-fail.yaml) — failing assertion (`Dashboard` text absent → CRIT).
- [`flows/demo/index.html`](../flows/demo/index.html) — bundled stable local target page.

## Recorder

The [`extension/`](../extension/) Chrome recorder (MV3) emits these steps using
GOAT's selector ladder (`data-testid` → stable id → unique `name` → unique class
combo → `nth-of-type` path), so recorded selectors stay stable and directly
compatible with this schema. Record a flow → **Export YAML** → save under
`flows/` → run with `runner/runner.py`. The exporter is validated against this
contract browser-free by [`extension/validate_export.sh`](../extension/validate_export.sh),
which produces [`flows/recorded-sample.yaml`](../flows/recorded-sample.yaml).
