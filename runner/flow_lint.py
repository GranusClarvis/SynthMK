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
    "press": ("key",),              # selector is optional (else focused element)
    "select_option": ("selector",),
    "hover": ("selector",),
    "scroll_into_view": ("selector",),
    "wait_ms": ("ms",),
    "wait_for_network_idle": (),  # no required keys; timeout_ms optional
    "screenshot": (),             # always-on capture; name/full_page optional
    "wait_for_element": ("selector",),
    "wait_for_url": ("contains",),
    "check_visible_text": ("text",),
    "check_text_absent": ("text",),
    "check_title": ("contains",),
    "check_url": ("contains",),
    "check_element_count": ("selector",),  # min is optional (defaults to 1)
    "check_element_attribute": ("selector", "attribute"),
    "check_checkbox": ("selector",),       # checked: true|false (default true)
    "include": ("flow",),                  # splice another flow's steps here
}

# Actions whose `selector` may be a fallback ladder (list tried in order).
SELECTOR_ACTIONS = {
    "click", "fill", "press", "select_option", "hover", "scroll_into_view",
    "wait_for_element", "check_element_count", "check_element_attribute",
    "check_checkbox",
}

# Keys a step may legally carry in addition to its required ones.
# 'optional: true' = best-effort step (e.g. cookie-consent click): a failure
# is skipped instead of failing the flow.
OPTIONAL_STEP_KEYS = {"action", "timeout_ms", "comment", "optional"}

# Per-action extras beyond the always-allowed OPTIONAL_STEP_KEYS.
ACTION_OPTIONAL_KEYS: dict[str, set[str]] = {
    "fill": {"value", "sensitive"},
    "press": {"selector"},
    "select_option": {"value"},
    "check_element_count": {"min"},
    "check_element_attribute": {"contains", "equals"},
    "check_checkbox": {"checked"},
    "screenshot": {"name", "full_page"},
}

TOP_LEVEL_KNOWN = {
    "name", "start_url", "timeout_ms", "warn_ms", "crit_ms",
    "browser", "screenshot_on_failure", "steps",
    # v0.2.0 additions:
    "checkmk_host",   # piggyback target host; the result is attributed to it
    "state_mode",     # "digit" (default) | "dynamic" (emit 'P', Checkmk thresholds)
    # v0.5.0 additions:
    "type",           # "flow" (default) | "script" (Playwright Python, trust-gated)
    "script",         # script flows: path to the .py, relative to the flow file
}

# Allowed values for the state_mode top-level field.
STATE_MODES = {"digit", "dynamic"}

# Recognized `browser:` engines (mirrors runner._BROWSER_ENGINES). An unknown
# value is a warning, not an error: the runner falls back to chromium so the
# flow still runs, but the operator probably meant one of these.
KNOWN_BROWSERS = {
    "chromium", "chrome", "google-chrome", "edge", "msedge",
    "firefox", "ff", "webkit", "safari",
}


def lint_flow(data: Any, *, source: str = "<flow>",
              base_dir: Path | None = None,
              _stack: tuple[str, ...] = ()) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for an already-parsed flow mapping.

    base_dir resolves `include:` references (usually the flow file's directory;
    pass --base-dir when linting text that will be saved elsewhere, e.g. the
    node dashboard editor). Without it, include targets are not followed.
    """
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

    browser = data.get("browser")
    if browser is not None and str(browser).strip().lower() not in KNOWN_BROWSERS:
        warnings.append(
            f"{source}: browser '{browser}' is not a known engine "
            f"({sorted(KNOWN_BROWSERS)}); runner will fall back to chromium"
        )

    state_mode = data.get("state_mode")
    if state_mode is not None and str(state_mode).lower() not in STATE_MODES:
        errors.append(
            f"{source}: state_mode '{state_mode}' must be one of {sorted(STATE_MODES)}"
        )
    # Dynamic state delegates thresholding to Checkmk, so a crit_ms is required
    # for it to be able to ever escalate — otherwise the service can only be OK.
    if str(state_mode).lower() == "dynamic" and crit_ms is None and warn_ms is None:
        warnings.append(
            f"{source}: state_mode 'dynamic' without warn_ms/crit_ms — Checkmk "
            f"has no threshold to escalate on (service will stay OK on success)"
        )

    checkmk_host = data.get("checkmk_host")
    if checkmk_host is not None and (not isinstance(checkmk_host, str) or not checkmk_host.strip()):
        errors.append(f"{source}: checkmk_host must be a non-empty string when set")

    ftype = str(data.get("type", "flow"))
    if ftype not in ("flow", "script"):
        errors.append(f"{source}: type '{ftype}' must be 'flow' or 'script'")
        return (errors, warnings)
    if ftype == "script":
        ref = data.get("script")
        if not isinstance(ref, str) or not ref.strip():
            errors.append(f"{source}: type: script requires a 'script' path")
        elif Path(ref).is_absolute():
            errors.append(f"{source}: script path must be relative to the flow file")
        elif base_dir is not None and not (base_dir / ref).is_file():
            errors.append(f"{source}: script file not found: {ref}")
        if "steps" in data:
            warnings.append(f"{source}: 'steps' is ignored on a type: script flow")
        if isinstance(ref, str) and ref.strip() and not ref.endswith(".py"):
            warnings.append(f"{source}: script path should end in .py")
        return (errors, warnings)

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
            if req not in step or step[req] in (None, "") or step[req] == []:
                errors.append(f"{where} ('{action}'): missing required key '{req}'")
        allowed = (OPTIONAL_STEP_KEYS | set(REQUIRED_KEYS[action])
                   | ACTION_OPTIONAL_KEYS.get(action, set()))
        for key in step:
            if key not in allowed:
                warnings.append(f"{where} ('{action}'): unexpected key '{key}'")
        # Selector fallback ladders: a list of selectors tried in order.
        sel = step.get("selector")
        if isinstance(sel, list):
            if action not in SELECTOR_ACTIONS:
                errors.append(f"{where} ('{action}'): selector cannot be a list here")
            elif any(not isinstance(c, str) or not c.strip() for c in sel):
                errors.append(
                    f"{where} ('{action}'): selector ladder entries must be "
                    f"non-empty strings"
                )
        if action == "include":
            if step.get("optional"):
                warnings.append(
                    f"{where} ('include'): 'optional' has no effect on include "
                    f"(mark the included steps optional instead)"
                )
            ref = str(step.get("flow", "")).strip()
            if ref and base_dir is not None:
                _lint_include(ref, base_dir, where, _stack, errors, warnings)
        # Credential hygiene: a fill that references {{ secret.X }} should be
        # marked sensitive so failure screenshots mask form fields.
        if action == "fill" and not step.get("sensitive"):
            value = str(step.get("value", ""))
            if "secret." in value and "{{" in value:
                warnings.append(
                    f"{where} ('fill'): references a secret but is not marked "
                    f"'sensitive: true' (failure screenshots would not mask inputs)"
                )

    return (errors, warnings)


def _lint_include(ref: str, base_dir: Path, where: str,
                  stack: tuple[str, ...],
                  errors: list[str], warnings: list[str]) -> None:
    """Follow an include reference: the target must exist, parse, and lint."""
    if Path(ref).is_absolute():
        errors.append(f"{where} ('include'): path must be relative: {ref}")
        return
    target = (base_dir / ref).resolve()
    if str(target) in stack:
        errors.append(f"{where} ('include'): cycle via '{ref}'")
        return
    if len(stack) >= 3:
        errors.append(f"{where} ('include'): nesting deeper than 3 levels")
        return
    if not target.is_file():
        errors.append(f"{where} ('include'): file not found: {ref}")
        return
    try:
        sub = yaml.safe_load(target.read_text())
    except yaml.YAMLError:
        errors.append(f"{where} ('include'): '{ref}' is not valid YAML")
        return
    if not isinstance(sub, dict) or not isinstance(sub.get("steps"), list) or not sub["steps"]:
        errors.append(f"{where} ('include'): '{ref}' has no 'steps' list")
        return
    sub_errs, sub_warns = lint_flow(
        {"name": "(included)", "steps": sub["steps"]},
        source=f"{where} -> {ref}", base_dir=target.parent,
        _stack=stack + (str(target),),
    )
    errors.extend(sub_errs)
    warnings.extend(sub_warns)


def lint_path(path: Path, base_dir: Path | None = None) -> int:
    """Lint a single flow file; print results; return an exit-code class."""
    if not path.exists():
        print(f"  FAIL - {path}: file not found")
        return 3
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        print(f"  FAIL - {path}: invalid YAML: {' '.join(str(exc).split())}")
        return 3

    errors, warnings = lint_flow(data, source=str(path),
                                 base_dir=base_dir or path.parent)
    for w in warnings:
        print(f"  warn - {w}")
    for e in errors:
        print(f"  FAIL - {e}")
    if errors:
        return 2
    if isinstance(data, dict) and str(data.get("type", "flow")) == "script":
        print(f"  ok   - {path} (script: {data.get('script')})")
    else:
        print(f"  ok   - {path} ({len(data.get('steps', []))} steps)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    base_dir: Path | None = None
    if "--base-dir" in args:
        i = args.index("--base-dir")
        try:
            base_dir = Path(args[i + 1])
        except IndexError:
            sys.stderr.write("--base-dir needs a directory argument\n")
            return 3
        args = args[:i] + args[i + 2:]
    if not args:
        sys.stderr.write("usage: flow_lint.py [--base-dir DIR] <flow.yaml> [flow.yaml ...]\n")
        return 3
    worst = 0
    for arg in args:
        rc = lint_path(Path(arg), base_dir=base_dir)
        worst = max(worst, rc)
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
