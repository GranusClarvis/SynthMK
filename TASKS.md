# SynthMK Task Track

Source of truth for autonomous scheduling is Clarvis
`memory/evolution/QUEUE.md`. This file mirrors the project-local direction.

## MVP

- [x] `[SYNTHMK_GOAT_REFERENCE_AUDIT]` audit GOAT paths and extract reusable concepts. → `docs/goat-reference-audit.md`
- [x] `[SYNTHMK_MVP_FLOW_SCHEMA]` define readable flow schema and examples. → `docs/flow-schema.md`, `flows/`
- [x] `[SYNTHMK_RUNNER_CHECKMK_OUTPUT]` build Chrome/Playwright runner with Checkmk output. → `runner/runner.py`
- [x] `[SYNTHMK_CHECKMK_ADDON_SKELETON]` wire runner into Checkmk service result path. → `checkmk/`
- [x] `[SYNTHMK_CHROME_RECORDER_MVP]` record clicks/fills/navigation/assertions into flow files. → `extension/` (MV3: manifest, content/background/popup, `recorder_export.js`), validated by `extension/validate_export.sh` → `flows/recorded-sample.yaml`.
- [x] `[SYNTHMK_END_TO_END_DEMO]` prove flow -> runner -> Checkmk-compatible service result. → `docs/home-lab.md`, `runner/test_contract.py`, `runner/smoke_test.sh`
- [x] `[SYNTHMK_FREE_PREMIUM_ROADMAP]` document free/community vs later premium boundaries. → `docs/product-roadmap.md`

## First Acceptance Target

A sample flow can be executed locally and produces output like:

```text
0 "Synthetic Example Check" duration=1200ms;3000;7000 OK - Flow completed successfully
2 "Synthetic Example Check" duration=6500ms;3000;7000 CRIT - Expected text 'Dashboard' not found
```

