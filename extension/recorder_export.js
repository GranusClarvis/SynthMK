/*
 * SynthMK recorder → flow YAML serializer.
 *
 * Pure, dependency-free. Loaded as a plain script (no ES modules) so it works
 * both as a content-script include and under `node --check` / a node test.
 * It attaches `SynthMKExport` to the global so popup.js and the node validator
 * can both call it.
 *
 * Output matches docs/flow-schema.md exactly: a top-level
 * name/start_url/timeout_ms/warn_ms/crit_ms/browser/screenshot_on_failure plus
 * an ordered `steps` list of open_url/click/fill/wait_for_element/
 * check_visible_text/check_title/check_url actions — the same surface the
 * existing runner.py accepts.
 */
(function (global) {
  'use strict';

  // Actions the runner understands (runner.py dispatch table). The recorder
  // only ever emits these; anything else is a bug we want the validator to catch.
  var KNOWN_ACTIONS = [
    'open_url',
    'click',
    'fill',
    'wait_for_element',
    'check_visible_text',
    'check_title',
    'check_url',
  ];

  // Double-quote a YAML scalar safely (escape backslash and quote, collapse
  // newlines). Keeps the emitted YAML on one line per value and parseable by
  // PyYAML's safe_load.
  function yamlScalar(value) {
    var s = String(value == null ? '' : value);
    s = s.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/[\r\n]+/g, ' ');
    return '"' + s + '"';
  }

  // Render a single recorded step into YAML lines under the `steps:` list.
  function stepToYaml(step) {
    var lines = ['  - action: ' + step.action];
    switch (step.action) {
      case 'open_url':
        lines.push('    url: ' + yamlScalar(step.url));
        break;
      case 'click':
        lines.push('    selector: ' + yamlScalar(step.selector));
        break;
      case 'fill':
        lines.push('    selector: ' + yamlScalar(step.selector));
        lines.push('    value: ' + yamlScalar(step.value));
        break;
      case 'wait_for_element':
        lines.push('    selector: ' + yamlScalar(step.selector));
        if (step.timeout_ms) lines.push('    timeout_ms: ' + parseInt(step.timeout_ms, 10));
        break;
      case 'check_visible_text':
        lines.push('    text: ' + yamlScalar(step.text));
        break;
      case 'check_title':
      case 'check_url':
        lines.push('    contains: ' + yamlScalar(step.contains));
        break;
      default:
        // Unknown action — emit a comment so a human notices, never silently drop.
        lines.push('    # UNKNOWN ACTION (not runner-compatible): ' + step.action);
    }
    return lines.join('\n');
  }

  // Build the full flow YAML document from recorded metadata + steps.
  function stepsToYaml(meta, steps) {
    meta = meta || {};
    steps = steps || [];
    var name = meta.name || 'Recorded Flow';
    var startUrl = meta.start_url || (steps[0] && steps[0].action === 'open_url' ? steps[0].url : '');

    var head = [
      '# Recorded by the SynthMK Chrome recorder. Review selectors/values before',
      '# committing; templatize secrets as {{ ENV_NAME }} (see docs/flow-schema.md).',
      'name: ' + yamlScalar(name),
    ];
    if (startUrl) head.push('start_url: ' + yamlScalar(startUrl));
    head.push('timeout_ms: ' + (meta.timeout_ms || 30000));
    head.push('warn_ms: ' + (meta.warn_ms || 3000));
    head.push('crit_ms: ' + (meta.crit_ms || 7000));
    head.push('browser: ' + (meta.browser || 'chrome'));
    head.push('screenshot_on_failure: ' + (meta.screenshot_on_failure === false ? 'false' : 'true'));
    head.push('steps:');

    var body = steps.map(stepToYaml);
    return head.concat(body).join('\n') + '\n';
  }

  global.SynthMKExport = {
    KNOWN_ACTIONS: KNOWN_ACTIONS,
    yamlScalar: yamlScalar,
    stepToYaml: stepToYaml,
    stepsToYaml: stepsToYaml,
  };

  // CommonJS export so a node test can require() it directly.
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = global.SynthMKExport;
  }
})(typeof window !== 'undefined' ? window : globalThis);
