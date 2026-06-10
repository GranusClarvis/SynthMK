#!/usr/bin/env python3
"""Contract tests for the Chrome DevTools Recorder importer.

Validates the JSON->YAML mapping against a representative recording (the step
types DevTools actually emits), that recorded passwords never survive into the
flow, and that the importer's output always lints clean.

Run:  python3 runner/test_import_devtools.py   (exit 0 = all passed)
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import import_devtools as I  # noqa: E402
import flow_lint as L  # noqa: E402

PASS = 0
FAILS = []


def check(label, cond):
    global PASS
    if cond:
        PASS += 1
        print(f"  ok   - {label}")
    else:
        FAILS.append(label)
        print(f"  FAIL - {label}")


# A condensed but faithful DevTools Recorder export: every supported type plus
# the ones the importer must skip gracefully.
RECORDING = {
    "title": "Portal login journey",
    "steps": [
        {"type": "setViewport", "width": 1280, "height": 720},
        {"type": "navigate", "url": "https://portal.example/login",
         "assertedEvents": [{"type": "navigation", "url": "https://portal.example/login",
                             "title": "Sign in"}]},
        {"type": "click",
         "selectors": [["aria/Username"], ["#user"],
                       ["xpath///*[@id='user']"], ["pierce/#user"]],
         "offsetX": 10, "offsetY": 8},
        {"type": "change", "value": "monitor-bot",
         "selectors": [["#user"], ["xpath///*[@id='user']"]]},
        {"type": "change", "value": "hunter2-recorded-plaintext",
         "selectors": [["#password"], ["xpath///*[@id='password']"]]},
        {"type": "keyDown", "key": "Enter"},
        {"type": "keyUp", "key": "Enter"},
        {"type": "keyDown", "key": "Shift"},
        {"type": "hover", "selectors": [["aria/Account menu"], ["#account"]]},
        {"type": "scroll", "x": 0, "y": 800},
        {"type": "scroll", "selectors": [["#footer"]]},
        {"type": "waitForElement", "selectors": [["#dashboard"]], "timeout": 9000},
        {"type": "waitForExpression", "expression": "document.title === 'Dash'"},
        {"type": "click", "selectors": [["iframe-outer", "#inner-button"]]},
        {"type": "close"},
    ],
}


def main() -> int:
    print("== DevTools selector conversion ==")
    notes: list[str] = []
    ladder = I.convert_selectors(
        [["aria/Submit"], ["[data-testid=go]"], ["xpath///*[@id='go']"], ["pierce/#go"]],
        notes)
    check("css/test-id candidates rank first", ladder[0] == "[data-testid=go]")
    check("pierce/ prefix stripped to plain css", "#go" in ladder)
    check("xpath candidate carries xpath= prefix", "xpath=//*[@id='go']" in ladder)
    check("aria candidate becomes a text= fallback (last)", ladder[-1] == "text=Submit")
    check("ladder is deduplicated", len(ladder) == len(set(ladder)))

    print("== full recording conversion ==")
    flow, notes = I.convert(RECORDING)
    actions = [s["action"] for s in flow["steps"]]
    check("flow name from recording title", flow["name"] == "Portal login journey")
    check("action sequence",
          actions == ["open_url", "click", "fill", "fill", "press",
                      "hover", "scroll_into_view", "wait_for_element"])
    check("navigate url preserved",
          flow["steps"][0]["url"] == "https://portal.example/login")
    check("multi-selector click keeps a ladder",
          isinstance(flow["steps"][1]["selector"], list)
          and flow["steps"][1]["selector"][0] == "#user")

    pw = flow["steps"][3]
    check("password plaintext discarded",
          "hunter2-recorded-plaintext" not in json.dumps(flow))
    check("password becomes a secret reference",
          pw["value"] == "{{ secret.password }}" and pw.get("sensitive") is True)
    check("password swap is reported", any("password-like" in n for n in notes))

    check("Enter keyDown becomes press, keyUp/Shift dropped",
          flow["steps"][4] == {"action": "press", "key": "Enter"})
    check("waitForElement carries its timeout",
          flow["steps"][7].get("timeout_ms") == 9000)
    check("pixel scroll skipped with note",
          any("pixel scroll" in n for n in notes))
    check("iframe-scoped candidate dropped with note",
          any("iframe-scoped" in n for n in notes))
    check("waitForExpression skipped with note",
          any("waitForExpression" in n for n in notes))

    print("== output lints clean and parses ==")
    errors, _ = L.lint_flow(flow, source="imported")
    check("converted flow lints clean", errors == [])
    text = I.to_yaml(flow)
    import yaml as Y
    reparsed = Y.safe_load(text)
    check("emitted YAML round-trips", reparsed["steps"] == flow["steps"])

    print("== CLI end to end ==")
    with tempfile.TemporaryDirectory() as td:
        rec = Path(td) / "recording.json"
        out = Path(td) / "imported.yaml"
        rec.write_text(json.dumps(RECORDING))
        proc = subprocess.run(
            [sys.executable, str(HERE / "import_devtools.py"), str(rec),
             "-o", str(out), "--name", "My Portal Check"],
            capture_output=True, text=True, timeout=30)
        check("CLI exits 0", proc.returncode == 0)
        check("CLI wrote the flow", out.is_file())
        check("CLI --name override applied",
              out.is_file() and "name: My Portal Check" in out.read_text())
        lint = subprocess.run(
            [sys.executable, str(HERE / "flow_lint.py"), str(out)],
            capture_output=True, text=True, timeout=30)
        check("CLI output passes the real linter", lint.returncode == 0)

        bad = Path(td) / "bad.json"
        bad.write_text("{not json")
        proc = subprocess.run(
            [sys.executable, str(HERE / "import_devtools.py"), str(bad)],
            capture_output=True, text=True, timeout=30)
        check("invalid JSON exits 3", proc.returncode == 3)

        empty = Path(td) / "empty.json"
        empty.write_text(json.dumps({"title": "x", "steps": [{"type": "close"}]}))
        proc = subprocess.run(
            [sys.executable, str(HERE / "import_devtools.py"), str(empty)],
            capture_output=True, text=True, timeout=30)
        check("recording with no usable steps exits 2", proc.returncode == 2)

    print(f"\n{PASS} checks passed, {len(FAILS)} failed.")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
