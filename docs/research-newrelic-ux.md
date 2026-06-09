# New Relic Synthetic Monitoring — UX & Product Design Research (2024–2026)

## 1. Monitor types and how users choose

New Relic offers **seven monitor types**, presented as a type-picker grid at the start of monitor creation (one.newrelic.com → Synthetic monitoring → Create monitor):

| Type (API name) | What it does | Positioning |
|---|---|---|
| **Ping** (`SIMPLE`) | HEAD/GET against one URL via a Java HTTP client (no JS execution); spoofs Chrome UA; fixed 60s timeout; optional response-string validation, custom headers, SSL verification, "redirect is failure", "bypass HEAD" | Cheapest availability check |
| **Simple browser** (`BROWSER`) | Loads one URL in a real Chrome/Firefox instance, full page-load waterfall | "Real user" availability without scripting |
| **Step monitor** (`STEP_MONITOR`) | **No-code** sequenced workflow built from prebuilt steps in the UI | Non-coders; simple journeys |
| **Scripted browser** (`SCRIPT_BROWSER`) | Custom Node.js/Selenium WebDriver script driving Chrome/Firefox | Complex journeys (search → click result → assert) |
| **API test** (`SCRIPT_API`) | Node script using the bundled `http-request`/`got` module to call and validate endpoints | Backend validation |
| **Broken links** (`BROKEN_LINKS`) | Crawls all links on a page, reports non-success ones | Specialized, zero-config |
| **Cert check** (`CERT_CHECK`) | Fails when TLS cert is within N configurable days of expiry | Specialized, zero-config |

Selection guidance in docs is complexity-laddered: ping for uptime → simple browser for "does it render" → step monitor for non-technical journey checks → scripted for everything else. All types share the same second-page config: name, period (every 1 min … daily), locations (public list + your private locations), runtime selection, and optional device emulation (device type + orientation) for browser types. Notably, ping and broken-links/cert-check are billed/treated as "lightweight"; browser/API/step are "heavyweight" — a distinction that flows all the way down to private-location sizing.

## 2. The no-code step builder UX

The step monitor (launched 2021, still the no-code flagship) lets users compose an ordered list from **~12 prebuilt step types**, the documented core being:

- **Navigate to URL**
- **Type text** (into a target element)
- **Click element**
- **Select from dropdown**
- **Assert text** — text appears (or doesn't appear) on screen
- **Assert element** — element (button/div/img) present or visible
- **Secure credential** — types a stored secret into a field *without ever showing the value*

Each step is a small form: pick the action, then identify the target element by **CSS class, HTML ID, link text, or XPath** — with inline help text on the right side of the panel explaining how to find these via browser inspect. Steps are listed vertically and run strictly in order. Before saving, the user hits **Validate**, which actually runs the monitor from a selected location ("may take a few minutes") and shows the result inline — a try-before-save loop that is essential to the UX. The canonical demo flow in New Relic's blog is a login journey: Navigate → Secure credential (email) → Click `login_submit`-style ID → Secure credential (password) → Click login → Assert text.

Key design choice: **secure-credential entry is a first-class step type**, not a variable interpolation feature — a non-coder picks "Secure credential", picks the element, and picks a credential key from a dropdown. They never see or paste the secret.

Limitations users hit: no conditionals/loops, no waits beyond implicit ones, locator-by-typing (no point-and-click element picker in-product — that gap is filled by the Recorder extension, below).

## 3. Scripted browser monitors

- **Environment:** Node.js scripts executing in New Relic's "Chrome 100+" runtime (post-2024 the only runtime; legacy Chrome 72/Node 10 runtime was hard-EOL'd **October 22, 2024**). Still **Selenium WebDriver–based** (selenium-webdriver 4.1), *not* Playwright — a point competitors like Checkly attack.
- **Scripting API:** `$selenium` (the whole selenium-webdriver module: `By`, `until`, `Button`, …) and `$webDriver` (a WebDriver instance with `get()`, `findElement()`, plus New Relic custom helpers like `waitForAndFindElement()`). Legacy `$browser`/`$driver` aliases remain **backward-compatible** in the new runtime (runtime ≥2.0.29 even silenced the deprecation warnings) — deliberate migration-friction reduction. Selenium 4 removed the promise manager, so scripts must use `await`/`.then` — the single biggest migration breakage.
- Extras: `$headers.add()` for header injection, `$urlFilter.addToAllowList()/addToDenyList()`, `$secure.*` for credentials, popular npm modules pre-bundled.
- **Authoring/debugging UX:** an in-browser IDE-style editor with autocomplete of functions/locators; **Validate** runs the script live before save; max run time 3 minutes (hard kill); `console.log()` lands in a **script log** (50KB cap) attached to each result; screenshots captured **on failure by default**; failed checks can be **re-run on demand** ("Run check") against one location. For the 2024 runtime EOL they shipped a dedicated **runtime upgrade UI**: batch-test all monitors against the new runtime, tabs for "validating / ready to update / updated", **AI-generated fixes with a side-by-side diff view**, shareable validation links so teams can split remediation.

## 4. Private locations / synthetics job manager (the self-hosted probe story)

This is the closest analog to SynthMK's runner-node appliance.

- **Concept split:** a *private location* is a logical entity created in the SaaS UI; a **synthetics job manager (SJM)** is the container appliance you run that services it. (The old appliance, the **containerized private minion / CPM**, was EOL'd Oct 2024 alongside legacy runtimes.)
- **Registration flow:** create private location in UI → UI displays a **private location key** → you pass that single key as `PRIVATE_LOCATION_KEY` env var to the container. That's the entire pairing ceremony. The key authenticates the SJM and binds it to the location; the location then appears in every monitor's location-picker next to public locations.
- **Pull, not push, networking:** the SJM makes **outbound-only** HTTPS calls to `synthetics-horde.nr-data.net` to fetch queued jobs and post results. No inbound ports; proxies supported via `HORDE_API_PROXY*` env vars. Firewalls only need outbound to the horde endpoint + docker.io for runtime images.
- **Architecture:** the SJM container is a *coordinator only*; each check spawns a **throwaway runtime container** (ping runtime / node-api runtime / node-browser runtime) — hence the mounted `docker.sock` requirement on Docker, or Helm-managed runtime pods on K8s. (This fixed a CPM bug class: CPM created a fresh Docker network per job and could exhaust IP ranges.)
- **Deploy options:** `docker run` one-liner, Podman (rootless, fiddly), Kubernetes via official Helm chart (`helm install ... --set synthetics.privateLocationKey=...`), with per-runtime resource knobs and a 2Gi default PVC.
- **Sizing guidance (their published numbers):**
  - **1 CPU core per concurrent heavyweight monitor** (browser/API/step); ~**3.3 GiB RAM per core**; ≥**50 GiB disk** per host.
  - K8s pod requests/limits: job manager 0.5–0.75 vCPU / 0.8–1.6Gi; ping runtime 0.5–0.75 vCPU / 0.5–1Gi; node-api 0.5–0.75 vCPU / 1.25–2.5Gi; node-browser **1–1.5 vCPU / 2–3Gi** (heaviest).
  - Throughput ceilings: one SJM ≈ **15 heavyweight jobs/min** and ≈ **75 ping checks/min**. To scale: **run more SJM instances** (separate Helm releases / hosts), explicitly *not* pod replicas; tune `parallelism` per SJM.
- **Health/queue observability:** the SaaS records `SyntheticsPrivateLocationStatus` events (e.g., `checksPending`); docs ship NRQL like `SELECT derivative(checksPending, 1 minute) ... TIMESERIES` to detect queue growth, and the UI can show/clear a backed-up location queue. An unhealthy/slow private node produces **false-positive alerts and result gaps** — documented as the main private-location failure mode.

## 5. Secure credentials

- Created in UI (**Synthetic monitoring → Secure credentials**) or NerdGraph API; key + value + description. **Keys must be UPPERCASE alphanumeric/underscore**; values ≤10,000 chars; ≤1,000 credentials/account.
- Referenced in scripts as **`$secure.MY_CREDENTIAL`** (dot notation only — bracket notation deliberately blocked, which prevents dynamic enumeration of secrets). Step monitors reference them via the Secure-credential step's dropdown.
- **Write-only by design:** after creation, values can never be viewed — only keys and metadata. Update = overwrite.
- Storage: **AES-GCM-256 at rest, keys in AWS KMS**; New Relic states employees cannot read values.
- **Output scrubbing:** the value is replaced with `_SECURECREDENTIAL_` in all monitor results, logs, and alerts (best-effort; a determined script could still exfiltrate, so docs scope it as "obscure, don't trust hostile script authors").
- **Permissions:** account-scoped; admins gate create/view(keys)/delete per user.
- **Audit:** saves/validations of monitors that touch a secure credential are logged as queryable `NrAuditEvent`s.
- Note: secrets live in the SaaS and are delivered to private-location runtimes at execution time — there's no customer-side vault option, an occasional enterprise complaint.

## 6. Results presentation, SLA, alerting

- **Per-monitor summary page:** availability %, median duration trends, results split by location.
- **Results list:** every check with status/duration/location, sortable and filterable (e.g., "show me the suspiciously fast results from Mumbai").
- **Individual check detail:** HTTP status, request/response headers, total load time/size, and a **resource waterfall** (every asset, ordered, with timing segments) for browser checks. For scripted monitors, the **script log + per-step timings** show where in the journey time was spent or where it died; **screenshots are attached on failure by default** (configurable). One-click **re-run check** from the failure view.
- **SLA report:** both per-monitor and an **account-wide SLA Reports page** showing aggregated uptime % and average duration over time — explicitly designed as the artifact you show management.
- **Alerting:** synthetic alerts are "three strikes" per location (3 consecutive failures from one location = one reported failure) to absorb flake; alert conditions plug into standard NR alert policies (multi-location thresholds available). **Monitor downtime windows** stop checks entirely during planned maintenance — explicitly so the SLA report is not polluted — vs. **muting**, which keeps checks running but silences notifications. Downtimes support recurrence and >24h spans (improved Dec 2023).

## 7. What users praise and complain about

**Praise** (G2 ~4.5/5, Capterra, PeerSpot): one platform — synthetics correlate with APM/browser/infra data; step monitor lowers the bar for QA/support staff; broad public location list; private locations "just work" once the key is in; SLA reports are management-friendly; validate-before-save loop.

**Complaints:**
- **Pricing dominates.** Per-user seat pricing (~$49–99/user/mo) plus consumption makes broad access expensive; synthetic check quotas (free: 500/mo-ish baseline tiers, then per-check overages) are hard to predict — Checkly's comparison taunts: "you will not be able to answer 'what will 12k browser sessions/month cost me?'". Quarterly price drift and add-on creep are recurring G2/middleware.io themes.
- **The 2024 forced runtime migration hurt.** Hard EOL Oct 22, 2024; monitors force-upgraded and broke (Selenium 4 promise-manager removal → `findElement` failures), triggering alert storms for laggards. The upgrade UI + AI fixes were a response to this pain.
- **Selenium, not Playwright** — perceived as legacy tech for new test authoring; no native Playwright runtime as of this research.
- **Private location ops:** docker.sock mount requirement raises security eyebrows; scaling rule of "more SJMs, never replicas" is unintuitive; unhealthy minions cause false positives/result gaps; queue troubleshooting requires NRQL.
- **Flaky-failure triage:** isolated single-location failures are common enough to need a dedicated troubleshooting doc; three-strike logic helps but confuses ("the monitor failed but the alert didn't fire").
- General platform UX: powerful but dense; navigation/learning curve cited repeatedly.

---

## Lessons for SynthMK

(Self-hosted Checkmk addon: YAML flow format, Playwright runner-node appliance, Chrome recorder extension.)

1. **Adopt the complexity ladder as the creation UX.** First screen = type picker with plain-language cards: "URL check (HTTP)" → "Page load (browser)" → "Recorded/step flow (no code)" → "Full Playwright flow (YAML)". Plus the two cheap specialized wins New Relic proves people love: **cert-expiry check** and **broken-links check** — both are ~free to implement on the Playwright/HTTP stack and demo brilliantly in Checkmk.

2. **Constrain the no-code vocabulary to New Relic's seven verbs.** `navigate, type, click, select, assert_text, assert_element, secure_credential` covers their entire no-code product. Make these the *only* step kinds the recorder extension emits and the YAML schema's "simple" profile — anything fancier is "eject to full Playwright YAML". Resist conditionals/loops in v1; New Relic never added them and the step monitor still carries the no-code segment.

3. **Copy `$secure.NAME` exactly — including the constraints.** UPPERCASE_UNDERSCORE keys, write-only after creation (show key + last-modified, never the value), referenced in YAML as `{{secure.LOGIN_PASSWORD}}` (or `secret: LOGIN_PASSWORD` as a step field), and **scrub the value to `***SECURE***` in all logs, screenshots-adjacent text, and Checkmk service output**. SynthMK's self-hosted twist is an *advantage to advertise*: secrets can live on the runner node (or in Checkmk's password store) and never transit a third party — the thing NR enterprise customers can't have.

4. **Make secure-credential a step type, not just interpolation.** The NR insight: a non-coder shouldn't paste `{{secure.X}}` into a "type text" step; they should pick the "Type secret" step and choose a key from a dropdown. The recorder extension should detect `<input type=password>` and *automatically* emit a `secure_credential` step with a placeholder key — never record the actual keystrokes.

5. **One-token runner registration.** New Relic's pairing flow is the gold standard: create location in UI → get one key → `docker run -e PRIVATE_LOCATION_KEY=...`. SynthMK should mirror it: define a "runner location" object in Checkmk (WATO), generate one registration token, and the appliance takes exactly `SYNTHMK_SITE_URL` + `SYNTHMK_LOCATION_KEY`. **Outbound-only, runner-pulls-jobs** if architecture allows (firewall-friendly, no inbound ports on the runner) — or at minimum make the agent-controller-style handshake one command.

6. **Publish blunt sizing numbers and a hard throughput ceiling.** "1 CPU core + ~3 GiB RAM per concurrent browser check; ~N browser checks/min per runner at M-second average flow time; scale by adding runners, not threads" — one table in the docs. NR's honesty here (15 heavyweight jobs/min/SJM) is what makes capacity planning possible; vagueness is what fills their forums.

7. **Expose runner queue depth as a Checkmk service.** NR makes users write NRQL to see `checksPending` growth; SynthMK can do better natively: every runner node ships a self-monitoring service (queue depth, jobs/min, last-seen, runtime container failures) so a wedged runner alerts *as itself* instead of as false positives on every monitored app. This directly addresses NR's #1 private-location complaint.

8. **Validate-before-save, everywhere.** Every creation/edit path (recorder import, YAML edit, UI) ends with a "Run now on runner X" button showing the full result inline before the flow is committed. This single loop is the most-praised piece of NR's authoring UX and trivially maps to a one-off Playwright run.

9. **Per-step result presentation: timeline + screenshot + log per step.** For each check: a step list with status icon, duration, and (on failure) screenshot at point-of-death + the Playwright error and console excerpt; below it, the network/HAR waterfall for browser flows. Playwright traces give SynthMK a *better* artifact than NR has — attach the trace.zip to failed results and link "open in trace viewer". Default to screenshots-on-failure-only (NR's default) to control disk.

10. **Three-strikes / retry semantics as a first-class, visible setting.** Implement `max_attempts: 3` (re-run before reporting CRIT) per monitor, and *surface it in the service details* ("failed 1/3 attempts — not yet alerting") so users aren't confused the way NR users are about failures that don't alert. In Checkmk terms this can also map onto check retries/soft states — pick one mechanism and document it.

11. **Downtime ≠ mute, and protect the SLA.** Mirror NR's split: Checkmk scheduled downtimes should *skip executing* the flow (so availability reports stay clean), while ack/mute keeps running but silences. SynthMK gets the SLA report nearly free via Checkmk availability reporting — make sure skipped-during-downtime results don't count as DOWN, and advertise "SLA report" explicitly; it's a feature buyers name.

12. **Treat runtime upgrades as a product feature from day one.** NR's biggest reputational hit was the 2024 forced runtime migration. SynthMK should version the runner image + YAML schema, let two runtime versions coexist per location, and offer a "test all flows against runtime vNext" batch job with pass/fail table *before* any cutover. Cheap to build now, very expensive to retrofit. (Skip the AI-autofix; keep the batch validation + diff idea.)

**Deliberately simplify vs. NR:** no per-user pricing concerns to design around (lean into "every engineer can author flows"); no SaaS secret escrow (runner-local secrets); no Selenium compatibility layer (Playwright-only, one API); no separate ping-vs-heavyweight runtime containers initially — one runner image with an internal lightweight HTTP path is enough at SynthMK's scale.

**Sources:** [Monitor types](https://docs.newrelic.com/docs/synthetics/synthetic-monitoring/getting-started/types-synthetic-monitors/) · [Add/edit monitors](https://docs.newrelic.com/docs/synthetics/synthetic-monitoring/using-monitors/add-edit-monitors/) · [No-code step monitor blog](https://newrelic.com/blog/how-to-relic/no-code-synthetics-monitoring) · [Step builder announcement](https://newrelic.com/blog/how-to-relic/better-synthetic-monitoring) · [Scripted browser intro](https://docs.newrelic.com/docs/synthetics/synthetic-monitoring/scripting-monitors/introduction-scripted-browser-monitors/) · [Chrome 100 scripted reference](https://docs.newrelic.com/docs/synthetics/synthetic-monitoring/scripting-monitors/synthetic-scripted-browser-reference-monitor-versions-chrome-100/) · [Runtime EOL notice](https://docs.newrelic.com/eol/2024/04/eol-04-22-24/) · [Runtime upgrade UI](https://docs.newrelic.com/docs/synthetics/synthetic-monitoring/using-monitors/runtime-upgrade-ui/) · [Install job manager](https://docs.newrelic.com/docs/synthetics/synthetic-monitoring/private-locations/install-job-manager/) · [Job manager config/sizing](https://docs.newrelic.com/docs/synthetics/synthetic-monitoring/private-locations/job-manager-configuration/) · [CPM→SJM transition](https://docs.newrelic.com/docs/synthetics/synthetic-monitoring/private-locations/job-manager-transition-guide/) · [Private location troubleshooting](https://docs.newrelic.com/docs/synthetics/synthetic-monitoring/private-locations/troubleshoot-private-locations/) · [Secure credentials](https://docs.newrelic.com/docs/synthetics/synthetic-monitoring/using-monitors/store-secure-credentials-scripted-browsers-api-tests/) · [View monitor results](https://docs.newrelic.com/docs/synthetics/synthetic-monitoring/using-monitors/view-simple-scripted-monitor-results/) · [SLA report](https://docs.newrelic.com/docs/synthetics/synthetic-monitoring/pages/synthetic-monitoring-aggregate-monitor-metrics/) · [Synthetic alerts](https://docs.newrelic.com/docs/synthetics/synthetic-monitoring/using-monitors/alerts-synthetic-monitoring/) · [Monitor downtimes](https://docs.newrelic.com/docs/synthetics/synthetic-monitoring/using-monitors/monitor-downtimes-disable-monitoring-during-scheduled-maintenance-times/) · [Synthetics Recorder extension blog](https://newrelic.com/blog/dem/efficiently-generate-synthetic-monitors-with-the-synthetics-recorder-chrome-extension) · [Checkly vs New Relic](https://www.checklyhq.com/blog/new-relic-vs-checkly/) · [New Relic pricing analysis](https://middleware.io/blog/new-relic-pricing/) · [G2 reviews](https://www.g2.com/products/new-relic/reviews)
