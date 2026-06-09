#!/usr/bin/env bash
# Build a Checkmk-MKP-style package skeleton for SynthMK.
#
# This produces a DETERMINISTIC, secret-free package tree + tarball under dist/.
# It is a packaging *skeleton*: it lays the payload out the way an MKP expects
# (agent local-check under local/, runtime payload under local/share/synthmk,
# plus the `info`/`info.json` metadata Checkmk's package manager reads) and tars
# it reproducibly. Wrapping into Checkmk's per-part member tarballs is the next
# step and is intentionally left as a documented TODO (see packaging/README.md).
#
#   ./packaging/build_mkp.sh            # -> dist/synthmk-<version>.mkp (+ staged tree)
#
# Determinism: fixed mtime/owner/group and sorted entries, so repeated builds of
# the same source produce a byte-identical archive (CI-checkable).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
VERSION="$(cat "$REPO/VERSION")"
DIST="$REPO/dist"
STAGE="$DIST/synthmk-$VERSION"

rm -rf "$STAGE"
mkdir -p "$STAGE/local/share/synthmk" "$STAGE/local/lib/check_mk_agent/local/300"

# --- metadata --------------------------------------------------------------
sed "s/@VERSION@/$VERSION/g" "$HERE/info.template" > "$STAGE/info"
# Minimal info.json mirror (Checkmk 2.x writes both; keep them consistent).
cat > "$STAGE/info.json" <<JSON
{"name": "synthmk", "version": "$VERSION", "title": "SynthMK synthetic monitoring",
 "author": "GranusClarvis", "version.min_required": "2.2.0",
 "download_url": "https://github.com/GranusClarvis/SynthMK"}
JSON

# --- payload ---------------------------------------------------------------
# Agent local-check at its install path.
cp "$REPO/checkmk/synthmk_check.sh" "$STAGE/local/lib/check_mk_agent/local/300/synthmk_check.sh"
chmod +x "$STAGE/local/lib/check_mk_agent/local/300/synthmk_check.sh"

# Native check plugin family at its server-side install path (agent_based v2
# check + rulesets + graphing; see checkmk/plugin/).
mkdir -p "$STAGE/local/lib/python3/cmk_addons/plugins/synthmk"
rsync -a --exclude='__pycache__' --exclude='*.pyc' \
      "$REPO/checkmk/plugin/" "$STAGE/local/lib/python3/cmk_addons/plugins/synthmk/"

# Runtime payload the local-check invokes (SYNTHMK_HOME points here).
for part in runner flows checkmk docs README.md VERSION; do
  src="$REPO/$part"
  [[ -e "$src" ]] || continue
  rsync -a --exclude='.git' --exclude='__pycache__' --exclude='.ruff_cache' \
        --exclude='*.pyc' --exclude='.env' --exclude='*.env' \
        --exclude='screenshots' --exclude='node_modules' --exclude='dist' \
        "$src" "$STAGE/local/share/synthmk/"
done

# --- deterministic tar -----------------------------------------------------
OUT="$DIST/synthmk-$VERSION.mkp"
tar --sort=name --owner=0 --group=0 --numeric-owner \
    --mtime='UTC 2020-01-01' \
    -czf "$OUT" -C "$DIST" "synthmk-$VERSION"

echo "built: ${OUT#$REPO/}"
echo "sha256: $(sha256sum "$OUT" | cut -d' ' -f1)"
echo "tree:"
tar -tzf "$OUT" | sed 's/^/  /'
