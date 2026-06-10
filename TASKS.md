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

## v0.5.0 — authoring & operations (released 2026-06-10)

- [x] `[SYNTHMK_SELECTOR_LADDERS]` [VERIFIED] selector fallback lists everywhere;
      recorder/importer/builder emit them. → `runner/runner.py`, contract suite.
- [x] `[SYNTHMK_STEP_BUILDER]` [VERIFIED live] point-and-click authoring on the
      node dashboard; every added step executes on the live page. →
      `runner-node/builder_session.py`, `/api/builder/*`, 21-check UI e2e.
- [x] `[SYNTHMK_DEVTOOLS_IMPORT]` [VERIFIED live] Chrome DevTools Recorder JSON
      import (CLI + dashboard upload); passwords discarded -> secret refs. →
      `runner/import_devtools.py`, `runner/test_import_e2e.py`.
- [x] `[SYNTHMK_SCRIPT_FLOWS]` [VERIFIED live] trust-gated Playwright Python
      checks (`run(page, api)`, SYNTHMK_ALLOW_SCRIPTS=1).
- [x] `[SYNTHMK_SUBFLOWS_TOTP_VARS]` include fragments, {{ totp.* }}, {{ var.* }},
      3 new assertions. All in the 15-flow live lab soak.
- [x] `[SYNTHMK_OPS_LAYER]` [VERIFIED] pause/resume, tags, version history +
      rollback, audit JSONL, viewer role. → 34-check admin HTTP suite.
- [x] `[SYNTHMK_MULTINODE_SPECIAL_AGENT]` special agent pulling several runner
      nodes ("locations") from the Checkmk side. → `checkmk/special/`.
- [x] `[SYNTHMK_THROUGHPUT_WATCHDOG]` saturation alarms even when fair
      round-robin hides per-flow lag. → scheduler self-service, stress test.

## v0.6.0 — verified end to end, enterprise hardening (this release)

- [x] `[SYNTHMK_MAX_ATTEMPTS]` [VERIFIED] retry-before-CRIT (1..3, capped,
      UNKNOWN never retried, attempts visible). → `runner.run_with_retries`.
- [x] `[SYNTHMK_REAL_MKP_CI]` Docker-gated CI job building + installing the
      real .mkp against an ephemeral Checkmk container. → `make real-mkp-ci`,
      `scripts/ci_real_mkp.sh`, `.github/workflows/real-mkp.yml`.
- [x] `[SYNTHMK_DASHBOARD_TLS_THROTTLE_CSP]` [VERIFIED] optional HTTPS for the
      dashboard, failed-login lockout, CSP + X-Frame-Options.
- [x] `[SYNTHMK_DASHBOARD_IMPORT]` [VERIFIED] "Import recording" upload on the
      dashboard -> `/api/import/devtools` -> lint-gated editor.
- [x] `[SYNTHMK_15FLOW_LIVE_SOAK]` [VERIFIED live] 15 concurrent distinct-shape
      checks green in Checkmk: Checkmk-UI login (piggybacked to host `cmk`),
      public journeys (example.com->IANA, Wikipedia), chromium/firefox/webkit,
      script flow, TOTP, ladders+include, forms, evidence. → `lab/flows/`.
- [x] `[SYNTHMK_RECORDER_E2E_TRIAD]` [VERIFIED live] all three authoring paths
      e2e in the runner image: extension (`extension/test_e2e.py`), DevTools
      import -> real run (`runner/test_import_e2e.py`), step builder UI
      (`runner-node/test_dashboard_e2e.py`, CSP-safe).
- [x] `[SYNTHMK_BUILDER_CSP_BYPASS]` builder authoring page sets bypass_csp so
      element picking works on CSP-strict sites (monitoring runs unaffected).

## v0.7.0 — cert + trace + store + soundness (this release)

- [x] `[SYNTHMK_CERT_CHECKS]` [VERIFIED live] `type: cert` TLS-expiry checks,
      cert_days_left metric, internal/self-signed CA fallback. → runner.py,
      flows/example-cert.yaml, lab/flows/cmk-cert.yaml.
- [x] `[SYNTHMK_TRACE_ARTIFACTS]` [VERIFIED live] `trace_on_failure` keeps a
      Playwright trace.zip; shot server serves .trace.zip with its token.
- [x] `[SYNTHMK_STORE_LISTINGS]` extension/store/ CWS+AMO package + website
      privacy page; manifest description fixed to the 132-char CWS limit.
      (Actual submission needs the operator's store accounts.)
- [x] `[SYNTHMK_SOUNDNESS_FIXES]` selector-ladder budget, retry state reset,
      include/script path confinement, importer candidate cap, graceful
      shutdown, builder SSRF blocklist, log token redaction, audit tail-read.

### Open (v0.8 candidates)

- [ ] `[SYNTHMK_BROKEN_LINKS_CHECK]` crawl-and-verify-links check type
      (the half of CERT_AND_LINKS not shipped in v0.7).
- [ ] `[SYNTHMK_FLOW_GROUPS]` serialized groups + lint-time interval math.
- [ ] `[SYNTHMK_AI_SCAFFOLD]` "describe the journey in English -> draft YAML"
      authoring assist (Checkly-style; authoring only, never the hot path).
- [ ] `[SYNTHMK_NODE_METRICS]` Prometheus /metrics on the node (runs, queue
      depth, browser RSS) for fleets that watch nodes outside Checkmk.
- [ ] `[SYNTHMK_SECRETS_BACKENDS]` optional Vault/SOPS secret sources behind
      the same {{ secret.* }} interface.
- [ ] `[SYNTHMK_HA_NODE_PAIR]` active/passive node pairing so one node's
      death does not blind the synthetic layer (special agent already
      tolerates a dead node loudly).

## First Acceptance Target

A sample flow can be executed locally and produces output like:

```text
0 "Synthetic Example Check" duration=1200ms;3000;7000 OK - Flow completed successfully
2 "Synthetic Example Check" duration=6500ms;3000;7000 CRIT - Expected text 'Dashboard' not found
```

