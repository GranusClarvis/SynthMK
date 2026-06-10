#!/usr/bin/env python3
"""Import a Chrome DevTools Recorder recording as a SynthMK flow.

Every Chrome ships a journey recorder (F12 → Recorder → record → export JSON).
This importer turns that JSON into a SynthMK flow YAML, so anyone can author a
check with zero extensions installed — record in the browser they already
have, import on the node, done.

    python3 runner/import_devtools.py recording.json
    python3 runner/import_devtools.py recording.json -o flows/my-check.yaml

Mapping notes
-------------
* DevTools records SEVERAL selectors per element (ARIA, test attributes, CSS,
  XPath, pierce). They become a SynthMK selector fallback ladder, preserving
  the recorder's resilience: css/test-id first, then xpath, then text.
* `aria/Name` selectors become Playwright `text=` candidates (the accessible
  name is usually the visible text); `pierce/x` becomes plain `x` (Playwright
  CSS pierces shadow DOM by default). Multi-part candidates (iframe hops) are
  dropped — SynthMK steps act on the top frame.
* A `change` on something that looks like a password field becomes a
  `{{ secret.NAME }}` reference + `sensitive: true` instead of the recorded
  plaintext — the importer never writes a credential into a flow file.
* Unsupported step types (setViewport, close, waitForExpression, pixel
  scrolls) are skipped and reported on stderr; the import never fails on them.

The emitted YAML is linted in-process before it is written: an import that
does not lint clean exits 2 and writes nothing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - dependency guard
    sys.stderr.write("PyYAML is required: pip install pyyaml\n")
    sys.exit(3)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flow_lint  # noqa: E402

PASSWORD_HINT_RE = re.compile(r"pass(word|wd)?|pwd", re.IGNORECASE)
# Keys worth replaying; bare modifier/letter keyDowns are typing noise that the
# preceding `change` step already captured as the final field value.
REPLAY_KEYS = {"Enter", "Tab", "Escape", "ArrowDown", "ArrowUp", "PageDown", "PageUp"}


# Cap on selector candidates kept per element. DevTools emits a handful;
# a hostile or pathological recording could carry thousands. A real element
# never needs more than a few resilient locators, and the runner tries them
# in order on every poll, so an unbounded ladder is both useless and a DoS.
MAX_CANDIDATES_PER_STEP = 8
# Cap on raw candidate entries scanned, so even truncating cannot be made
# expensive by a huge input array.
MAX_RAW_SCAN = 200


def convert_selectors(raw: list, notes: list[str]) -> list[str]:
    """DevTools selectors[] (list of candidate arrays) -> SynthMK ladder."""
    primary: list[str] = []   # css / test-attribute / pierce
    xpath: list[str] = []
    text: list[str] = []      # aria/text fallbacks
    scanned = (raw or [])[:MAX_RAW_SCAN]
    if raw and len(raw) > MAX_RAW_SCAN:
        notes.append(f"recording had {len(raw)} selector candidates for one "
                     f"element; scanned the first {MAX_RAW_SCAN}")
    for cand in scanned:
        if not isinstance(cand, list) or not cand:
            continue
        if len(cand) > 1:
            notes.append("dropped an iframe-scoped selector candidate")
            continue
        sel = str(cand[0])
        if sel.startswith("aria/"):
            text.append(f"text={sel[len('aria/'):]}")
        elif sel.startswith("text/"):
            text.append(f"text={sel[len('text/'):]}")
        elif sel.startswith("xpath/"):
            xpath.append(f"xpath={sel[len('xpath/'):]}")
        elif sel.startswith("pierce/"):
            primary.append(sel[len("pierce/"):])
        else:
            primary.append(sel)
    ladder: list[str] = []
    for sel in primary + xpath + text:
        if sel not in ladder:
            ladder.append(sel)
    if len(ladder) > MAX_CANDIDATES_PER_STEP:
        notes.append(f"kept the {MAX_CANDIDATES_PER_STEP} strongest of "
                     f"{len(ladder)} selector candidates for an element")
        ladder = ladder[:MAX_CANDIDATES_PER_STEP]
    return ladder


def selector_value(ladder: list[str]):
    """Collapse a one-entry ladder to a plain string for cleaner YAML."""
    return ladder[0] if len(ladder) == 1 else ladder


def convert(recording: dict) -> tuple[dict, list[str]]:
    """DevTools recording dict -> (SynthMK flow dict, skipped/changed notes)."""
    notes: list[str] = []
    steps: list[dict] = []
    secret_seq = 0

    for i, rec in enumerate(recording.get("steps") or []):
        rtype = rec.get("type")
        ladder = convert_selectors(rec.get("selectors") or [], notes)

        if rtype == "navigate":
            steps.append({"action": "open_url", "url": str(rec.get("url", ""))})
        elif rtype in ("click", "doubleClick"):
            if not ladder:
                notes.append(f"step {i}: {rtype} without usable selectors skipped")
                continue
            step = {"action": "click", "selector": selector_value(ladder)}
            if rtype == "doubleClick":
                step["comment"] = "was doubleClick in the recording"
            steps.append(step)
        elif rtype == "change":
            if not ladder:
                notes.append(f"step {i}: change without usable selectors skipped")
                continue
            value = str(rec.get("value", ""))
            step = {"action": "fill", "selector": selector_value(ladder)}
            if any(PASSWORD_HINT_RE.search(s) for s in ladder):
                secret_seq += 1
                name = "password" if secret_seq == 1 else f"password{secret_seq}"
                step["value"] = "{{ secret.%s }}" % name
                step["sensitive"] = True
                notes.append(
                    f"step {i}: password-like field -> {{{{ secret.{name} }}}} "
                    f"(add the real value to your secrets file; the recorded "
                    f"plaintext was discarded)"
                )
            else:
                step["value"] = value
            steps.append(step)
        elif rtype == "keyDown":
            key = str(rec.get("key", ""))
            if key in REPLAY_KEYS:
                steps.append({"action": "press", "key": key})
            # other keyDowns are typing noise; `change` carries the final value
        elif rtype == "keyUp":
            continue
        elif rtype == "hover":
            if ladder:
                steps.append({"action": "hover", "selector": selector_value(ladder)})
        elif rtype == "scroll":
            if ladder:
                steps.append({"action": "scroll_into_view",
                              "selector": selector_value(ladder)})
            else:
                notes.append(f"step {i}: pixel scroll skipped (no element target)")
        elif rtype == "waitForElement":
            if ladder:
                step = {"action": "wait_for_element", "selector": selector_value(ladder)}
                if rec.get("timeout"):
                    step["timeout_ms"] = int(rec["timeout"])
                steps.append(step)
        elif rtype in ("setViewport", "close", "emulateNetworkConditions"):
            continue  # environment setup, not journey content
        elif rtype == "waitForExpression":
            notes.append(f"step {i}: waitForExpression skipped (no SynthMK equivalent)")
        else:
            notes.append(f"step {i}: unsupported type '{rtype}' skipped")

    flow = {
        "name": str(recording.get("title") or "Imported recording"),
        "timeout_ms": 30000,
        "screenshot_on_failure": True,
        "steps": steps,
    }
    return flow, notes


def to_yaml(flow: dict) -> str:
    header = (
        "# Imported from a Chrome DevTools Recorder recording by\n"
        "# runner/import_devtools.py. Selector lists are fallback ladders;\n"
        "# candidates are tried in order. Review, add assertions (check_*),\n"
        "# set warn_ms/crit_ms, then schedule it in flows.conf.\n"
    )
    return header + yaml.safe_dump(flow, sort_keys=False, default_flow_style=False,
                                   allow_unicode=True, width=88)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert a Chrome DevTools Recorder JSON export to a SynthMK flow")
    parser.add_argument("recording", type=Path, help="recording.json from DevTools")
    parser.add_argument("-o", "--out", type=Path, default=None,
                        help="write the flow here (default: stdout)")
    parser.add_argument("--name", default=None, help="override the flow/service name")
    args = parser.parse_args(argv)

    try:
        recording = json.loads(args.recording.read_text())
    except FileNotFoundError:
        sys.stderr.write(f"recording not found: {args.recording}\n")
        return 3
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"not valid JSON: {exc}\n")
        return 3
    if not isinstance(recording, dict):
        sys.stderr.write("recording must be a JSON object with a 'steps' list\n")
        return 3

    flow, notes = convert(recording)
    if args.name:
        flow["name"] = args.name
    for note in notes:
        sys.stderr.write(f"  note - {note}\n")
    if not flow["steps"]:
        sys.stderr.write("recording produced no usable steps\n")
        return 2

    errors, warnings = flow_lint.lint_flow(flow, source=str(args.recording))
    for w in warnings:
        sys.stderr.write(f"  warn - {w}\n")
    if errors:
        for e in errors:
            sys.stderr.write(f"  FAIL - {e}\n")
        return 2

    text = to_yaml(flow)
    if args.out:
        args.out.write_text(text)
        sys.stderr.write(f"wrote {args.out} ({len(flow['steps'])} steps)\n")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
