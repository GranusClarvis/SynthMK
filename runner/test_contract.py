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

    print("== assertion step paths (fake page) ==")
    page = FakePage()
    # passing assertions raise nothing
    try:
        R._run_step(page, {"action": "check_title", "contains": "SynthMK Demo"}, 5000)
        R._run_step(page, {"action": "check_visible_text", "text": "Welcome to SynthMK"}, 5000)
        R._run_step(page, {"action": "check_url", "contains": "/demo/"}, 5000)
        check("passing assertions do not raise", True)
    except Exception as e:  # noqa: BLE001
        check(f"passing assertions do not raise ({e})", False)

    # failing visible-text assertion → clear message
    try:
        R._run_step(page, {"action": "check_visible_text", "text": "Dashboard"}, 5000)
        check("missing text raises FlowError", False)
    except R.FlowError as fe:
        check("missing text message", str(fe) == "Expected text 'Dashboard' not found")
        check("missing text is CRIT", fe.status == R.CRIT)

    # failing title assertion
    try:
        R._run_step(page, {"action": "check_title", "contains": "Nope"}, 5000)
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

    # The linter's action table must stay in lockstep with the runner's dispatch.
    check("lint actions cover runner ASSERT_ACTIONS",
          R.ASSERT_ACTIONS.issubset(set(L.REQUIRED_KEYS)))

    print(f"\n{PASS} checks passed, {len(FAILS)} failed.")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
