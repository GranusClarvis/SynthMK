# SynthMK Recorder: store listing copy

Verified against the actual code on 2026-06-10 (manifest.json, manifest.firefox.json,
background.js, content.js, popup.js, recorder_export.js, popup.html). Every claim
below is checkable in those files. The extension makes zero network requests: there
is no fetch, no XMLHttpRequest, no WebSocket, and no remotely loaded script anywhere
in the package.

---

## Chrome Web Store

### Name

SynthMK Recorder

### Summary (132 chars max; this is 129)

Record browser journeys and export SynthMK YAML synthetic checks for Checkmk. Passwords become secret references, never recorded.

### Detailed description

SynthMK Recorder turns a manual click-through of your web application into a
synthetic monitoring check for Checkmk.

Press Start, perform the journey once like a real user, press Stop. Every click,
text entry, dropdown selection, Enter press and page navigation lands in a live
step list inside the popup. Edit the list on the spot: delete a mis-click, insert
assertions (visible text, title contains, URL contains), and set WARN and CRIT
response-time thresholds. Then export the journey as a short, readable YAML flow
file that the open-source SynthMK runner executes on a schedule and reports into
Checkmk as a normal service.

What it records:

* Navigations as open_url steps
* Clicks with a stable CSS selector (data-testid, stable id, unique name, unique class combination, then a positional fallback)
* Text input as fill steps, debounced so you get the final value, not keystrokes
* Dropdown changes as select_option steps
* Enter presses as press steps
* Assertions you add manually from the popup

Credential hygiene, by construction:

Typing into a password field NEVER records the typed value. The recorder
substitutes a {{ secret.<field> }} reference and marks the step sensitive. You add
the real credential later, on the monitoring node, in a root-readable secrets file.
The password does not enter the recording, the export, or extension storage.

Privacy, by construction:

* No telemetry, no analytics, no accounts
* The extension performs zero network requests of its own
* The recording lives in the extension's local storage on your machine only
* Export is a local file download (or copy to clipboard); nothing is uploaded
* Privacy policy: https://granusclarvis.github.io/SynthMK-Web/privacy-extension.html

SynthMK Recorder is one part of SynthMK, an MIT-licensed, self-hosted synthetic
monitoring addon for Checkmk. This extension is fully usable without any account
or service: the YAML it produces is plain text you can read, diff and review.

Source code: https://github.com/GranusClarvis/SynthMK (the extension ships exactly
as it is in the repository; nothing is minified or bundled).

### Category

Developer Tools

### Language

English

### Single-purpose statement

This extension has a single purpose: recording the user's interactions with a web
page (clicks, text entry, selections, navigations) and exporting them as a SynthMK
YAML synthetic-check definition for Checkmk. It has no other functionality.

### Permission justifications (one per permission)

* activeTab: When the user presses Start in the popup, the extension records the
  tab the user is currently on. activeTab scopes that user-initiated recording
  intent to the active tab (popup.js queries the active tab and passes its id to
  the background worker, which records only that tab).

* tabs: The background worker must follow the recorded tab across navigations.
  It listens to tabs.onUpdated and reads the tab URL to record open_url steps,
  and it uses tabs.get and tabs.sendMessage to start and stop the content-script
  recorder in that one tab (background.js recordNavigation and START/STOP
  handlers). Tab URLs are stored only in the local step list; they are never
  transmitted anywhere.

* storage: chrome.storage.local persists the in-progress recording
  (synthmk_state) so a Manifest V3 service-worker restart or a page navigation
  does not lose the session, and persists the popup's check settings
  (synthmk_meta: service name, thresholds, screenshot toggle). All storage is
  local; the sync storage area is not used.

* downloads: The Download .yaml button saves the exported flow as a local file
  via chrome.downloads.download from a Blob URL (popup.js). This is the product's
  output path: a file on the user's machine. No data leaves the browser.

* Host permission <all_urls> (also used by the content script match pattern):
  The recorder must be able to capture clicks and form fills on whatever site the
  operator chooses to monitor. SynthMK is used against internal applications
  (intranet portals, admin consoles, self-hosted tools) whose URLs cannot be
  enumerated in advance, so a narrower match list is impossible. The injected
  content script is inert until the user presses Start: it registers no page
  event listeners until it receives RECORDING_STARTED, it captures nothing while
  idle, and it sends data only to the extension's own background worker, never to
  any server.

* Remote code: none. All JavaScript is packaged in the extension; there is no
  remotely hosted code, no eval of fetched strings, and no custom
  content_security_policy.

### Privacy tab answers (CWS data-usage disclosures)

* Does the extension collect or use any of the listed data categories
  (personally identifiable information, health, financial, authentication,
  personal communications, location, web history, user activity, website
  content)? Answer NO to every category. Rationale: recorded interactions and
  URLs are processed locally and stored only in chrome.storage.local on the
  user's machine at the user's explicit request; nothing is transmitted to the
  developer or to any third party. Passwords are explicitly excluded from
  capture.
* I do not sell or transfer user data to third parties, outside of the approved
  use cases: CERTIFY (true; there is no transfer at all).
* I do not use or transfer user data for purposes that are unrelated to my
  item's single purpose: CERTIFY.
* I do not use or transfer user data to determine creditworthiness or for
  lending purposes: CERTIFY.
* Privacy policy URL: https://granusclarvis.github.io/SynthMK-Web/privacy-extension.html

---

## Firefox Add-ons (AMO)

### Name

SynthMK Recorder

### Summary (250 chars max; this is 219)

Record a browser journey once and export it as a SynthMK YAML synthetic check for
Checkmk. Clicks, fills, assertions and thresholds, edited live in the popup.
Passwords are exported as secret references, never recorded.

(Single line when pasted into AMO; the wrap above is for this file only.)

### Description

Use the detailed description from the Chrome Web Store section above, unchanged,
with one Firefox-specific addition at the end:

Firefox note: Manifest V3 extensions in Firefox do not get access to all sites
automatically. After installing, open the extension's permission settings (or use
the prompt) and grant access to the sites you want to record, or grant Access your
data for all websites if you record many internal applications.

### Tags / categories

Category: Web Development (closest AMO category to developer tools).
Tags: monitoring, checkmk, synthetic-monitoring, testing, recorder, automation, yaml, devops.

### License

MIT (same as the SynthMK repository).

### Does this extension collect data?

No. The extension makes no network requests, contains no telemetry or analytics,
and stores recordings only in local extension storage. Export is a local file
download initiated by the user. Password values are never captured; the recorder
substitutes {{ secret.<name> }} references. If the AMO submission flow (or the
validator) asks for the data_collection_permissions manifest key introduced by
Firefox's data-consent feature, declare "none" (no data collected).

### Source code submission note

AMO reviewers may request source code when an extension ships minified or
generated files. SynthMK Recorder requires no such submission caveats: the
packaged files ARE the source. Nothing is minified, transpiled or bundled; there
are no build-time transformations, only zip packaging.

* Repository: https://github.com/GranusClarvis/SynthMK (extension/ directory)
* Exact build instructions: `bash extension/build.sh` from the repository root.
  This produces dist/synthmk-recorder-chrome-<version>.zip and
  dist/synthmk-recorder-firefox-<version>.zip. The Firefox zip is identical to
  the repository files except that manifest.firefox.json is written into the
  archive as manifest.json.
* Build environment: any POSIX shell with python3 (the script only zips files).
* To verify reproducibility: unzip the store package and diff it against the
  extension/ directory of the tagged release.
