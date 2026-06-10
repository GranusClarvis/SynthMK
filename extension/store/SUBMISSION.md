# SynthMK Recorder: store submission guide (operator runbook)

Step-by-step instructions for publishing the recorder to the Chrome Web Store,
Firefox Add-ons (AMO), and Microsoft Edge Add-ons. Listing copy lives in
LISTING.md, the privacy policy in PRIVACY.md (published at
https://granusclarvis.github.io/SynthMK-Web/privacy-extension.html).

Steps marked [OWNER] need the developer account credentials and payment details;
only the account owner can do them. Everything else can be prepared by anyone.

## 0. Build the packages

```
cd /home/agent/agents/synthmk/workspace
bash extension/build.sh
```

Outputs (version read from manifest.json, currently 0.6.0):

* dist/synthmk-recorder-chrome-0.6.0.zip  (Chrome Web Store AND Edge Add-ons)
* dist/synthmk-recorder-firefox-0.6.0.zip (AMO; contains manifest.firefox.json renamed to manifest.json)

Sanity check before any upload: unzip each package to a temp dir and load it as
an unpacked/temporary extension (chrome://extensions with Developer mode, or
about:debugging#/runtime/this-firefox), record a short journey, export, confirm
the YAML.

## 1. Screenshots (shared across all three stores)

Requirements (Chrome Web Store, the strictest): 1280x800 or 640x400, PNG or JPEG,
no alpha, at least 1, up to 5. Reuse the same images for AMO and Edge.

Suggested set:

1. The popup mid-recording with a live step list including a secret-reference
   password step (the website already has assets/recorder-popup.png; re-capture
   at 1280x800 with the page behind it).
2. The exported YAML preview in the popup.
3. The resulting service in Checkmk (ties the story together).

Optional: small promo tile 440x280 PNG for CWS (improves listing placement; not
strictly required to publish).

## 2. Chrome Web Store

1. [OWNER] Developer account: https://chrome.google.com/webstore/devconsole.
   One-time 5 USD registration fee on first use. Use a group/publisher email you
   are happy to show publicly.
2. [OWNER] Click New item, upload dist/synthmk-recorder-chrome-0.6.0.zip.
3. Store listing tab: paste name, summary, detailed description, category
   (Developer Tools), language (English) from LISTING.md. Upload screenshots and
   icon (the 128px icon is taken from the zip automatically; the listing icon
   field also accepts extension/icons/icon128.png).
4. Privacy practices tab (CWS rejects items with this tab incomplete):
   * Single purpose: paste the single-purpose statement from LISTING.md.
   * Permission justifications: one box per permission (activeTab, tabs, storage,
     downloads, host permission <all_urls>); paste from LISTING.md.
   * Remote code: select No, I am not using remote code.
   * Data usage: check NO collection for every category, certify the three
     disclosures (no sale/transfer, no unrelated use, no creditworthiness use).
   * Privacy policy URL:
     https://granusclarvis.github.io/SynthMK-Web/privacy-extension.html
5. Distribution tab: Public, all regions (default).
6. [OWNER] Submit for review.
7. Review timeline: typically under 24 hours for most items, but allow up to a
   few days; <all_urls> host permissions route the item to in-depth review, which
   can take 1 to 3 weeks on the slow end. Do not resubmit while a review is
   pending. The permission justifications in LISTING.md exist exactly for this
   review.
8. After approval the item goes live automatically (default publish option).
   Note the item ID and add the store URL to the website download section.

Updates: bump "version" in BOTH manifests, rebuild, upload the new zip on the
existing item, re-submit. The privacy tab answers persist between versions.

## 3. Firefox Add-ons (AMO)

1. [OWNER] Firefox account at https://addons.mozilla.org, then enable the
   developer hub (no fee).
2. [OWNER] https://addons.mozilla.org/developers/ then Submit a New Add-on.
3. Distribution choice: select On this site (listed). Listed means AMO hosts,
   signs and updates the add-on; users find it on addons.mozilla.org. Self-hosted
   (unlisted) only gets you a signed XPI to distribute yourself; choose that only
   for a private/enterprise rollout. We want listed.
4. Upload dist/synthmk-recorder-firefox-0.6.0.zip. The validator runs
   immediately; warnings are usually fine, errors block.
   * If the validator requires the data_collection_permissions key (Firefox
     data-consent rollout for new submissions), add to manifest.firefox.json
     under browser_specific_settings.gecko:
     "data_collection_permissions": { "required": ["none"] }
     then rebuild and re-upload. Declare "none": this extension collects nothing.
5. Source code step: when asked Do you need to submit source code, answer No.
   The package is unminified source; there is no build-time transformation. Put
   this in the reviewer notes field:
   "All files are unminified source, identical to
   https://github.com/GranusClarvis/SynthMK (extension/ directory). Build is zip
   packaging only: bash extension/build.sh. No bundler, no transpiler, no remote
   code, no network requests."
6. Listing details: paste name, summary, description, category (Web Development),
   tags and license (MIT) from LISTING.md. Privacy policy: paste the PRIVACY.md
   text into AMO's privacy-policy field (AMO displays it inline) and also link
   the website page.
7. Data collection question: No data collected (see LISTING.md AMO section).
8. [OWNER] Submit. New listed add-ons get a human review; typical turnaround is
   a day to about a week. Automated signing may make the add-on available sooner
   with review happening post-publication.
9. After approval, note the AMO listing URL for the website.

Firefox-specific user note (also in the listing description): Firefox MV3 does
not grant host permissions at install time. Users must grant site access from
the extension's Permissions settings or the per-site prompt before recording.

## 4. Microsoft Edge Add-ons

1. [OWNER] Register at https://partner.microsoft.com/dashboard/microsoftedge
   (free, no fee since 2021; a Microsoft account is required).
2. [OWNER] Create a new extension submission and upload the SAME chrome package:
   dist/synthmk-recorder-chrome-0.6.0.zip. Edge installs Chromium MV3 packages
   unchanged; no Edge-specific manifest is needed.
3. Fill listing: reuse the CWS name, summary, description and screenshots.
   Category: Developer tools. Privacy policy URL: same website page.
4. Answer the data-collection questionnaire: no data collected or transmitted.
5. [OWNER] Submit. Edge review typically takes up to 7 business days.

## 5. Post-publication checklist

* Add the three store URLs to the website (index download section and/or footer).
* Keep the GitHub release zips in place; the footer already links them for users
  who prefer side-loading.
* For every future release: bump version in manifest.json AND
  manifest.firefox.json (keep them identical), rebuild, upload to all three
  stores, and update CHANGELOG.md.
