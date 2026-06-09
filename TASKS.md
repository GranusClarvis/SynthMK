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

## Phase 2 — installable community addon

- [x] `[SYNTHMK_INSTALL_SKELETON]` idempotent, secret-free `install.sh` (install/uninstall/dry-run/DESTDIR) + `Makefile` placing runner/flows/check into predictable locations. → `install.sh`, `Makefile`
- [x] `[SYNTHMK_MKP_PACKAGING_SKELETON]` deterministic MKP-style package builder + metadata. → `packaging/build_mkp.sh`, `packaging/info.template`, `packaging/README.md` (byte-identical rebuild verified)
- [x] `[SYNTHMK_VALIDATE_ENTRYPOINT]` single `make validate` target proving runner output contract + recorder-exported YAML is runner-consumable. → `Makefile` (`validate` = `test_contract.py` + `extension/validate_export.sh`)
- [x] `[SYNTHMK_INSTALL_DOCS]` install/update/uninstall path for a Checkmk home lab. → `INSTALL.md`

## Phase 3 — community release quality

- [x] `[SYNTHMK_CI_CONTRACT]` single `make ci` / `scripts/ci.sh` entrypoint running all deterministic gates (validate, shell+JS syntax, package determinism, secret scan, version consistency). → `scripts/ci.sh`, `Makefile` (`ci`)
- [x] `[SYNTHMK_GITHUB_ACTIONS_CI]` GitHub Actions workflow running the same `make ci` contract on push/PR to main. → `.github/workflows/ci.yml`
- [x] `[SYNTHMK_RELEASE_DOCS]` changelog + release checklist preparing the v0.1.0 community release. → `CHANGELOG.md`, `RELEASE_CHECKLIST.md`
- [x] `[SYNTHMK_VERSION_CONSISTENCY_CHECK]` CI gate asserting `VERSION` == built `info.json` version == docs version refs. → `scripts/ci.sh` (version-consistency section)

## Phase 4 — release-readiness hardening

- [x] `[SYNTHMK_PACKAGE_PAYLOAD_CONTRACT]` [VERIFIED] payload contract test proving the built MKP contains the expected files at the expected install paths (executable local-check, runner/flows/demo payload, version-consistent metadata) and leaks no build junk — beyond byte-identical rebuild. → `packaging/test_package_contract.py`, wired into `scripts/ci.sh` (payload-contract gate) + `make package-contract`. (15/15 checks pass in `make ci`.)
- [x] `[SYNTHMK_FLOW_LINT]` [VERIFIED] static, browser-free flow linter (known actions, per-action required keys, `warn_ms<=crit_ms`, empty-steps) with clear messages + exit codes (0/2/3); lints every tracked flow in CI; runner↔linter action-table lockstep asserted in the contract suite. → `runner/flow_lint.py`, `make lint-flows`, `scripts/ci.sh` (flow-lint gate), tests in `runner/test_contract.py`.
- [x] `[SYNTHMK_FAILURE_MODE_DOCS]` [VERIFIED] operator-facing failure-mode + exit-code reference for the runner, linter, and package contract. → `docs/failure-modes.md`.

## First Acceptance Target

A sample flow can be executed locally and produces output like:

```text
0 "Synthetic Example Check" duration=1200ms;3000;7000 OK - Flow completed successfully
2 "Synthetic Example Check" duration=6500ms;3000;7000 CRIT - Expected text 'Dashboard' not found
```

