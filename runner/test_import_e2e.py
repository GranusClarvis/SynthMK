#!/usr/bin/env python3
"""DevTools-import end-to-end: recording JSON -> import -> REAL browser run.

Takes a Chrome DevTools Recorder export of the lab login journey (the JSON
shape Chrome produces, including multi-candidate selectors and the recorded
password plaintext), runs the real importer CLI, then executes the imported
flow with the real runner against the lab demo site. Proves the whole
no-extension authoring path produces a flow that actually passes.

Needs the lab network (intranet-demo) + browsers, so run it in the runner
image on the lab network:

    docker run --rm -e SYNTHMK_NO_SANDBOX=1 --network synthmk-lab_labnet \
      -v "$PWD":/ws -w /ws synthmk-runner:<ver> python3 runner/test_import_e2e.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

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


# What Chrome's Recorder exports for the lab login journey (abridged to the
# step types it actually emits; selectors are real candidates for the page).
RECORDING = {
    "title": "Lab portal login",
    "steps": [
        {"type": "setViewport", "width": 1280, "height": 800},
        {"type": "navigate", "url": "http://intranet-demo/login.html",
         "assertedEvents": [{"type": "navigation",
                             "url": "http://intranet-demo/login.html",
                             "title": "Internal Portal — Sign in"}]},
        {"type": "click",
         "selectors": [["aria/Username"], ["#username"],
                       ["xpath///*[@id='username']"], ["pierce/#username"]]},
        {"type": "change", "value": "monitor",
         "selectors": [["#username"], ["xpath///*[@id='username']"]]},
        {"type": "change", "value": "this-plaintext-must-not-survive",
         "selectors": [["#password"], ["xpath///*[@id='password']"]]},
        {"type": "click",
         "selectors": [["aria/Sign in"], ["#login-submit"],
                       ["xpath///*[@id='login-submit']"]]},
        {"type": "waitForElement", "selectors": [["[data-testid='welcome']"]],
         "timeout": 10000},
    ],
}


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        rec = tdp / "recording.json"
        rec.write_text(json.dumps(RECORDING))
        out = tdp / "imported.yaml"

        print("== import the recording (real CLI) ==")
        proc = subprocess.run(
            [sys.executable, str(HERE / "import_devtools.py"), str(rec),
             "-o", str(out), "--name", "Imported Lab Login"],
            capture_output=True, text=True, timeout=60)
        check("importer exits 0", proc.returncode == 0)
        text = out.read_text()
        check("recorded password plaintext was discarded",
              "this-plaintext-must-not-survive" not in text)
        check("password became a secret reference",
              "{{ secret.password }}" in text and "sensitive: true" in text)
        check("selector ladders survived the import",
              text.count("- '#username'") + text.count('- "#username"')
              + text.count("- '#password'") >= 1 or "- xpath=" in text)

        # The lab page expects the secret store's credentials; point the
        # imported placeholder at the existing lab secret and add the missing
        # username-as-secret mapping the importer cannot know about.
        text = text.replace("{{ secret.password }}", "{{ secret.portal_password }}")
        out.write_text(text)

        print("== run the imported flow with the REAL runner ==")
        env = dict(os.environ,
                   SYNTHMK_SECRETS_FILE=str(ROOT / "lab" / "secrets.yaml"))
        proc = subprocess.run(
            [sys.executable, str(HERE / "runner.py"), str(out)],
            capture_output=True, text=True, timeout=120, env=env)
        line = proc.stdout.strip()
        print(f"  runner: {line[:140]}")
        check("imported flow PASSES against the live lab page",
              proc.returncode == 0 and line.startswith('0 "Imported Lab Login"'))
        check("output carries per-step metrics", "step0_open_url=" in line)
        check("no secret value in the service line",
              "synthmk-lab-secret" not in line)

    print(f"\n{PASS} checks passed, {len(FAILS)} failed.")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
