#!/usr/bin/env bash
# SynthMK Checkmk local check.
#
# Install: copy (or symlink) this file into the Checkmk agent's local-check dir:
#     /usr/lib/check_mk_agent/local/300/synthmk_check.sh      # 300s interval dir
#   or for the default interval:
#     /usr/lib/check_mk_agent/local/synthmk_check.sh
# Make it executable (chmod +x). The Checkmk agent runs every script in that
# directory and forwards each line of stdout as a service result. SynthMK's
# runner emits exactly one local-check line per flow:
#
#     <status> "<service>" duration=<ms>ms;<warn>;<crit> <STATE> - <summary>
#
# so no parsing or piggyback wrapper is needed — the runner output IS the
# local-check protocol.
set -uo pipefail

# --- configuration (edit for your host) -------------------------------------
SYNTHMK_HOME="${SYNTHMK_HOME:-/opt/synthmk}"
SYNTHMK_PYTHON="${SYNTHMK_PYTHON:-python3}"
SYNTHMK_FLOWS="${SYNTHMK_FLOWS:-$SYNTHMK_HOME/flows}"
# Space-separated list of flow files to run each interval.
SYNTHMK_FLOW_FILES="${SYNTHMK_FLOW_FILES:-example-ok.yaml}"
# Demo URL / credentials are passed through as {{ }} placeholders.
export SYNTHMK_DEMO_URL="${SYNTHMK_DEMO_URL:-file://$SYNTHMK_FLOWS/demo/index.html}"
# ----------------------------------------------------------------------------

for flow in $SYNTHMK_FLOW_FILES; do
  out="$("$SYNTHMK_PYTHON" "$SYNTHMK_HOME/runner/runner.py" "$SYNTHMK_FLOWS/$flow" 2>/dev/null)"
  if [[ -z "$out" ]]; then
    # Runner produced nothing → report UNKNOWN so the service never goes silent.
    echo "3 \"SynthMK $flow\" - UNKNOWN - runner produced no output"
  else
    echo "$out"
  fi
done
