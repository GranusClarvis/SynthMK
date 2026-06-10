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
| `browser` | string | no (`chrome`) | Target engine: `chromium`/`chrome`/`google-chrome` (bundled Chromium), `firefox`, `webkit`/`safari`, or `edge`/`msedge` (Edge release channel, falls back to bundled Chromium if absent). Unknown values fall back to Chromium. |
| `screenshot_on_failure` | bool | no (false) | On a failing step, capture `screenshots/<flow>-fail-step<N>.png` and cite it in the output line (a clickable link when a screenshot base URL is configured; see below). |
| `state_mode` | string | no (`digit`) | `digit` = runner computes the state (authoritative failure message); `dynamic` = emit a `P` state on success and let Checkmk threshold `duration` from `warn_ms`/`crit_ms`. |
| `checkmk_host` | string | no | Piggyback target: attribute the result to this Checkmk host (the monitored site appears as its own host) instead of the runner node. Consumed by the runner-node scheduler / `checkmk/piggyback_wrap.sh`, not `runner.py`. |
| `type` | string | no (`flow`) | `flow` = declarative steps (this schema). `script` = operator Playwright Python (see **Script flows**). `cert` = TLS certificate expiry (see **Certificate checks**). |
| `script` | string | script flows | Path to the `.py`, relative to the flow file (confined to the flow's directory tree). |
| `max_attempts` | int | no (1) | 1 to 3. A WARN/CRIT outcome re-runs with a fresh browser before alarming; UNKNOWN is never retried; the attempt count shows in the summary. |
| `trace_on_failure` | bool | no (false) | Keep a Playwright trace.zip (screenshots plus DOM snapshots) next to the failure PNG when the flow fails. Open it at trace.playwright.dev. |
| `steps` | list | yes (flow type) | Ordered steps (below). |

## Selector fallback ladders

Everywhere a step takes a `selector`, it accepts **either one selector or a
list**: a fallback ladder tried in order until one matches:

```yaml
- action: click
  selector:
    - "[data-testid=login-submit]"   # survives redesigns
    - "button[type=submit]"          # structural fallback
```

This is the multi-locator resilience commercial tools sell as their top
anti-flake feature: a page change that breaks the CSS path still matches the
test attribute. The recorder, the DevTools importer, and the dashboard step
builder all emit ladders automatically.

## Step actions

Interaction steps:

| `action` | Fields | Behavior |
|---|---|---|
| `open_url` | `url` | `page.goto(url, wait_until=domcontentloaded)`. |
| `click` | `selector` | `page.click(selector)`. |
| `fill` | `selector`, `value`, `sensitive?` | `page.fill(selector, value)`. `value` supports `{{ }}`. `sensitive: true` = credential hygiene (below). |
| `press` | `key`, `selector?` | Key press (e.g. `Enter`), on the selector or the focused element. |
| `select_option` | `selector`, `value` | Select a `<select>` option by value, falling back to visible label. |
| `hover` | `selector` | Mouse-over (opens hover menus). |
| `scroll_into_view` | `selector` | Scroll the element into the viewport. |
| `wait_ms` | `ms` | Fixed wait. Prefer `wait_for_element`/`wait_for_url`. |
| `wait_for_network_idle` | `timeout_ms?` | Wait until there are no network connections for 500ms (Playwright `networkidle`); clear failure if the page stays chatty past the timeout. Use after a click that fires XHR/fetch before the next assertion. |
| `screenshot` | `name?`, `full_page?` | Always-on capture to `screenshots/<flow>-<name>.png` regardless of pass/fail (evidence / visual-diff baseline). Form inputs are masked first if a `sensitive` fill has run, so it can never leak a credential. A capture failure never flips a passing flow (treated as `optional`). |
| `wait_for_element` | `selector`, `timeout_ms?` | Wait until selector is visible; clear failure if not. |
| `wait_for_url` | `contains`, `timeout_ms?` | Wait until the URL contains a substring (post-login redirects). |

Assertion steps (failure ends the flow CRIT with a clear message):

| `action` | Fields | Failure message |
|---|---|---|
| `check_visible_text` | `text` | `Expected text '<text>' not found` |
| `check_text_absent` | `text` | `Text '<text>' is visible on the page (expected absent)`. Use it to assert error banners are NOT there. |
| `check_title` | `contains` | `Expected title to contain '<x>', got '<actual>'` |
| `check_url` | `contains` | `Expected URL to contain '<x>', got '<actual>'` |
| `check_element_count` | `selector`, `min?` (1) | `Expected at least <min> element(s) matching '<sel>', found <n>` |
| `check_element_attribute` | `selector`, `attribute`, `equals?`/`contains?` | Attribute must exist; with `equals`/`contains`, its value must match. |
| `check_checkbox` | `selector`, `checked?` (true) | Checkbox/radio state must match `checked`. |

Structure:

| `action` | Fields | Behavior |
|---|---|---|
| `include` | `flow` | Splice another file's `steps:` in place (path relative to the including flow). Share one login fragment across many checks instead of copying steps. Cycle-safe, max 3 levels / 200 expanded steps; the linter follows and lints the included file. |

Per-step `timeout_ms` overrides the flow default.

Any step may carry `optional: true`: a failing optional step is skipped instead
of failing the flow. Use it for best-effort interactions like cookie-consent
clicks (see [`flows/google-search.yaml`](../flows/google-search.yaml)).

A raw Playwright failure on a step (click timeout, bad selector) is reported as
`CRIT - Step <N> (<action>) failed: <first error line>` (a check failure, not a
runner error) and still triggers the failure screenshot.

## Value substitution & secrets

Two placeholder forms are resolved in `url`/`value` fields at run time:

* **`{{ secret.NAME }}`: the right way to do credentials.** Resolved from the
  node-local **secrets file** (`--secrets-file` / `$SYNTHMK_SECRETS_FILE`), a
  YAML mapping that MUST be `chmod 600` and owned by the runner user; anything
  looser is refused up front (UNKNOWN, flow never runs with blank creds).
  A missing name is a hard UNKNOWN with no value leaked. Every resolved secret
  value is **redacted to `***` in all service output and error messages**.
* **`{{ totp.NAME }}`: MFA logins.** NAME is a **base32 TOTP seed** stored in
  the same secrets file (the string you get from "can't scan the QR code?").
  Resolves to the current 6-digit RFC 6238 code at run time, so SynthMK can
  monitor MFA-protected logins. The seed is redacted like any secret.
* **`{{ var.uuid }}` / `{{ var.timestamp }}` / `{{ var.random }}`**: builtin
  per-run values, stable within one run: type `ticket-{{ var.uuid }}` into a
  form, then assert the same uuid is echoed back.
* `{{ NAME }}`: legacy environment lookup (unknown → empty string). Fine for
  non-secrets like base URLs.

Mark credential fills `sensitive: true`: the value is registered for redaction
even if it didn't come from the secrets file, and a later failure screenshot
**blanks all form fields** before capture so the PNG can't leak what was typed.
The linter warns when a fill references `{{ secret.* }}` without `sensitive: true`.

Example secrets file (`/etc/synthmk/secrets.yaml`, mode 600):

```yaml
portal_user: monitor
portal_password: a-real-password
```

Never commit secrets (`.env`, `*.key`, `*credentials*`, `lab/secrets.yaml`-style
files outside the lab are gitignored; CI secret-scans tracked files).

## Output contract

The runner emits exactly one Checkmk local-check line:

```text
<status> "<name>" duration=<ms>ms;<warn>;<crit>|step0_<action>=<ms>ms|… <STATE> - <summary>
```

Each step contributes its own `stepN_<action>` perfdata metric, so Checkmk
graphs where time is spent *inside* the journey (login vs. search vs. render),
not just the total.

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
2 "<name>" duration=... CRIT - <message> <a href="http://<runner>:9180/<flow>-fail-step<N>.png?t=<token>">screenshot</a>
```

The runner-node appliance serves screenshots through an **authenticated** HTTP
server (`runner-node/shot_server.py`): per-file HMAC tokens signed with a
node-local key (`$SYNTHMK_SHOT_KEY_FILE`), no directory listing, no traversal.
The runner appends the matching `?t=` token automatically when the key file is
readable. The link only renders in the Checkmk GUI if **"Escape HTML codes
in service output"** is turned **Off** for the runner host (scope it narrowly:
escaping-off is an XSS surface; SynthMK's output is always a single sanitized
line). Without a base URL the line keeps the plain `(screenshot: <path>)` form.

### Piggyback (`checkmk_host`)

By default a flow becomes a service of the runner node. Set `checkmk_host:` and
the runner-node scheduler wraps the result in a Checkmk piggyback envelope
(`checkmk/piggyback_wrap.sh`) so the **monitored site appears as its own Checkmk
host** carrying the synthetic service: one runner, many target hosts.

## Certificate checks (`type: cert`)

A certificate check needs no browser and no steps, just an endpoint. It opens
one TLS connection and reports the days left until the certificate expires:

```yaml
name: Synthetic TLS Certificate (portal)
type: cert
host: portal.example.internal   # or url: https://portal.example.internal:8443/
port: 443                       # optional, default 443 (or the url's port)
warn_days: 21                   # WARN when fewer days remain
crit_days: 7                    # CRIT when fewer days remain
require_valid_chain: false      # true also fails when the chain does not verify
```

The result carries a `cert_days_left` metric (graphable in Checkmk) and a
summary naming the expiry date. Internal-CA and self-signed certificates are
still monitored for expiry: if the chain does not verify against the system
trust store and `require_valid_chain` is off, the runner falls back to reading
the certificate via `openssl` and the summary notes that the chain was not
verified. Cert checks honour `checkmk_host` (piggyback) and `max_attempts`.

## Trace artifacts (`trace_on_failure`)

Set `trace_on_failure: true` on any browser flow and a failing run keeps a
Playwright `trace.zip` (full screenshots and DOM snapshots) next to the
failure screenshot. The node serves it through the same authenticated
screenshot server, and the failing service links it (download, then open at
trace.playwright.dev). Tracing is off by default because it costs memory and
the zips are large; turn it on for the journeys you actually need to debug.

## Script flows (`type: script`)

When the declarative schema isn't enough (conditionals, loops, computed
values), a flow can be real Playwright Python:

```yaml
name: Checkout Deep Journey
type: script
script: scripts/checkout.py     # relative to this file
warn_ms: 8000
crit_ms: 20000
screenshot_on_failure: true
```

The script defines `run(page, api)`: `page` is the raw Playwright sync Page,
`api` adds the monitoring contract: `api.step("label")` (named per-step
timing graphed in Checkmk + failure attribution), `api.secret("name")`
(secrets-file value, auto-redacted + screenshot-masked), `api.totp("name")`,
`api.var("uuid")`, `api.screenshot("name")`, `api.fail("message")`. A bare
`assert` fails the check cleanly; syntax errors and a missing `run()` are
UNKNOWN, never tracebacks. See
[`flows/scripts/example_journey.py`](../flows/scripts/example_journey.py).

**Trust gate:** script flows run operator code with full page access, so the
node must opt in with `SYNTHMK_ALLOW_SCRIPTS=1` (compose template comment).
Without it every script flow reports UNKNOWN. Enable only where everyone who
can write the flows volume may run code as the runner user.

## Importing Chrome DevTools recordings

Every Chrome ships a recorder (F12 → Recorder). Export the recording as JSON
and convert it, with no extension installed on the recording machine:

```bash
python3 runner/import_devtools.py recording.json -o flows/my-check.yaml
```

DevTools' multiple selectors per element become SynthMK fallback ladders;
password fields are swapped to `{{ secret.* }}` + `sensitive: true` (the
recorded plaintext is discarded); unsupported step types are skipped with
notes; output is linted before write. Review, add `check_*` assertions, set
thresholds, schedule.

## Visual step builder

The node dashboard (`:9181` → **Step builder**) authors flows point-and-click
against a live page: open a URL, click an element in the preview (Chrome-
inspect style), get a verified-unique selector ladder + suggested action,
**every added step executes immediately on the live page** (added = tested),
then export to the lint-gated editor. Passwords default to secret references.

## Examples

- [`flows/example-ok.yaml`](../flows/example-ok.yaml): passing journey.
- [`flows/example-fail.yaml`](../flows/example-fail.yaml): failing assertion (`Dashboard` text absent → CRIT).
- [`flows/wikipedia-search.yaml`](../flows/wikipedia-search.yaml): real multi-step
  public journey (fill → press Enter → wait_for_url → asserts), verified live.
- [`flows/google-search.yaml`](../flows/google-search.yaml): search-engine journey
  *template* incl. `optional: true` consent click; see its header for why Google
  bot-blocks headless runners (use the shape on sites you own).
- [`lab/flows/intranet-login.yaml`](../lab/flows/intranet-login.yaml): the
  flagship 10-step login journey: secrets file, sensitive fill, wait_for_url,
  hover menu, select_option, element count. Runs E2E in the LAN lab.
- [`flows/example-advanced.yaml`](../flows/example-advanced.yaml): v0.5
  feature tour: selector ladders, `include`, `{{ totp.* }}`, `{{ var.* }}`,
  the new assertions (template, fictional portal).
- [`flows/shared/portal-login.yaml`](../flows/shared/portal-login.yaml):
  reusable login fragment for `include`.
- [`flows/example-script.yaml`](../flows/example-script.yaml) +
  [`flows/scripts/example_journey.py`](../flows/scripts/example_journey.py):
  script flow template.
- [`flows/demo/index.html`](../flows/demo/index.html): bundled stable local target page.

## Recorder

The [`extension/`](../extension/) Chrome recorder (MV3) emits these steps using
GOAT's selector ladder (`data-testid` → stable id → unique `name` → unique class
combo → `nth-of-type` path), so recorded selectors stay stable and directly
compatible with this schema. Record a flow → live step list (delete bad steps,
insert assertions, set name + thresholds) → **Download .yaml** → drop in
`flows/` + one `flows.conf` line.

Credential hygiene is built in: typing into a password field records
`{{ secret.<field> }}` + `sensitive: true`, so **the typed value never leaves the
page**; the popup tells you to add the real value to the node's secrets file.
Enter keypresses are recorded as `press`, `<select>` changes as `select_option`.

Validation is two-layer: browser-free contract
([`extension/validate_export.sh`](../extension/validate_export.sh) →
[`flows/recorded-sample.yaml`](../flows/recorded-sample.yaml), exporter action
table locked to the linter's) and a real-browser E2E
([`extension/test_e2e.py`](../extension/test_e2e.py)) that loads the extension
in Chromium, records the lab login journey, and asserts the export lints clean
with the secret reference intact.
