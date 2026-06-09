#!/usr/bin/env bash
# Build a REAL, installable Checkmk MKP using a Checkmk site's own `mkp` tool.
#
# build_mkp.sh produces a deterministic *skeleton* (good for offline CI checksums)
# but not Checkmk's member-tarball format. This script uses the genuine packer
# inside a running Checkmk site (the lab container by default), so the resulting
# .mkp installs cleanly via Setup -> Extension packages.
#
# Verified against Checkmk Raw 2.3.0p48 (cmk-mkp-tool 0.2.0). Flow:
#   stage files under the site -> `mkp template` (auto file list) -> patch
#   metadata -> `mkp package` (creates + installs) -> copy the .mkp out.
#
#   (cd lab && docker compose up -d checkmk)   # need a running site
#   ./packaging/make_real_mkp.sh               # -> dist/synthmk-<version>.mkp
#
# Env:  CMK_CONTAINER (default cmk)   CMK_SITE (default cmk)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
VERSION="$(cat "$REPO/VERSION")"
DIST="$REPO/dist"; mkdir -p "$DIST"
CMK_CONTAINER="${CMK_CONTAINER:-cmk}"
SITE="${CMK_SITE:-cmk}"
NAME="synthmk"
MIN_REQUIRED="${SYNTHMK_MIN_CMK:-2.3.0}"

if ! docker ps --format '{{.Names}}' | grep -qx "$CMK_CONTAINER"; then
  echo "error: Checkmk container '$CMK_CONTAINER' not running. Start it with:" >&2
  echo "  (cd lab && docker compose up -d checkmk)" >&2
  exit 1
fi

echo "== clearing any previously-installed SynthMK package =="
# `mkp template` only lists UNPACKAGED files, and `mkp package` also installs and
# refuses if name+version already exists — so remove any installed synthmk first.
docker exec -u "$SITE" "$CMK_CONTAINER" bash -lc "
  mkp list | awk '\$1==\"${NAME}\"{print \$2}' | while read -r v; do
    [ -n \"\$v\" ] || continue
    mkp disable ${NAME} \"\$v\" 2>/dev/null || true   # enabled pkgs must be disabled first
    mkp remove  ${NAME} \"\$v\" 2>/dev/null || true
  done
" || true

echo "== staging SynthMK agent payload into site '$SITE' =="
# Agent file-part base is ~/local/share/check_mk/agents/. Namespace under custom/.
BASE="/omd/sites/$SITE/local/share/check_mk/agents/custom/$NAME"
docker exec "$CMK_CONTAINER" bash -c "rm -rf '$BASE' && mkdir -p '$BASE/lib/local' '$BASE/runner' '$BASE/flows'"
docker cp "$REPO/checkmk/synthmk_check.sh"  "$CMK_CONTAINER:$BASE/lib/local/synthmk_check.sh"
docker cp "$REPO/checkmk/piggyback_wrap.sh" "$CMK_CONTAINER:$BASE/lib/local/piggyback_wrap.sh"
docker cp "$REPO/runner/." "$CMK_CONTAINER:$BASE/runner/"
docker cp "$REPO/flows/."  "$CMK_CONTAINER:$BASE/flows/"
docker exec "$CMK_CONTAINER" bash -c "chmod +x '$BASE/lib/local/'*.sh && chown -R $SITE:$SITE '$BASE'"

echo "== staging native check plugin (agent_based v2 + rulesets + graphing) =="
# Server-side plugin family: services with unit-aware metrics, the Setup
# ruleset, and graph/perf-o-meter definitions (checkmk/plugin/ in the repo).
PLUG="/omd/sites/$SITE/local/lib/python3/cmk_addons/plugins/$NAME"
docker exec "$CMK_CONTAINER" bash -c "rm -rf '$PLUG' && mkdir -p '$PLUG'"
docker cp "$REPO/checkmk/plugin/." "$CMK_CONTAINER:$PLUG/"
docker exec "$CMK_CONTAINER" bash -c "chown -R $SITE:$SITE '$PLUG'"

echo "== template + patch manifest + package (as site user) =="
# `mkp template` auto-discovers the staged files (via `mkp find`) so the file
# list always matches what we shipped; we only patch the metadata fields.
docker exec -u "$SITE" "$CMK_CONTAINER" bash -lc "
  set -e
  M=\$(mktemp)
  mkp template ${NAME} >/dev/null
  T=~/tmp/check_mk/${NAME}.manifest.temp
  sed -e \"s|Add your name here|GranusClarvis|\" \
      -e \"s|Please add a description here|SynthMK — record-and-run browser synthetic checks rendered as native Checkmk local-check services. No cloud backend.|\" \
      -e \"s|https://example.com/${NAME}/|https://github.com/GranusClarvis/SynthMK|\" \
      -e \"s|Title of ${NAME}|SynthMK synthetic monitoring|\" \
      -e \"s|'version': '1.0.0'|'version': '${VERSION}'|\" \
      \"\$T\" > \"\$M\"
  # Pin minimum Checkmk version (template defaults to the running patch level).
  python3 - \"\$M\" <<'PY'
import sys, ast
p = sys.argv[1]
d = ast.literal_eval(open(p).read())
d['version.min_required'] = '${MIN_REQUIRED}'
open(p, 'w').write(repr(d))
PY
  mkp package \"\$M\"
"

SRC="/omd/sites/$SITE/var/check_mk/packages_local/${NAME}-${VERSION}.mkp"
docker exec "$CMK_CONTAINER" test -f "$SRC" \
  || { echo "error: expected .mkp not found at $SRC" >&2; exit 1; }
docker cp "$CMK_CONTAINER:$SRC" "$DIST/${NAME}-${VERSION}.mkp"

echo "built: dist/${NAME}-${VERSION}.mkp"
sha256sum "$DIST/${NAME}-${VERSION}.mkp" | cut -d' ' -f1 | sed 's/^/sha256: /'
echo "manifest (as Checkmk packed it):"
docker exec -u "$SITE" "$CMK_CONTAINER" bash -lc "mkp inspect '$SRC' 2>/dev/null" | sed 's/^/  /' || true
