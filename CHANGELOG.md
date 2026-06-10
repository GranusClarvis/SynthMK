# Changelog

All notable changes to SynthMK are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); SynthMK uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed (runner hardening)
- **Capability floor on the runner container.** Both compose files (production
  `runner-node/compose.yaml` and `lab/docker-compose.yml`) and the raw
  `docker run` example now `cap_drop: ALL` and re-add only the five caps the
  root→`pwuser` privilege drop requires (`CHOWN, DAC_OVERRIDE, FOWNER, SETUID,
  SETGID`). `NET_RAW` is gone, so a hostile flow target cannot make the node
  craft raw packets to port-scan the internal range (verified: `SOCK_RAW`
  creation returns `EPERM` under the new cap set on `synthmk-runner:0.7.0`).
- **Seccomp posture documented.** Docker's default seccomp profile is retained
  (never `seccomp:unconfined`); `--no-sandbox` Chromium does not need a relaxed
  profile, unlike Chromium's own sandbox.
- **PID limit** (`deploy.resources.limits.pids: 1024` / `--pids-limit 1024`) as
  a fork-bomb ceiling for the browser pool, alongside the existing cpu/memory caps.

### Docs
- **Trust boundary section** in `runner-node/README.md`: `flows/` + `flows.conf`
  are operator-only inputs with no untrusted-submission path; a flow can reach
  internal hosts (SSRF/scan) and run code as `pwuser` by design, so flow
  authoring must never be exposed to untrusted users. Residual-risk table in
  `docs/STATUS.md` updated to match.

## [0.7.0] - 2026-06-10

New check types and artifacts, the extension store package, and a round of
fixes from an adversarial soundness review of the engine and node services.

### Added
- **Certificate checks** (`type: cert`): browser-free TLS expiry monitoring.
  Reports a `cert_days_left` metric and alarms as the remaining days cross
  `warn_days`/`crit_days`. Monitors internal-CA and self-signed certificates
  too (falls back to openssl and notes an unverified chain); set
  `require_valid_chain: true` to also fail when the chain does not verify.
- **Trace artifacts** (`trace_on_failure: true`): a failing browser flow keeps
  a Playwright trace.zip next to the failure screenshot, served by the node's
  authenticated shot server and linked from the failing service (open at
  trace.playwright.dev). Off by default.
- **Extension store package** (`extension/store/`): Chrome Web Store and
  Firefox AMO listing copy, per-permission justifications, a submission
  runbook, and a privacy policy, plus a privacy page on the website. Fixed the
  manifest description to the 132-char CWS limit found during the pass.

### Fixed (adversarial soundness review)
- Selector fallback ladders now return the remaining time budget, so a slow
  ladder no longer hands the following action a second full timeout. One step
  stays inside one budget.
- `run_with_retries` resets the per-process secret/variable state between
  attempts: each retry gets a fresh `{{ var.uuid }}` and its failure message
  is not masked by a previous attempt's secret.
- `include` and script paths are confined to the flow's own directory tree
  (symlink-aware), so a flow cannot splice steps or load code from outside it.
- The DevTools importer caps selector candidates (8 per element, 200 scanned)
  against a hostile or pathological recording.
- Container shutdown is graceful: the entrypoint no longer `exec`s the agent
  transport, so its trap forwards SIGTERM to the scheduler, dashboard and shot
  server and waits for them, and the scheduler sweeps stale spool `.tmp` files
  on start. No more truncated spool or audit lines on stop.
- The visual builder refuses loopback, link-local, private and cloud-metadata
  URLs by default (SSRF hardening; opt out with
  `SYNTHMK_BUILDER_ALLOW_INTERNAL=1`).
- The login token is redacted from request logs, and the audit endpoint reads
  only the tail of the log instead of the whole file.

### Verified live (0.7.0 image, lab stack)
- 17 concurrent checks green, including the new cert check (cert_days_left in
  the spool and as a Checkmk service) and a trace-on-failure demo whose
  trace.zip downloads from the shot server with its token (403 without).
- Graceful shutdown confirmed: `docker stop` triggers the entrypoint's
  shutdown handler.
- All three authoring paths e2e on the 0.7.0 image (extension, DevTools
  import, step builder). Contract suite 145, admin HTTP suite 40.

## [0.6.0] - 2026-06-10

The verification and hardening release: everything proven live against a full
Checkmk stack, plus the operational features an enterprise rollout asks for
first.

### Verified end to end (all live on the lab stack, 2026-06-10)
- **15 concurrent checks of distinct shapes, all green in Checkmk itself**:
  a journey that logs into the Checkmk web UI (piggybacked to the `cmk`
  host), public journeys that tolerate headless runners (example.com to
  IANA, Wikipedia search), Chromium, Firefox and WebKit engines, the script
  flow, TOTP entry, selector ladders + shared include fragment, checkbox and
  attribute assertions, per-run unique values, negative text assertions and
  always-on evidence capture. Verified at the spool, at the agent, and as
  discovered services on three Checkmk hosts. New lab pages and flows ship
  in `lab/`.
- **All three authoring paths e2e in the runner image**: recorder extension
  (`extension/test_e2e.py`), DevTools recording import then a REAL browser
  run of the imported flow (`runner/test_import_e2e.py`, proves the recorded
  password plaintext is discarded and the flow passes), and the step builder
  UI (`runner-node/test_dashboard_e2e.py`, 21 checks, now CSP-safe).
- Scheduler stress re-run on this release: 150 flows sustained plus the
  deliberate-overload phase, 8/8.
- Real-browser scale test re-run at 60 flows on the new image.

### Added
- **`max_attempts` (1..3)**: a CRIT/WARN outcome re-runs with a fresh
  browser before the service alarms; UNKNOWN (operator error) never
  retries; the attempt count is visible in the summary, so a flapping check
  looks flapping. Lint-validated.
- **Dashboard HTTPS**: set `SYNTHMK_ADMIN_TLS_CERT`/`SYNTHMK_ADMIN_TLS_KEY`
  (PEM) and the dashboard serves TLS 1.2+ with a Secure session cookie.
- **Failed-login lockout**: five bad sign-ins from one address lock
  `/api/login` for 60 seconds (tunable); attempts and lockouts are audited.
- **Content-Security-Policy** and `X-Frame-Options: DENY` on all dashboard
  HTML. This also exposed a real builder limitation: element inspection ran
  in the page main world, where a strict target-site CSP could veto it. The
  builder's authoring page now sets `bypass_csp`; scheduled monitoring runs
  keep a normal page so checks observe real site behavior.
- **Import recording button** on the dashboard: upload a DevTools Recorder
  JSON, the converted flow opens in the lint-gated editor with the
  importer's notes shown.
- **Ephemeral real-MKP CI** (`make real-mkp-ci`, `scripts/ci_real_mkp.sh`,
  optional GitHub workflow): builds the real .mkp against a throwaway
  Checkmk Raw container and proves `mkp add` + `mkp enable` succeed.

### Changed
- Service summaries, lint messages and dashboard strings no longer use em
  dashes (the website was rewritten the same way).
- Lab schedule now carries 15 flows with tags; demo site gained a settings
  page (checkboxes, select, MFA field) for live form-assertion coverage.
- Contract suites: runner 120 to 128 checks, admin HTTP 26 to 34 (import
  endpoint, CSP headers, lockout, TLS).

## [0.5.0] - 2026-06-10

The authoring & operations release: four ways to create a check (record /
import / build visually / write YAML or Playwright code), and a node you can
operate like a fleet appliance (pause, tags, history, audit, roles) — plus
multi-node locations.

### Added — authoring
- **Selector fallback ladders**: every `selector:` accepts a list tried in
  order (multi-locator anti-flake — a redesign that breaks the CSS path still
  matches the test attribute). Runner resolves the first matching candidate;
  the linter validates ladders; recorder, importer and builder emit them.
- **Visual step builder** on the node dashboard (`runner-node/builder_session.py`
  + `/api/builder/*`): open a live page, click elements in the preview
  (Chrome-inspect style) → verified-unique selector ladder + suggested action
  (inputs→fill, passwords→secret refs, selects→select_option with real
  options, text→assertion) → **every added step executes immediately on the
  live page** (added = tested) → replay → export into the lint-gated editor.
  One token+CSRF-gated session per node; idle worker reaped after 10 min.
- **Chrome DevTools Recorder import** (`runner/import_devtools.py`): converts
  the JSON every Chrome can record (F12 → Recorder → export) into a flow —
  no extension needed on the recording machine. DevTools `selectors[]` arrays
  become fallback ladders; recorded password plaintext is **discarded** and
  replaced with `{{ secret.* }}` + `sensitive: true`; unsupported step types
  are skipped with notes; output linted before write. 25-check importer
  contract suite wired into `make validate`.
- **Script flows** (`type: script` + `script: x.py`): full Playwright Python
  `run(page, api)` for journeys YAML can't express — named per-step timings
  (`api.step`), auto-redacted `api.secret()`, `api.totp()`, `api.var()`,
  masked `api.screenshot()`, clean CRIT/UNKNOWN mapping (assertions, fails,
  syntax errors — never tracebacks). **Trust-gated: off unless
  `SYNTHMK_ALLOW_SCRIPTS=1`.** Template: `flows/example-script.yaml`.
- **Sub-flows**: `action: include, flow: shared/login.yaml` splices a
  reusable fragment (shared login) — cycle-safe, ≤3 levels, ≤200 expanded
  steps; the linter follows and lints included files (`--base-dir`).
- **MFA/TOTP secrets**: `{{ totp.NAME }}` derives the current RFC 6238 code
  from a base32 seed stored in the secrets file (stdlib-only; seed redacted
  like any credential). Monitors MFA-protected logins.
- **Builtin variables**: `{{ var.uuid }}`, `{{ var.timestamp }}`,
  `{{ var.random }}` — per-run stable (type it, then assert it echoed).
- **New assertions**: `check_text_absent` (assert error banners are NOT
  shown), `check_element_attribute` (present/equals/contains),
  `check_checkbox` (checked state).

### Added — operations
- **Pause/resume** from the dashboard: pausing rewrites the flows.conf line
  with a `#PAUSED ` prefix — a comment to the scheduler (zero special-casing),
  structured state to the dashboard, schedule preserved for resume.
- **Tags**: `tags=payments,critical` conf token; shown as pills in the table,
  edited in the editor (scheduler tolerates and ignores them).
- **Flow version history + rollback**: every dashboard save snapshots the
  prior content (`flows/.history`, keep `SYNTHMK_HISTORY_KEEP`=10); view any
  version and roll back (lint-gated) from the editor.
- **Audit trail**: append-only JSONL (`SYNTHMK_AUDIT_LOG`, default
  `/var/log/synthmk-audit.log`, pre-created pwuser-owned) of every login
  attempt and state change — who/when/what/from-where; `/api/audit` (admin).
- **Viewer role**: `SYNTHMK_VIEWER_TOKEN` = read-only sign-in (live table,
  YAML, history; every write refused + write UI hidden).
- Scheduler: `SYNTHMK_RUNNER_CMD` stub hook for browser-free stress testing.

### Tests
- Runner contract suite 69 → **120 checks**; importer **25**; dashboard HTTP
  contract **26** (`runner-node/test_admin_contract.py`: auth+roles, lint
  gate, history/rollback, pause, audit) — all in `make validate`.
- **Dashboard UI e2e, 21 checks** (`runner-node/test_dashboard_e2e.py`, real
  Chromium in the runner image): sign-in → builder point-and-click on a live
  preview → tested steps (click/fill/select/assert) → failing step rejected →
  export → lint & save → appears in table → pause. All green 2026-06-10.
- **Scheduler stress** (`runner-node/stress_test.py`): 150 flows sustained
  (4× the documented envelope) with hot-reload and run-now under load, plus a
  deliberate overload phase asserting the node **alarms loudly** (scheduler
  self-service → WARN with overdue count) instead of degrading silently.

### Added — platform
- **Multi-node "locations" special agent** (`checkmk/special/agent_synthmk.py`,
  `checkmk/plugin/{rulesets/special_agent_synthmk,server_side_calls/synthmk}.py`,
  `runner-node/admin_server.py` `/api/results`): a Checkmk datasource program
  that runs on the Checkmk server and *pulls* flow results from one or more
  runner-node HTTP endpoints, so several runners on different network segments —
  each reachable only from the server — feed **one** configured host. Each node
  exposes a read-only `/api/results` feed (scoped `SYNTHMK_RESULTS_TOKEN` or the
  admin token); the agent re-emits each node's native `<<<synthmk:sep(0)>>>`
  section (the bundled check plugin is unchanged), piggybacking flows to their
  `checkmk_host` and adding a `SynthMK Node <name>` connectivity service that
  goes CRIT when a runner is unreachable. The agent always exits 0 so one dead
  node can't blank the others. Setup GUI: "SynthMK runner nodes (multi-node
  locations)". Ships in the MKP at the cmk_addons libexec path (mode 0755).
  Test: `checkmk/special/test_agent_synthmk.py` (two fake nodes → one host,
  piggyback routing, CRIT-on-unreachable, real-plugin parse) — wired into
  `scripts/ci.sh` and `packaging/test_package_contract.py`.
- **Multi-browser engine + expanded step vocabulary** (`runner/runner.py`,
  `runner/flow_lint.py`): the flow `browser:` field now selects the engine —
  `firefox`, `webkit`/`safari`, `edge`/`msedge` (Edge release channel, degrades
  to bundled Chromium if absent), in addition to `chromium`/`chrome` (bundled).
  Unknown values fall back to Chromium. Two new steps: `wait_for_network_idle`
  (Playwright `networkidle`, timeout-guarded) and `screenshot` (always-on,
  credential-masked evidence capture). Linter and runner dispatch stay in
  lockstep; `browser:` values are lint-validated. Example: `flows/example-firefox.yaml`.
  `runner/test_contract.py` 55→69 checks (engine resolution, both new steps,
  no-regression on `browser: chrome` → bundled chromium).
- **Local-check first-run warmup** (`checkmk/synthmk_check.sh`): the empty-output
  fallback no longer hard-codes a `SynthMK <file>` UNKNOWN name (which Checkmk
  discovery would lock in). It now resolves the flow's real `name:` and emits
  `OK - warming up` on the first ever empty run, `UNKNOWN` only after a real
  result has been seen — so cold-start discovery captures the right service name
  (matches the runner-node scheduler's existing `emit_warmup`).
- **Bake the official Checkmk agent into the image** (`runner-node/Dockerfile`):
  optional `--build-arg CMK_AGENT_DEB=<site agent .deb url>` installs the
  version-matched official agent + `cmk-agent-ctl` (TLS controller) at build
  time, so production runner nodes carry the encrypted transport with zero
  runtime download. Default empty → lab socat path unchanged; `register_agent.sh`
  remains the runtime install/registration alternative. The per-site TLS
  *registration* stays a one-time runtime step (an image can't bind a site cert).
  Entrypoint's `official`-mode error and `runner-node/README.md` now document
  both routes. `docker build --check` clean.

## [0.4.0] — native Checkmk plugin, node dashboard, multi-browser recorder, website

The "real product" release: SynthMK is now a genuine Checkmk plugin with
settings in the Setup GUI and first-class graphs, the runner node grew a
management dashboard, the recorder ships for Chrome, Edge and Firefox, and
the project has a website: https://granusclarvis.github.io/SynthMK-Web/

### Added
- **Native Checkmk check plugin** (`checkmk/plugin/`, ships in the MKP):
  the runner node emits a JSON `<<<synthmk:sep(0)>>>` section (runner
  `--json`); an agent-based v2 plugin renders every journey as a first-class
  service — unit-aware duration metric in seconds with warn/crit bands,
  per-step metrics, step breakdown + screenshot link in the details, and a
  human summary ("Journey duration: 239 milliseconds"). Verified live: rule
  override flipped a service CRIT from the GUI.
- **Setup ruleset** ("SynthMK synthetic browser checks", rulesets v1):
  override journey duration thresholds per service/host/folder from Checkmk —
  no flow-file edit, no node access.
- **Graphing definitions** (graphing v1): registered duration metric, named
  graph, perf-o-meter on every service row.
- **Node management dashboard** (`runner-node/admin_server.py`, :9181):
  token sign-in (CSRF-guarded, constant-time compares), live check table
  (state badges, per-step timings, schedule, last-run age, screenshot links),
  one-click run-now, and a flow editor that lints before every save —
  invalid YAML is rejected with the linter's messages. Degrades to view-only
  on read-only flow mounts. `SYNTHMK_ADMIN=off` disables it.
- **Run-now triggers**: the scheduler watches a trigger directory; the
  dashboard queues immediate runs without restarts.
- **Multi-browser recorder packages** (`extension/build.sh`): icons, Chrome +
  Edge package and a Firefox MV3 variant (gecko event page), built to
  `dist/synthmk-recorder-{chrome,firefox}-<version>.zip`.
- **Website** (separate repo SynthMK-Web, GitHub Pages): landing with real
  lab screenshots, vs-Robotmk comparison, quickstart, downloads, full docs.
- CI: python-syntax gate for all tracked `.py` (the site-side plugin must
  always parse); MKP payload contract covers the plugin family files.

### Changed
- `SYNTHMK_OUTPUT=native` is the node default (the MKP ships the plugin);
  `SYNTHMK_OUTPUT=local` keeps the v0.3 `<<<local>>>` lines for sites
  without it. Re-run service discovery after upgrading.
- `make lab-up` defaults the screenshot base URL to the host's LAN IP, so
  links in Checkmk work from other machines (was: localhost).
- Lab compose publishes the dashboard (:9181) and mounts flows writable so
  the editor can be demonstrated; extension manifest carries icons + 0.4.0.

## [0.3.0] — enterprise hardening: secrets, scale, TLS, recorder UX

The "trust it with production checks" release: secure credentials end to end,
a scheduler measured at 60 flows on one node, an authenticated screenshot
server, a TLS agent transport, and a recorder that never sees your passwords.
Everything below verified live against Checkmk Raw 2.3.0p48 (see
`docs/STATUS.md` for the test evidence).

### Added
- **Secret store for login flows** (`runner/secret_source.py`):
  `{{ secret.NAME }}` resolves from a node-local YAML secrets file
  (`--secrets-file` / `$SYNTHMK_SECRETS_FILE`) that must be chmod 600 — looser
  permissions are refused before the browser ever launches. Missing secrets are
  a hard UNKNOWN with no value leaked; **every resolved value is redacted to
  `***` in all service output**. `sensitive: true` fills additionally blank all
  form fields before a failure screenshot is captured.
- **Expanded step vocabulary**: `press`, `select_option`, `hover`,
  `scroll_into_view`, `wait_ms`, `wait_for_url`, `check_element_count`, and
  `optional: true` on any step (cookie-consent clicks). Raw Playwright errors
  (click timeout, bad selector) now surface as `CRIT - Step N (<action>)
  failed: …` with screenshot instead of UNKNOWN.
- **Per-step timing perfdata**: every service line carries
  `stepN_<action>=<ms>ms` metrics — Checkmk graphs where time goes inside the
  journey.
- **Worker-pool scheduler** (`runner-node/scheduler.py`, replaces the bash
  loop): `SYNTHMK_MAX_CONCURRENCY` (default 4), startup stagger, overlap
  suppression, hard per-run timeout, hot config reload, **warmup lines** (every
  flow is discoverable under its real service name immediately at node start),
  and a **`SynthMK Scheduler` self-monitoring service** that WARNs on the node
  when flows go overdue. Measured: 60 flows / 37 runs/min sustained on default
  sizing with zero overdue (docs/scaling.md).
- **Authenticated screenshot server** (`runner-node/shot_server.py`, replaces
  `python -m http.server`): per-file HMAC token URLs signed with an
  auto-generated 0600 node key, no directory listing, traversal-safe, PNG-only,
  `/healthz` endpoint (wired as the container HEALTHCHECK). The runner appends
  matching `?t=` tokens to screenshot links automatically.
- **TLS agent transport** (`runner-node/register_agent.sh`,
  `SYNTHMK_AGENT_MODE=official`): one command downloads the site's
  version-matched agent .deb, installs it, and registers `cmk-agent-ctl`;
  the entrypoint provides the agent socket in containers (no systemd needed).
  Verified live: TLS pull with site-CA certificate, spool sections intact.
- **Recorder extension UX overhaul**: live editable step list with per-step
  delete, check settings (service name, WARN/CRIT thresholds, screenshot
  toggle) persisted across popup opens, name-derived download filename — and
  **credential hygiene**: typing into a password field records
  `{{ secret.<field> }} + sensitive: true`; the typed value never leaves the
  page. Enter keypresses → `press`, `<select>` → `select_option`. New
  real-browser E2E (`extension/test_e2e.py`) loads the extension in Chromium,
  records the lab login journey and asserts the export lints clean. Fixed an
  MV3 state race that could drop a recorded step when two events landed
  back-to-back.
- **Production deployment template** (`runner-node/compose.yaml`): resource
  limits sized to the pool, `no-new-privileges`, healthcheck, secrets mount,
  named volumes incl. TLS registration state.
- **Real-world example flows**: `flows/wikipedia-search.yaml` (verified live),
  `flows/google-search.yaml` (consent-click template + documented bot-block
  caveat), and the lab's flagship 10-step `intranet-login.yaml` (secrets,
  hover, select, element count) against a new multi-page demo app
  (login → dashboard).
- **Scale test harness** (`scripts/scale_test.sh`) + capacity formula and
  measured results (`docs/scaling.md`).
- **Competitive research** (`docs/competitive-landscape.md` + full reports):
  what v0.3 adopts from New Relic, Checkly, Grafana SM, Robotmk, Elastic — and
  what it deliberately rejects.

### Changed
- **Browser/HTTP processes run as the unprivileged `pwuser`** in the appliance
  (entrypoint drops from root via setpriv); bind-mounted secrets are staged to
  a runner-owned 0600 copy at start.
- The linter knows all new actions/fields and warns when a fill references
  `{{ secret.* }}` without `sensitive: true`; the recorder exporter's action
  table is asserted against the linter's in CI.

### Security
- Closes v0.2 STATUS.md findings #1 (screenshot credential capture — masked),
  #2 (open screenshot server — token auth), #3 (plaintext agent — TLS path),
  #4 (env-only secrets — permission-checked file + redaction), #6/#7 (no
  limits / root browser — shipped limits + privilege drop).

## [0.2.0] — LAN runner node, real MKP, screenshots

Makes SynthMK deployable in a real LAN: one runner node inside the intranet runs
many browser checks against internal-only sites and reports to a self-hostable
Checkmk. Verified end-to-end against Checkmk Raw 2.3.0p48 (real Chromium →
discovered services → live OK/CRIT → screenshot link → installable MKP).

### Added
- **Runner-node Docker appliance** (`runner-node/`): a single container you host
  in the intranet — scheduler running flows on independent intervals into the
  Checkmk **spool directory** (scales to many/long checks), socat **agent
  transport** on 6556, and a screenshot HTTP server. Dockerfile + entrypoint +
  scheduler + `flows.conf` config + README.
- **Self-hosted LAN lab** (`lab/`): `docker compose` of Checkmk Raw +
  runner-node + an internal-only nginx demo site, plus
  `docs/lan-quickstart.md` (add host → discover → break → CRIT + screenshot).
- **Real, installable MKP** (`packaging/make_real_mkp.sh`, `make real-mkp`):
  builds a genuine `info` + `info.json` + member-tarball `.mkp` via a running
  Checkmk site's own `mkp` tool. `build_mkp.sh` stays as the deterministic
  skeleton (CI checksum); this is the authoritative Exchange-installable artifact.
- **Piggyback attribution** (`checkmk/piggyback_wrap.sh`, flow `checkmk_host:`):
  one runner serves many target hosts — each monitored site appears as its own
  Checkmk host carrying the synthetic service.
- **Clickable failure screenshots**: `runner.py --screenshot-base-url` /
  `$SYNTHMK_SHOT_BASE_URL` renders an `<a href>` link to the node-served PNG
  (with the scoped "Escape HTML codes" guidance — Werk #6058).
- **Dynamic Checkmk state**: flow `state_mode: dynamic` / `runner.py --p-state`
  emits a `P` state on success so Checkmk thresholds `duration` itself.
- `SYNTHMK_NO_SANDBOX` launch flag for Chromium-in-Docker.
- `docs/architecture.md`; README "vs Checkmk Synthetic Monitoring (Robotmk)"
  positioning; flow-schema docs for the new fields.

### Changed
- Flow linter validates `state_mode` and `checkmk_host`; CI lints `lab/flows/`
  too; `make` gains `real-mkp`, `runner-image`, `lab-up`, `lab-down`.
- README recorder wording corrected (the MV3 recorder is built, not a placeholder).

## [0.1.0] — first community milestone

### Added
- `scripts/ci.sh` + `make ci`: single release contract run by both agents and
  GitHub Actions — `make validate`, shell syntax (`bash -n` + shellcheck), JS
  syntax (`node --check`), byte-identical package rebuild, tracked-file secret
  scan, and VERSION↔package↔docs version-consistency check.
- `.github/workflows/ci.yml`: runs `make ci` on push/PR to `main`.
- `RELEASE_CHECKLIST.md`: community-release steps.
- `runner/flow_lint.py` + `make lint-flows`: static, browser-free flow linter
  (unknown actions, missing per-action keys, `warn_ms>crit_ms`, empty steps)
  with clear messages and 0/2/3 exit codes; every tracked flow is linted in CI,
  and the runner↔linter action table is asserted in lockstep.
- `packaging/test_package_contract.py` + `make package-contract`: asserts the
  built MKP payload has the expected files at the expected install paths
  (executable local-check, version-consistent metadata) and leaks no build junk
  — a correctness gate on top of the existing determinism gate.
- `docs/failure-modes.md`: operator-facing exit-code and failure reference.
- This changelog.

Browser-recorded website flows render as native Checkmk local-check services;
no cloud backend. Foundation:
- Flow schema + readable YAML examples (`flows/`, `docs/flow-schema.md`).
- Playwright synthetic runner emitting Checkmk local-check output, with a
  browser-free contract test and smoke script (`runner/`).
- Checkmk local-check addon skeleton (`checkmk/`).
- Chrome MV3 recorder MVP exporting recorded sessions to runner-consumable YAML,
  gated by `extension/validate_export.sh` (`extension/`).
- Idempotent, secret-free `install.sh` (install/uninstall/dry-run/DESTDIR) and
  `Makefile` placing payload at predictable locations.
- Deterministic MKP-style package builder + metadata (`packaging/`).
- Home-lab install/update/uninstall docs (`INSTALL.md`, `docs/home-lab.md`).

[Unreleased]: https://github.com/GranusClarvis/SynthMK/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/GranusClarvis/SynthMK/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/GranusClarvis/SynthMK/releases/tag/v0.1.0
