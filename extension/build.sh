#!/usr/bin/env bash
# Build store-ready SynthMK Recorder packages for Chrome/Edge and Firefox.
#
#   bash extension/build.sh        # -> dist/synthmk-recorder-{chrome,firefox}-<ver>.zip
#
# Chrome and Edge share one MV3 package (Edge installs Chrome MV3 extensions
# as-is). Firefox gets manifest.firefox.json (gecko id + event-page background
# instead of a service worker — same source files otherwise).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
VERSION="$(python3 -c "import json; print(json.load(open('$HERE/manifest.json'))['version'])")"
DIST="$REPO/dist"
mkdir -p "$DIST"

FILES=(background.js content.js popup.html popup.js recorder_export.js README.md
       icons/icon16.png icons/icon32.png icons/icon48.png icons/icon128.png)

build() { # $1 = browser tag, $2 = manifest file
  local out="$DIST/synthmk-recorder-$1-$VERSION.zip"
  python3 - "$out" "$HERE" "$2" "${FILES[@]}" <<'PY'
import sys, zipfile, pathlib
out, here, manifest, *files = sys.argv[1:]
here = pathlib.Path(here)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(here / manifest, "manifest.json")
    for f in files:
        z.write(here / f, f)
print(f"built: {out}")
PY
}

build chrome  manifest.json
build firefox manifest.firefox.json

echo "Edge uses the chrome package (Chromium MV3, installs unchanged)."