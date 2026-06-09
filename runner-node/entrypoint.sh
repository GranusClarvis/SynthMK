#!/usr/bin/env bash
# SynthMK runner-node entrypoint.
#
# Starts three things and keeps the agent transport in the foreground as PID 1:
#   1. screenshot HTTP server  — serves screenshots/ so failing services can link
#   2. synthmk-scheduler       — runs flows on their intervals into the spool dir
#   3. agent transport (socat) — answers Checkmk polls on 6556 with agent_output.sh
set -uo pipefail

SYNTHMK_HOME="${SYNTHMK_HOME:-/opt/synthmk}"
SHOT_DIR="${SYNTHMK_SHOT_DIR:-$SYNTHMK_HOME/screenshots}"
SHOT_PORT="${SYNTHMK_SHOT_PORT:-9180}"
AGENT_PORT="${SYNTHMK_AGENT_PORT:-6556}"
export SYNTHMK_VERSION="${SYNTHMK_VERSION:-$(cat "$SYNTHMK_HOME/VERSION" 2>/dev/null || echo 0.0.0)}"
export SYNTHMK_SPOOL="${SYNTHMK_SPOOL:-/var/lib/check_mk_agent/spool}"
# How Checkmk users reach this node's screenshots; default to the container name.
export SYNTHMK_SHOT_BASE_URL="${SYNTHMK_SHOT_BASE_URL:-http://$(hostname):$SHOT_PORT}"

mkdir -p "$SHOT_DIR" "$SYNTHMK_SPOOL"

echo "== SynthMK runner-node $SYNTHMK_VERSION =="
echo "  agent transport : tcp/$AGENT_PORT (socat -> agent_output.sh)"
echo "  screenshots     : http/$SHOT_PORT  base=$SYNTHMK_SHOT_BASE_URL"
echo "  spool           : $SYNTHMK_SPOOL"

# 1. screenshot static server
python3 -m http.server "$SHOT_PORT" --directory "$SHOT_DIR" >/var/log/synthmk-shots.log 2>&1 &

# 2. flow scheduler
bash "$SYNTHMK_HOME/runner-node/synthmk-scheduler.sh" &

# Reap children cleanly on stop.
trap 'kill $(jobs -p) 2>/dev/null' TERM INT

# 3. agent transport in the foreground (the container's main process).
exec socat -T30 "TCP-LISTEN:$AGENT_PORT,reuseaddr,fork,crlf" \
     "EXEC:bash $SYNTHMK_HOME/runner-node/agent_output.sh"
