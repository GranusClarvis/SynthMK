#!/usr/bin/env python3
"""Real-browser E2E for the SynthMK recorder extension.

Loads the MV3 extension into a real Chromium (Playwright persistent context),
drives an actual login journey on the target page, then pulls the recorded
steps out of the background service worker and validates them:

  * password input was recorded as a {{ secret.* }} reference + sensitive flag
    (the typed value must appear NOWHERE in the export)
  * Enter keypress became a `press` step, select became `select_option`
  * the YAML the popup would download parses and lints clean

Needs the full Chromium (extensions don't run in headless-shell):
    python3 extension/test_e2e.py http://intranet-demo/login.html
Typically run inside the runner-node container (browsers preinstalled):
    docker exec synthmk-runner python3 /work/extension/test_e2e.py ...
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

EXT_DIR = Path(__file__).resolve().parent
REPO = EXT_DIR.parent

FAILS: list[str] = []


def check(label: str, cond: bool) -> None:
    print(f"  {'ok  ' if cond else 'FAIL'} - {label}")
    if not cond:
        FAILS.append(label)


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "http://intranet-demo/login.html"
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p, tempfile.TemporaryDirectory() as profile:
        context = p.chromium.launch_persistent_context(
            profile,
            channel="chromium",          # full Chromium: extensions unsupported in headless-shell
            headless=True,
            args=[
                f"--disable-extensions-except={EXT_DIR}",
                f"--load-extension={EXT_DIR}",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        try:
            # The MV3 service worker is the recorder's brain.
            if not context.service_workers:
                context.wait_for_event("serviceworker", timeout=15000)
            sw = context.service_workers[0]
            check("extension service worker started", sw is not None)

            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url, wait_until="domcontentloaded")

            tab_id = sw.evaluate(
                "url => new Promise(res => chrome.tabs.query({}, tabs =>"
                " res((tabs.find(t => (t.url||'').startsWith(url)) || {}).id)))",
                url.split("login.html")[0],
            )
            check("recorded tab found", isinstance(tab_id, int))

            # Drive the REAL popup page (extension messaging only works from a
            # separate extension context, not from the service worker itself).
            ext_id = sw.url.split("/")[2]
            popup = context.new_page()
            popup.goto(f"chrome-extension://{ext_id}/popup.html")
            check("popup renders", popup.locator("#start").is_visible())

            # START through the real runtime.sendMessage channel; explicit
            # tabId because in a tab-hosted popup the 'active tab' is itself.
            popup.evaluate(
                "id => new Promise(res => chrome.runtime.sendMessage("
                "{type:'START', tabId:id}, res))", tab_id)

            # The journey a user would record.
            page.bring_to_front()
            page.fill("#username", "monitor")
            page.fill("#password", "synthmk-lab-secret")
            page.press("#password", "Enter")
            page.wait_for_url("**/dashboard.html")
            page.select_option("#report-period", "week")
            time.sleep(1.2)  # let the debounced fill + final steps land

            state = popup.evaluate(
                "() => new Promise(res => chrome.runtime.sendMessage("
                "{type:'STOP'}, () => chrome.runtime.sendMessage("
                "{type:'GET_STATE'}, res)))")
            steps = state["state"]["steps"]

            # The popup's live step list must render the recorded steps.
            popup.reload()
            popup.wait_for_timeout(500)
            rendered = popup.locator("#steps li").count()
            check("popup step list renders recorded steps", rendered == len(steps))
            check("popup flags the secret reference",
                  popup.locator("#secret-hint").is_visible())
            print(f"  recorded steps: {json.dumps(steps, indent=2)[:800]}")

            actions = [s["action"] for s in steps]
            check("navigation recorded", "open_url" in actions)
            check("username fill recorded",
                  any(s["action"] == "fill" and s.get("value") == "monitor" for s in steps))
            pw = [s for s in steps if s["action"] == "fill" and s.get("sensitive")]
            check("password recorded as sensitive secret ref",
                  len(pw) == 1 and pw[0]["value"] == "{{ secret.password }}")
            check("typed password value appears nowhere",
                  "synthmk-lab-secret" not in json.dumps(steps))
            check("Enter became a press step",
                  any(s["action"] == "press" and s.get("key") == "Enter" for s in steps))
            check("select became select_option",
                  any(s["action"] == "select_option" and s.get("value") == "week"
                      for s in steps))
            check("dashboard navigation recorded",
                  any(s["action"] == "open_url" and "dashboard" in s.get("url", "")
                      for s in steps))

            # Serialize exactly as the popup's download button would. Use the
            # node binary Playwright bundles (the appliance image has no system
            # node), falling back to system node on dev machines.
            import shutil
            node_bin = shutil.which("node")
            if not node_bin:
                import playwright as _pw
                node_bin = str(Path(_pw.__file__).parent / "driver" / "node")
            yaml_text = subprocess.run(
                [node_bin, "-e",
                 "const E=require(process.argv[1]);"
                 "let chunks=[];process.stdin.on('data',c=>chunks.push(c));"
                 "process.stdin.on('end',()=>{"
                 "const steps=JSON.parse(Buffer.concat(chunks));"
                 "process.stdout.write(E.stepsToYaml({name:'Recorded Login'},steps));});",
                 str(EXT_DIR / "recorder_export.js")],
                input=json.dumps(steps), capture_output=True, text=True,
            ).stdout
            check("export produced YAML", yaml_text.startswith("#"))

            flow_file = Path(tempfile.mkstemp(suffix=".yaml")[1])
            flow_file.write_text(yaml_text)
            lint = subprocess.run(
                [sys.executable, str(REPO / "runner" / "flow_lint.py"), str(flow_file)],
                capture_output=True, text=True)
            print(lint.stdout.rstrip())
            check("exported YAML lints clean (exit 0)", lint.returncode == 0)
            check("exported YAML carries the secret ref",
                  "{{ secret.password }}" in yaml_text and "sensitive: true" in yaml_text)
        finally:
            context.close()

    print(f"\n{'E2E OK' if not FAILS else 'E2E FAILED: ' + ', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
