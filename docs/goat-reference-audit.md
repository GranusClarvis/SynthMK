# GOAT Reference Audit

**Audited repo:** `/home/agent/agents/goat/workspace` (GOAT)
**Date:** 2026-06-09
**Purpose:** Extract reusable synthetic-monitoring concepts before building the
SynthMK MVP. GOAT is *inspiration*, not architecture — SynthMK keeps the Checkmk
user flow as its center of gravity and deliberately ignores GOAT's broader
admin-suite/dashboard ambitions.

## What GOAT is

GOAT is a full browser-automation product: a Chrome recorder extension, a
Next.js admin suite with a synthetic-monitoring subsystem, an agent installer,
and a `create-goat-app` scaffolder. Only a thin slice is relevant to SynthMK:
the **recorder → readable steps → Playwright runner** path.

## Reusable concepts (with concrete paths)

1. **Selector priority ladder** — `chrome-extension/content.js`, `getSelector()`
   (lines ~14-83). Priority order: `data-testid` → stable non-dynamic `id`
   (rejects `^[a-z]+-[a-f0-9-]+$` UUID-ish ids) → `name` attr for form elements
   (only if unique) → shortest unique class combination → `nth-of-type` parent
   path fallback. This is exactly the heuristic SynthMK's future recorder should
   emit, and it produces the kind of stable CSS selectors our flow `selector:`
   field expects.

2. **High-level recorded step model, not raw script** —
   `admin-suite/src/lib/synthetic/types.ts`, `RecordedStep` interface
   (lines ~20-30). Fields: `action`, `selector`, `value`, `waitFor`, `timeout`,
   `description`, `assertType` (`visible|text|value|url`), `assertValue`. SynthMK's
   YAML flow schema is a near-isomorphic, human-authorable version of this —
   readable steps instead of Playwright code, which is the core product promise.

3. **Step→Playwright action dispatch** —
   `admin-suite/src/lib/synthetic/runner.ts`, `executeStep()` (lines ~60-120).
   A `switch(step.action)` mapping `navigate→page.goto(waitUntil:'domcontentloaded')`,
   `click→page.click`, `type→page.fill`, etc., each wrapped with a per-step
   `timeout` (default `STEP_TIMEOUT = 10000`). SynthMK's `runner.py` mirrors this
   dispatch table directly.

4. **Per-step timing + structured result** — `types.ts` `TestStepResult`
   (`stepId`, `action`, `status`, `duration`, `error`, `screenshot`) and
   `TestResult` (total `duration`, `status`). GOAT times each step with
   `Date.now()` deltas. SynthMK reuses the per-step duration idea but the
   *total* `duration` is what feeds Checkmk perfdata (`duration=NNNms;warn;crit`).

5. **`{{ }}` value substitution for secrets/params** — `runner.ts`
   `resolveSecrets()` / `substituteSecrets()` (lines ~50-55) and `types.ts`
   comment "secret ref like `{{secret:password}}`". SynthMK adopts the
   `{{ name }}` placeholder convention in flow `value:` fields (see
   `flows/example-login.yaml`), though MVP resolves them from env, not GOAT's
   encrypted store.

6. **Recording lifecycle = navigation-first + last-stopped retention** —
   `chrome-extension/background.js`, `recordingState` (lines ~8-16) and
   `START_RECORDING` (line ~42) seed the recording with the active tab URL as the
   first step and retain `lastRecordedSteps` after stop. SynthMK's flow files
   already start with an `open_url`/`start_url`; the "first step is the
   navigation" convention is worth keeping for the future recorder.

7. **Screenshot-on-step metadata** — `TestStepResult.screenshot?: string` path
   field. SynthMK exposes this as optional `screenshot_on_failure` flow metadata
   so a failing Checkmk service can point at evidence without making screenshots
   mandatory.

## Non-goals (what SynthMK explicitly rejects from GOAT)

1. **The admin-suite dashboard / Next.js UI** (`admin-suite/`) — GOAT renders
   results in a web app with feature flags (`src/lib/feature-flags.ts`), a result
   store, and scheduling UI. SynthMK has *no* dashboard: Checkmk **is** the UI.
   Results are a single stdout line in local-check format.

2. **Encrypted secret store + crypto layer** (`runner.ts` imports
   `decryptSecret`, `getSecret` from `./store` and `../crypto`). Overkill for a
   home-lab MVP. SynthMK resolves `{{ }}` placeholders from environment variables
   and never writes a secret store; `.env`/`*.key`/`*credentials*` are gitignored.

3. **Raw-Playwright "script mode"** — GOAT's `SyntheticTest.mode = 'script'` with
   an `AsyncFunction`-eval'd `script` string (`runner.ts` header comment). This is
   precisely the thing SynthMK promises users they will *not* have to write. MVP
   is steps-only; no arbitrary code execution path.

4. **Cron scheduler / agent installer / remote runner fleet** (`agent/install.sh`,
   `SyntheticTest.schedule` cron field, `create-goat-app` scaffolder). SynthMK
   delegates scheduling entirely to Checkmk's existing local-check interval —
   no separate scheduler, no coordinator, no remote runner network in iteration one.

## Update (v0.2.0): the runner node, Checkmk-native

GOAT's strongest idea for our use case is the **remote runner that executes flows
from inside the network** (so internal-only sites can be checked). SynthMK adopts
*that idea* but **not GOAT's mechanism**. Where GOAT uses a Next.js admin-suite
coordinator that remote agents poll, SynthMK's `runner-node/` appliance is purely
Checkmk-native:

- a lightweight **scheduler** writes results to the Checkmk **spool directory**
  (so slow browser runs never block agent collection — the scaling story), and
- **piggyback** (`checkmk/piggyback_wrap.sh`) attributes each result to its target
  host, so one node serves many "sites" — GOAT's "locations" without a coordinator.

Checkmk remains the UI, the scheduler of record, and the alerting engine. There is
still **no central SynthMK service** to run — the rejection of GOAT's admin-suite
(non-goal #1) stands. A multi-node *fleet* (special-agent pull) remains future work.

## How this shapes the SynthMK MVP

- Flow schema = a readable YAML projection of GOAT's `RecordedStep`.
- `runner.py` = a Python port of `executeStep`'s dispatch table, but its *output
  contract* is Checkmk local-check format, not a `TestResult` JSON object.
- Selector ladder from `content.js` is the recorder's future spec, captured here
  so the (deferred) Chrome recorder has a target.
- Everything dashboard/scheduler/secret-store in GOAT is deliberately dropped.
