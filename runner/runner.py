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
    "check_title",
    "check_url",
    "check_element_count",
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

    def perfdata(self) -> str:
        warn = "" if self.warn_ms is None else str(self.warn_ms)
        crit = "" if self.crit_ms is None else str(self.crit_ms)
        # Checkmk perfdata: name=value;warn;crit, multiple metrics '|'-separated.
        parts = [f"duration={self.duration_ms}ms;{warn};{crit}"]
        for label, ms in (self.step_timings or []):
            parts.append(f"{label}={ms}ms")
        return "|".join(parts)

    def _screenshot_suffix(self) -> str:
        if not self.screenshot:
            return ""
        if self.shot_base_url:
            # Clickable link rendered in the Checkmk service Details — requires the
            # "Escape HTML codes in service output" rule turned Off for this host.
            name = os.path.basename(self.screenshot)
            url = f"{self.shot_base_url.rstrip('/')}/{name}"
            token = _shot_token(name)
            if token:
                url += f"?t={token}"
            return f' <a href="{url}">screenshot</a>'
        return f" (screenshot: {self.screenshot})"

    def to_json(self) -> str:
        """Machine-readable result for the native <<<synthmk>>> agent section.

        The native Checkmk check plugin (checkmk/plugin/) consumes this and
        renders proper services with unit-aware metrics, rulesets, and graphs —
        richer than the local-check line. All text passes the same redaction.
        """
        import json
        shot_url = None
        if self.screenshot and self.shot_base_url:
            name = os.path.basename(self.screenshot)
            shot_url = f"{self.shot_base_url.rstrip('/')}/{name}"
            token = _shot_token(name)
            if token:
                shot_url += f"?t={token}"
        return json.dumps({
            "service": self.service,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "warn_ms": self.warn_ms,
            "crit_ms": self.crit_ms,
            "summary": _oneline(self.summary),
            "failed_step": self.step_index,
            "steps": [{"label": label, "ms": ms} for label, ms in (self.step_timings or [])],
            "screenshot_url": shot_url,
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
    if "steps" not in data or not isinstance(data["steps"], list):
        raise FlowError(f"Flow file {path} missing a 'steps' list", UNKNOWN)
    return data


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
        page.click(step["selector"], timeout=timeout)
    elif action == "fill":
        value = _substitute(str(step.get("value", "")))
        # A sensitive fill (passwords, tokens) is never echoed anywhere and
        # poisons later failure screenshots (inputs get masked before capture).
        if step.get("sensitive"):
            secret_source.register_sensitive(value)
            ctx["sensitive_used"] = True
        page.fill(step["selector"], value, timeout=timeout)
    elif action == "press":
        # Key press, optionally scoped to a selector (else the focused element).
        key = str(step["key"])
        if step.get("selector"):
            page.press(step["selector"], key, timeout=timeout)
        else:
            page.keyboard.press(key)
    elif action == "select_option":
        # Match by value first; fall back to visible label for recorder output.
        sel, value = step["selector"], _substitute(str(step.get("value", "")))
        try:
            page.select_option(sel, value=value, timeout=timeout)
        except Exception:
            try:
                page.select_option(sel, label=value, timeout=timeout)
            except Exception:
                raise FlowError(f"Could not select option '{value}' in '{sel}'")
    elif action == "hover":
        page.hover(step["selector"], timeout=timeout)
    elif action == "scroll_into_view":
        page.locator(step["selector"]).first.scroll_into_view_if_needed(timeout=timeout)
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
                if ctx.get("sensitive_used"):
                    page.evaluate(_MASK_INPUTS_JS)
                page.screenshot(path=str(shot), full_page=bool(step.get("full_page", False)))
                ctx.setdefault("screenshots", []).append(str(shot))
            except Exception as exc:
                # An always-on screenshot is evidence, not an assertion: a capture
                # failure must not flip an otherwise-passing flow to CRIT.
                if not step.get("optional", True):
                    raise FlowError(f"Screenshot capture failed: {exc}")
    elif action == "wait_for_element":
        try:
            page.wait_for_selector(step["selector"], timeout=timeout, state="visible")
        except Exception:
            raise FlowError(f"Element '{step['selector']}' not found within {timeout}ms")
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
        sel = step["selector"]
        minimum = int(step.get("min", 1))
        count = page.locator(sel).count()
        if count < minimum:
            raise FlowError(
                f"Expected at least {minimum} element(s) matching '{sel}', found {count}"
            )
    else:
        raise FlowError(f"Unknown action '{action}'", UNKNOWN)


# JS run on the page before a failure screenshot when a sensitive fill happened:
# blanks every input/textarea so the captured PNG cannot contain a credential
# (or anything typed after it) in a form field.
_MASK_INPUTS_JS = (
    "() => { for (const el of document.querySelectorAll('input, textarea')) "
    "{ try { el.value = '\\u2022\\u2022\\u2022'; } catch (e) {} } }"
)


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
        timings: list[tuple[str, int]] = []
        result.step_timings = timings
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
                            if ctx["sensitive_used"]:
                                # Blank form fields so the PNG can't leak creds.
                                page.evaluate(_MASK_INPUTS_JS)
                            page.screenshot(path=str(shot))
                            result.screenshot = str(shot)
                        except Exception:
                            pass
                    break
                finally:
                    label = re.sub(r"[^A-Za-z0-9_]", "_", f"step{i}_{step.get('action', 'unknown')}")
                    timings.append((label, int((time.monotonic() - step_start) * 1000)))
        finally:
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
        result = run_flow(
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
