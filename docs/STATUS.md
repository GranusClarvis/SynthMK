# SynthMK: Status, Test Evidence, Open Work & Security

**As of:** 2026-06-10 · **Version:** 0.7.0 · **Branch:** `main`
**Repo:** `git@github.com:GranusClarvis/SynthMK.git` ·
**Website:** https://granusclarvis.github.io/SynthMK-Web/

## -3. What was done in v0.7.0 (cert + trace + store + soundness), evidence 2026-06-10

New: `type: cert` TLS-expiry checks (cert_days_left metric; internal/self-
signed CA fallback), `trace_on_failure` Playwright trace.zip artifacts
(tokenized by the shot server), and the browser-extension store submission
package (CWS + AMO listing, privacy policy, website privacy page).

Fixes from an adversarial soundness review (two reviewers over engine and node
services; false alarms discarded, accepted-by-design items noted):

| Fix | What it prevents |
|---|---|
| Selector ladder returns remaining budget | a slow ladder granting the action a second full timeout (step exceeding its budget) |
| Retry resets secret/var state | a retry reusing a stale `{{ var.uuid }}` or masking the real failure with a prior secret |
| include/script confined to flow tree (symlink-aware) | `../../etc` escape or a planted symlink loading foreign code/steps |
| DevTools importer caps candidates (8/step, 200 scan) | a hostile recording.json exhausting memory/CPU |
| Entrypoint graceful shutdown (no exec; trap + wait) | truncated spool or audit lines when the container is stopped/killed |
| Builder SSRF blocklist | an admin screenshotting cloud-metadata/loopback endpoints from the node |
| Login token redacted from logs; audit tail-read | the token leaking into container logs; loading a huge audit file into memory |

Live verification on the 0.7.0 image: 17 concurrent lab checks green
(incl. the cert check, visible as a Checkmk service with cert_days_left, and a
trace-on-failure demo whose trace.zip downloads from the shot server with its
token and 403s without). `docker stop` confirmed to fire the entrypoint's
shutdown handler. All three authoring paths e2e green. Contract 145, admin 40.

## -2. What was done in v0.6.0 (verified end to end + hardening), evidence 2026-06-10

The whole product was exercised LIVE against a full lab stack (Checkmk Raw
2.3 + runner node + demo site), all on the freshly built 0.6.0 image:

| Proof | Result |
|---|---|
| 15 concurrent distinct-shape checks, 40+ min soak | **15/15 green**, verified in the spool, at the agent, AND as discovered Checkmk services on 3 hosts. Shapes: Checkmk-UI login journey (piggybacked to host `cmk`), example.com to IANA + Wikipedia public journeys, chromium/firefox/webkit engines, script flow, TOTP entry, ladders + shared include, checkbox/attribute forms, per-run unique values, negative text, evidence capture |
| Recorder e2e (extension) | `extension/test_e2e.py` green in the runner image |
| DevTools import e2e | `runner/test_import_e2e.py`: recording JSON -> import CLI -> REAL browser run passes; recorded password plaintext discarded |
| Step builder UI e2e | `runner-node/test_dashboard_e2e.py` 21/21, CSP-safe |
| Scheduler stress | 150 flows sustained + deliberate overload, 8/8 |
| Real-browser scale | 60 flows / 240s soak: 60/60 fresh OK, 0 overdue, agent poll 559ms, container 0.32% CPU / 21 MiB between runs |
| Real-MKP install proof | `scripts/ci_real_mkp.sh`: 0.6.0 artifact `mkp add` + `mkp enable` on an EPHEMERAL Checkmk site, payload listed |
| Contract suites | runner 128, importer 25, admin HTTP 34 (incl. TLS, CSP, lockout, import endpoint), all in `make validate` |

Hardening added in 0.6.0: `max_attempts` retries (UNKNOWN never retried),
dashboard HTTPS (`SYNTHMK_ADMIN_TLS_CERT/KEY`), failed-login lockout
(5 fails -> 60s, audited), CSP + X-Frame-Options, dashboard
"Import recording" upload, builder `bypass_csp` (authoring only; monitoring
pages keep the site's real policy). Service output and docs carry no em
dashes (operator request: copy must not look generated).

## -1. What was done in v0.5.0 (authoring & operations), evidence 2026-06-10

Authoring (four paths, see CHANGELOG for detail): selector fallback ladders,
visual **step builder** on the dashboard (live page preview, click-to-pick,
every step executed live before it's added), **Chrome DevTools Recorder
import** (no extension needed; recorded passwords discarded → secret refs),
**script flows** (`run(page, api)`, trust-gated `SYNTHMK_ALLOW_SCRIPTS=1`),
sub-flow `include`, `{{ totp.* }}` MFA, `{{ var.* }}` builtins, 3 new
assertions. Operations: pause/resume, tags, version history + lint-gated
rollback, JSONL audit trail, read-only viewer token, multi-node special agent.

**Test evidence (all green 2026-06-10):**

| Suite | Checks | How run |
|---|---|---|
| Runner contract (`runner/test_contract.py`) | 120 | `make validate`, browser-free |
| DevTools importer (`runner/test_import_devtools.py`) | 25 | `make validate` |
| Dashboard HTTP contract (`runner-node/test_admin_contract.py`) | 26 | `make validate`, real server on loopback |
| Dashboard **UI e2e** (`runner-node/test_dashboard_e2e.py`) | 21 | real Chromium in the runner image: sign-in → builder point-and-click → tested steps → failing step rejected → export → lint & save → table → pause |
| Special agent (`checkmk/special/test_agent_synthmk.py`) | n/a | two fake nodes → one host |
| Scheduler **stress** (`runner-node/stress_test.py`) | 8 | 150 flows sustained (4× the documented envelope), hot-reload + run-now under load, overload phase must alarm |
| Full CI (`scripts/ci.sh`) | all gates | validate + syntax + determinism + payload + secret scan + versions |

**Stress finding worth knowing:** a saturated pool round-robins fairly, so no
single flow ever trips the per-flow overdue alarm while every service quietly
runs at a multiple of its configured interval. v0.5.0 adds a **throughput
watchdog** to the scheduler self-service (achieved vs demanded runs/min over
a 5-minute window; WARN below 80%) so saturation is loud, not silent.

## 0. What was done in v0.4.0 (native plugin, dashboard, browsers, website)

- **Native Checkmk plugin** (agent-based v2 + rulesets v1 + graphing v1, in the
  MKP): JSON `<<<synthmk>>>` section → real services with unit-aware duration
  metric (s) incl. warn/crit bands, per-step metrics, perf-o-meter, step
  breakdown + screenshot link in details. **Verified live**: `cmk -nvp` shows
  `synthmk_duration=0.239;4;10`; a Setup rule (REST-created) overrode flow
  thresholds and flipped the service CRIT; ruleset visible as
  "SynthMK synthetic browser checks"; MKP 0.4.0 (17 files) enabled on the site.
- **Node management dashboard** (:9181, token + CSRF): live check table from
  the spool, run-now (verified: trigger → scheduler immediate run), flow editor
  that lints before saving (verified: bad action rejected with linter message,
  valid flow saved + auto-scheduled). Auth verified: 401 without/with wrong
  token, 401 on POST without the CSRF header.
- **Recorder packages** for Chrome/Edge + Firefox with icons (`extension/build.sh`);
  real-browser E2E re-verified after the manifest changes.
- **Screenshot links LAN fix**: `make lab-up` defaults the base URL to the
  host's LAN IP, so links in Checkmk now work from other machines.
- **Website**: SynthMK-Web repo on GitHub Pages, real lab screenshots.
- v0.3.0 tagged + released on GitHub with MKP + extension assets.

Below sections describe v0.3.0's foundation (all still true).

This is the living "where things stand" doc. Roadmap tags below mirror the Clarvis
evolution queue (`PROJECT:SYNTHMK`) and the repo `TASKS.md`.

---

## 1. What SynthMK is

Readable YAML browser flow → Playwright runner → native Checkmk **local-check**
service. Lightweight, Raw/CRE-friendly alternative to Checkmk's enterprise
Synthetic Monitoring (Robotmk / Robot Framework). One **runner node** hosted
inside the intranet runs many flows against internal-only sites and reports to
Checkmk; Checkmk is the UI, scheduler-of-record, and alerting engine. A Chrome
MV3 recorder turns clicks into flows. Positioning vs. the field:
[competitive-landscape.md](competitive-landscape.md).

---

## 2. What was done in v0.3.0 (enterprise hardening)

- **Secure credentials end to end**: `{{ secret.NAME }}` from a chmod-600
  node-local secrets file (loose perms refused up front), values redacted to
  `***` in all output, `sensitive: true` fills blank form fields before failure
  screenshots; recorder converts password fields to secret refs so typed values
  never leave the page.
- **Scale**: Python worker-pool scheduler (concurrency cap, stagger, overlap
  suppression, hard timeouts, hot reload, warmup lines under real service
  names) + `SynthMK Scheduler` self-monitoring service + capacity formula and a
  measured 60-flow scale test ([scaling.md](scaling.md)).
- **Node security**: token-authenticated screenshot server (HMAC per-file URLs,
  no listing/traversal), TLS agent transport via one-command registration
  (`register_agent.sh` + `SYNTHMK_AGENT_MODE=official`), browser/HTTP processes
  dropped to `pwuser`, hardened production compose (limits,
  no-new-privileges, healthcheck).
- **Flows**: `press`, `select_option`, `hover`, `scroll_into_view`, `wait_ms`,
  `wait_for_url`, `check_element_count`, `optional: true` (consent banners);
  per-step timing perfdata; Playwright errors → named-step CRIT + screenshot.
- **Examples**: Wikipedia multi-step journey (live-verified), Google template
  with documented bot-block reality, lab login→dashboard journey with secrets.
- **Recorder UX**: live editable step list, thresholds/name settings, secret
  hints, real-browser E2E; MV3 state race fixed (dropped-step bug).

## 3. What was tested (and the result)

All verified 2026-06-09 against **Checkmk Raw 2.3.0p48** in the LAN lab:

| Test | Result |
|---|---|
| `make ci` (browser/Docker-free contract) | ✅ green; see CI section in repo |
| Contract suite (`runner/test_contract.py`) | ✅ 55 checks: line format, per-step perfdata, secret load/refusal/redaction, lint lockstep for all 14 actions, optional steps |
| 10-step lab login journey (secrets, hover, select, count) | ✅ OK in 406 ms standalone; ✅ live OK as `Synthetic Portal Login` on piggyback host `intranet-demo` |
| Live CRIT → recovery cycle through Checkmk | ✅ broke the dashboard → `state=2`, message **redacted** (`'Signed in as ***'`), tokenized screenshot link in plugin output → restored → back to OK |
| Screenshot auth | ✅ link `?t=<hmac>` → HTTP 200; same URL without token → 403; traversal/listing/key-file → 404 |
| Sensitive-fill screenshot masking | ✅ captured PNG shows `•••` in both form fields |
| Secrets negative paths | ✅ 0644 file refused (UNKNOWN, "chmod 600"); missing secret name → UNKNOWN without value; assertion text never substitutes secrets |
| Warmup / discovery | ✅ node start publishes per-flow warmup lines under real service names; discovery `fix_all` lands all services incl. `SynthMK Scheduler` |
| **TLS agent transport** | ✅ `register_agent.sh` against the lab site (version-matched .deb download → install → register), `cmk-agent-ctl status` = pull-agent with site-CA cert, `cmk -d` over TLS returns spool sections incl. tokenized screenshot links |
| **Scale: 60 flows on one default node** | ✅ 5-min soak: 60/60 fresh OK, 0 stale/overdue/overlap-skips, ≈37 runs/min sustained (matches formula), slowest run 0.6 s, agent poll < 0.5 s, CPU 12–25 % of 4-core budget |
| Recorder real-browser E2E | ✅ extension loaded in Chromium, recorded the login journey: password → `{{ secret.password }}`+sensitive (typed value nowhere), Enter → press, select → select_option, popup list renders, export lints clean |
| Public internet journey | ✅ Wikipedia search flow live OK (807 ms, 7 steps). Google/DuckDuckGo: bot-blocked (reCAPTCHA / duck-CAPTCHA) from datacenter IP; documented as expected in `flows/google-search.yaml` |
| Real `.mkp` | ✅ rebuilt + installed for 0.3.0 (see §6 evidence note) |

### Not yet tested / assumptions
- Only Checkmk Raw 2.3; not 2.2/2.4, CEE/bakery, or distributed sites.
- Only Chromium. Firefox/Edge untested.
- TLS mode soaked minutes, not weeks; registration persistence across container
  recreation relies on the `/var/lib/cmk-agent` volume (documented, not soaked).
- Scale test used short intranet flows; long-journey saturation is computed
  (formula) not yet empirically swept.

---

## 4. Open work (mirrors queue `PROJECT:SYNTHMK`)

| Pri | Tag | Summary |
|---|---|---|
| P2 | `SYNTHMK_MULTINODE_SPECIAL_AGENT` | Multi-node "locations": special agent pulling several runner nodes from the Checkmk side. |
| P2 | `SYNTHMK_REAL_MKP_CI` | Docker-gated CI job that builds + installs the real `.mkp` against an ephemeral Checkmk container. |
| P3 | `SYNTHMK_CERT_AND_LINKS_CHECKS` | Cert-expiry + broken-links check types (cheap, loved; the New Relic lesson). |
| P3 | `SYNTHMK_TRACE_ARTIFACTS` | Playwright trace.zip on failure, served next to screenshots. |
| P3 | `SYNTHMK_MAX_ATTEMPTS` | Retry-before-CRIT with visible attempt count. |
| P3 | `SYNTHMK_FLOW_GROUPS` | Serialized flow groups + lint-time interval math. |

---

## 5. Security posture (v0.3.0)

v0.2's must-fix set is closed: **#1** screenshots after sensitive fills are
masked + values redacted; **#2** screenshot server requires per-file HMAC
tokens, no listing/traversal; **#3** TLS agent transport available and
verified (socat stays as the explicitly-labelled lab fallback; firewall 6556
to the Checkmk server if you use it); **#4** secrets in a permission-checked
0600 file with global output redaction (env `{{ }}` remains for non-secrets);
**#6** shipped compose carries mem/cpu limits + no-new-privileges; **#7**
browsers run as unprivileged `pwuser`.

Residual / operator duties:

| # | Severity | Item | Status |
|---|---|---|---|
| 1 | Medium | Chromium runs `--no-sandbox` inside the container (standard for Docker; privilege-dropped to pwuser). Point flows only at trusted sites; keep the image updated. | Accepted, documented |
| 2 | Medium | "Escape HTML codes in service output" must be Off for screenshot links; scope that rule to runner host(s) only (Werk #6058 XSS surface). | Documented, operator must scope |
| 3 | Low | socat lab transport is plaintext: lab/firewalled use only; production = `SYNTHMK_AGENT_MODE=official`. | Documented |
| 4 | Low | Lab hardcodes `synthmk-lab-admin` + lab-only demo credentials in-repo. Never reuse outside the lab. | Documented |
| 5 | Low | Supply chain: base image pinned by version, not digest; review MKP contents before distributing. | Partial |

---

## 6. Operational notes / gotchas

- **Clean lab cycle:** `make lab-down && make lab-up`. Don't bring the lab up
  mid-git-rewrite (stale bind mounts). Services are discoverable immediately
  now (warmup lines); the old "discover only after first run" gotcha is gone.
- **Secrets in the appliance:** mount your 600-mode file and set
  `SYNTHMK_SECRETS_FILE`; the entrypoint stages a runner-owned copy so host
  uid/ownership doesn't matter.
- **Screenshot links across the LAN:** set `SYNTHMK_SHOT_BASE_URL=http://<lan-ip>:9180`;
  links carry their own tokens.
- **TLS mode:** host must exist in Checkmk first; keep a volume on
  `/var/lib/cmk-agent`; `register_agent.sh` needs the agent receiver port
  (default 8000) reachable.
- **Real MKP** needs a running site: `make lab-up` then `make real-mkp`.
  Enabled package removal needs `mkp disable` before `mkp remove`.
- **Scale:** `bash scripts/scale_test.sh 60 300` reproduces the measured run;
  watch the `SynthMK Scheduler` service: overdue flows WARN on the node.
