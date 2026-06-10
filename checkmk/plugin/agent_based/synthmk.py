"""SynthMK native check plugin (Checkmk agent-based API v2).

Consumes the runner node's `<<<synthmk:sep(0)>>>` agent section — one JSON
object per line, one synthetic check per object (see runner.py to_json()) —
and renders each as a first-class Checkmk service:

  * unit-aware duration metric (seconds) with warn/crit bands on the graph
  * per-step timing metrics (`synthmk_step*`) for journey breakdown graphs
  * thresholds overridable from Setup via the "SynthMK synthetic browser
    checks" ruleset (rulesets/synthmk.py) — no flow-file edit needed
  * failure screenshot link and step breakdown in the service details

The legacy `<<<local>>>` output remains available (SYNTHMK_OUTPUT=local on the
node) but this is the richer, default integration.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from cmk.agent_based.v2 import (
    AgentSection,
    CheckPlugin,
    CheckResult,
    DiscoveryResult,
    Metric,
    Result,
    Service,
    State,
    check_levels,
    render,
)

Section = Mapping[str, Mapping[str, Any]]

_METRIC_SAFE = re.compile(r"[^A-Za-z0-9_]")


def parse_synthmk(string_table) -> Section:
    flows: dict[str, dict[str, Any]] = {}
    for line in string_table:
        if not line:
            continue
        try:
            entry = json.loads(line[0])
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("service"):
            flows[str(entry["service"])] = entry
    return flows


agent_section_synthmk = AgentSection(name="synthmk", parse_function=parse_synthmk)


def discover_synthmk(section: Section) -> DiscoveryResult:
    for name in section:
        yield Service(item=name)


def _metric_name(label: str) -> str:
    return "synthmk_" + _METRIC_SAFE.sub("_", str(label))


def check_synthmk(item: str, params: Mapping[str, Any], section: Section) -> CheckResult:
    entry = section.get(item)
    if entry is None:
        # No data this cycle -> let the service go stale rather than guess.
        return

    status = int(entry.get("status", 3))
    duration_s = float(entry.get("duration_ms", 0)) / 1000.0
    summary = str(entry.get("summary", "")) or "no summary"
    failed_step = entry.get("failed_step")

    # Duration levels: Setup rule wins, else the flow file's warn_ms/crit_ms.
    levels = params.get("duration_levels")
    if levels is None:
        warn_ms, crit_ms = entry.get("warn_ms"), entry.get("crit_ms")
        if warn_ms is not None and crit_ms is not None:
            levels = ("fixed", (float(warn_ms) / 1000.0, float(crit_ms) / 1000.0))
        else:
            levels = ("no_levels", None)

    if status == 0:
        # Healthy journey: state from the duration levels (graph gets bands).
        yield from check_levels(
            duration_s,
            levels_upper=levels,
            metric_name="synthmk_duration",
            label="Journey duration",
            render_func=render.timespan,
        )
        yield Result(state=State.OK, summary=summary)
    else:
        # Failed journey: the runner's message is authoritative.
        text = summary
        if failed_step is not None and "tep" not in summary[:8]:
            text = f"{text} (step {failed_step})"
        yield Result(state=State(status), summary=text)
        yield Metric("synthmk_duration", duration_s)

    shot = entry.get("screenshot_url")
    if shot:
        # Clickable in the GUI when "Escape HTML codes in service output" is
        # Off for this host (scope the rule narrowly; single sanitized line).
        yield Result(state=State.OK, notice=f'<a href="{shot}" target="_blank">Failure screenshot</a>')

    trace = entry.get("trace_url")
    if trace:
        # Playwright trace.zip: download and open at trace.playwright.dev for a
        # step-by-step replay with DOM snapshots.
        yield Result(state=State.OK, notice=f'<a href="{trace}" target="_blank">Playwright trace</a>')

    steps = entry.get("steps") or []
    if steps:
        breakdown = " → ".join(f"{s.get('label', '?')} {s.get('ms', 0)}ms" for s in steps)
        yield Result(state=State.OK, notice=f"Steps: {breakdown}")
        for step in steps:
            yield Metric(_metric_name(step.get("label", "step")), float(step.get("ms", 0)) / 1000.0)

    # Extra named metrics: cert_days_left from cert checks, and the runner's
    # generic list ([{label, value}]).
    for extra in (entry.get("extras") or []):
        try:
            yield Metric(_metric_name(extra.get("label", "extra")), float(extra.get("value")))
        except (TypeError, ValueError):
            continue

    # Generic extra metrics (used by the SynthMK Scheduler self-service:
    # flows / active / overdue / runs / overlap skips ...).
    for key, value in (entry.get("metrics") or {}).items():
        try:
            yield Metric(_metric_name(key), float(value))
        except (TypeError, ValueError):
            continue


check_plugin_synthmk = CheckPlugin(
    name="synthmk",
    service_name="%s",
    sections=["synthmk"],
    discovery_function=discover_synthmk,
    check_function=check_synthmk,
    check_ruleset_name="synthmk",
    check_default_parameters={},
)
