#!/usr/bin/env bash
# Docker-gated CI proof: build a REAL .mkp against an ephemeral Checkmk Raw
# site, then prove the *built artifact itself* installs from scratch via the
# site's own `mkp add` + `mkp enable` and lists the files we shipped.
#
# This is deliberately NOT part of `make ci` (which is browser/Docker-free and
# runs everywhere). It needs a Docker daemon and pulls the Checkmk Raw image,
# so it lives in its own optional GitHub Actions job (.github/workflows/
# real-mkp.yml) and can be run locally with:
#
#   bash scripts/ci_real_mkp.sh
#
# It owns the container lifecycle end-to-end: starts a throwaway `cmk` site,
# waits for it to come up, builds + adds + enables the package, then tears the
# container down (even on failure) so reruns are clean.
#
# Env knobs:
#   CMK_IMAGE      Checkmk Raw image       (default checkmk/check-mk-raw:2.3.0-latest)
#   CMK_CONTAINER  container/site name     (default cmk)  — also consumed by make_real_mkp.sh
#   CMK_PASSWORD   cmkadmin password       (default synthmk-ci-admin)
#   CMK_WAIT_SECS  site-readiness timeout  (default 240)
#   KEEP_CONTAINER 1 = skip teardown (debug)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
VERSION="$(cat "$REPO/VERSION")"
NAME="synthmk"

CMK_IMAGE="${CMK_IMAGE:-checkmk/check-mk-raw:2.3.0-latest}"
CMK_CONTAINER="${CMK_CONTAINER:-cmk}"
# Site id is independent of the container name (Checkmk site ids forbid hyphens
# and cap at 16 chars, so they can't always equal a Docker name). Mirrors the
# CMK_SITE/CMK_CONTAINER split in make_real_mkp.sh.
SITE="${CMK_SITE:-cmk}"
CMK_PASSWORD="${CMK_PASSWORD:-synthmk-ci-admin}"
CMK_WAIT_SECS="${CMK_WAIT_SECS:-240}"

export CMK_CONTAINER CMK_SITE="$SITE"

# Files the operator depends on; `mkp files <name> <version>` must list every
# one of these. Paths mirror what the REAL packer ships (verified against the
# manifest `make real-mkp` produces): agent payload under
# .../agents/custom/synthmk/, server-side plugin family under
# .../cmk_addons/plugins/synthmk/. (NOT the deterministic *skeleton* layout that
# packaging/test_package_contract.py asserts — that is a different artifact.)
EXPECTED_FILES=(
  "agents/custom/synthmk/lib/local/synthmk_check.sh"
  "agents/custom/synthmk/runner/runner.py"
  "agents/custom/synthmk/flows/example-ok.yaml"
  "cmk_addons/plugins/synthmk/agent_based/synthmk.py"
  "cmk_addons/plugins/synthmk/rulesets/synthmk.py"
  "cmk_addons/plugins/synthmk/graphing/synthmk.py"
  "cmk_addons/plugins/synthmk/server_side_calls/synthmk.py"
)

log()  { echo "== $* =="; }
fail() { echo "error: $*" >&2; exit 1; }

teardown() {
  if [ "${KEEP_CONTAINER:-0}" = "1" ]; then
    echo "KEEP_CONTAINER=1 — leaving '$CMK_CONTAINER' running" >&2
    return
  fi
  log "teardown: removing container '$CMK_CONTAINER'"
  docker rm -f "$CMK_CONTAINER" >/dev/null 2>&1 || true
}
trap teardown EXIT

command -v docker >/dev/null 2>&1 || fail "docker not found — this job needs a Docker daemon"

# --- 1. fresh ephemeral Checkmk Raw site -----------------------------------
log "starting ephemeral Checkmk Raw site ($CMK_IMAGE)"
docker rm -f "$CMK_CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$CMK_CONTAINER" --hostname "$CMK_CONTAINER" \
  -e CMK_SITE_ID="$SITE" -e CMK_PASSWORD="$CMK_PASSWORD" \
  --tmpfs "/opt/omd/sites/$SITE/tmp:uid=1000,gid=1000" \
  "$CMK_IMAGE" >/dev/null

# --- 2. wait for the site to be ready (mkp usable) -------------------------
log "waiting up to ${CMK_WAIT_SECS}s for site '$SITE' to come up"
deadline=$((SECONDS + CMK_WAIT_SECS))
until docker exec -u "$SITE" "$CMK_CONTAINER" bash -lc 'mkp list >/dev/null 2>&1'; do
  if [ "$SECONDS" -ge "$deadline" ]; then
    docker logs --tail 60 "$CMK_CONTAINER" >&2 || true
    fail "site '$SITE' not ready after ${CMK_WAIT_SECS}s"
  fi
  if [ "$(docker inspect -f '{{.State.Running}}' "$CMK_CONTAINER" 2>/dev/null)" != "true" ]; then
    docker logs --tail 60 "$CMK_CONTAINER" >&2 || true
    fail "container '$CMK_CONTAINER' exited during startup"
  fi
  sleep 5
done
log "site is up"

# --- 3. build the REAL .mkp against that site ------------------------------
log "make real-mkp"
make -C "$REPO" real-mkp

MKP="$REPO/dist/${NAME}-${VERSION}.mkp"
[ -f "$MKP" ] || fail "expected artifact not built: $MKP"

# --- 4. prove the ARTIFACT installs from scratch ---------------------------
# make_real_mkp.sh already package+installs as a side effect; here we exercise
# the operator path on the .mkp FILE itself: clear it, then `add` + `enable`.
log "clearing any installed/staged '$NAME' from the site"
docker exec -u "$SITE" "$CMK_CONTAINER" bash -lc "
  mkp list | awk '\$1==\"${NAME}\"{print \$2}' | while read -r v; do
    [ -n \"\$v\" ] || continue
    mkp disable ${NAME} \"\$v\" 2>/dev/null || true
    mkp remove  ${NAME} \"\$v\" 2>/dev/null || true
  done
" || true

# Copy onto the container's writable layer — NOT the site's tmp/ (a tmpfs mount,
# which docker cp does not reliably populate) — and make it world-readable so
# the site user can `mkp add` it.
REMOTE="/var/tmp/${NAME}-${VERSION}.mkp"
docker cp "$MKP" "$CMK_CONTAINER:$REMOTE"
docker exec "$CMK_CONTAINER" chmod 0644 "$REMOTE"

log "mkp add ${NAME}-${VERSION}.mkp"
docker exec -u "$SITE" "$CMK_CONTAINER" bash -lc "mkp add '$REMOTE'" \
  || fail "mkp add failed for the built artifact"

log "mkp enable $NAME $VERSION"
docker exec -u "$SITE" "$CMK_CONTAINER" bash -lc "mkp enable '$NAME' '$VERSION'" \
  || fail "mkp enable failed for $NAME $VERSION"

# --- 5. assert it is enabled and lists the files we shipped ----------------
log "mkp list (must show $NAME $VERSION enabled)"
LIST="$(docker exec -u "$SITE" "$CMK_CONTAINER" bash -lc 'mkp list')"
echo "$LIST"
echo "$LIST" | awk -v n="$NAME" -v v="$VERSION" '
  $1==n && $2==v { found=1 }
  END { exit found ? 0 : 1 }
' || fail "$NAME $VERSION not present in 'mkp list' after enable"

log "mkp files $NAME $VERSION (expected payload present)"
FILES="$(docker exec -u "$SITE" "$CMK_CONTAINER" bash -lc "mkp files '$NAME' '$VERSION'")"
echo "$FILES"
missing=()
for f in "${EXPECTED_FILES[@]}"; do
  # `mkp files` prints absolute site paths (…/local/share/check_mk/agents/… and
  # …/local/lib/python3/cmk_addons/plugins/…); each expected entry is an exact
  # trailing substring of one of those, so a fixed-string match is enough.
  if ! grep -qF "$f" <<<"$FILES"; then
    missing+=("$f")
  fi
done
[ "${#missing[@]}" -eq 0 ] || fail "mkp files missing expected payload: ${missing[*]}"

log "OK — built artifact adds, enables, and lists ${#EXPECTED_FILES[@]} expected files"
echo "REAL-MKP CI OK: $NAME $VERSION"
