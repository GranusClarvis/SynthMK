#!/usr/bin/env bash
# SynthMK local validation: runs the OK flow and the failing flow against the
# bundled local demo page, and asserts the runner emits the expected Checkmk
# status digits. No network or live login required.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
export SYNTHMK_DEMO_URL="file://$REPO/flows/demo/index.html"
export DEMO_USER="demo"
export DEMO_PASS="demo"

PY="${PYTHON:-python3}"
fail=0

run_case() {
  local flow="$1" expect="$2" label="$3"
  echo "--- $label ($flow) ---"
  local line status
  line="$("$PY" "$REPO/runner/runner.py" "$REPO/flows/$flow")"
  status=$?
  echo "$line"
  if [[ "$status" -ne "$expect" ]]; then
    echo "FAIL: expected exit $expect, got $status"
    fail=1
  fi
  # First char of the Checkmk line must equal the expected status digit.
  if [[ "${line:0:1}" != "$expect" ]]; then
    echo "FAIL: expected Checkmk status digit $expect, got '${line:0:1}'"
    fail=1
  fi
}

run_case example-ok.yaml   0 "OK flow"
run_case example-fail.yaml 2 "Failing assertion flow"

if [[ "$fail" -eq 0 ]]; then
  echo "SMOKE OK: both flows produced the expected Checkmk status."
else
  echo "SMOKE FAILED."
fi
exit "$fail"
