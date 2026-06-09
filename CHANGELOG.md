# Changelog

All notable changes to SynthMK are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); SynthMK uses
[Semantic Versioning](https://semver.org/).

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
