"""Example SynthMK script flow — referenced by flows/example-script.yaml.

`run(page, api)` is the entry point. `page` is a regular Playwright sync
Page (full API, no YAML ceiling). `api` adds the monitoring contract:

  api.step("label")    context manager; the block's duration becomes a named
                       per-step metric graphed in Checkmk, and a failure
                       inside it is reported as failing that step
  api.secret("name")   value from the node's secrets file; automatically
                       redacted from all output and masked in screenshots
  api.totp("name")     6-digit RFC 6238 code from a base32 seed secret
  api.var("uuid")      per-run stable builtin (uuid | timestamp | random)
  api.screenshot("x")  evidence capture (masked once a secret was used)
  api.fail("message")  fail the check with a clear message

Raising AssertionError (a bare `assert`) also fails the check cleanly.
"""


def run(page, api):
    with api.step("open_login"):
        page.goto("https://portal.example.internal/login")

    with api.step("login"):
        page.fill("#user", api.secret("portal_user"))
        page.fill("#password", api.secret("portal_password"))
        page.click("button[type=submit]")

    with api.step("dashboard"):
        page.wait_for_selector("#dashboard")
        assert "Dashboard" in page.title(), "dashboard title missing after login"

    # Anything YAML flows can't do — loop over rows, branch on page state:
    with api.step("widgets"):
        rows = page.locator(".widget").count()
        if rows < 3:
            api.fail(f"expected at least 3 dashboard widgets, found {rows}")
