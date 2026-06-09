# GOAT Reference Notes

Initial inspection recovered these useful concepts:

- `chrome-extension/content.js` has selector priority logic:
  `data-testid`, stable IDs, named form fields, unique class combinations, and
  parent path fallback.
- `chrome-extension/background.js` maintains recording state, starts with a
  navigation step, records tab URL changes, and keeps the last stopped recording.
- GOAT records high-level steps instead of raw Playwright code. That aligns with
  SynthMK's readable flow-file goal.
- GOAT's runner concept maps steps to Playwright actions and records per-step
  durations and clear errors. SynthMK should keep that behavior but emit Checkmk
  states and perfdata as the primary output.

Non-goals for SynthMK MVP:

- Do not inherit GOAT's broader monitoring dashboard/admin-suite architecture.
- Do not build a cloud coordinator or remote runner network in iteration one.
- Do not force users to write arbitrary script blocks for basic checks.

