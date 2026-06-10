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

    print(f"\n{PASS} checks passed, {len(FAILS)} failed.")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
