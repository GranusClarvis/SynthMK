#!/usr/bin/env bash
# SynthMK piggyback / spool wrapper.
#
# Reads SynthMK runner output (one or more Checkmk local-check lines) on stdin
# and emits *agent-section* output suitable for the Checkmk spool directory.
#
# A bare `local/` script's stdout is auto-wrapped under <<<local>>> by the agent,
# but spool files and piggyback data must carry their own section headers. This
# filter adds them so the runner-node scheduler can:
#
#   * attribute a check to ANOTHER host (piggyback) so an intranet site shows up
#     as its own Checkmk host instead of a service of the runner node, and/or
#   * write the result to the spool dir for asynchronous collection.
#
# Usage:
#   runner.py flow.yaml | piggyback_wrap.sh                  # flat: <<<local>>>
#   runner.py flow.yaml | piggyback_wrap.sh intranet-wiki    # piggyback host
#
# Output (piggyback example):
#   <<<<intranet-wiki>>>>
#   <<<local>>>
#   0 "Synthetic Login" duration=1200ms;3000;7000 OK - ...
#   <<<<>>>>
set -euo pipefail

HOST="${1:-}"
PAYLOAD="$(cat)"

if [[ -n "$HOST" ]]; then
  printf '<<<<%s>>>>\n' "$HOST"
  printf '<<<local>>>\n'
  printf '%s\n' "$PAYLOAD"
  printf '<<<<>>>>\n'   # close the piggyback block (back to the runner host)
else
  printf '<<<local>>>\n'
  printf '%s\n' "$PAYLOAD"
fi
