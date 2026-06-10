#!/usr/bin/env python3
"""Browser-free validation of the SynthMK runner's Checkmk output contract.

This is the local validation command for the MVP. It exercises the parts of the
runner that define the product surface — the Checkmk local-check line, the
warn/crit duration escalation, the assertion-failure messages, and the {{ }}
env substitution — WITHOUT launching a real browser, using a tiny fake page.

The real end-to-end browser run lives in runner/smoke_test.sh and needs a
working Playwright Chromium (system X libs). This test runs anywhere Python +
PyYAML are available, so CI always validates the output contract.

Run:  python3 runner/test_contract.py   (exit 0 = all assertions passed)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner as R  # noqa: E402


class FakeLocator:
    def __init__(self, matches):
        self._matches = matches

    def count(self):
        return len(self._matches)

    def nth(self, i):
        return self._matches[i]


class FakeMatch:
    def __init__(self, visible=True):
        self._visible = visible

    def is_visible(self):
        return self._visible


class FakePage:
    """Minimal stand-in for a Playwright Page for assertion-path testing."""

    def __init__(self, title="SynthMK Demo App", url="file:///demo/index.html",
                 visible_texts=("Welcome to SynthMK", "Account Overview")):
        self._title = title
        self.url = url
        self._visible_texts = set(visible_texts)

    def title(self):
        return self._title

    def get_by_text(self, text):
        if text in self._visible_texts:
            return FakeLocator([FakeMatch(visible=True)])
        return FakeLocator([])


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


def main() -> int:
    print("== Checkmk line formatting ==")
    ok = R.FlowResult(service="Synthetic Example Check", status=R.OK,
                      duration_ms=1200, warn_ms=3000, crit_ms=7000)
    line = ok.checkmk_line()
    check("OK line shape", line ==
          '0 "Synthetic Example Check" duration=1200ms;3000;7000 OK - Flow completed successfully')

    crit = R.FlowResult(service="Synthetic Example Check", status=R.CRIT,
                        duration_ms=6500, warn_ms=3000, crit_ms=7000,
                        summary="Expected text 'Dashboard' not found")
    cline = crit.checkmk_line()
    check("CRIT line shape", cline ==
          '2 "Synthetic Example Check" duration=6500ms;3000;7000 CRIT - Expected text \'Dashboard\' not found')

    shot = R.FlowResult(service="S", status=R.CRIT, duration_ms=10,
                        summary="boom", screenshot="screenshots/s-fail.png")
    check("screenshot metadata in line", "(screenshot: screenshots/s-fail.png)" in shot.checkmk_line())

    # screenshot link (v0.2.0): with a base URL, render a clickable <a href>.
    shot_url = R.FlowResult(service="S", status=R.CRIT, duration_ms=10,
                            summary="boom", screenshot="screenshots/s-fail.png",
                            shot_base_url="http://runner:9180/")
    check("screenshot link uses base url + basename",
          '<a href="http://runner:9180/s-fail.png">screenshot</a>' in shot_url.checkmk_line())

    # dynamic state (v0.2.0): passing flow emits 'P' and no "OK -" prefix so
    # Checkmk computes the state from the duration thresholds.
    dyn = R.FlowResult(service="S", status=R.OK, duration_ms=1200,
                       warn_ms=3000, crit_ms=7000, dynamic=True)
    dline = dyn.checkmk_line()
    check("dynamic OK emits P", dline.startswith('P "S" duration=1200ms;3000;7000 '))
    check("dynamic OK has no digit-state prefix", " OK - " not in dline)
    # A failure stays an explicit digit even in dynamic mode.
    dyn_fail = R.FlowResult(service="S", status=R.CRIT, duration_ms=10,
                            summary="boom", dynamic=True)
    check("dynamic failure keeps digit state", dyn_fail.checkmk_line().startswith('2 "S" '))

    print("== assertion step paths (fake page) ==")
    page = FakePage()
    # passing assertions raise nothing
    try:
        R._run_step(page, {"action": "check_title", "contains": "SynthMK Demo"}, 5000, {})
        R._run_step(page, {"action": "check_visible_text", "text": "Welcome to SynthMK"}, 5000, {})
        R._run_step(page, {"action": "check_url", "contains": "/demo/"}, 5000, {})
        check("passing assertions do not raise", True)
    except Exception as e:  # noqa: BLE001
        check(f"passing assertions do not raise ({e})", False)

    # failing visible-text assertion → clear message
    try:
        R._run_step(page, {"action": "check_visible_text", "text": "Dashboard"}, 5000, {})
        check("missing text raises FlowError", False)
    except R.FlowError as fe:
        check("missing text message", str(fe) == "Expected text 'Dashboard' not found")
        check("missing text is CRIT", fe.status == R.CRIT)

    # failing title assertion
    try:
        R._run_step(page, {"action": "check_title", "contains": "Nope"}, 5000, {})
        check("bad title raises FlowError", False)
    except R.FlowError as fe:
        check("bad title message mentions expected", "Nope" in str(fe))

    print("== duration threshold escalation (post-run logic) ==")

    def escalate(duration, warn, crit):
        r = R.FlowResult(service="S", status=R.OK, duration_ms=duration,
                         warn_ms=warn, crit_ms=crit)
        if r.status == R.OK:
            if crit is not None and r.duration_ms >= crit:
                r.status = R.CRIT
            elif warn is not None and r.duration_ms >= warn:
                r.status = R.WARN
        return r.status

    check("under warn -> OK", escalate(1200, 3000, 7000) == R.OK)
    check("over warn -> WARN", escalate(4000, 3000, 7000) == R.WARN)
    check("over crit -> CRIT", escalate(8000, 3000, 7000) == R.CRIT)

    print("== {{ }} env substitution ==")
    os.environ["SYNTHMK_X"] = "https://demo.local"
    check("placeholder resolved", R._substitute("{{ SYNTHMK_X }}/login") == "https://demo.local/login")
    check("unknown placeholder -> empty", R._substitute("{{ NOPE_VAR }}") == "")

    print("== flow_lint static validation ==")
    import flow_lint as L  # noqa: E402

    clean = {"name": "ok", "steps": [
        {"action": "open_url", "url": "x"},
        {"action": "check_title", "contains": "T"},
    ]}
    errs, _ = L.lint_flow(clean, source="t")
    check("clean flow has no errors", errs == [])

    errs, _ = L.lint_flow({"steps": [{"action": "clikc", "selector": "#x"}]}, source="t")
    check("unknown action is an error", any("unknown action" in e for e in errs))

    errs, _ = L.lint_flow({"steps": [{"action": "click"}]}, source="t")
    check("missing required key is an error", any("missing required key 'selector'" in e for e in errs))

    errs, _ = L.lint_flow({"steps": [], "name": "x"}, source="t")
    check("empty steps is an error", any("empty" in e for e in errs))

    errs, _ = L.lint_flow({"warn_ms": 9000, "crit_ms": 3000,
                           "steps": [{"action": "open_url", "url": "x"}]}, source="t")
    check("warn_ms > crit_ms is an error", any("warn_ms" in e for e in errs))

    _, warns = L.lint_flow({"steps": [{"action": "open_url", "url": "x", "typo": 1}]}, source="t")
    check("unexpected step key is a warning, not error", any("typo" in w for w in warns))

    # v0.2.0 fields: state_mode + checkmk_host
    errs, _ = L.lint_flow({"state_mode": "sideways",
                           "steps": [{"action": "open_url", "url": "x"}]}, source="t")
    check("bad state_mode is an error", any("state_mode" in e for e in errs))

    errs, _ = L.lint_flow({"state_mode": "dynamic", "crit_ms": 7000,
                           "steps": [{"action": "open_url", "url": "x"}]}, source="t")
    check("valid dynamic state_mode is clean", errs == [])

    errs, _ = L.lint_flow({"checkmk_host": "",
                           "steps": [{"action": "open_url", "url": "x"}]}, source="t")
    check("empty checkmk_host is an error", any("checkmk_host" in e for e in errs))

    errs, _ = L.lint_flow({"checkmk_host": "intranet-wiki",
                           "steps": [{"action": "open_url", "url": "x"}]}, source="t")
    check("valid checkmk_host is clean", errs == [])

    # The linter's action table must stay in lockstep with the runner's dispatch.
    check("lint actions cover runner ASSERT_ACTIONS",
          R.ASSERT_ACTIONS.issubset(set(L.REQUIRED_KEYS)))

    print("== v0.4.0: multi-browser engine resolution ==")
    check("chromium default", R._browser_engine(None) == ("chromium", None))
    # `chrome` maps to BUNDLED chromium (no channel) so appliance flows that say
    # `browser: chrome` never demand an OS-installed Chrome stable binary.
    check("chrome -> bundled chromium (no channel)", R._browser_engine("chrome") == ("chromium", None))
    check("edge -> chromium msedge channel", R._browser_engine("Edge") == ("chromium", "msedge"))
    check("firefox -> firefox engine", R._browser_engine("firefox") == ("firefox", None))
    check("webkit -> webkit engine", R._browser_engine("safari") == ("webkit", None))
    check("unknown browser falls back to chromium", R._browser_engine("lynx") == ("chromium", None))
    check("known browsers lint set matches runner engines",
          set(L.KNOWN_BROWSERS) == set(R._BROWSER_ENGINES))

    print("== v0.4.0: wait_for_network_idle + screenshot steps ==")
    # wait_for_network_idle on a page that exposes wait_for_load_state passes;
    # on a page that raises, it surfaces a clear FlowError (not a runner crash).
    class IdlePage(FakePage):
        def wait_for_load_state(self, state, timeout=None):
            assert state == "networkidle"
    try:
        R._run_step(IdlePage(), {"action": "wait_for_network_idle"}, 50, {})
        check("network idle passes when page settles", True)
    except R.FlowError:
        check("network idle passes when page settles", False)

    class BusyPage(FakePage):
        def wait_for_load_state(self, state, timeout=None):
            raise RuntimeError("timeout")
    try:
        R._run_step(BusyPage(), {"action": "wait_for_network_idle"}, 50, {})
        check("network never idle raises FlowError", False)
    except R.FlowError as fe:
        check("network never idle raises FlowError", "did not go idle" in str(fe))

    # screenshot step writes a PNG under ctx['shot_dir'] and records its path.
    import tempfile as _tf
    class ShotPage(FakePage):
        def screenshot(self, path=None, full_page=False):
            Path(path).write_bytes(b"PNG")
    with _tf.TemporaryDirectory() as _sd:
        sctx = {"shot_dir": _sd, "flow_stem": "demo"}
        R._run_step(ShotPage(), {"action": "screenshot", "name": "after-login"}, 50, sctx)
        shots = sctx.get("screenshots", [])
        check("screenshot step records a capture path", len(shots) == 1)
        check("screenshot file written to shot_dir", shots and Path(shots[0]).is_file()
              and "demo-after-login.png" in shots[0])
    # screenshot with no shot_dir is a safe no-op (never raises).
    try:
        R._run_step(ShotPage(), {"action": "screenshot"}, 50, {})
        check("screenshot without shot_dir is a no-op", True)
    except Exception:  # noqa: BLE001
        check("screenshot without shot_dir is a no-op", False)

    print("== v0.3.0: expanded step vocabulary ==")
    # Every action in the linter table must be dispatchable by the runner: an
    # unknown action raises FlowError(UNKNOWN), a known one fails differently
    # (FakePage lacks the method) or passes — so "unknown action" leaking
    # through for a linted action is the lockstep regression we guard against.
    for action in L.REQUIRED_KEYS:
        step = {"action": action, "url": "x", "selector": "#x", "key": "Enter",
                "ms": 1, "contains": "x", "text": "x", "value": "x", "min": 1}
        try:
            R._run_step(FakePage(), step, 50, {})
        except R.FlowError as fe:
            if "Unknown action" in str(fe):
                check(f"runner dispatches lint action '{action}'", False)
                continue
        except Exception:
            pass  # FakePage lacks the Playwright method — dispatch happened.
        check(f"runner dispatches lint action '{action}'", True)

    # check_element_count semantics on the fake page
    class CountPage(FakePage):
        def locator(self, sel):
            return FakeLocator([FakeMatch(), FakeMatch()])
    try:
        R._run_step(CountPage(), {"action": "check_element_count",
                                  "selector": ".row", "min": 3}, 50, {})
        check("element count below min raises", False)
    except R.FlowError as fe:
        check("element count below min raises", "at least 3" in str(fe))
    try:
        R._run_step(CountPage(), {"action": "check_element_count",
                                  "selector": ".row", "min": 2}, 50, {})
        check("element count at min passes", True)
    except R.FlowError:
        check("element count at min passes", False)

    print("== v0.3.0: per-step timing perfdata ==")
    timed = R.FlowResult(service="S", status=R.OK, duration_ms=900,
                         warn_ms=3000, crit_ms=7000,
                         step_timings=[("step0_open_url", 500), ("step1_fill", 12)])
    tline = timed.checkmk_line()
    check("per-step perfdata appended",
          "duration=900ms;3000;7000|step0_open_url=500ms|step1_fill=12ms " in tline)

    print("== v0.3.0: secret source ==")
    import secret_source as S  # noqa: E402
    import tempfile

    S.reset()
    with tempfile.TemporaryDirectory() as td:
        sf = Path(td) / "secrets.yaml"
        sf.write_text("portal_password: hunter2-secret\nportal_user: monitor\n")
        os.chmod(sf, 0o600)
        if os.geteuid() != 0:
            os.chmod(sf, 0o644)
            try:
                S.load_secrets(sf)
                check("world-readable secrets file refused", False)
            except S.SecretError as e:
                check("world-readable secrets file refused", "chmod 600" in str(e))
            os.chmod(sf, 0o600)
        secrets = S.load_secrets(sf)
        check("secrets file loads", secrets["portal_user"] == "monitor")
        check("{{ secret.X }} resolves",
              S.substitute("{{ secret.portal_password }}", secrets) == "hunter2-secret")
        check("legacy {{ ENV }} still resolves",
              S.substitute("{{ SYNTHMK_X }}", secrets) == "https://demo.local")
        try:
            S.substitute("{{ secret.nope }}", secrets)
            check("missing secret raises", False)
        except S.SecretError as e:
            check("missing secret raises", "nope" in str(e) and "hunter2" not in str(e))
        try:
            S.substitute("{{ secret.x }}", None)
            check("secret ref without secrets file raises", False)
        except S.SecretError:
            check("secret ref without secrets file raises", True)
        # Redaction: resolved values are scrubbed from any outgoing line.
        check("resolved secret is redacted",
              S.redact("could not fill 'hunter2-secret' into #pw")
              == f"could not fill '{S.MASK}' into #pw")
        leaky = R.FlowResult(service="S", status=R.CRIT, duration_ms=10,
                             summary="boom hunter2-secret boom")
        check("checkmk line is secret-redacted", "hunter2-secret" not in leaky.checkmk_line())
    S.reset()

    print("== v0.3.0: optional steps + secret-hygiene lint ==")
    errs, _ = L.lint_flow({"steps": [
        {"action": "click", "selector": "#consent", "optional": True},
        {"action": "open_url", "url": "x"},
    ]}, source="t")
    check("optional step key is accepted", errs == [])
    _, warns = L.lint_flow({"steps": [
        {"action": "fill", "selector": "#pw", "value": "{{ secret.pw }}"},
    ]}, source="t")
    check("unmasked secret fill warns", any("sensitive" in w for w in warns))
    _, warns = L.lint_flow({"steps": [
        {"action": "fill", "selector": "#pw", "value": "{{ secret.pw }}", "sensitive": True},
    ]}, source="t")
    check("sensitive secret fill is quiet", not any("sensitive" in w for w in warns))

    print("== v0.5.0: selector fallback ladders ==")
    check("string selector -> single candidate",
          R._selector_candidates("#login") == ["#login"])
    check("list selector -> ordered candidates",
          R._selector_candidates(["[data-testid=go]", "#go", ""]) == ["[data-testid=go]", "#go"])

    class LadderPage(FakePage):
        """locator(sel) matches only the selectors in `present`."""
        def __init__(self, present):
            super().__init__()
            self._present = set(present)
        def locator(self, sel):
            return FakeLocator([FakeMatch()] if sel in self._present else [])
        def wait_for_timeout(self, ms):
            pass

    chosen, budget = R._resolve_selector(LadderPage({"#go"}), ["[data-testid=go]", "#go"], 200)
    check("ladder falls back to the first matching candidate", chosen == "#go")
    check("ladder returns a positive remaining budget (floored)", budget >= 250)
    # A single selector returns the FULL budget (no resolution time spent).
    chosen, budget = R._resolve_selector(FakePage(), "#only", 5000)
    check("single selector keeps the full timeout budget", chosen == "#only" and budget == 5000)
    chosen, _ = R._resolve_selector(LadderPage({"[data-testid=go]", "#go"}),
                                    ["[data-testid=go]", "#go"], 200)
    check("ladder prefers the earlier candidate", chosen == "[data-testid=go]")
    try:
        R._resolve_selector(LadderPage(set()), ["#a", "#b"], 0)
        check("exhausted ladder raises", False)
    except R.FlowError as fe:
        check("exhausted ladder raises", "candidates" in str(fe))

    errs, _ = L.lint_flow({"steps": [
        {"action": "click", "selector": ["[data-testid=go]", "#go"]},
        {"action": "open_url", "url": "x"},
    ]}, source="t")
    check("lint accepts a selector ladder", errs == [])
    errs, _ = L.lint_flow({"steps": [{"action": "click", "selector": []}]}, source="t")
    check("lint rejects an empty ladder", any("missing required key" in e for e in errs))
    errs, _ = L.lint_flow({"steps": [{"action": "click", "selector": ["#a", 7]}]}, source="t")
    check("lint rejects non-string ladder entries", any("non-empty strings" in e for e in errs))

    print("== v0.5.0: new assertions ==")
    page = FakePage()  # visible: "Welcome to SynthMK", "Account Overview"
    try:
        R._run_step(page, {"action": "check_text_absent", "text": "Error 500"}, 50, {})
        check("absent text passes check_text_absent", True)
    except R.FlowError:
        check("absent text passes check_text_absent", False)
    try:
        R._run_step(page, {"action": "check_text_absent", "text": "Welcome to SynthMK"}, 50, {})
        check("present text fails check_text_absent", False)
    except R.FlowError as fe:
        check("present text fails check_text_absent", "expected absent" in str(fe))

    class AttrPage(FakePage):
        class _First:
            def __init__(self, attrs, checked=False):
                self._attrs, self._checked = attrs, checked
            def get_attribute(self, name):
                return self._attrs.get(name)
            def is_checked(self):
                return self._checked
        def __init__(self, attrs=None, checked=False):
            super().__init__()
            self.first = AttrPage._First(attrs or {}, checked)
        def locator(self, sel):
            loc = FakeLocator([FakeMatch()])
            loc.first = self.first
            return loc

    apage = AttrPage({"href": "/account/settings", "class": "btn primary"})
    try:
        R._run_step(apage, {"action": "check_element_attribute", "selector": "#x",
                            "attribute": "href", "contains": "/account/"}, 50, {})
        check("attribute contains passes", True)
    except R.FlowError:
        check("attribute contains passes", False)
    try:
        R._run_step(apage, {"action": "check_element_attribute", "selector": "#x",
                            "attribute": "href", "equals": "/nope"}, 50, {})
        check("attribute equals mismatch fails", False)
    except R.FlowError as fe:
        check("attribute equals mismatch fails", "expected" in str(fe))
    try:
        R._run_step(apage, {"action": "check_element_attribute", "selector": "#x",
                            "attribute": "data-missing"}, 50, {})
        check("missing attribute fails", False)
    except R.FlowError as fe:
        check("missing attribute fails", "no attribute" in str(fe))

    try:
        R._run_step(AttrPage(checked=True), {"action": "check_checkbox",
                                             "selector": "#agree"}, 50, {})
        check("checked checkbox passes (default expected=checked)", True)
    except R.FlowError:
        check("checked checkbox passes (default expected=checked)", False)
    try:
        R._run_step(AttrPage(checked=False), {"action": "check_checkbox",
                                              "selector": "#agree", "checked": True}, 50, {})
        check("unchecked checkbox fails when checked expected", False)
    except R.FlowError as fe:
        check("unchecked checkbox fails when checked expected", "unchecked" in str(fe))

    print("== v0.5.0: TOTP + builtin variables ==")
    # RFC 6238 appendix B vector: ASCII secret '12345678901234567890', T=59s,
    # SHA-1, 8 digits -> 94287082 (so 6 digits -> 287082).
    rfc_seed_b32 = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    check("RFC 6238 test vector (t=59)",
          S.totp_code(rfc_seed_b32, now=59) == "287082")
    check("TOTP code is 6 digits",
          len(S.totp_code(rfc_seed_b32)) == 6 and S.totp_code(rfc_seed_b32).isdigit())
    try:
        S.totp_code("not-base32!!!")
        check("invalid base32 TOTP seed raises", False)
    except S.SecretError:
        check("invalid base32 TOTP seed raises", True)
    code = S.substitute("{{ totp.mfa_seed }}", {"mfa_seed": rfc_seed_b32})
    check("{{ totp.X }} resolves via the secrets file", len(code) == 6 and code.isdigit())
    check("TOTP seed itself is registered for redaction",
          S.redact(f"boom {rfc_seed_b32} boom") == "boom *** boom")
    try:
        S.substitute("{{ totp.mfa_seed }}", {"mfa_seed": "!!!"})
        check("non-base32 totp secret raises with name", False)
    except S.SecretError as e:
        check("non-base32 totp secret raises with name",
              "mfa_seed" in str(e) and "!!!" not in str(e))

    S.reset()
    u1 = S.substitute("{{ var.uuid }}", None)
    u2 = S.substitute("user-{{ var.uuid }}@test", None)
    check("var.uuid is stable within a run", u1 in u2 and len(u1) == 36)
    check("var.timestamp is epoch seconds",
          S.substitute("{{ var.timestamp }}", None).isdigit())
    check("var.random is 12 chars", len(S.substitute("{{ var.random }}", None)) == 12)
    try:
        S.substitute("{{ var.nope }}", None)
        check("unknown builtin var raises", False)
    except S.SecretError as e:
        check("unknown builtin var raises", "var.nope" in str(e))
    S.reset()

    print("== v0.5.0: include sub-flows ==")
    with _tf.TemporaryDirectory() as td:
        tdp = Path(td)
        (tdp / "shared").mkdir()
        (tdp / "shared" / "login.yaml").write_text(
            "name: shared login\nsteps:\n"
            "  - action: fill\n    selector: '#user'\n    value: bot\n"
            "  - action: click\n    selector: '#go'\n")
        (tdp / "main.yaml").write_text(
            "name: Main\nsteps:\n"
            "  - action: open_url\n    url: https://x\n"
            "  - action: include\n    flow: shared/login.yaml\n"
            "  - action: check_title\n    contains: Dash\n")
        flow = R.load_flow(tdp / "main.yaml")
        actions = [s["action"] for s in flow["steps"]]
        check("include splices the shared steps in place",
              actions == ["open_url", "fill", "click", "check_title"])

        (tdp / "a.yaml").write_text(
            "steps:\n  - action: include\n    flow: b.yaml\n")
        (tdp / "b.yaml").write_text(
            "steps:\n  - action: include\n    flow: a.yaml\n")
        try:
            R.load_flow(tdp / "a.yaml")
            check("include cycle raises UNKNOWN", False)
        except R.FlowError as fe:
            check("include cycle raises UNKNOWN",
                  fe.status == R.UNKNOWN and "cycle" in str(fe))

        (tdp / "miss.yaml").write_text(
            "steps:\n  - action: include\n    flow: nope.yaml\n")
        try:
            R.load_flow(tdp / "miss.yaml")
            check("missing include raises UNKNOWN", False)
        except R.FlowError as fe:
            check("missing include raises UNKNOWN", fe.status == R.UNKNOWN)

        errs, _ = L.lint_flow(
            {"name": "m", "steps": [{"action": "include", "flow": "shared/login.yaml"}]},
            source="t", base_dir=tdp)
        check("lint follows a resolvable include", errs == [])
        errs, _ = L.lint_flow(
            {"name": "m", "steps": [{"action": "include", "flow": "nope.yaml"}]},
            source="t", base_dir=tdp)
        check("lint flags a missing include target",
              any("file not found" in e for e in errs))
        (tdp / "bad.yaml").write_text(
            "steps:\n  - action: clikc\n    selector: '#x'\n")
        errs, _ = L.lint_flow(
            {"name": "m", "steps": [{"action": "include", "flow": "bad.yaml"}]},
            source="t", base_dir=tdp)
        check("lint surfaces errors inside the included file",
              any("unknown action" in e for e in errs))
        errs, _ = L.lint_flow(
            {"name": "m", "steps": [{"action": "include", "flow": "shared/login.yaml"}]},
            source="t")
        check("lint without base_dir does not follow includes", errs == [])

    print("== v0.5.0: script flows (trust-gated code path) ==")
    with _tf.TemporaryDirectory() as td:
        tdp = Path(td)
        (tdp / "j.py").write_text(
            "def run(page, api):\n"
            "    with api.step('open'):\n"
            "        page.title()\n"
            "    with api.step('verify'):\n"
            "        assert page.title() == 'SynthMK Demo App'\n")
        (tdp / "s.yaml").write_text(
            "name: Scripted\ntype: script\nscript: j.py\n")

        os.environ.pop("SYNTHMK_ALLOW_SCRIPTS", None)
        try:
            R.load_flow(tdp / "s.yaml")
            check("script flow blocked without SYNTHMK_ALLOW_SCRIPTS", False)
        except R.FlowError as fe:
            check("script flow blocked without SYNTHMK_ALLOW_SCRIPTS",
                  fe.status == R.UNKNOWN and "disabled" in str(fe))
        os.environ["SYNTHMK_ALLOW_SCRIPTS"] = "1"
        flow = R.load_flow(tdp / "s.yaml")
        check("script flow loads when gate is open", flow["script"] == "j.py")
        (tdp / "missing.yaml").write_text("type: script\nscript: nope.py\n")
        try:
            R.load_flow(tdp / "missing.yaml")
            check("missing script file is UNKNOWN at load", False)
        except R.FlowError as fe:
            check("missing script file is UNKNOWN at load", fe.status == R.UNKNOWN)

        def run_script(page=None):
            res = R.FlowResult(service="S")
            timings: list = []
            res.step_timings = timings
            R._execute_script_flow(flow, tdp / "s.yaml", page or FakePage(),
                                   {"flow_stem": "s"}, timings, res, False)
            return res, timings

        res, timings = run_script()
        check("passing script stays OK", res.status == R.OK)
        check("api.step records named timings",
              [t[0] for t in timings] == ["step0_open", "step1_verify"])

        res, _ = run_script(FakePage(title="Broken"))
        check("script assertion failure is CRIT", res.status == R.CRIT)
        check("failure names the script step", "in step 'verify'" in res.summary)

        (tdp / "j.py").write_text(
            "def run(page, api):\n"
            "    api.fail('backend returned a 500 banner')\n")
        res, _ = run_script()
        check("api.fail message surfaces", "500 banner" in res.summary
              and res.status == R.CRIT)

        (tdp / "j.py").write_text("def helper():\n    pass\n")
        res, _ = run_script()
        check("script without run() is UNKNOWN",
              res.status == R.UNKNOWN and "run(page, api)" in res.summary)

        (tdp / "j.py").write_text("def run(page, api:\n")
        res, _ = run_script()
        check("script syntax error is UNKNOWN with line",
              res.status == R.UNKNOWN and "syntax error" in res.summary)

        # api.secret pulls from the loaded secret store and registers redaction.
        (tdp / "j.py").write_text(
            "def run(page, api):\n"
            "    v = api.secret('portal_password')\n"
            "    raise RuntimeError('could not type ' + v)\n")
        S.reset()
        R._SECRETS = {"portal_password": "hunter2-script"}
        res, _ = run_script()
        check("api.secret value is redacted from failures",
              "hunter2-script" not in R._oneline(res.summary)
              and S.MASK in R._oneline(res.summary))
        R._SECRETS = None
        S.reset()
        os.environ.pop("SYNTHMK_ALLOW_SCRIPTS", None)

        errs, warns = L.lint_flow(
            {"name": "s", "type": "script", "script": "j.py"},
            source="t", base_dir=tdp)
        check("lint accepts a script flow with resolvable script", errs == [])
        errs, _ = L.lint_flow(
            {"name": "s", "type": "script", "script": "nope.py"},
            source="t", base_dir=tdp)
        check("lint flags a missing script file",
              any("script file not found" in e for e in errs))
        errs, _ = L.lint_flow({"name": "s", "type": "script"}, source="t")
        check("lint requires 'script' on type: script",
              any("requires a 'script' path" in e for e in errs))
        errs, _ = L.lint_flow({"name": "s", "type": "robot"}, source="t")
        check("lint rejects unknown flow type", any("type 'robot'" in e for e in errs))

    print("== v0.6.0: max_attempts retry ==")
    with _tf.TemporaryDirectory() as td:
        tdp = Path(td)
        flaky = tdp / "flaky.yaml"
        flaky.write_text("name: F\nmax_attempts: 3\nsteps:\n"
                         "  - action: open_url\n    url: x\n")
        calls = {"n": 0}
        real_run_flow = R.run_flow

        def fake_run_flow(path, **kwargs):
            calls["n"] += 1
            status = R.CRIT if calls["n"] < 3 else R.OK
            return R.FlowResult(service="F", status=status,
                                summary="boom" if status else "Flow completed successfully")
        R.run_flow = fake_run_flow
        try:
            res = R.run_with_retries(flaky)
            check("flaky flow recovers within max_attempts",
                  res.status == R.OK and calls["n"] == 3)
            check("recovery is visible in the summary",
                  "recovered on attempt 3/3" in res.summary)

            calls["n"] = 0

            def always_crit(path, **kwargs):
                calls["n"] += 1
                return R.FlowResult(service="F", status=R.CRIT, summary="down")
            R.run_flow = always_crit
            res = R.run_with_retries(flaky)
            check("hard failure exhausts attempts and stays CRIT",
                  res.status == R.CRIT and calls["n"] == 3
                  and "attempt 3/3" in res.summary)

            calls["n"] = 0

            def unknown_once(path, **kwargs):
                calls["n"] += 1
                return R.FlowResult(service="F", status=R.UNKNOWN, summary="no secret")
            R.run_flow = unknown_once
            res = R.run_with_retries(flaky)
            check("UNKNOWN (operator error) is never retried",
                  res.status == R.UNKNOWN and calls["n"] == 1)

            single = tdp / "single.yaml"
            single.write_text("name: S\nsteps:\n  - action: open_url\n    url: x\n")
            calls["n"] = 0
            R.run_flow = always_crit
            res = R.run_with_retries(single)
            check("default is exactly one attempt, summary untouched",
                  calls["n"] == 1 and res.summary == "down")

            capped = tdp / "capped.yaml"
            capped.write_text("name: C\nmax_attempts: 99\nsteps:\n"
                              "  - action: open_url\n    url: x\n")
            calls["n"] = 0
            res = R.run_with_retries(capped)
            check("max_attempts is capped at 3", calls["n"] == 3)
        finally:
            R.run_flow = real_run_flow

    errs, _ = L.lint_flow({"name": "r", "max_attempts": 2,
                           "steps": [{"action": "open_url", "url": "x"}]}, source="t")
    check("lint accepts max_attempts 2", errs == [])
    errs, _ = L.lint_flow({"name": "r", "max_attempts": 9,
                           "steps": [{"action": "open_url", "url": "x"}]}, source="t")
    check("lint rejects max_attempts > 3", any("max_attempts" in e for e in errs))

    print("== v0.7.0: cert check type ==")
    cert_flow = {"name": "C", "type": "cert", "host": "x.example",
                 "warn_days": 21, "crit_days": 7}
    check("_cert_host from host/port", R._cert_host(cert_flow) == ("x.example", 443))
    check("_cert_host parses url + port",
          R._cert_host({"type": "cert", "url": "https://y.example:8443/x"})
          == ("y.example", 8443))
    # render bands without a network call by stubbing _fetch_cert_expiry
    real_fetch = R._fetch_cert_expiry
    try:
        R._fetch_cert_expiry = lambda h, p, t, v: (90.0, "Jan 1 2027", True)
        res = R.run_flow(_cert_tmp(_tf, cert_flow))
        check("healthy cert is OK with days-left metric",
              res.status == R.OK and ("cert_days_left", 90.0) in (res.extra_metrics or []))
        R._fetch_cert_expiry = lambda h, p, t, v: (10.0, "soon", True)
        res = R.run_flow(_cert_tmp(_tf, cert_flow))
        check("cert below warn_days is WARN", res.status == R.WARN)
        R._fetch_cert_expiry = lambda h, p, t, v: (3.0, "very soon", True)
        res = R.run_flow(_cert_tmp(_tf, cert_flow))
        check("cert below crit_days is CRIT", res.status == R.CRIT)
        R._fetch_cert_expiry = lambda h, p, t, v: (60.0, "ok", False)
        res = R.run_flow(_cert_tmp(_tf, cert_flow))
        check("unverified chain is noted in the summary",
              "chain not verified" in res.summary)
    finally:
        R._fetch_cert_expiry = real_fetch
    check("cert perfdata carries the extra metric",
          "cert_days_left=" in R.FlowResult(service="C",
                                            extra_metrics=[("cert_days_left", 90.0)]).perfdata())
    errs, _ = L.lint_flow({"name": "c", "type": "cert"}, source="t")
    check("lint requires host/url on cert", any("requires 'host' or 'url'" in e for e in errs))
    errs, _ = L.lint_flow({"name": "c", "type": "cert", "host": "x",
                           "warn_days": 5, "crit_days": 30}, source="t")
    check("lint rejects crit_days > warn_days", any("crit_days" in e for e in errs))
    errs, _ = L.lint_flow({"name": "c", "type": "cert", "host": "x", "port": 70000},
                          source="t")
    check("lint rejects an out-of-range port", any("port" in e for e in errs))

    print("== v0.7.0: trace artifact in output ==")
    traced = R.FlowResult(service="S", status=R.CRIT, duration_ms=10, summary="boom",
                          screenshot="screenshots/s-fail.png",
                          trace="screenshots/s-fail.trace.zip",
                          shot_base_url="http://runner:9180/")
    line = traced.checkmk_line()
    check("trace renders a clickable link",
          '<a href="http://runner:9180/s-fail.trace.zip">trace</a>' in line)
    import json as _json
    j = _json.loads(traced.to_json())
    check("trace_url present in JSON output", j["trace_url"].endswith("s-fail.trace.zip"))

    print("== v0.7.0: retry resets per-run state ==")
    with _tf.TemporaryDirectory() as td:
        f = Path(td) / "r.yaml"
        f.write_text("name: R\nmax_attempts: 2\nsteps:\n  - action: open_url\n    url: x\n")
        seen = []
        real_run_flow = R.run_flow

        def capture(path, **kwargs):
            seen.append(S.substitute("{{ var.uuid }}", None))
            return R.FlowResult(service="R", status=R.CRIT, summary="down")
        R.run_flow = capture
        try:
            S.reset()
            R.run_with_retries(f)
            check("each retry attempt gets a fresh var.uuid",
                  len(seen) == 2 and seen[0] != seen[1])
        finally:
            R.run_flow = real_run_flow
            S.reset()

    print("== v0.7.0: include/script path-escape guard ==")
    with _tf.TemporaryDirectory() as td:
        tdp = Path(td)
        (tdp / "flows").mkdir()
        secret = tdp / "secret.yaml"
        secret.write_text("name: x\nsteps:\n  - action: open_url\n    url: x\n")
        main = tdp / "flows" / "m.yaml"
        main.write_text("name: M\nsteps:\n"
                        "  - action: include\n    flow: ../secret.yaml\n")
        try:
            R.load_flow(main)
            check("include escaping the flow dir is refused", False)
        except R.FlowError as fe:
            check("include escaping the flow dir is refused",
                  fe.status == R.UNKNOWN and "escapes" in str(fe))
        os.environ["SYNTHMK_ALLOW_SCRIPTS"] = "1"
        (tdp / "evil.py").write_text("def run(p, a): pass\n")
        smain = tdp / "flows" / "s.yaml"
        smain.write_text("name: S\ntype: script\nscript: ../evil.py\n")
        try:
            R.load_flow(smain)
            check("script escaping the flow dir is refused", False)
        except R.FlowError as fe:
            check("script escaping the flow dir is refused", "escapes" in str(fe))
        os.environ.pop("SYNTHMK_ALLOW_SCRIPTS", None)

    print(f"\n{PASS} checks passed, {len(FAILS)} failed.")
    return 1 if FAILS else 0


def _cert_tmp(_tf, flow):
    """Write a cert flow to a temp file and return its path (helper for tests)."""
    import tempfile
    import yaml as _yaml
    d = tempfile.mkdtemp()
    p = Path(d) / "cert.yaml"
    p.write_text(_yaml.safe_dump(flow))
    return p


if __name__ == "__main__":
    raise SystemExit(main())
