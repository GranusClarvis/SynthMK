# SynthMK Release Checklist

A small, repeatable gate for cutting a SynthMK community release. Everything here
is browser-free and runs from a clean checkout.

## 1. Pre-flight

- [ ] Working tree clean: `git status --short` is empty.
- [ ] `VERSION` holds the intended release version (e.g. `0.1.0`).
- [ ] `CHANGELOG.md` has an entry for this version (move items out of
      `[Unreleased]` into the dated section).

## 2. Green contract

- [ ] `make ci` exits `0` and prints `CI OK`. This proves, in one command:
  - runner output contract + recorder-export contract (`make validate`),
  - shell syntax (`bash -n` + shellcheck) and JS syntax (`node --check`),
  - byte-identical package rebuild (determinism),
  - tracked-file secret scan,
  - `VERSION` ↔ built `info.json` ↔ docs version consistency.
- [ ] GitHub Actions `ci` workflow is green on the release commit.

## 3. Package

- [ ] `make package` builds `dist/synthmk-<VERSION>.mkp`.
- [ ] Record the printed `sha256:` in the release notes (determinism receipt).
- [ ] `tar -tzf dist/synthmk-<VERSION>.mkp` shows only intended payload
      (no `.git`, `__pycache__`, `.env`, screenshots, or node_modules).

## 4. Install smoke (optional, home-lab)

- [ ] `sudo ./install.sh --dry-run` lists the expected target paths.
- [ ] On a throwaway host: `sudo ./install.sh` then `sudo ./install.sh --uninstall`
      both succeed and leave the system clean.

## 5. Tag & publish

- [ ] Commit release prep (`CHANGELOG.md`, `VERSION` if bumped).
- [ ] `git tag -a v<VERSION> -m "SynthMK v<VERSION>"` and `git push origin v<VERSION>`.
- [ ] Create the GitHub release; attach `dist/synthmk-<VERSION>.mkp` and paste the
      `sha256`.

## 6. Post-release

- [ ] Add a new `[Unreleased]` section to `CHANGELOG.md`.
- [ ] Bump `VERSION` to the next planned version if starting new work.
