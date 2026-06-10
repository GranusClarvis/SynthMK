"""Lab script flow: logs into the demo portal with code instead of YAML.

Proves the script-check contract live: api.step timings become per-step
metrics in Checkmk, api.secret values are pulled from the node secrets file
and redacted everywhere, and a plain assert fails the check cleanly.
"""


def run(page, api):
    with api.step("open_login"):
        page.goto("http://intranet-demo/login.html")

    with api.step("login"):
        page.fill("#username", api.secret("portal_user"))
        page.fill("#password", api.secret("portal_password"))
        page.click("#login-submit")
        page.wait_for_url("**/dashboard.html")

    with api.step("verify"):
        assert page.locator("[data-testid=welcome]").is_visible(), \
            "welcome banner missing after login"
        rows = page.locator("tr.order-row").count()
        if rows < 3:
            api.fail(f"expected at least 3 order rows, found {rows}")
