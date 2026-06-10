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
# Per-flow "has this flow ever produced a real result?" markers live here, so a
# first-run (cold Playwright) empty output is reported as a discoverable warmup
# under the REAL service name instead of a stale "SynthMK <file>" UNKNOWN.
SYNTHMK_STATE_DIR="${SYNTHMK_STATE_DIR:-${TMPDIR:-/tmp}/synthmk-localcheck}"
# Demo URL / credentials are passed through as {{ }} placeholders.
export SYNTHMK_DEMO_URL="${SYNTHMK_DEMO_URL:-file://$SYNTHMK_FLOWS/demo/index.html}"
# ----------------------------------------------------------------------------

# Resolve a flow's intended service name (its YAML `name:`, like the runner's
# `flow.get("name", stem)`) so the empty-output fallback never locks discovery
# onto a "SynthMK <file>.yaml" name that the real result would never use.
flow_service_name() {
  local path="$1" name
  name="$("$SYNTHMK_PYTHON" - "$path" <<'PY' 2>/dev/null
import sys
try:
    import yaml
    data = yaml.safe_load(open(sys.argv[1]).read())
    n = data.get("name") if isinstance(data, dict) else None
    print(n if n else "")
except Exception:
    print("")
PY
)"
  if [[ -z "$name" ]]; then
    # No PyYAML / unparsable → fall back to the file stem (matches runner).
    name="$(basename "$path")"; name="${name%.*}"
  fi
  printf '%s' "$name"
}

mkdir -p "$SYNTHMK_STATE_DIR" 2>/dev/null || true

for flow in $SYNTHMK_FLOW_FILES; do
  flow_path="$SYNTHMK_FLOWS/$flow"
  out="$("$SYNTHMK_PYTHON" "$SYNTHMK_HOME/runner/runner.py" "$flow_path" 2>/dev/null)"
  marker="$SYNTHMK_STATE_DIR/$(echo "$flow" | tr '/ ' '__').seen"
  if [[ -n "$out" ]]; then
    # Real result: remember the flow has run at least once, then forward it.
    : > "$marker" 2>/dev/null || true
    echo "$out"
  else
    # Runner produced nothing. Report under the REAL service name so discovery
    # (which may happen on the very first, browser-cold interval) captures the
    # right service. First-ever empty run = warming up (OK); a later empty run
    # is a genuine UNKNOWN so the service still alerts if the runner breaks.
    svc="$(flow_service_name "$flow_path")"
    if [[ -e "$marker" ]]; then
      echo "3 \"$svc\" - UNKNOWN - runner produced no output"
    else
      echo "0 \"$svc\" - OK - warming up, first result pending"
    fi
  fi
done
