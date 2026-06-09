#!/usr/bin/env python3
"""SynthMK flow linter — static, browser-free validation of a flow YAML.

The runner only discovers a malformed flow at execution time, inside a real
browser, one step in. That is a poor operator experience: a typo'd action or a
missing selector should fail *before* you deploy the check, with a line-pointed
message, not as a CRIT service at 02:00.

`flow_lint.py` validates the parts of a flow the runner depends on WITHOUT
launching Playwright:

  * top-level shape: `steps` is a non-empty list; `name` present (warn if not)
  * every step has a known `action` (matching the runner's dispatch table)
  * every step carries the keys that action requires (e.g. click->selector)
  * threshold ordering: warn_ms <= crit_ms when both are set
  * unknown step keys are reported as warnings (likely typos), never errors

Exit codes:
    0  clean (no errors; warnings allowed)
    2  at least one lint error
    3  file missing / not valid YAML / not a mapping

Usage:
    python3 runner/flow_lint.py flows/example-ok.yaml
    python3 runner/flow_lint.py flows/*.yaml        # lint several, exit 2 if any fail
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - dependency guard
    sys.stderr.write("PyYAML is required: pip install pyyaml\n")
    sys.exit(3)

# Required keys per action — mirrors runner._run_step's dispatch table. Keeping
# this in lockstep with the runner is the whole point of the linter, so adding a
# new action to the runner without listing it here makes the linter reject flows
# that the runner would accept (a deliberate, visible coupling).
REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "open_url": ("url",),
    "click": ("selector",),
    "fill": ("selector",),          # value is optional (defaults to "")
    "wait_for_element": ("selector",),
    "check_visible_text": ("text",),
    "check_title": ("contains",),
    "check_url": ("contains",),
}

# Keys a step may legally carry in addition to its required ones.
OPTIONAL_STEP_KEYS = {"action", "timeout_ms", "value", "comment"}

TOP_LEVEL_KNOWN = {
    "name", "start_url", "timeout_ms", "warn_ms", "crit_ms",
    "browser", "screenshot_on_failure", "steps",
}


def lint_flow(data: Any, *, source: str = "<flow>") -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for an already-parsed flow mapping."""
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(data, dict):
        return ([f"{source}: flow did not parse to a mapping"], warnings)

    if "name" not in data:
        warnings.append(f"{source}: no top-level 'name' (service will fall back to file stem)")

    for key in data:
        if key not in TOP_LEVEL_KNOWN:
            warnings.append(f"{source}: unknown top-level key '{key}'")

    warn_ms, crit_ms = data.get("warn_ms"), data.get("crit_ms")
    if isinstance(warn_ms, int) and isinstance(crit_ms, int) and warn_ms > crit_ms:
        errors.append(
            f"{source}: warn_ms ({warn_ms}) must be <= crit_ms ({crit_ms})"
        )

    steps = data.get("steps")
    if not isinstance(steps, list):
        errors.append(f"{source}: 'steps' must be a list")
        return (errors, warnings)
    if not steps:
        errors.append(f"{source}: 'steps' is empty — nothing to run")
        return (errors, warnings)

    for i, step in enumerate(steps):
        where = f"{source}: step {i}"
        if not isinstance(step, dict):
            errors.append(f"{where}: not a mapping")
            continue
        action = step.get("action")
        if action is None:
            errors.append(f"{where}: missing 'action'")
            continue
        if action not in REQUIRED_KEYS:
            known = ", ".join(sorted(REQUIRED_KEYS))
            errors.append(f"{where}: unknown action '{action}' (known: {known})")
            continue
        for req in REQUIRED_KEYS[action]:
            if req not in step or step[req] in (None, ""):
                errors.append(f"{where} ('{action}'): missing required key '{req}'")
        allowed = OPTIONAL_STEP_KEYS | set(REQUIRED_KEYS[action])
        for key in step:
            if key not in allowed:
                warnings.append(f"{where} ('{action}'): unexpected key '{key}'")

    return (errors, warnings)


def lint_path(path: Path) -> int:
    """Lint a single flow file; print results; return an exit-code class."""
    if not path.exists():
        print(f"  FAIL - {path}: file not found")
        return 3
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        print(f"  FAIL - {path}: invalid YAML: {' '.join(str(exc).split())}")
        return 3

    errors, warnings = lint_flow(data, source=str(path))
    for w in warnings:
        print(f"  warn - {w}")
    for e in errors:
        print(f"  FAIL - {e}")
    if errors:
        return 2
    print(f"  ok   - {path} ({len(data.get('steps', []))} steps)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        sys.stderr.write("usage: flow_lint.py <flow.yaml> [flow.yaml ...]\n")
        return 3
    worst = 0
    for arg in args:
        rc = lint_path(Path(arg))
        worst = max(worst, rc)
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
