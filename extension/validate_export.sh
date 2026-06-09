#!/usr/bin/env bash
# Validates that the SynthMK recorder's exporter produces YAML the runner accepts.
#
# 1. node --check on every extension JS file (syntax gate).
# 2. Run the REAL exporter (recorder_export.js via gen_sample.js) over a sample
#    recorded session → flows/recorded-sample.yaml.
# 3. Parse that YAML through the runner's own load_flow() and assert every step
#    uses a known runner action. No browser required.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
NODE="${NODE:-node}"
PY="${PYTHON:-python3}"
SAMPLE="$REPO/flows/recorded-sample.yaml"
fail=0

echo "== node --check (extension JS syntax) =="
for f in "$HERE"/recorder_export.js "$HERE"/content.js "$HERE"/background.js "$HERE"/popup.js "$HERE"/gen_sample.js; do
  if "$NODE" --check "$f"; then
    echo "  ok   - $(basename "$f")"
  else
    echo "  FAIL - $(basename "$f")"
    fail=1
  fi
done

echo "== export sample session → YAML =="
if "$NODE" "$HERE/gen_sample.js" > "$SAMPLE"; then
  echo "  ok   - wrote $(realpath --relative-to="$REPO" "$SAMPLE")"
else
  echo "  FAIL - exporter errored"
  fail=1
fi

echo "== validate exported YAML against the runner contract =="
SAMPLE="$SAMPLE" REPO="$REPO" "$PY" - <<'PY'
import os, sys
from pathlib import Path
repo = Path(os.environ["REPO"])
sys.path.insert(0, str(repo / "runner"))
import runner as R

sample = Path(os.environ["SAMPLE"])
fails = []

try:
    flow = R.load_flow(sample)
except Exception as e:  # noqa: BLE001
    print(f"  FAIL - runner.load_flow rejected exported YAML: {e}")
    sys.exit(1)

print("  ok   - runner.load_flow parsed the exported YAML")

# Every emitted step must use an action the runner dispatch table handles,
# with the keys it requires. flow_lint.REQUIRED_KEYS is the single source of
# truth (the contract suite asserts it stays in lockstep with the runner).
import flow_lint as L  # noqa: E402
for i, step in enumerate(flow.get("steps", [])):
    action = step.get("action")
    if action not in L.REQUIRED_KEYS:
        fails.append(f"step {i}: unknown action {action!r}")
        continue
    for need in L.REQUIRED_KEYS[action]:
        if need not in step:
            fails.append(f"step {i}: {action} missing required field {need!r}")
# The exporter's action list must not drift ahead of (or behind) the linter.
exporter_actions = set()
import json, subprocess
node = os.environ.get("NODE", "node")
out = subprocess.run(
    [node, "-e",
     "console.log(JSON.stringify(require(process.argv[1]).KNOWN_ACTIONS))",
     str(repo / "extension" / "recorder_export.js")],
    capture_output=True, text=True)
if out.returncode == 0:
    exporter_actions = set(json.loads(out.stdout))
    extra = exporter_actions - set(L.REQUIRED_KEYS)
    if extra:
        fails.append(f"exporter KNOWN_ACTIONS not in runner/linter: {sorted(extra)}")
else:
    fails.append("could not read exporter KNOWN_ACTIONS")

if not flow.get("name"):
    fails.append("flow missing 'name'")
if not flow.get("steps"):
    fails.append("flow has no steps")

if fails:
    for f in fails:
        print(f"  FAIL - {f}")
    sys.exit(1)

print(f"  ok   - all {len(flow['steps'])} steps use runner-known actions with required fields")
PY
[[ $? -ne 0 ]] && fail=1

if [[ "$fail" -eq 0 ]]; then
  echo "EXPORT VALIDATION OK"
else
  echo "EXPORT VALIDATION FAILED"
fi
exit "$fail"
