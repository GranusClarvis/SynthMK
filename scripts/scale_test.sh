#!/usr/bin/env bash
# SynthMK scale test — N flows on one runner node, measured.
#
# Generates N flows (every 5th is the full multi-step login journey, the rest
# light 3-step checks), schedules them at mixed intervals, runs them on a
# dedicated runner-node container against the lab's internal demo site, and
# after a soak window reports:
#
#   * spool freshness   — every flow must have a fresh (non-stale) result
#   * scheduler health  — the node's own "SynthMK Scheduler" service line
#   * agent poll        — full agent output fetch time (must stay instant;
#                         that's the point of the spool decoupling)
#   * container CPU/RSS — docker stats snapshot
#
# Usage: scripts/scale_test.sh [N] [SOAK_SECONDS]   (default 60 flows, 240s)
# Needs: the LAN lab up (make lab-up) for labnet + intranet-demo.
set -euo pipefail

N="${1:-60}"
SOAK="${2:-240}"
WORK="$(mktemp -d /tmp/synthmk-scale.XXXXXX)"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMG="synthmk-runner:$(cat "$REPO/VERSION")"
NET="synthmk-lab_labnet"
NAME="synthmk-scale"

mkdir -p "$WORK/flows"
echo "== generating $N flows in $WORK =="
for i in $(seq 1 "$N"); do
  if (( i % 5 == 0 )); then
    cat > "$WORK/flows/scale-$i.yaml" <<EOF
name: Scale Login $i
timeout_ms: 20000
warn_ms: 5000
crit_ms: 15000
steps:
  - action: open_url
    url: http://intranet-demo/login.html
  - action: fill
    selector: "#username"
    value: "{{ secret.portal_user }}"
  - action: fill
    selector: "#password"
    value: "{{ secret.portal_password }}"
    sensitive: true
  - action: click
    selector: "#login-submit"
  - action: wait_for_url
    contains: dashboard.html
  - action: check_visible_text
    text: Signed in as monitor
EOF
  else
    cat > "$WORK/flows/scale-$i.yaml" <<EOF
name: Scale Check $i
timeout_ms: 15000
warn_ms: 5000
crit_ms: 12000
steps:
  - action: open_url
    url: http://intranet-demo/
  - action: check_title
    contains: Internal Dashboard
  - action: check_visible_text
    text: Account Overview
EOF
  fi
  # Mixed intervals 60/120/180s so due-times interleave.
  echo "scale-$i.yaml $(( 60 + (i % 3) * 60 ))" >> "$WORK/flows.conf"
done
install -m 600 "$REPO/lab/secrets.yaml" "$WORK/secrets.yaml"

echo "== starting $NAME ($IMG, concurrency 4, 6g limit) =="
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --network "$NET" \
  --memory 6g --cpus 4 --shm-size 1g --security-opt no-new-privileges \
  -v "$WORK/flows:/opt/synthmk/flows:ro" \
  -v "$WORK/flows.conf:/opt/synthmk/runner-node/flows.conf:ro" \
  -v "$WORK/secrets.yaml:/run/synthmk/secrets.yaml:ro" \
  -e SYNTHMK_SECRETS_FILE=/run/synthmk/secrets.yaml \
  -e SYNTHMK_MAX_CONCURRENCY=4 \
  "$IMG" >/dev/null

echo "== soaking ${SOAK}s =="
sleep "$SOAK"

echo
echo "== RESULTS after ${SOAK}s =="
echo "-- agent poll latency (full output over TCP 6556) --"
T0=$(date +%s%3N)
LINES=$(docker run --rm --network "$NET" busybox sh -c "nc $NAME 6556" | wc -l)
T1=$(date +%s%3N)
echo "   $LINES lines in $(( T1 - T0 ))ms"

echo "-- spool freshness --"
docker exec "$NAME" sh -c '
  now=$(date +%s); fresh=0; stale=0; warm=0; failed=0
  for f in /var/lib/check_mk_agent/spool/*; do
    base=$(basename "$f"); maxage=${base%%_*}
    mtime=$(stat -c %Y "$f")
    case "$base" in *scheduler*) continue;; esac
    if [ $(( now - mtime )) -gt "$maxage" ]; then stale=$((stale+1)); fi
    if grep -q "warming up" "$f"; then warm=$((warm+1));
    # native (default) results are JSON entries; local results are digit lines
    elif grep -qE "\"status\": 0" "$f" || grep -qE "^0 |^P " "$f"; then fresh=$((fresh+1)); fi
    if grep -qE "^[123] " "$f" || grep -qE "\"status\": [123]" "$f"; then failed=$((failed+1)); fi
  done
  echo "   ok-results=$fresh still-warming=$warm stale=$stale non-ok=$failed"
'
echo "-- scheduler self-monitoring --"
docker exec "$NAME" cat /var/lib/check_mk_agent/spool/120_synthmk_scheduler | grep -v "^<<<"
echo "-- container resources --"
docker stats --no-stream --format "   cpu={{.CPUPerc}} mem={{.MemUsage}}" "$NAME"
echo "-- scheduler log tail --"
docker logs "$NAME" 2>&1 | grep -E "scheduler|error" | tail -5

echo
echo "Leave it running for longer observation, or clean up with:"
echo "  docker rm -f $NAME && rm -rf $WORK"
