/*
 * SynthMK Recorder — popup controller.
 *
 * Drives the background service worker (start/stop/clear/assert) and turns the
 * recorded step buffer into SynthMK flow YAML via the shared SynthMKExport
 * serializer (recorder_export.js).
 */
'use strict';

function send(message) {
  return new Promise(function (resolve) {
    chrome.runtime.sendMessage(message, function (resp) {
      void chrome.runtime.lastError;
      resolve(resp || {});
    });
  });
}

function activeTabId() {
  return new Promise(function (resolve) {
    chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
      resolve(tabs && tabs[0] ? tabs[0].id : null);
    });
  });
}

var els = {};
['state', 'count', 'start', 'stop', 'clear', 'assert-text', 'assert-title',
 'assert-url', 'export', 'copy', 'download', 'yaml'].forEach(function (id) {
  els[id] = document.getElementById(id);
});

function render(state) {
  if (!state) return;
  els.state.textContent = state.isRecording ? 'recording' : 'idle';
  els.count.textContent = state.stepCount != null ? state.stepCount : 0;
}

function refresh() {
  send({ type: 'GET_STATE' }).then(function (resp) { render(resp.state); });
}

els.start.addEventListener('click', function () {
  activeTabId().then(function (tabId) {
    send({ type: 'START', tabId: tabId }).then(function (resp) { render(resp.state); });
  });
});

els.stop.addEventListener('click', function () {
  send({ type: 'STOP' }).then(function (resp) { render(resp.state); });
});

els.clear.addEventListener('click', function () {
  send({ type: 'CLEAR' }).then(function (resp) {
    render(resp.state);
    els.yaml.value = '';
    els.yaml.style.display = 'none';
  });
});

function insertAssertion(action, promptText, field) {
  var value = window.prompt(promptText);
  if (value == null || value === '') return;
  var step = { action: action };
  step[field] = value;
  send({ type: 'ADD_ASSERTION', step: step }).then(function (resp) { render(resp.state); });
}

els['assert-text'].addEventListener('click', function () {
  insertAssertion('check_visible_text', 'Visible text that must be present:', 'text');
});
els['assert-title'].addEventListener('click', function () {
  insertAssertion('check_title', 'Page title must contain:', 'contains');
});
els['assert-url'].addEventListener('click', function () {
  insertAssertion('check_url', 'URL must contain:', 'contains');
});

function buildYaml() {
  return send({ type: 'GET_STATE' }).then(function (resp) {
    var steps = (resp.state && resp.state.steps) || [];
    return window.SynthMKExport.stepsToYaml({ name: 'Recorded Flow' }, steps);
  });
}

els.export.addEventListener('click', function () {
  buildYaml().then(function (yaml) {
    els.yaml.value = yaml;
    els.yaml.style.display = 'block';
  });
});

els.copy.addEventListener('click', function () {
  buildYaml().then(function (yaml) {
    els.yaml.value = yaml;
    els.yaml.style.display = 'block';
    navigator.clipboard.writeText(yaml).catch(function () {
      els.yaml.select();
      document.execCommand('copy');
    });
  });
});

els.download.addEventListener('click', function () {
  buildYaml().then(function (yaml) {
    var blob = new Blob([yaml], { type: 'text/yaml' });
    var url = URL.createObjectURL(blob);
    chrome.downloads
      ? chrome.downloads.download({ url: url, filename: 'recorded-flow.yaml' })
      : (function () {
          var a = document.createElement('a');
          a.href = url;
          a.download = 'recorded-flow.yaml';
          a.click();
        })();
  });
});

refresh();
