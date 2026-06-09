# SynthMK Product Roadmap & Scope

SynthMK is a home-lab-first synthetic monitoring addon for Checkmk. The guiding
rule is **simplicity first**: a user defines a readable flow, Checkmk runs it,
and a normal Checkmk service shows the result. No separate dashboard, scheduler,
or cloud backend.

## Free / community scope (now — the MVP)

Everything in this repo is free and self-hostable:

- Readable YAML **flow schema** (`docs/flow-schema.md`).
- Python **Playwright runner** emitting Checkmk local-check output
  (`runner/runner.py`), with optional dynamic (`P`) state and clickable
  failure-screenshot links.
- **Checkmk local-check** (`checkmk/synthmk_check.sh`) — drop-in, uses Checkmk's
  own interval and service rendering.
- **Runner-node Docker appliance** (`runner-node/`) you host inside the intranet:
  scheduler (spool-dir, scales to many/long checks), agent transport, screenshot
  server, and **piggyback** so each monitored site is its own Checkmk host.
- **Chrome MV3 recorder** (`extension/`) — record → export flow YAML.
- **Self-hosted LAN lab** (`lab/`) — Checkmk Raw + runner + internal demo site,
  one `docker compose up`.
- Bundled **demo page + example flows** (OK + failing) and a browser-free
  **validation command** (`runner/test_contract.py`).
- Core assertions: visible text, page title, URL, element wait, warn/crit
  duration thresholds, clear failure messages, optional screenshot-on-failure.

Target user: someone running Checkmk Raw/CRE at home who wants "is my login
flow still working?" as a normal service, without writing Playwright.

## Premium / later scope (NOT built now)

Candidates for a later paid/hosted tier, explicitly deferred:

- Encrypted **secret store** and credential vault (today resolves `{{ }}` from env).
- **Multi-step result drill-down** UI / per-step timing dashboards (GOAT's
  admin-suite territory — deliberately rejected).
- **Multi-node fleet / locations**: a pool of runner nodes with a special-agent
  (HTTP) pull mode. v0.2.0 ships the *single* runner-node appliance; the
  multi-node coordinator is the documented next step (see `docs/architecture.md`).
- Hosted SaaS coordinator, alert routing integrations, SLA reporting.

(The Chrome recorder and the single runner node, previously listed here, are now
shipped in the community scope above.)

## Out of scope — first iteration (hard "no")

- No enterprise dashboard or web UI — **Checkmk is the UI**.
- No licensing/billing system.
- No cloud backend or remote runner network.
- No raw-Playwright "script mode" / arbitrary code execution in flows.
- No deep Chrome recorder build in this pass (schema notes + placeholder only).

## Why this boundary

The MVP must prove one loop end-to-end — *readable flow → runner →
Checkmk-compatible output → Checkmk service* — before adding surface area.
Premium features only make sense once that loop is trusted in a real home lab.
See [home-lab.md](home-lab.md) for the demo.
