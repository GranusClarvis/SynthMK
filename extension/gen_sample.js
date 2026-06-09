/*
 * Drives the REAL recorder serializer (recorder_export.js) over a representative
 * recorded session and prints the resulting SynthMK flow YAML to stdout.
 *
 * Used by validate_export.sh to prove the exporter emits runner-compatible YAML
 * without a browser. The session mirrors what the content script captures on a
 * login journey: navigate, fill username, fill PASSWORD (exported as a
 * {{ secret.* }} reference + sensitive flag, never the typed value), press
 * Enter, wait, select a report period, then assertions.
 */
'use strict';

var SynthMKExport = require('./recorder_export.js');

var steps = [
  { action: 'open_url', url: '{{ SYNTHMK_DEMO_URL }}' },
  { action: 'fill', selector: '#username', value: '{{ secret.portal_user }}' },
  { action: 'fill', selector: '#password', value: '{{ secret.portal_password }}', sensitive: true },
  { action: 'press', selector: '#password', key: 'Enter' },
  { action: 'wait_for_element', selector: "[data-testid=\"dashboard\"]", timeout_ms: 5000 },
  { action: 'select_option', selector: '#report-period', value: 'week' },
  { action: 'check_element_count', selector: 'tr.order-row', min: 3 },
  { action: 'check_visible_text', text: 'Account Overview' },
  { action: 'check_title', contains: 'SynthMK Demo' },
  { action: 'check_url', contains: 'dashboard' },
];

process.stdout.write(SynthMKExport.stepsToYaml(
  { name: 'Recorded Demo Flow', warn_ms: 3000, crit_ms: 7000 }, steps));
