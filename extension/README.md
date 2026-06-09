# SynthMK Recorder (browser extension)

Record a real browser journey — clicks, typing, dropdowns, Enter presses —
and export it as a SynthMK YAML flow ready for the runner node. The popup
shows a **live, editable step list** (delete mis-clicks, insert text/title/URL
assertions), check settings (service name, WARN/CRIT thresholds, screenshot
toggle), and one-click **Download .yaml**.

**Credential hygiene built in:** typing into a password field records
`{{ secret.<field> }}` with `sensitive: true` — the typed value never leaves
the page. Add the real value to the runner node's secrets file instead.

## Install

| Browser | How |
|---|---|
| **Chrome** | `chrome://extensions` → enable *Developer mode* → *Load unpacked* → this folder (or the unzipped `synthmk-recorder-chrome-<ver>.zip` from the GitHub release). |
| **Edge** | `edge://extensions` → *Developer mode* → *Load unpacked* → same package (Edge runs Chrome MV3 extensions unchanged). |
| **Firefox** | Build the Firefox package (`bash extension/build.sh`), then `about:debugging` → *This Firefox* → *Load Temporary Add-on* → pick `manifest.json` inside the unzipped `synthmk-recorder-firefox-<ver>.zip`. (Permanent install needs signing via addons.mozilla.org.) |

Store listings are planned; until then the release zips on
[GitHub Releases](https://github.com/GranusClarvis/SynthMK/releases) are the
distribution channel.

## Record a check in 60 seconds

1. Open the page where the journey starts, click the SynthMK icon → **● Start**.
2. Do the journey like a user (type, click, press Enter). Watch steps appear
   in the popup; hit ✕ on anything accidental.
3. Add assertions (*Visible text* / *Title contains* / *URL contains*) — at
   least one, so the check actually asserts something.
4. Set the service name + WARN/CRIT thresholds → **Download .yaml**.
5. Drop the file in the runner node's `flows/` + one `flows.conf` line — or
   paste it into the node's management dashboard (`http://<node>:9181`),
   which lints it before saving.

## Files

- `manifest.json` / `manifest.firefox.json` — MV3 manifests (Chrome/Edge, Firefox)
- `background.js` — recording state machine (serialized message queue)
- `content.js` — event capture + GOAT selector ladder (`data-testid` → stable id → unique name → class combo → nth-of-type)
- `recorder_export.js` — pure YAML serializer (shared with the validators)
- `popup.html` / `popup.js` — the UI
- `build.sh` — produces the per-browser zips into `dist/`
- `validate_export.sh` — browser-free contract check (runs in `make ci`)
- `test_e2e.py` — real-browser E2E: loads the extension in Chromium, records
  the lab login journey, asserts the export lints clean and the typed
  password appears nowhere
