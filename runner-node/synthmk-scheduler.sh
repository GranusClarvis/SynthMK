#!/usr/bin/env bash
# SynthMK runner-node scheduler.
#
# Runs each configured flow on its own interval and writes the result to the
# Checkmk spool directory, where the agent transport (agent_output.sh) picks it
# up on the next poll. Decoupling slow browser runs from fast agent polls is what
# lets one node scale to many / long-running checks without ever stalling
# collection. Adding a check = adding a flow file + a line in flows.conf.
#
# flows.conf format (whitespace-separated, '#' comments, blank lines ignored):
#     <flow_file>   <interval_seconds>   [checkmk_host]
# e.g.
#     example-ok.yaml      300
#     intranet-wiki.yaml   120            intranet-wiki
set -uo pipefail

SYNTHMK_HOME="${SYNTHMK_HOME:-/opt/synthmk}"
FLOWS_DIR="${SYNTHMK_FLOWS:-$SYNTHMK_HOME/flows}"
CONF="${SYNTHMK_FLOWS_CONF:-$SYNTHMK_HOME/runner-node/flows.conf}"
SPOOL="${SYNTHMK_SPOOL:-/var/lib/check_mk_agent/spool}"
SHOT_DIR="${SYNTHMK_SHOT_DIR:-$SYNTHMK_HOME/screenshots}"
SHOT_RETENTION_DAYS="${SYNTHMK_SHOT_RETENTION_DAYS:-7}"
PYTHON="${SYNTHMK_PYTHON:-python3}"
TICK="${SYNTHMK_SCHED_TICK:-5}"            # scheduler loop granularity (seconds)
WRAP="$SYNTHMK_HOME/checkmk/piggyback_wrap.sh"

export SYNTHMK_NO_SANDBOX="${SYNTHMK_NO_SANDBOX:-1}"   # Chromium-in-Docker default

mkdir -p "$SPOOL" "$SHOT_DIR"

declare -A NEXT_RUN   # flowid -> epoch seconds of next due run

slug() { printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '_'; }

run_one() {
  local flow_file="$1" interval="$2" host="${3:-}"
  local flow_path="$FLOWS_DIR/$flow_file"
  local id; id="$(slug "$flow_file")"
  local maxage=$(( interval * 3 ))
  local tmp="$SPOOL/.synthmk_${id}.tmp"
  local dest="$SPOOL/${maxage}_synthmk_${id}"

  if [[ ! -f "$flow_path" ]]; then
    # Never go silent: emit an UNKNOWN section so the operator sees the misconfig.
    { printf '3 "SynthMK %s" duration=0ms;; UNKNOWN - flow file not found\n' "$flow_file" \
        | bash "$WRAP" "$host"; } > "$tmp"
    mv -f "$tmp" "$dest"
    return
  fi

  # runner.py exits non-zero on WARN/CRIT/UNKNOWN; that's expected, capture stdout.
  local out
  out="$("$PYTHON" "$SYNTHMK_HOME/runner/runner.py" "$flow_path" 2>/dev/null || true)"
  [[ -z "$out" ]] && out='3 "SynthMK '"$flow_file"'" duration=0ms;; UNKNOWN - runner produced no output'

  printf '%s\n' "$out" | bash "$WRAP" "$host" > "$tmp"
  mv -f "$tmp" "$dest"        # atomic publish so a poll never reads a half-write
}

prune_screenshots() {
  find "$SHOT_DIR" -type f -name '*.png' -mtime +"$SHOT_RETENTION_DAYS" -delete 2>/dev/null || true
}

echo "synthmk-scheduler: home=$SYNTHMK_HOME conf=$CONF spool=$SPOOL tick=${TICK}s"

while true; do
  now="$(date +%s)"
  if [[ -f "$CONF" ]]; then
    while read -r flow_file interval host _rest; do
      [[ -z "${flow_file:-}" || "$flow_file" == \#* ]] && continue
      [[ "$interval" =~ ^[0-9]+$ ]] || { echo "skip bad interval for $flow_file: '$interval'"; continue; }
      id="$(slug "$flow_file")"
      due="${NEXT_RUN[$id]:-0}"
      if (( now >= due )); then
        run_one "$flow_file" "$interval" "${host:-}"
        NEXT_RUN[$id]=$(( now + interval ))
      fi
    done < "$CONF"
  else
    echo "synthmk-scheduler: no config at $CONF (waiting)"
  fi
  prune_screenshots
  sleep "$TICK"
done
