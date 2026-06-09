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

# Checkmk status digits
OK, WARN, CRIT, UNKNOWN = 0, 1, 2, 3
STATE_NAME = {OK: "OK", WARN: "WARN", CRIT: "CRIT", UNKNOWN: "UNKNOWN"}


def _oneline(text: str, limit: int = 240) -> str:
    """Collapse a message to a single Checkmk-safe line (no newlines/pipes)."""
    flat = " ".join(str(text).split()).replace("|", "/")
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"

# Actions that perform an interaction vs. assert a condition.
ASSERT_ACTIONS = {
    "check_visible_text",
    "check_title",
    "check_url",
    "wait_for_element",
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

    def perfdata(self) -> str:
        warn = "" if self.warn_ms is None else str(self.warn_ms)
        crit = "" if self.crit_ms is None else str(self.crit_ms)
        # Checkmk perfdata: name=value;warn;crit  (unit suffix on value is allowed)
        return f"duration={self.duration_ms}ms;{warn};{crit}"

    def checkmk_line(self) -> str:
        extra = ""
        if self.screenshot:
            extra = f" (screenshot: {self.screenshot})"
        return (
            f"{self.status} \"{self.service}\" {self.perfdata()} "
            f"{STATE_NAME[self.status]} - {_oneline(self.summary)}{extra}"
        )


class FlowError(Exception):
    """A flow assertion or interaction failure with a clear, user-facing message."""

    def __init__(self, message: str, status: int = CRIT):
        super().__init__(message)
        self.status = status


def _substitute(value: str) -> str:
    """Resolve {{ name }} placeholders from environment variables (GOAT-style)."""
    def repl(match: re.Match) -> str:
        name = match.group(1).strip()
        return os.environ.get(name, "")
    return re.sub(r"\{\{\s*([^}]+?)\s*\}\}", repl, value)


def load_flow(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise FlowError(f"Flow file {path} did not parse to a mapping", UNKNOWN)
    if "steps" not in data or not isinstance(data["steps"], list):
        raise FlowError(f"Flow file {path} missing a 'steps' list", UNKNOWN)
    return data


def _run_step(page, step: dict[str, Any], default_timeout: int) -> None:
    action = step.get("action")
    timeout = int(step.get("timeout_ms", default_timeout))
    if action == "open_url":
        url = _substitute(step["url"])
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    elif action == "click":
        page.click(step["selector"], timeout=timeout)
    elif action == "fill":
        page.fill(step["selector"], _substitute(str(step.get("value", ""))), timeout=timeout)
    elif action == "wait_for_element":
        try:
            page.wait_for_selector(step["selector"], timeout=timeout, state="visible")
        except Exception:
            raise FlowError(f"Element '{step['selector']}' not found within {timeout}ms")
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
    else:
        raise FlowError(f"Unknown action '{action}'", UNKNOWN)


def run_flow(path: Path, headed: bool = False) -> FlowResult:
    flow = load_flow(path)
    service = flow.get("name", path.stem)
    warn_ms = flow.get("warn_ms")
    crit_ms = flow.get("crit_ms")
    default_timeout = int(flow.get("timeout_ms", 30000))
    shot_on_fail = bool(flow.get("screenshot_on_failure", False))

    result = FlowResult(service=service, warn_ms=warn_ms, crit_ms=crit_ms)

    from playwright.sync_api import sync_playwright

    start = time.monotonic()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page()
        try:
            for i, step in enumerate(flow["steps"]):
                try:
                    _run_step(page, step, default_timeout)
                except FlowError as fe:
                    result.status = fe.status
                    result.summary = str(fe)
                    result.step_index = i
                    if shot_on_fail:
                        shot_dir = path.parent.parent / "screenshots"
                        shot_dir.mkdir(exist_ok=True)
                        shot = shot_dir / f"{path.stem}-fail-step{i}.png"
                        try:
                            page.screenshot(path=str(shot))
                            result.screenshot = str(shot)
                        except Exception:
                            pass
                    break
        finally:
            result.duration_ms = int((time.monotonic() - start) * 1000)
            browser.close()

    # Duration thresholds only escalate a passing flow (a failure stays CRIT).
    if result.status == OK:
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
    args = parser.parse_args(argv)

    try:
        result = run_flow(args.flow, headed=args.headed)
    except FlowError as fe:
        # Schema / load failure → emit an UNKNOWN Checkmk line, not a traceback.
        service = args.flow.stem
        print(f'{fe.status} "{service}" duration=0ms;; {STATE_NAME[fe.status]} - {_oneline(str(fe))}')
        return fe.status
    except Exception as exc:  # pragma: no cover - runner-internal failure
        service = args.flow.stem
        print(f'3 "{service}" duration=0ms;; UNKNOWN - Runner error: {_oneline(str(exc))}')
        return UNKNOWN

    print(result.checkmk_line())
    return result.status


if __name__ == "__main__":
    raise SystemExit(main())
