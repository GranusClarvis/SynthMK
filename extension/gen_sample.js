/*
 * Drives the REAL recorder serializer (recorder_export.js) over a representative
 * recorded session and prints the resulting SynthMK flow YAML to stdout.
 *
 * Used by validate_export.sh to prove the exporter emits runner-compatible YAML
 * without a browser. The session below mirrors what the content script would
 * capture on the bundled demo page (flows/demo/index.html): navigate, fill the
 * login form, click submit, then two manual assertions.
 */
'use strict';

var SynthMKExport = require('./recorder_export.js');

var steps = [
  { action: 'open_url', url: '{{ SYNTHMK_DEMO_URL }}' },
  { action: 'fill', selector: '#username', value: '{{ DEMO_USER }}' },
  { action: 'fill', selector: '#password', value: '{{ DEMO_PASS }}' },
  { action: 'click', selector: '#submit' },
  { action: 'wait_for_element', selector: "[data-testid=\"dashboard\"]", timeout_ms: 5000 },
  { action: 'check_visible_text', text: 'Account Overview' },
  { action: 'check_title', contains: 'SynthMK Demo' },
];

process.stdout.write(SynthMKExport.stepsToYaml({ name: 'Recorded Demo Flow' }, steps));
