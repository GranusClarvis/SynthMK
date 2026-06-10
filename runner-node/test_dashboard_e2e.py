#!/usr/bin/env python3
"""Dashboard UI end-to-end test — real browser, real admin server, real builder.

Drives the management dashboard with Playwright the way an operator would:
sign in, open the visual step builder, point-and-click elements on a live
page preview, add tested steps, export to the editor, lint & save, see the
check appear in the table, pause it.

Needs Playwright browsers + system libs, so it runs inside the runner image
(matching extension/test_e2e.py's approach for the recorder):

    docker run --rm -e SYNTHMK_NO_SANDBOX=1 \
      -v "$PWD":/ws -w /ws synthmk-runner:0.4.0 \
      python3 runner-node/test_dashboard_e2e.py

Also captures site-assets/step-builder.png (element picked, panel open) for
the website when SYNTHMK_E2E_SHOTS=1.
"""
from __future__ import annotations

import http.server
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

ADMIN_TOK = "e2e-admin-token"

# Deterministic target page: full-width 100px-tall bands, so picking by
# coordinates is exact at the builder's fixed 1280x800 viewport.
TEST_PAGE = """<!DOCTYPE html><html><head><title>Builder Target App</title>
<style>body{margin:0;font:16px sans-serif}
div{height:100px;display:flex;align-items:center;padding:0 20px;box-sizing:border-box;width:100%}
</style></head><body>
<div><button id="go" style="width:100%;height:80px" data-testid="go-button">Continue</button></div>
<div><input id="user" name="username" style="width:100%;height:60px" placeholder="username"></div>
<div><select id="plan" name="plan" style="width:100%;height:60px">
  <option value="basic">Basic</option><option value="pro">Pro</option></select></div>
<div><h1 id="headline">Welcome to the Target App</h1></div>
</body></html>"""

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


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        flows = tdp / "flows"
        flows.mkdir()
        conf = tdp / "flows.conf"
        conf.write_text("")
        (tdp / "spool").mkdir()
        web = tdp / "web"
        web.mkdir()
        (web / "app.html").write_text(TEST_PAGE)

        web_port = free_port()
        httpd = http.server.ThreadingHTTPServer(
            ("127.0.0.1", web_port),
            lambda *a, **kw: http.server.SimpleHTTPRequestHandler(
                *a, directory=str(web), **kw))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        admin_port = free_port()
        env = dict(os.environ,
                   SYNTHMK_HOME=str(ROOT),
                   SYNTHMK_FLOWS=str(flows),
                   SYNTHMK_FLOWS_CONF=str(conf),
                   SYNTHMK_SPOOL=str(tdp / "spool"),
                   SYNTHMK_RUN_NOW_DIR=str(tdp / "run-now"),
                   SYNTHMK_ADMIN_PORT=str(admin_port),
                   SYNTHMK_ADMIN_BIND="127.0.0.1",
                   SYNTHMK_ADMIN_TOKEN=ADMIN_TOK,
                   SYNTHMK_AUDIT_LOG=str(tdp / "audit.log"),
                   SYNTHMK_ADMIN_TOKEN_FILE=str(tdp / "token"),
                   SYNTHMK_BUILDER_ALLOW_INTERNAL="1")
        server = subprocess.Popen([sys.executable, str(HERE / "admin_server.py")],
                                  env=env, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                try:
                    socket.create_connection(("127.0.0.1", admin_port), 0.2).close()
                    break
                except OSError:
                    time.sleep(0.1)

            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                args = ["--no-sandbox", "--disable-dev-shm-usage"] \
                    if os.environ.get("SYNTHMK_NO_SANDBOX") else []
                browser = p.chromium.launch(headless=True, args=args)
                page = browser.new_page(viewport={"width": 1500, "height": 1000})

                print("== sign in ==")
                page.goto(f"http://127.0.0.1:{admin_port}/login")
                page.fill("#tok", ADMIN_TOK)
                page.click("button")
                page.wait_for_selector("#rows", timeout=10000)
                check("login reaches the dashboard", "/login" not in page.url)

                print("== step builder: open page ==")
                page.click("#builderbtn")
                page.fill("#burl", f"http://127.0.0.1:{web_port}/app.html")
                page.get_by_role("button", name="Open page").click()
                page.wait_for_selector("#bshot[src^='data:image/png']",
                                       timeout=30000)
                check("live page preview rendered", True)
                check("open_url recorded as step 0",
                      "open_url" in page.locator("#bsteplist").inner_text())

                def pick(natural_y):
                    """Click the preview at page-natural (640, natural_y)."""
                    box = page.locator("#bshot").bounding_box()
                    page.mouse.click(box["x"] + box["width"] * 0.5,
                                     box["y"] + box["height"] * natural_y / 800)
                    page.wait_for_selector("#bact", timeout=15000)

                print("== pick button -> click step ==")
                pick(50)
                panel = page.locator("#belem").inner_text()
                check("button picked with its tag shown", "<button" in panel)
                check("test-attribute candidate ranked",
                      "data-testid" in page.locator("#belem").inner_text())
                check("default action for a button is click",
                      page.locator("#bact").input_value() == "click")
                page.get_by_role("button", name="Add & test step").click()
                page.wait_for_selector("#bsteplist li:nth-of-type(2)", timeout=20000)
                assert page.locator("#bsteplist li").count() == 2
                check("click step tested live and added", True)

                print("== pick input -> fill step ==")
                pick(150)
                check("default action for an input is fill",
                      page.locator("#bact").input_value() == "fill")
                page.fill("#bval", "monitor-bot")
                page.get_by_role("button", name="Add & test step").click()
                page.wait_for_selector("#bsteplist li:nth-of-type(3)", timeout=20000)
                assert page.locator("#bsteplist li").count() == 3
                check("fill step tested live and added", True)

                if os.environ.get("SYNTHMK_E2E_SHOTS"):
                    pick(250)  # select element picked, panel open — site shot
                    page.screenshot(path=str(ROOT / "site-assets" / "step-builder.png"))
                    page.keyboard.press("Escape")

                print("== pick select -> select_option step ==")
                pick(250)
                check("default action for a select is select_option",
                      page.locator("#bact").input_value() == "select_option")
                page.select_option("#bval", "pro")
                page.get_by_role("button", name="Add & test step").click()
                page.wait_for_selector("#bsteplist li:nth-of-type(4)", timeout=20000)
                assert page.locator("#bsteplist li").count() == 4
                check("select_option step tested live and added", True)

                print("== pick headline -> text assertion ==")
                pick(350)
                check("default action for text content is check_visible_text",
                      page.locator("#bact").input_value() == "check_visible_text")
                check("assertion text prefilled from the element",
                      "Welcome to the Target App" in page.locator("#bval").input_value())
                page.get_by_role("button", name="Add & test step").click()
                page.wait_for_selector("#bsteplist li:nth-of-type(5)", timeout=20000)
                assert page.locator("#bsteplist li").count() == 5
                check("text assertion tested live and added", True)

                print("== quick page check + failing step is rejected ==")
                page.once("dialog", lambda d: d.accept("Builder Target App"))
                page.get_by_role("button", name="Assert title").click()
                page.wait_for_selector("#bsteplist li:nth-of-type(6)", timeout=20000)
                assert page.locator("#bsteplist li").count() == 6
                check("assert-title quick action added", True)
                page.once("dialog", lambda d: d.accept("THIS TEXT IS NOT THERE"))
                page.get_by_role("button", name="Assert text…").click()
                page.wait_for_selector("#bstatus:has-text('not added')", timeout=20000)
                count = page.locator("#bsteplist li").count()
                check("failing step is NOT added to the flow", count == 6)

                print("== export -> lint & save -> appears in table ==")
                page.fill("#bname", "UI E2E Journey")
                page.get_by_role("button", name="Open in editor").click()
                yaml_text = page.locator("#eyaml").input_value()
                check("exported YAML has the journey",
                      "open_url" in yaml_text and "select_option" in yaml_text
                      and "check_visible_text" in yaml_text)
                check("exported YAML uses a selector ladder",
                      "- \"[data-testid=" in yaml_text or "- \"#" in yaml_text)
                page.get_by_role("button", name="Lint & save").click()
                page.wait_for_selector("#msg:has-text('Saved')", timeout=15000)
                check("builder-exported flow lints and saves",
                      (flows / "ui-e2e-journey.yaml").is_file())

                print("== manage: pause from the table ==")
                page.wait_for_selector("text=ui-e2e-journey.yaml", timeout=15000)
                page.get_by_role("button", name="Pause").first.click()
                page.wait_for_selector("text=PAUSED", timeout=10000)
                check("pause reflects in the table", True)
                check("conf line paused on disk",
                      conf.read_text().strip().startswith("#PAUSED "))

                browser.close()
        finally:
            server.kill()
            httpd.shutdown()

    print(f"\n{PASS} checks passed, {len(FAILS)} failed.")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
