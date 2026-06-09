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
| `screenshot_on_failure` | bool | no (false) | On a failing step, capture `screenshots/<flow>-fail-step<N>.png` and cite it in the output line. |
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
