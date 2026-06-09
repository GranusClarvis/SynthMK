# SynthMK Task Track

Source of truth for autonomous scheduling is Clarvis
`memory/evolution/QUEUE.md`. This file mirrors the project-local direction.

## MVP

- `[SYNTHMK_GOAT_REFERENCE_AUDIT]` audit GOAT paths and extract reusable concepts.
- `[SYNTHMK_MVP_FLOW_SCHEMA]` define readable flow schema and examples.
- `[SYNTHMK_RUNNER_CHECKMK_OUTPUT]` build Chrome/Playwright runner with Checkmk output.
- `[SYNTHMK_CHECKMK_ADDON_SKELETON]` wire runner into Checkmk service result path.
- `[SYNTHMK_CHROME_RECORDER_MVP]` record clicks/fills/navigation/assertions into flow files.
- `[SYNTHMK_END_TO_END_DEMO]` prove flow -> runner -> Checkmk-compatible service result.
- `[SYNTHMK_FREE_PREMIUM_ROADMAP]` document free/community vs later premium boundaries.

## First Acceptance Target

A sample flow can be executed locally and produces output like:

```text
0 "Synthetic Example Check" duration=1200ms;3000;7000 OK - Flow completed successfully
2 "Synthetic Example Check" duration=6500ms;3000;7000 CRIT - Expected text 'Dashboard' not found
```

