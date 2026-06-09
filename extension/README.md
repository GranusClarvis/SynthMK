# SynthMK Chrome Recorder

A Manifest V3 Chrome extension that records a browser flow — navigation, clicks,
field fills, and manual assertions — and exports a readable **SynthMK YAML flow
file** that the existing [`runner/runner.py`](../runner/runner.py) executes
directly. You record once in the browser instead of hand-writing flow YAML.

## Files

| File | Role |
|---|---|
| `manifest.json` | MV3 manifest (popup + service worker + content script). |
| `recorder_export.js` | Pure step→YAML serializer (shared by popup and the validator). |
| `content.js` | Captures clicks/fills, builds stable selectors (GOAT ladder). |
| `background.js` | Service worker — recording state + tab-navigation steps. |
| `popup.html` / `popup.js` | Start / Stop / Clear / assertions / Export YAML UI. |
| `gen_sample.js` | Drives the real exporter for the validator (no browser). |
| `validate_export.sh` | `node --check` + export + runner-contract validation. |

## Install (load unpacked)

1. Open `chrome://extensions`.
2. Toggle **Developer mode** on (top right).
3. Click **Load unpacked** and select this `extension/` directory.
4. Pin the **SynthMK Recorder** action so the popup is one click away.

## Record → Export → Run

1. Navigate to the page you want to monitor.
2. Open the popup, click **● Start**. A teal "recording" badge appears on the page.
3. Drive the flow: click buttons/links, type into fields, change selects. Each
   interaction is captured (the popup step count ticks up). Navigations are
   recorded as `open_url` steps automatically.
4. Add checks with **Visible text**, **Title contains**, **URL contains** — each
   prompts for the expected value and inserts an assertion step at the end.
5. Click **■ Stop**, then **Export YAML**. Use **Copy** or **Download .yaml**.
6. Save the file under `flows/`, review it (templatize secrets as `{{ ENV_NAME }}`),
   then run it:

   ```bash
   export SYNTHMK_DEMO_URL="file://$PWD/flows/demo/index.html"
   python3 runner/runner.py flows/your-recorded-flow.yaml
   ```

   The runner emits one Checkmk local-check line (see [`../docs/flow-schema.md`](../docs/flow-schema.md)).

## Selector strategy (ported from GOAT)

`content.js getSelector()` is a port of GOAT's
`chrome-extension/content.js`, picking the most stable selector available:

1. `data-testid`
2. stable `id` (rejects UUID-ish `^[a-z]+-[a-f0-9-]+$`)
3. unique `name` on form controls
4. shortest unique class combination
5. `nth-of-type` parent-path fallback

## Recorded event → flow action mapping

| Recorded interaction | Flow action |
|---|---|
| navigation / tab URL change | `open_url` |
| click on a non-input element | `click` |
| input/change on a field | `fill` (templatize secrets as `{{ }}`) |
| manual assertion (popup) | `check_visible_text` / `check_title` / `check_url` |

## Validation

`validate_export.sh` is browser-free and CI-safe — it `node --check`s every JS
file, runs the **real** exporter over a sample session, and asserts the emitted
YAML parses through the runner's own `load_flow()` using only runner-known
actions:

```bash
bash extension/validate_export.sh
# … EXPORT VALIDATION OK
```

The generated sample lands at [`../flows/recorded-sample.yaml`](../flows/recorded-sample.yaml)
— note it is structurally identical to the hand-written
[`../flows/example-ok.yaml`](../flows/example-ok.yaml), confirming the recorder
targets the exact schema the runner already trusts.

## Security

The recorder never reads `.env` files or any secret store. Field values are
captured as typed; **review and templatize credentials as `{{ ENV_NAME }}`
before committing** a recorded flow (the runner resolves placeholders from env at
run time — see the flow schema's value-substitution section).
