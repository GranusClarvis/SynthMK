# Competitive landscape — what SynthMK adopts, and from whom

Research date: 2026-06-09. Full reports: [research-oss-landscape.md](research-oss-landscape.md)
(Robotmk, Grafana SM/k6, Uptime Kuma, Checkly, blackbox_exporter, Elastic
Synthetics, sitespeed.io, Upright, OneUptime) and
[research-newrelic-ux.md](research-newrelic-ux.md) (New Relic Synthetics UX deep-dive).

## Positioning in one paragraph

Checkmk's official synthetic monitoring (Robotmk v2) is enterprise-only, Robot
Framework based, and its worst operator pain is environment management (RCC
builds) and plaintext credentials in agent config. Uptime Kuma proves huge
demand for simple self-hosted monitoring but has no multi-step browser flows at
all. Checkly and New Relic show what great authoring UX looks like, but their
control planes are SaaS. **SynthMK's lane: Playwright-native multi-step browser
checks, fully self-hosted, declarative YAML, pre-baked appliance, free on
Checkmk Raw.**

## Decisions adopted in v0.3.0 (and their source)

| v0.3.0 feature | Inspired by |
|---|---|
| `{{ secret.NAME }}` reference-by-name + values masked in ALL output + 0600 permission-checked file on the node only | New Relic `$secure.NAME` (write-only, `_SECURECREDENTIAL_` scrubbing), Grafana SM secrets store; **anti-pattern avoided:** Robotmk's plaintext secrets in agent config |
| Recorder auto-converts `<input type=password>` to a secret reference + `sensitive: true` — the typed value never leaves the page | New Relic's "Secure credential" as a first-class *step type*, not interpolation |
| Worker-pool scheduler (`SYNTHMK_MAX_CONCURRENCY`), startup stagger, overlap suppression, hard run timeout | Checkly `JOB_CONCURRENCY` (max 10/agent), Upright `stagger_by_site`; **anti-pattern avoided:** Uptime Kuma's unpooled browser spawning |
| `SynthMK Scheduler` self-monitoring service (overdue flows ⇒ WARN on the NODE) | New Relic's #1 private-location complaint (wedged minions alert as false positives on apps); Robotmk's `RMK Scheduler Status` |
| Per-step duration perfdata on every service | Elastic `journey/step` timings, Robotmk keyword "KPI monitoring" |
| Published capacity formula (docs/scaling.md) | Grafana SM resource budgets, New Relic SJM sizing tables ("1 core per concurrent browser check") |
| Token-authenticated screenshot server on the node, links in service output | workadventure's node-served artifacts pattern + Checkly artifact surfacing, hardened |
| Official Checkmk agent + `cmk-agent-ctl` TLS registration path | New Relic one-key private-location pairing (`register_agent.sh` is our one-command equivalent) |
| Warmup placeholder lines under the real service name at node start | Robotmk anti-pattern: runtime-only failures / bad early discovery |
| `optional: true` steps (cookie-consent clicks) | Empirical: Google/DDG consent + bot-block testing (see flows/google-search.yaml) |
| Pre-baked appliance image, no per-flow env building | Robotmk's RCC pain is its loudest forum complaint; Checkmk itself is replacing RCC in 2.5 |

## Deliberately NOT adopted (yet) — with reasons

* **Robot Framework compatibility** — the entire point is avoiding that stack on Raw.
* **Conditionals/loops in flows** — New Relic never added them to step monitors;
  declarative simplicity is the product. `optional: true` covers the dominant
  real-world case (consent banners).
* **Raw Playwright spec files as flows** (Checkly's killer feature) — on the
  roadmap as an *opt-in, operator-enabled* directory; running user-authored JS
  on the probe is RCE-by-design (see OneUptime advisories GHSA-4j36-39gm-8vq8 +
  sandbox escape) and needs explicit trust gating, not a default.
* **SaaS control plane / job pulling** — Checkmk *is* our control plane;
  the spool model keeps the node autonomous and the agent poll instant.
* **Per-user pricing-driven design** — lean into self-hosted: every engineer
  can record and ship a flow.

## Roadmap candidates extracted from research (post-v0.3)

1. **Cert-expiry + broken-links check types** (New Relic's beloved cheap wins).
2. **Playwright trace.zip on failure** served next to screenshots ("open in
   trace viewer" — better artifact than New Relic has).
3. **`max_attempts` / three-strikes retry** with attempt count surfaced in
   service details (New Relic's flake absorber, made legible).
4. **Flow groups** (`group: payments` ⇒ serialized within, parallel across) with
   lint-time interval math (Robotmk's primitive, automated).
5. **`synthmk doctor`** — env/browser/SELinux self-check (Robotmk RHEL9 pain).
6. **Versioned runtime upgrades** — batch "validate all flows on vNext" before
   cutover (New Relic's 2024 forced-migration lesson).
7. **YAML→Playwright compiler** so flows can "graduate" to code (Checkly bridge).
