# Changelog

All notable changes to SynthMK are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); SynthMK uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `scripts/ci.sh` + `make ci`: single release contract run by both agents and
  GitHub Actions — `make validate`, shell syntax (`bash -n` + shellcheck), JS
  syntax (`node --check`), byte-identical package rebuild, tracked-file secret
  scan, and VERSION↔package↔docs version-consistency check.
- `.github/workflows/ci.yml`: runs `make ci` on push/PR to `main`.
- `RELEASE_CHECKLIST.md`: v0.1.0 community-release steps.
- This changelog.

## [0.1.0] — pending first community release

First installable community milestone. Browser-recorded website flows render as
native Checkmk local-check services; no cloud backend.

### Added
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

[Unreleased]: https://github.com/GranusClarvis/SynthMK/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/GranusClarvis/SynthMK/releases/tag/v0.1.0
