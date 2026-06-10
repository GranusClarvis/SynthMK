#!/usr/bin/env python3
"""SynthMK synthetic runner.

Executes a readable YAML flow file with Playwright (Chromium first) and emits a
single Checkmk local-check line:

    <status> "<service>" <perfdata> <STATE> - <summary>

e.g.

    0 "Synthetic Example Check" duration=1200ms;3000;7000 OK - Flow completed successfully
    2 "Synthetic Example Check" duration=6500ms;3000;7000 CRIT - Expected text 'Dashboard' not found

The runner is a Python port of GOAT's `executeStep` dispatch table
(admin-suite/src/lib/synthetic/runner.ts) but its output contract is Checkmk
local-check format, not a JSON TestResult. See docs/goat-reference-audit.md.

Usage:
    python3 runner/runner.py flows/example-ok.yaml
    python3 runner/runner.py flows/example-fail.yaml --headed

Exit code mirrors the Checkmk status digit (0 OK / 1 WARN / 2 CRIT / 3 UNKNOWN)
so the runner is usable both as a Checkmk local check and as a CI smoke test.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - dependency guard
    sys.stderr.write("PyYAML is required: pip install pyyaml\n")
    sys.exit(3)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import secret_source  # noqa: E402

# Checkmk status digits
OK, WARN, CRIT, UNKNOWN = 0, 1, 2, 3
STATE_NAME = {OK: "OK", WARN: "WARN", CRIT: "CRIT", UNKNOWN: "UNKNOWN"}


def _oneline(text: str, limit: int = 240) -> str:
    """Collapse a message to a single Checkmk-safe, secret-redacted line."""
    flat = " ".join(secret_source.redact(text).split()).replace("|", "/")
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"

# Actions that perform an interaction vs. assert a condition.
ASSERT_ACTIONS = {
    "check_visible_text",
    "check_text_absent",
    "check_title",
    "check_url",
    "check_element_count",
    "check_element_attribute",
    "check_checkbox",
    "wait_for_element",
    "wait_for_url",
}


@dataclass
class FlowResult:
    service: str
    status: int = OK
    duration_ms: int = 0
    warn_ms: int | None = None
    crit_ms: int | None = None
    summary: str = "Flow completed successfully"
    screenshot: str | None = None
    step_index: int | None = None
    # Output-format options (resolved by main()):
    #   dynamic       -> emit a 'P' state on success and let Checkmk threshold
    #                    duration from the perfdata warn/crit (state_mode: dynamic).
    #   shot_base_url -> turn a captured screenshot path into a clickable link
    #                    served by the runner-node's screenshot HTTP server.
    dynamic: bool = False
    shot_base_url: str | None = None
    # Per-step timings [(metric_label, ms)], emitted as extra perfdata so
    # Checkmk graphs where time is spent inside the journey, not just totals.
    step_timings: list[tuple[str, int]] | None = None
    # Playwright trace.zip captured on failure (trace_on_failure: true).
    trace: str | None = None
    # Unit-less extra metrics [(label, value)], e.g. cert_days_left.
    extra_metrics: list[tuple[str, float]] | None = None

    def perfdata(self) -> str:
        warn = "" if self.warn_ms is None else str(self.warn_ms)
        crit = "" if self.crit_ms is None else str(self.crit_ms)
        # Checkmk perfdata: name=value;warn;crit, multiple metrics '|'-separated.
        parts = [f"duration={self.duration_ms}ms;{warn};{crit}"]
        for label, ms in (self.step_timings or []):
            parts.append(f"{label}={ms}ms")
        for label, value in (self.extra_metrics or []):
            parts.append(f"{label}={value}")
        return "|".join(parts)

    def _artifact_url(self, path: str) -> str | None:
        """Tokenized node-served URL for an artifact (screenshot/trace)."""
        if not self.shot_base_url:
            return None
        name = os.path.basename(path)
        url = f"{self.shot_base_url.rstrip('/')}/{name}"
        token = _shot_token(name)
        if token:
            url += f"?t={token}"
        return url

    def _screenshot_suffix(self) -> str:
        suffix = ""
        if self.screenshot:
            # Clickable links rendered in the Checkmk service Details — require
            # the "Escape HTML codes in service output" rule turned Off for
            # this host.
            url = self._artifact_url(self.screenshot)
            suffix += (f' <a href="{url}">screenshot</a>' if url
                       else f" (screenshot: {self.screenshot})")
        if self.trace:
            url = self._artifact_url(self.trace)
            suffix += (f' <a href="{url}">trace</a>' if url
                       else f" (trace: {self.trace})")
        return suffix

    def to_json(self) -> str:
        """Machine-readable result for the native <<<synthmk>>> agent section.

        The native Checkmk check plugin (checkmk/plugin/) consumes this and
        renders proper services with unit-aware metrics, rulesets, and graphs —
        richer than the local-check line. All text passes the same redaction.
        """
        import json
        return json.dumps({
            "service": self.service,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "warn_ms": self.warn_ms,
            "crit_ms": self.crit_ms,
            "summary": _oneline(self.summary),
            "failed_step": self.step_index,
            "steps": [{"label": label, "ms": ms} for label, ms in (self.step_timings or [])],
            "screenshot_url": self._artifact_url(self.screenshot) if self.screenshot else None,
            "trace_url": self._artifact_url(self.trace) if self.trace else None,
            "extras": [{"label": label, "value": value}
                       for label, value in (self.extra_metrics or [])],
            "dynamic": self.dynamic,
        }, sort_keys=True)

    def checkmk_line(self) -> str:
        extra = self._screenshot_suffix()
        # Dynamic mode on a passing flow: hand state determination to Checkmk via
        # the 'P' marker (it computes OK/WARN/CRIT from the duration thresholds).
        # Any real failure keeps an explicit digit so the failure message is
        # authoritative and never silently downgraded by a missing threshold.
        if self.dynamic and self.status == OK:
            return (
                f"P \"{self.service}\" {self.perfdata()} "
                f"{_oneline(self.summary)}{extra}"
            )
        return (
            f"{self.status} \"{self.service}\" {self.perfdata()} "
            f"{STATE_NAME[self.status]} - {_oneline(self.summary)}{extra}"
        )


class FlowError(Exception):
    """A flow assertion or interaction failure with a clear, user-facing message."""

    def __init__(self, message: str, status: int = CRIT):
        super().__init__(message)
        self.status = status


# Secrets loaded once per process by run_flow(); None until configured.
_SECRETS: dict[str, str] | None = None


def _shot_token(name: str) -> str | None:
    """Sign a screenshot filename for the node's authenticated shot server.

    Same scheme as runner-node/shot_server.py: HMAC-SHA256(key, basename)
    truncated to 32 hex chars. Returns None when no key is configured (e.g.
    standalone runner without the appliance, or SYNTHMK_SHOT_AUTH=off)."""
    key_file = os.environ.get("SYNTHMK_SHOT_KEY_FILE")
    if not key_file or not os.path.isfile(key_file):
        return None
    try:
        import hashlib
        import hmac as hmac_mod
        key = Path(key_file).read_bytes().strip()
        return hmac_mod.new(key, name.encode(), hashlib.sha256).hexdigest()[:32]
    except Exception:
        return None


def _substitute(value: str) -> str:
    """Resolve {{ secret.NAME }} (secrets file) / {{ NAME }} (env) placeholders."""
    return secret_source.substitute(value, _SECRETS)


def load_flow(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise FlowError(f"Flow file {path} did not parse to a mapping", UNKNOWN)
    if str(data.get("type", "flow")) == "cert":
        # Certificate checks need no browser and no steps; just an endpoint.
        if not (data.get("host") or data.get("url")):
            raise FlowError(f"Flow file {path} is type: cert but has no 'host' or 'url'",
                            UNKNOWN)
        return data
    if str(data.get("type", "flow")) == "script":
        # Script flows run operator-authored Playwright Python with full page
        # access — real code, no YAML ceiling. That power is an explicit trust
        # decision, so the node must opt in via SYNTHMK_ALLOW_SCRIPTS=1.
        if not os.environ.get("SYNTHMK_ALLOW_SCRIPTS"):
            raise FlowError(
                "script flows are disabled on this node "
                "(set SYNTHMK_ALLOW_SCRIPTS=1 to enable)", UNKNOWN)
        ref = str(data.get("script", "")).strip()
        if not ref:
            raise FlowError(f"Flow file {path} is type: script but has no 'script'", UNKNOWN)
        if Path(ref).is_absolute():
            raise FlowError("script path must be relative to the flow file", UNKNOWN)
        # Resolve symlinks and confirm the script stays inside the flow's
        # directory tree: a flow must not load code from /etc or a sibling
        # project via `script: ../../x.py` or a planted symlink.
        target = (path.parent / ref).resolve()
        if not _within(target, path.parent):
            raise FlowError("script path escapes the flow directory", UNKNOWN)
        if not target.is_file():
            raise FlowError(f"script not found: {ref}", UNKNOWN)
        return data
    if "steps" not in data or not isinstance(data["steps"], list):
        raise FlowError(f"Flow file {path} missing a 'steps' list", UNKNOWN)
    data["steps"] = expand_includes(data["steps"], path.parent, root=path.parent)
    return data


def _within(target: Path, root: Path) -> bool:
    """True if `target` resolves inside `root` (symlink-aware boundary check)."""
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


# Sub-flow inclusion (`action: include, flow: shared/login.yaml`): reuse one
# journey fragment (typically a login) across many flows instead of copying
# steps. Bounded so a typo can never make the runner read files forever.
MAX_INCLUDE_DEPTH = 3
MAX_EXPANDED_STEPS = 200


def expand_includes(steps: list, base_dir: Path, *, root: Path | None = None,
                    _stack: tuple[str, ...] = ()) -> list:
    root = root or base_dir
    out: list = []
    for step in steps:
        if not (isinstance(step, dict) and step.get("action") == "include"):
            out.append(step)
            continue
        ref = str(step.get("flow", "")).strip()
        if not ref:
            raise FlowError("include step missing 'flow'", UNKNOWN)
        if Path(ref).is_absolute():
            raise FlowError(f"include path must be relative: {ref}", UNKNOWN)
        target = (base_dir / ref).resolve()
        # Confine includes to the top-level flow's directory tree: a flow must
        # not splice steps from outside it via `../` or a planted symlink.
        if not _within(target, root):
            raise FlowError(f"include {ref} escapes the flow directory", UNKNOWN)
        if str(target) in _stack:
            raise FlowError(f"include cycle via {ref}", UNKNOWN)
        if len(_stack) >= MAX_INCLUDE_DEPTH:
            raise FlowError(f"include nesting deeper than {MAX_INCLUDE_DEPTH} ({ref})", UNKNOWN)
        try:
            data = yaml.safe_load(target.read_text())
        except FileNotFoundError:
            raise FlowError(f"include not found: {ref}", UNKNOWN)
        except yaml.YAMLError:
            raise FlowError(f"include is not valid YAML: {ref}", UNKNOWN)
        sub = data.get("steps") if isinstance(data, dict) else None
        if not isinstance(sub, list) or not sub:
            raise FlowError(f"include {ref} has no 'steps' list", UNKNOWN)
        out.extend(expand_includes(sub, target.parent, root=root,
                                   _stack=_stack + (str(target),)))
    if len(out) > MAX_EXPANDED_STEPS:
        raise FlowError(f"flow expands to more than {MAX_EXPANDED_STEPS} steps", UNKNOWN)
    return out


def _selector_candidates(spec: Any) -> list[str]:
    """A step `selector:` is one selector or a fallback ladder (list, tried in
    order). Multi-locator redundancy is the single best anti-flake measure:
    a page redesign that breaks the CSS path still matches the data-testid."""
    if isinstance(spec, list):
        return [str(s) for s in spec if str(s).strip()]
    return [str(spec)]


def _resolve_selector(page, spec: Any, timeout: int) -> tuple[str, int]:
    """Resolve a selector (or fallback ladder) to (selector, remaining_ms).

    A single selector returns instantly with the full budget. A ladder polls
    its candidates until one matches, and returns the time LEFT so the caller's
    action does not get a second full timeout on top of resolution time (the
    whole step stays inside one budget)."""
    cands = _selector_candidates(spec)
    if len(cands) == 1:
        return cands[0], timeout
    deadline = time.monotonic() + timeout / 1000.0
    while True:
        for cand in cands:
            try:
                if page.locator(cand).count() > 0:
                    remaining = int((deadline - time.monotonic()) * 1000)
                    return cand, max(remaining, 250)  # floor so the action can act
            except Exception:
                continue  # one invalid candidate must not kill the ladder
        if time.monotonic() >= deadline:
            raise FlowError(
                f"None of {len(cands)} selector candidates matched: {cands}"
            )
        page.wait_for_timeout(150)


# Flow `browser:` value -> (Playwright engine attribute, optional channel).
# Firefox and WebKit are first-class Playwright engines (already bundled).
# `chrome`/`chromium` map to the BUNDLED chromium (no channel) — that is what
# the appliance ships and what `browser: chrome` flows have always run on, so
# they must not suddenly require an OS-installed Chrome. Only `edge` opts into a
# release channel (the OS Edge), and even that falls back if the channel binary
# is absent. An unrecognized value falls back to bundled chromium.
_BROWSER_ENGINES: dict[str, tuple[str, str | None]] = {
    "chromium": ("chromium", None),
    "chrome": ("chromium", None),
    "google-chrome": ("chromium", None),
    "edge": ("chromium", "msedge"),
    "msedge": ("chromium", "msedge"),
    "firefox": ("firefox", None),
    "ff": ("firefox", None),
    "webkit": ("webkit", None),
    "safari": ("webkit", None),
}


def _browser_engine(value: Any) -> tuple[str, str | None]:
    """Resolve a flow's `browser:` field to a (engine, channel) launch target."""
    key = str(value or "chromium").strip().lower()
    return _BROWSER_ENGINES.get(key, ("chromium", None))


def _run_step(page, step: dict[str, Any], default_timeout: int, ctx: dict[str, Any]) -> None:
    action = step.get("action")
    timeout = int(step.get("timeout_ms", default_timeout))
    if action == "open_url":
        url = _substitute(step["url"])
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    elif action == "click":
        sel, budget = _resolve_selector(page, step["selector"], timeout)
        page.click(sel, timeout=budget)
    elif action == "fill":
        value = _substitute(str(step.get("value", "")))
        # A sensitive fill (passwords, tokens) is never echoed anywhere and
        # poisons later failure screenshots (inputs get masked before capture).
        if step.get("sensitive"):
            secret_source.register_sensitive(value)
            ctx["sensitive_used"] = True
        sel, budget = _resolve_selector(page, step["selector"], timeout)
        page.fill(sel, value, timeout=budget)
    elif action == "press":
        # Key press, optionally scoped to a selector (else the focused element).
        key = str(step["key"])
        if step.get("selector"):
            sel, budget = _resolve_selector(page, step["selector"], timeout)
            page.press(sel, key, timeout=budget)
        else:
            page.keyboard.press(key)
    elif action == "select_option":
        # Match by value first; fall back to visible label for recorder output.
        sel, budget = _resolve_selector(page, step["selector"], timeout)
        value = _substitute(str(step.get("value", "")))
        try:
            page.select_option(sel, value=value, timeout=budget)
        except Exception:
            try:
                page.select_option(sel, label=value, timeout=budget)
            except Exception:
                raise FlowError(f"Could not select option '{value}' in '{sel}'")
    elif action == "hover":
        sel, budget = _resolve_selector(page, step["selector"], timeout)
        page.hover(sel, timeout=budget)
    elif action == "scroll_into_view":
        sel, budget = _resolve_selector(page, step["selector"], timeout)
        page.locator(sel).first.scroll_into_view_if_needed(timeout=budget)
    elif action == "wait_ms":
        page.wait_for_timeout(int(step["ms"]))
    elif action == "wait_for_network_idle":
        # Wait until there have been no network connections for 500ms (Playwright's
        # "networkidle"). Useful after a click that kicks off XHR/fetch before the
        # next assertion. Guarded by timeout so a chatty page can't hang the run.
        try:
            page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception:
            raise FlowError(f"Network did not go idle within {timeout}ms")
    elif action == "screenshot":
        # Screenshot-always: capture evidence at this point regardless of
        # pass/fail. Masks form inputs first if a sensitive fill has happened,
        # so an always-on capture can never leak a credential.
        shot_dir = ctx.get("shot_dir")
        if shot_dir is not None:
            seq = ctx.get("shot_seq", 0)
            ctx["shot_seq"] = seq + 1
            label = re.sub(r"[^A-Za-z0-9_-]", "_", str(step.get("name", f"step{seq}")))
            shot = Path(shot_dir) / f"{ctx.get('flow_stem', 'flow')}-{label}.png"
            try:
                Path(shot_dir).mkdir(parents=True, exist_ok=True)
                _mask_before_shot(page, ctx)
                page.screenshot(path=str(shot), full_page=bool(step.get("full_page", False)))
                ctx.setdefault("screenshots", []).append(str(shot))
            except Exception as exc:
                # An always-on screenshot is evidence, not an assertion: a capture
                # failure must not flip an otherwise-passing flow to CRIT.
                if not step.get("optional", True):
                    raise FlowError(f"Screenshot capture failed: {exc}")
    elif action == "wait_for_element":
        sel, budget = _resolve_selector(page, step["selector"], timeout)
        try:
            page.wait_for_selector(sel, timeout=budget, state="visible")
        except Exception:
            raise FlowError(f"Element '{sel}' not found within {timeout}ms")
    elif action == "wait_for_url":
        contains = step["contains"]
        try:
            page.wait_for_url(lambda url: contains in url, timeout=timeout)
        except Exception:
            raise FlowError(
                f"URL did not contain '{contains}' within {timeout}ms (got '{page.url}')"
            )
    elif action == "check_visible_text":
        text = step["text"]
        # Visible-text assertion: locate by text, require at least one visible match.
        loc = page.get_by_text(text)
        if loc.count() == 0 or not any(
            loc.nth(i).is_visible() for i in range(loc.count())
        ):
            raise FlowError(f"Expected text '{text}' not found")
    elif action == "check_title":
        contains = step["contains"]
        title = page.title()
        if contains not in title:
            raise FlowError(f"Expected title to contain '{contains}', got '{title}'")
    elif action == "check_url":
        contains = step["contains"]
        url = page.url
        if contains not in url:
            raise FlowError(f"Expected URL to contain '{contains}', got '{url}'")
    elif action == "check_element_count":
        minimum = int(step.get("min", 1))
        # With a fallback ladder every candidate addresses the same element(s);
        # the best (max) count across candidates is the honest answer.
        count = 0
        for cand in _selector_candidates(step["selector"]):
            try:
                count = max(count, page.locator(cand).count())
            except Exception:
                continue
        if count < minimum:
            sel = step["selector"]
            raise FlowError(
                f"Expected at least {minimum} element(s) matching '{sel}', found {count}"
            )
    elif action == "check_text_absent":
        text = step["text"]
        loc = page.get_by_text(text)
        n = loc.count()
        if n and any(loc.nth(i).is_visible() for i in range(n)):
            raise FlowError(f"Text '{text}' is visible on the page (expected absent)")
    elif action == "check_element_attribute":
        sel, _ = _resolve_selector(page, step["selector"], timeout)
        attr = str(step["attribute"])
        value = page.locator(sel).first.get_attribute(attr)
        if value is None:
            raise FlowError(f"Element '{sel}' has no attribute '{attr}'")
        if "equals" in step and str(step["equals"]) != value:
            raise FlowError(
                f"Attribute '{attr}' of '{sel}' is '{value}' (expected '{step['equals']}')"
            )
        if "contains" in step and str(step["contains"]) not in value:
            raise FlowError(
                f"Attribute '{attr}' of '{sel}' is '{value}' "
                f"(expected to contain '{step['contains']}')"
            )
    elif action == "check_checkbox":
        sel, _ = _resolve_selector(page, step["selector"], timeout)
        want = bool(step.get("checked", True))
        got = bool(page.locator(sel).first.is_checked())
        if got != want:
            raise FlowError(
                f"Checkbox '{sel}' is {'checked' if got else 'unchecked'} "
                f"(expected {'checked' if want else 'unchecked'})"
            )
    elif action == "include":
        # Includes are spliced by expand_includes() at load time; reaching the
        # dispatcher means the flow bypassed load_flow (a runner bug, not a
        # site failure).
        raise FlowError("include step was not expanded at load time", UNKNOWN)
    else:
        raise FlowError(f"Unknown action '{action}'", UNKNOWN)


# JS run on the page before a failure screenshot when a sensitive fill happened:
# blanks every input/textarea so the captured PNG cannot contain a credential
# (or anything typed after it) in a form field.
_MASK_INPUTS_JS = (
    "() => { for (const el of document.querySelectorAll('input, textarea')) "
    "{ try { el.value = '\\u2022\\u2022\\u2022'; } catch (e) {} } }"
)

# Defense-in-depth: a password field is a credential by HTML semantics, so it is
# blanked before EVERY capture — even when the flow author forgot to mark the
# fill `sensitive: true`. A login screenshot can never leak the password, and
# this requires no per-flow opt-in.
_MASK_PASSWORDS_JS = (
    "() => { for (const el of document.querySelectorAll('input[type=password]')) "
    "{ try { el.value = '\\u2022\\u2022\\u2022'; } catch (e) {} } }"
)


def _mask_before_shot(page, ctx: dict[str, Any]) -> None:
    """Blank credential-bearing form fields just before a screenshot.

    Always blanks `input[type=password]` (HTML-semantic credentials). When the
    flow has touched a declared secret (`sensitive: true` fill or api.secret()),
    every input/textarea is blanked too — anything typed afterward could be a
    token. Masking must never break a capture, so failures are swallowed.
    """
    try:
        page.evaluate(_MASK_INPUTS_JS if ctx.get("sensitive_used")
                      else _MASK_PASSWORDS_JS)
    except Exception:
        pass


def _flow_has_sensitive(flow: dict[str, Any]) -> bool:
    """True if the flow may type a credential into the page.

    Declarative flows: any `fill` step marked `sensitive: true`. Script flows
    can pull from the secret store at will via `api.secret()`, so they are
    treated as potentially sensitive. Used to strip rich snapshots/screenshots
    from a served `.trace.zip`, which would otherwise embed the credential DOM
    captured *before* the failure-time mask runs.
    """
    if str(flow.get("type", "flow")) == "script":
        return True
    for step in flow.get("steps", []) or []:
        if (isinstance(step, dict) and step.get("action") == "fill"
                and step.get("sensitive")):
            return True
    return False


class ScriptApi:
    """The `api` object handed to a script flow's run(page, api).

    Scripts get the raw Playwright page — the api adds what monitoring needs
    on top of test code: named per-step timings (graphed in Checkmk), secret
    access with automatic redaction, evidence screenshots, clean failures.

        def run(page, api):
            page.goto("https://portal.example/login")
            with api.step("login"):
                page.fill("#user", api.secret("portal_user"))
                page.fill("#pw", api.secret("portal_password"))
                page.click("button[type=submit]")
            with api.step("dashboard"):
                page.wait_for_selector("#dashboard")
                if "Dashboard" not in page.title():
                    api.fail("dashboard title missing after login")
    """

    def __init__(self, page, ctx: dict[str, Any], timings: list[tuple[str, int]]):
        self._page = page
        self._ctx = ctx
        self._timings = timings
        self._seq = 0
        self.current_step: str | None = None

    def secret(self, name: str) -> str:
        value = _substitute("{{ secret.%s }}" % name)
        # Anything a script pulls from the secret store is treated as
        # sensitive: redacted from output and masked in screenshots.
        secret_source.register_sensitive(value)
        self._ctx["sensitive_used"] = True
        return value

    def totp(self, name: str) -> str:
        return _substitute("{{ totp.%s }}" % name)

    def var(self, name: str) -> str:
        return _substitute("{{ var.%s }}" % name)

    def fail(self, message: str) -> None:
        raise FlowError(str(message))

    def step(self, label: str):
        api = self

        class _Step:
            def __enter__(self):
                api.current_step = label
                self._start = time.monotonic()
                return self

            def __exit__(self, exc_type, exc, tb):
                clean = re.sub(r"[^A-Za-z0-9_]", "_", f"step{api._seq}_{label}")
                api._timings.append((clean, int((time.monotonic() - self._start) * 1000)))
                api._seq += 1
                if exc_type is None:
                    api.current_step = None
                return False  # never swallow failures

        return _Step()

    def screenshot(self, name: str = "evidence") -> str | None:
        return _capture_screenshot(self._page, self._ctx, name)


def _capture_screenshot(page, ctx: dict[str, Any], name: str) -> str | None:
    """Shared evidence capture: masked when secrets touched, never raises."""
    shot_dir = ctx.get("shot_dir")
    if shot_dir is None:
        return None
    seq = ctx.get("shot_seq", 0)
    ctx["shot_seq"] = seq + 1
    label = re.sub(r"[^A-Za-z0-9_-]", "_", str(name or f"step{seq}"))
    shot = Path(shot_dir) / f"{ctx.get('flow_stem', 'flow')}-{label}.png"
    try:
        Path(shot_dir).mkdir(parents=True, exist_ok=True)
        _mask_before_shot(page, ctx)
        page.screenshot(path=str(shot), full_page=False)
        ctx.setdefault("screenshots", []).append(str(shot))
        return str(shot)
    except Exception:
        return None


def _execute_script_flow(flow: dict[str, Any], path: Path, page,
                         ctx: dict[str, Any], timings: list[tuple[str, int]],
                         result: FlowResult, shot_on_fail: bool) -> None:
    """Load and run a `type: script` flow's run(page, api) entry point."""
    import importlib.util

    script_path = (path.parent / str(flow["script"])).resolve()
    try:
        spec = importlib.util.spec_from_file_location(
            f"synthmk_script_{path.stem}", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except SyntaxError as exc:
        result.status = UNKNOWN
        result.summary = f"Script has a syntax error: line {exc.lineno}"
        return
    except Exception as exc:
        result.status = UNKNOWN
        result.summary = f"Script failed to load: {str(exc).splitlines()[0]}"
        return
    run = getattr(module, "run", None)
    if not callable(run):
        result.status = UNKNOWN
        result.summary = "Script defines no run(page, api) function"
        return

    api = ScriptApi(page, ctx, timings)
    try:
        run(page, api)
    except FlowError as fe:
        result.status = fe.status
        result.summary = str(fe) + (f" (in step '{api.current_step}')" if api.current_step else "")
    except secret_source.SecretError as exc:
        result.status = UNKNOWN
        result.summary = str(exc)
    except AssertionError as exc:
        result.status = CRIT
        msg = str(exc).strip().splitlines()[0] if str(exc).strip() else "assertion failed"
        result.summary = f"Script assertion failed: {msg}" + (
            f" (in step '{api.current_step}')" if api.current_step else "")
    except Exception as exc:
        result.status = CRIT
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
        result.summary = f"Script failed: {first}" + (
            f" (in step '{api.current_step}')" if api.current_step else "")
    if result.status not in (OK,) and shot_on_fail:
        shot = _capture_screenshot(page, ctx, f"fail-{path.stem}")
        if shot:
            result.screenshot = shot


def _cert_host(flow: dict[str, Any]) -> tuple[str, int]:
    """Endpoint from `host:`/`port:` or parsed out of `url:`."""
    host = str(flow.get("host", "")).strip()
    port = int(flow.get("port", 443))
    if not host and flow.get("url"):
        from urllib.parse import urlparse
        parsed = urlparse(str(flow["url"]))
        host = parsed.hostname or ""
        if parsed.port:
            port = parsed.port
    return host, port


def _fetch_cert_expiry(host: str, port: int, timeout_s: float,
                       require_valid_chain: bool) -> tuple[float, str, bool]:
    """(days_left, notAfter string, chain_verified) for the endpoint's cert.

    First a normally-verified handshake (system CA store). If verification
    fails and require_valid_chain is off, fall back to an unverified fetch
    and parse the DER via openssl so internal-CA and self-signed certs can
    still be expiry-monitored (their chains are the operator's business; the
    summary says the chain was not verified).
    """
    import socket as socket_mod
    import ssl

    def handshake(ctx) -> tuple[dict | None, bytes | None]:
        with socket_mod.create_connection((host, port), timeout=timeout_s) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                return tls.getpeercert(), tls.getpeercert(binary_form=True)

    try:
        cert, _ = handshake(ssl.create_default_context())
        not_after = str(cert.get("notAfter", ""))
        expires = ssl.cert_time_to_seconds(not_after)
        return ((expires - time.time()) / 86400.0, not_after, True)
    except ssl.SSLCertVerificationError as exc:
        if require_valid_chain:
            raise FlowError(
                f"Certificate chain for {host}:{port} failed verification: "
                f"{getattr(exc, 'verify_message', '') or exc}")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        _, der = handshake(ctx)
        if not der:
            raise FlowError(f"No certificate received from {host}:{port}")
        import subprocess
        pem = ssl.DER_cert_to_PEM_cert(der)
        proc = subprocess.run(
            ["openssl", "x509", "-noout", "-enddate"],
            input=pem, capture_output=True, text=True, timeout=15)
        if proc.returncode != 0 or "notAfter=" not in proc.stdout:
            raise FlowError("openssl could not parse the certificate "
                            "(needed for non-system-CA chains)", UNKNOWN)
        not_after = proc.stdout.split("notAfter=", 1)[1].strip()
        expires = ssl.cert_time_to_seconds(not_after)
        return ((expires - time.time()) / 86400.0, not_after, False)


def _run_cert_flow(flow: dict[str, Any], path: Path) -> FlowResult:
    service = flow.get("name", path.stem)
    warn_days = int(flow.get("warn_days", 21))
    crit_days = int(flow.get("crit_days", 7))
    timeout_s = int(flow.get("timeout_ms", 15000)) / 1000.0
    host, port = _cert_host(flow)
    result = FlowResult(service=service)
    start = time.monotonic()
    try:
        days, not_after, verified = _fetch_cert_expiry(
            host, port, timeout_s, bool(flow.get("require_valid_chain")))
    except FlowError as fe:
        result.status = fe.status
        result.summary = str(fe)
        result.duration_ms = int((time.monotonic() - start) * 1000)
        return result
    except Exception as exc:
        # Unreachable endpoint is a site failure, not a runner bug.
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
        result.status = CRIT
        result.summary = f"TLS endpoint {host}:{port} unreachable: {first}"
        result.duration_ms = int((time.monotonic() - start) * 1000)
        return result
    result.duration_ms = int((time.monotonic() - start) * 1000)
    result.extra_metrics = [("cert_days_left", round(days, 1))]
    note = "" if verified else " (chain not verified: internal/self-signed CA)"
    result.summary = (f"Certificate for {host}:{port} expires in {days:.0f} "
                      f"days ({not_after}){note}")
    if days < crit_days:
        result.status = CRIT
        result.summary = (f"Certificate for {host}:{port} expires in {days:.1f} "
                          f"days ({not_after}), below the {crit_days}-day "
                          f"critical threshold{note}")
    elif days < warn_days:
        result.status = WARN
        result.summary = (f"Certificate for {host}:{port} expires in {days:.1f} "
                          f"days ({not_after}), below the {warn_days}-day "
                          f"warning threshold{note}")
    return result


def run_flow(
    path: Path,
    headed: bool = False,
    *,
    dynamic: bool | None = None,
    shot_base_url: str | None = None,
    secrets_file: str | None = None,
) -> FlowResult:
    global _SECRETS
    flow = load_flow(path)
    if str(flow.get("type", "flow")) == "cert":
        # No browser, no secrets, no Playwright import: a cert check is one
        # TLS handshake. Cheap enough to schedule densely.
        return _run_cert_flow(flow, path)
    # Load the (permission-checked) secrets file up front so a misconfigured
    # secret store fails fast as UNKNOWN instead of mid-flow with blank creds.
    secrets_path = secret_source.secrets_file_path(secrets_file)
    if secrets_path is not None:
        try:
            _SECRETS = secret_source.load_secrets(secrets_path)
        except secret_source.SecretError as exc:
            raise FlowError(str(exc), UNKNOWN)
    service = flow.get("name", path.stem)
    warn_ms = flow.get("warn_ms")
    crit_ms = flow.get("crit_ms")
    default_timeout = int(flow.get("timeout_ms", 30000))
    shot_on_fail = bool(flow.get("screenshot_on_failure", False))
    # CLI flag wins; otherwise honor the flow's state_mode (digit|dynamic).
    if dynamic is None:
        dynamic = str(flow.get("state_mode", "digit")).lower() == "dynamic"

    result = FlowResult(
        service=service, warn_ms=warn_ms, crit_ms=crit_ms,
        dynamic=dynamic, shot_base_url=shot_base_url,
    )

    from playwright.sync_api import sync_playwright

    # In a container Chromium's sandbox usually can't initialize; the runner-node
    # appliance sets SYNTHMK_NO_SANDBOX=1. --disable-dev-shm-usage avoids crashes
    # on the small default /dev/shm in Docker.
    launch_args: dict[str, Any] = {}
    if os.environ.get("SYNTHMK_NO_SANDBOX"):
        launch_args["args"] = ["--no-sandbox", "--disable-dev-shm-usage"]

    engine, channel = _browser_engine(flow.get("browser"))
    # A channel (Chrome/Edge stable) only applies to the chromium engine; the
    # --no-sandbox args are Chromium-only too — Firefox/WebKit reject them.
    if engine != "chromium":
        launch_args.pop("args", None)
    elif channel:
        launch_args["channel"] = channel

    start = time.monotonic()
    with sync_playwright() as p:
        try:
            browser = getattr(p, engine).launch(headless=not headed, **launch_args)
        except Exception:
            # A requested release channel (e.g. Edge) may not be installed on
            # this node — degrade to the bundled chromium rather than failing
            # the whole check, so multi-browser flows stay portable.
            if launch_args.pop("channel", None) is not None:
                browser = getattr(p, engine).launch(headless=not headed, **launch_args)
            else:
                raise
        page = browser.new_page()
        ctx: dict[str, Any] = {
            "sensitive_used": False,
            "shot_dir": str(path.parent.parent / "screenshots"),
            "flow_stem": path.stem,
        }
        # trace_on_failure: record a Playwright trace (screenshots + DOM
        # snapshots) and keep the .zip ONLY when the flow fails — the deep
        # debugging artifact next to the failure PNG. Off by default: tracing
        # costs memory and the zips are large.
        tracing = bool(flow.get("trace_on_failure"))
        if tracing:
            # A served trace.zip embeds DOM snapshots + screenshots taken
            # continuously — for a credential flow those capture the password
            # BEFORE the failure-time mask runs, leaking it on the same :9180
            # server as the PNGs. For sensitive flows keep only the action/timing
            # log (snapshots/screenshots off), which is what a trace is usually
            # opened for anyway.
            rich_trace = not _flow_has_sensitive(flow)
            try:
                page.context.tracing.start(screenshots=rich_trace,
                                           snapshots=rich_trace)
            except Exception:
                tracing = False  # tracing must never break the check itself

        def save_trace_if_failed() -> None:
            if not tracing:
                return
            try:
                if result.status == OK:
                    page.context.tracing.stop()
                else:
                    shot_dir = path.parent.parent / "screenshots"
                    shot_dir.mkdir(exist_ok=True)
                    step = result.step_index if result.step_index is not None else "x"
                    trace_path = shot_dir / f"{path.stem}-fail-step{step}.trace.zip"
                    page.context.tracing.stop(path=str(trace_path))
                    result.trace = str(trace_path)
            except Exception:
                pass  # artifact capture failures never change the verdict

        timings: list[tuple[str, int]] = []
        result.step_timings = timings
        if str(flow.get("type", "flow")) == "script":
            try:
                page.set_default_timeout(default_timeout)
                _execute_script_flow(flow, path, page, ctx, timings, result,
                                     shot_on_fail)
            finally:
                save_trace_if_failed()
                result.duration_ms = int((time.monotonic() - start) * 1000)
                browser.close()
            if result.status == OK and not dynamic:
                if crit_ms is not None and result.duration_ms >= crit_ms:
                    result.status = CRIT
                    result.summary = (f"Flow passed but took {result.duration_ms}ms "
                                      f"(crit threshold {crit_ms}ms)")
                elif warn_ms is not None and result.duration_ms >= warn_ms:
                    result.status = WARN
                    result.summary = (f"Flow passed but took {result.duration_ms}ms "
                                      f"(warn threshold {warn_ms}ms)")
            return result
        try:
            for i, step in enumerate(flow["steps"]):
                step_start = time.monotonic()
                try:
                    try:
                        _run_step(page, step, default_timeout, ctx)
                    except FlowError:
                        raise
                    except secret_source.SecretError as exc:
                        # Missing/misconfigured secret is operator error, not a
                        # site failure: UNKNOWN, and the message never carries
                        # a secret value.
                        raise FlowError(str(exc), UNKNOWN)
                    except Exception as exc:
                        # A raw Playwright failure (click/goto timeout, bad
                        # selector) is a real check failure, not a runner bug:
                        # surface it as CRIT with the step named, and keep the
                        # message to its first line (Playwright appends logs).
                        first = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
                        raise FlowError(
                            f"Step {i} ({step.get('action', '?')}) failed: {first}"
                        )
                except FlowError as fe:
                    # 'optional: true' marks best-effort steps (cookie/consent
                    # banners, region popups): a failure is simply skipped.
                    if step.get("optional"):
                        continue
                    result.status = fe.status
                    result.summary = str(fe)
                    result.step_index = i
                    if shot_on_fail:
                        shot_dir = path.parent.parent / "screenshots"
                        shot_dir.mkdir(exist_ok=True)
                        shot = shot_dir / f"{path.stem}-fail-step{i}.png"
                        try:
                            # Blank password fields always; all inputs once a
                            # declared secret was used — the PNG can't leak creds.
                            _mask_before_shot(page, ctx)
                            page.screenshot(path=str(shot))
                            result.screenshot = str(shot)
                        except Exception:
                            pass
                    break
                finally:
                    label = re.sub(r"[^A-Za-z0-9_]", "_", f"step{i}_{step.get('action', 'unknown')}")
                    timings.append((label, int((time.monotonic() - step_start) * 1000)))
        finally:
            save_trace_if_failed()
            result.duration_ms = int((time.monotonic() - start) * 1000)
            browser.close()

    # Duration thresholds only escalate a passing flow (a failure stays CRIT).
    # In dynamic mode Checkmk owns the thresholding, so the runner does not
    # pre-compute WARN/CRIT from duration here.
    if result.status == OK and not dynamic:
        if crit_ms is not None and result.duration_ms >= crit_ms:
            result.status = CRIT
            result.summary = (
                f"Flow passed but took {result.duration_ms}ms "
                f"(crit threshold {crit_ms}ms)"
            )
        elif warn_ms is not None and result.duration_ms >= warn_ms:
            result.status = WARN
            result.summary = (
                f"Flow passed but took {result.duration_ms}ms "
                f"(warn threshold {warn_ms}ms)"
            )
    return result


MAX_ATTEMPTS_CAP = 3


def run_with_retries(path: Path, **kwargs) -> FlowResult:
    """run_flow honoring the flow's `max_attempts` (default 1, capped at 3).

    Only CRIT/WARN check outcomes retry — UNKNOWN means operator error
    (missing secret, bad schema) and retrying cannot fix it. Each attempt is a
    fresh browser. The final result notes the attempts so a flapping check is
    visible as flapping, not hidden.
    """
    try:
        attempts = int((yaml.safe_load(path.read_text()) or {}).get("max_attempts", 1))
    except Exception:
        attempts = 1
    attempts = max(1, min(attempts, MAX_ATTEMPTS_CAP))

    result = run_flow(path, **kwargs)
    tried = 1
    while tried < attempts and result.status in (WARN, CRIT):
        # Each attempt is a fresh run: clear the per-process redaction registry
        # and builtin-variable cache so a retry gets new {{ var.uuid }} values
        # and its failure message is not masked by a previous attempt's secret.
        secret_source.reset()
        result = run_flow(path, **kwargs)
        tried += 1
    if tried > 1:
        suffix = f" (attempt {tried}/{attempts})"
        if result.status == OK:
            suffix = f" (recovered on attempt {tried}/{attempts})"
        result.summary = result.summary + suffix
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SynthMK synthetic runner")
    parser.add_argument("flow", type=Path, help="Path to a YAML flow file")
    parser.add_argument("--headed", action="store_true", help="Run with a visible browser")
    parser.add_argument(
        "--p-state", action="store_true",
        help="Emit a 'P' state on success and let Checkmk threshold duration "
             "(overrides the flow's state_mode).",
    )
    parser.add_argument(
        "--screenshot-base-url", default=os.environ.get("SYNTHMK_SHOT_BASE_URL"),
        help="Base URL of the screenshot HTTP server; renders a clickable link "
             "in the failing service (default: $SYNTHMK_SHOT_BASE_URL).",
    )
    parser.add_argument(
        "--secrets-file", default=None,
        help="YAML secrets file for {{ secret.NAME }} references "
             "(default: $SYNTHMK_SECRETS_FILE; must be chmod 600).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit a JSON result (native <<<synthmk>>> section format) "
             "instead of a Checkmk local-check line.",
    )
    args = parser.parse_args(argv)
    dynamic = True if args.p_state else None  # None => honor flow state_mode

    try:
        result = run_with_retries(
            args.flow, headed=args.headed,
            dynamic=dynamic, shot_base_url=args.screenshot_base_url,
            secrets_file=args.secrets_file,
        )
    except FlowError as fe:
        # Schema / load failure → emit an UNKNOWN result, not a traceback.
        fallback = FlowResult(service=args.flow.stem, status=fe.status,
                              summary=str(fe))
        print(fallback.to_json() if args.json else fallback.checkmk_line())
        return fe.status
    except Exception as exc:  # pragma: no cover - runner-internal failure
        fallback = FlowResult(service=args.flow.stem, status=UNKNOWN,
                              summary=f"Runner error: {exc}")
        print(fallback.to_json() if args.json else fallback.checkmk_line())
        return UNKNOWN

    print(result.to_json() if args.json else result.checkmk_line())
    return result.status


if __name__ == "__main__":
    raise SystemExit(main())
