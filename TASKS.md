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

## v0.2.0 — LAN runner node, real MKP, screenshots

- [x] `[SYNTHMK_SCHEMA_PIGGYBACK_PSTATE_SHOTS]` runner+lint: `checkmk_host` piggyback,
      `state_mode: dynamic` (`P`), clickable screenshot links, `SYNTHMK_NO_SANDBOX`.
      → `runner/runner.py`, `runner/flow_lint.py`, `checkmk/piggyback_wrap.sh`,
      `runner/test_contract.py` (27 checks), `docs/flow-schema.md`.
- [x] `[SYNTHMK_RUNNER_NODE_APPLIANCE]` Docker appliance: scheduler→spool dir (scales),
      socat agent transport, screenshot server. → `runner-node/`.
- [x] `[SYNTHMK_LAN_LAB]` self-hosted Checkmk Raw + runner + internal demo site;
      verified E2E (real Chromium → discovery → live OK/CRIT → screenshot).
      → `lab/`, `docs/lan-quickstart.md`, `docs/architecture.md`.
- [x] `[SYNTHMK_REAL_MKP]` genuine installable `.mkp` via the site's `mkp` tool;
      verified install on Checkmk Raw 2.3.0p48. → `packaging/make_real_mkp.sh`,
      `make real-mkp`.
- [x] `[SYNTHMK_POSITIONING]` README vs Robotmk; roadmap + GOAT-audit updates;
      CI lints `lab/flows/`; `make` runner-image/lab targets; VERSION 0.2.0.

## v0.3.0 — enterprise hardening: secrets, scale, TLS, recorder UX

- [x] `[SYNTHMK_BROWSER_AND_STEPS_EXPANSION]` [VERIFIED] press/select_option/hover/
      scroll_into_view/wait_ms/wait_for_url/check_element_count + `optional: true`
      steps; Playwright errors → CRIT with step name + screenshot; per-step timing
      perfdata. → `runner/runner.py`, `runner/flow_lint.py`, 55-check contract suite.
- [x] `[SYNTHMK_SECRET_SOURCE]` [VERIFIED] `{{ secret.NAME }}` from chmod-600
      secrets file, refusal on loose perms, hard-UNKNOWN on missing names, global
      output redaction, sensitive-fill screenshot masking. → `runner/secret_source.py`.
- [x] `[SYNTHMK_SCHEDULER_POOL]` [VERIFIED] worker-pool scheduler with stagger,
      overlap suppression, hard timeouts, hot reload, warmup lines
      (= `SYNTHMK_FIRST_RUN_WARMUP`), `SynthMK Scheduler` self-monitoring service.
      → `runner-node/scheduler.py`. Scale-tested: 60 flows, 37 runs/min, 0 overdue.
- [x] `[SYNTHMK_SHOT_AUTH]` [VERIFIED] HMAC-token screenshot server, no listing,
      traversal-safe, /healthz; runner signs links. → `runner-node/shot_server.py`.
- [x] `[SYNTHMK_AGENT_TLS_REGISTRATION]` [VERIFIED] official version-matched agent
      + cmk-agent-ctl TLS via one-command `register_agent.sh`; container socket
      shim; `SYNTHMK_AGENT_MODE=official`. Live TLS pull verified vs Raw 2.3.0p48.
- [x] `[SYNTHMK_RECORDER_UX]` [VERIFIED] live step list + delete, check settings,
      password→`{{ secret.* }}`+sensitive (value never leaves the page), Enter→press,
      select→select_option, MV3 state-race fix; real-browser E2E
      (`extension/test_e2e.py`) green.
- [x] `[SYNTHMK_PROD_DEPLOY]` hardened `runner-node/compose.yaml` (limits,
      no-new-privileges, healthcheck, secrets mount), non-root browser execution.
- [x] `[SYNTHMK_RESEARCH_LANDSCAPE]` competitive research folded into
      `docs/competitive-landscape.md` (+ full reports in docs/).
- [x] `[SYNTHMK_REAL_FLOWS]` Wikipedia (live-verified), Google template
      (bot-block documented), lab login→dashboard journey E2E through Checkmk.

## v0.4.0 — native plugin, node dashboard, multi-browser recorder, website

- [x] `[SYNTHMK_NATIVE_PLUGIN]` [VERIFIED] JSON `<<<synthmk>>>` section + agent-based
      v2 check plugin + rulesets v1 (Setup GUI thresholds, live-verified override)
      + graphing v1 (duration metric/graph/perf-o-meter). → `checkmk/plugin/`.
- [x] `[SYNTHMK_NODE_DASHBOARD]` [VERIFIED] token+CSRF web UI on :9181 — live check
      table, run-now, lint-gated flow editor. → `runner-node/admin_server.py`.
- [x] `[SYNTHMK_BROWSER_PACKAGES]` Chrome/Edge + Firefox builds with icons.
      → `extension/build.sh`, `manifest.firefox.json`.
- [x] `[SYNTHMK_SHOT_URL_LAN]` lab screenshot links default to the host LAN IP.
- [x] `[SYNTHMK_WEBSITE]` SynthMK-Web repo, GitHub Pages, real lab screenshots.
- [x] `[SYNTHMK_RELEASES]` v0.3.0 + v0.4.0 tagged and released with assets.

### Open (v0.5 candidates — see docs/competitive-landscape.md roadmap)

- [ ] `[SYNTHMK_MULTINODE_SPECIAL_AGENT]` special agent pulling several runner
      nodes ("locations") from the Checkmk side.
- [ ] `[SYNTHMK_REAL_MKP_CI]` Docker-gated CI job building + installing the real
      .mkp against an ephemeral Checkmk container.
- [ ] `[SYNTHMK_CERT_AND_LINKS_CHECKS]` cert-expiry + broken-links check types.
- [ ] `[SYNTHMK_TRACE_ARTIFACTS]` Playwright trace.zip on failure next to PNGs.
- [ ] `[SYNTHMK_MAX_ATTEMPTS]` retry-before-CRIT with visible attempt count.
- [ ] `[SYNTHMK_FLOW_GROUPS]` serialized groups + lint-time interval math.

## First Acceptance Target

A sample flow can be executed locally and produces output like:

```text
0 "Synthetic Example Check" duration=1200ms;3000;7000 OK - Flow completed successfully
2 "Synthetic Example Check" duration=6500ms;3000;7000 CRIT - Expected text 'Dashboard' not found
```

