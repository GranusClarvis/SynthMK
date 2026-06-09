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
 * an ordered `steps` list using only actions the runner dispatch table accepts.
 *
 * Credential handling (v0.3.0): the content script NEVER ships a typed
 * password — it substitutes a `{{ secret.<field> }}` reference and marks the
 * step `sensitive: true`. This serializer just preserves those fields.
 */
(function (global) {
  'use strict';

  // Actions the runner understands (runner.py dispatch table). The recorder
  // only ever emits these; anything else is a bug we want the validator to catch.
  var KNOWN_ACTIONS = [
    'open_url',
    'click',
    'fill',
    'press',
    'select_option',
    'hover',
    'scroll_into_view',
    'wait_ms',
    'wait_for_element',
    'wait_for_url',
    'check_visible_text',
    'check_title',
    'check_url',
    'check_element_count',
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
      case 'hover':
      case 'scroll_into_view':
        lines.push('    selector: ' + yamlScalar(step.selector));
        break;
      case 'fill':
        lines.push('    selector: ' + yamlScalar(step.selector));
        lines.push('    value: ' + yamlScalar(step.value));
        if (step.sensitive) lines.push('    sensitive: true');
        break;
      case 'press':
        if (step.selector) lines.push('    selector: ' + yamlScalar(step.selector));
        lines.push('    key: ' + yamlScalar(step.key));
        break;
      case 'select_option':
        lines.push('    selector: ' + yamlScalar(step.selector));
        lines.push('    value: ' + yamlScalar(step.value));
        break;
      case 'wait_ms':
        lines.push('    ms: ' + parseInt(step.ms, 10));
        break;
      case 'wait_for_element':
        lines.push('    selector: ' + yamlScalar(step.selector));
        if (step.timeout_ms) lines.push('    timeout_ms: ' + parseInt(step.timeout_ms, 10));
        break;
      case 'wait_for_url':
      case 'check_title':
      case 'check_url':
        lines.push('    contains: ' + yamlScalar(step.contains));
        break;
      case 'check_visible_text':
        lines.push('    text: ' + yamlScalar(step.text));
        break;
      case 'check_element_count':
        lines.push('    selector: ' + yamlScalar(step.selector));
        lines.push('    min: ' + parseInt(step.min || 1, 10));
        break;
      default:
        // Unknown action — emit a comment so a human notices, never silently drop.
        lines.push('    # UNKNOWN ACTION (not runner-compatible): ' + step.action);
    }
    if (step.optional) lines.push('    optional: true');
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
      '# committing. Password fields were exported as {{ secret.<name> }} refs —',
      '# add the real values to the runner node\'s secrets file (chmod 600), see',
      '# docs/flow-schema.md.',
      'name: ' + yamlScalar(name),
    ];
    if (startUrl) head.push('start_url: ' + yamlScalar(startUrl));
    head.push('timeout_ms: ' + (parseInt(meta.timeout_ms, 10) || 30000));
    head.push('warn_ms: ' + (parseInt(meta.warn_ms, 10) || 3000));
    head.push('crit_ms: ' + (parseInt(meta.crit_ms, 10) || 7000));
    head.push('browser: ' + (meta.browser || 'chrome'));
    head.push('screenshot_on_failure: ' + (meta.screenshot_on_failure === false ? 'false' : 'true'));
    head.push('steps:');

    var body = steps.map(stepToYaml);
    return head.concat(body).join('\n') + '\n';
  }

  // One-line human description of a step for the popup's live step list.
  function stepLabel(step) {
    switch (step.action) {
      case 'open_url': return 'Open ' + step.url;
      case 'click': return 'Click ' + step.selector;
      case 'fill':
        return step.sensitive
          ? 'Type secret into ' + step.selector
          : 'Type "' + step.value + '" into ' + step.selector;
      case 'press': return 'Press ' + step.key + (step.selector ? ' in ' + step.selector : '');
      case 'select_option': return 'Select "' + step.value + '" in ' + step.selector;
      case 'hover': return 'Hover ' + step.selector;
      case 'scroll_into_view': return 'Scroll to ' + step.selector;
      case 'wait_ms': return 'Wait ' + step.ms + 'ms';
      case 'wait_for_element': return 'Wait for ' + step.selector;
      case 'wait_for_url': return 'Wait for URL ~ "' + step.contains + '"';
      case 'check_visible_text': return 'Assert text "' + step.text + '"';
      case 'check_title': return 'Assert title ~ "' + step.contains + '"';
      case 'check_url': return 'Assert URL ~ "' + step.contains + '"';
      case 'check_element_count':
        return 'Assert ≥' + (step.min || 1) + ' × ' + step.selector;
      default: return step.action;
    }
  }

  global.SynthMKExport = {
    KNOWN_ACTIONS: KNOWN_ACTIONS,
    yamlScalar: yamlScalar,
    stepToYaml: stepToYaml,
    stepsToYaml: stepsToYaml,
    stepLabel: stepLabel,
  };

  // CommonJS export so a node test can require() it directly.
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = global.SynthMKExport;
  }
})(typeof window !== 'undefined' ? window : globalThis);
