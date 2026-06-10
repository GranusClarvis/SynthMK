# Changelog

All notable changes to SynthMK are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); SynthMK uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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
