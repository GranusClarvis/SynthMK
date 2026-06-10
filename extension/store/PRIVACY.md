# SynthMK Recorder privacy policy

Last updated: 2026-06-10. Applies to the SynthMK Recorder browser extension for
Chrome, Edge and Firefox. Also published at
https://granusclarvis.github.io/SynthMK-Web/privacy-extension.html

## The short version

SynthMK Recorder collects nothing. It has no telemetry, no analytics, no accounts,
and it makes no network requests of any kind. Everything it records stays on your
machine until you export it yourself as a local file.

## What the extension does

While you are recording (and only then), the extension captures your interactions
with the page you chose: clicks, text you type into non-password fields, dropdown
selections, Enter presses, and the URLs the recorded tab navigates to. These steps
are stored in the extension's local storage in your browser so a recording survives
page navigations. When you export, the steps are turned into a YAML text file and
saved through your browser's normal download mechanism, or copied to your
clipboard if you press Copy.

## What never happens

* No data leaves your browser. The extension contains no network code: no fetch,
  no XMLHttpRequest, no WebSocket, no analytics SDK, no error reporting.
* No remote code is loaded. Every script ships inside the extension package.
* Passwords are never recorded. Typing into a password field stores a placeholder
  reference of the form {{ secret.<field-name> }} instead of the value, and marks
  the step as sensitive. The actual password exists only on the page you typed it
  into.
* Nothing is collected while you are not recording. The content script registers
  no page event listeners until you press Start, and removes them when you press
  Stop.
* Nothing is sold, shared or transferred to anyone, because nothing is collected.

## Data storage and deletion

Recordings and popup settings (service name, thresholds, screenshot toggle) live
in the browser's local extension storage on your device. Press Clear in the popup
to delete the current recording, or uninstall the extension to remove everything
it ever stored.

## Permissions, in plain language

* Access to sites: needed so the recorder can capture clicks and fills on
  whichever site you choose to record. It is passive until you press Start.
* Tabs: needed to follow the recorded tab across page navigations and record them
  as steps.
* Storage: needed to keep the in-progress recording on your machine.
* Downloads: needed to save the exported YAML file locally.

## Contact

Questions or concerns: open an issue at
https://github.com/GranusClarvis/SynthMK/issues
