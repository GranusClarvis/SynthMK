/*
 * SynthMK Recorder — popup controller.
 *
 * Drives the background service worker (start/stop/clear/assert/delete) and
 * turns the recorded step buffer into SynthMK flow YAML via the shared
 * SynthMKExport serializer (recorder_export.js).
 *
 * v0.3.0 UX: live editable step list, check settings (service name +
 * thresholds + screenshot toggle), secret-reference hint for password fills,
 * and a kebab-cased download filename derived from the service name.
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
['state', 'count', 'start', 'stop', 'clear', 'steps', 'secret-hint',
 'assert-text', 'assert-title', 'assert-url',
 'meta-name', 'meta-warn', 'meta-crit', 'meta-shot',
 'export', 'copy', 'download', 'yaml'].forEach(function (id) {
  els[id] = document.getElementById(id);
});

// --- Live step list ---------------------------------------------------------
function renderSteps(steps) {
  els.steps.textContent = '';
  var anySecret = false;
  (steps || []).forEach(function (step, i) {
    var li = document.createElement('li');

    var idx = document.createElement('span');
    idx.className = 'idx';
    idx.textContent = String(i + 1);

    var lbl = document.createElement('span');
    lbl.className = 'lbl' + (step.sensitive ? ' secret' : '');
    lbl.textContent = window.SynthMKExport.stepLabel(step);
    lbl.title = lbl.textContent;
    if (step.sensitive) anySecret = true;

    var del = document.createElement('button');
    del.className = 'del';
    del.textContent = '✕';
    del.title = 'Remove this step';
    del.addEventListener('click', function () {
      send({ type: 'DELETE_STEP', index: i }).then(function (resp) { render(resp.state); });
    });

    li.appendChild(idx);
    li.appendChild(lbl);
    li.appendChild(del);
    els.steps.appendChild(li);
  });
  els['secret-hint'].style.display = anySecret ? 'block' : 'none';
}

function render(state) {
  if (!state) return;
  els.state.textContent = state.isRecording ? 'recording' : 'idle';
  els.count.textContent = state.stepCount != null ? state.stepCount : 0;
  renderSteps(state.steps);
}

function refresh() {
  send({ type: 'GET_STATE' }).then(function (resp) { render(resp.state); });
}

// --- Recording controls -----------------------------------------------------
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

// --- Assertions --------------------------------------------------------------
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

// --- Check settings (persisted so a popup reopen keeps them) -----------------
function metaFromForm() {
  return {
    name: els['meta-name'].value || 'Recorded Flow',
    warn_ms: parseInt(els['meta-warn'].value, 10) || 3000,
    crit_ms: parseInt(els['meta-crit'].value, 10) || 7000,
    screenshot_on_failure: els['meta-shot'].checked,
  };
}

function saveMeta() {
  chrome.storage.local.set({ synthmk_meta: metaFromForm() });
}

['meta-name', 'meta-warn', 'meta-crit'].forEach(function (id) {
  els[id].addEventListener('input', saveMeta);
});
els['meta-shot'].addEventListener('change', saveMeta);

chrome.storage.local.get('synthmk_meta', function (data) {
  var meta = data && data.synthmk_meta;
  if (!meta) return;
  if (meta.name) els['meta-name'].value = meta.name;
  if (meta.warn_ms) els['meta-warn'].value = meta.warn_ms;
  if (meta.crit_ms) els['meta-crit'].value = meta.crit_ms;
  els['meta-shot'].checked = meta.screenshot_on_failure !== false;
});

// --- Export -------------------------------------------------------------------
function buildYaml() {
  return send({ type: 'GET_STATE' }).then(function (resp) {
    var steps = (resp.state && resp.state.steps) || [];
    return window.SynthMKExport.stepsToYaml(metaFromForm(), steps);
  });
}

function flowFilename() {
  var name = (els['meta-name'].value || 'recorded-flow')
    .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return (name || 'recorded-flow') + '.yaml';
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
      ? chrome.downloads.download({ url: url, filename: flowFilename() })
      : (function () {
          var a = document.createElement('a');
          a.href = url;
          a.download = flowFilename();
          a.click();
        })();
  });
});

refresh();
// Keep the step list live while the popup is open and recording continues.
setInterval(refresh, 800);
