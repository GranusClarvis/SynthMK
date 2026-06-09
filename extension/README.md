# SynthMK Chrome Recorder (placeholder — deferred)

The Chrome recorder is **out of scope for the MVP** (see
[`../docs/product-roadmap.md`](../docs/product-roadmap.md)). This directory is a placeholder that
captures the *target spec* so the recorder, when built, emits flow files this
repo's runner already understands.

## What the recorder must emit

YAML matching [`../docs/flow-schema.md`](../docs/flow-schema.md): a top-level
`name`/`warn_ms`/`crit_ms`/`steps`, where each step is one of `open_url`,
`click`, `fill`, `wait_for_element`, `check_visible_text`, `check_title`,
`check_url`.

## Selector strategy (adopt from GOAT)

Use GOAT's selector ladder verbatim — it produces stable selectors and is
documented with concrete paths in
[`../docs/goat-reference-audit.md`](../docs/goat-reference-audit.md):

1. `data-testid`
2. stable `id` (reject UUID-ish `^[a-z]+-[a-f0-9-]+$`)
3. unique `name` on form elements
4. shortest unique class combination
5. `nth-of-type` parent-path fallback

Reference implementation to port: GOAT `chrome-extension/content.js`
`getSelector()`. Recording lifecycle (navigation-first, retain last-stopped
steps): GOAT `chrome-extension/background.js` `recordingState`.

## Mapping recorded events → flow actions

| Recorded interaction | Flow action |
|---|---|
| navigation / tab URL change | `open_url` |
| click on non-input element | `click` |
| input/change on a field | `fill` (value `{{ }}`-templated for secrets) |
| explicit wait / appearance | `wait_for_element` |
| manual assertion (text/title/url) | `check_visible_text` / `check_title` / `check_url` |

No code is shipped here yet — intentionally. Build this only after the
flow→runner→Checkmk loop is trusted in a real home lab.
