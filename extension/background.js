/*
 * SynthMK Recorder — background service worker (MV3).
 *
 * Owns recording state and the recorded-step buffer (persisted in
 * chrome.storage.local so a service-worker restart doesn't lose a session).
 * Records tab navigations as `open_url` steps and relays start/stop to the
 * active tab's content script.
 */
'use strict';

var STATE = { isRecording: false, tabId: null, steps: [], lastUrl: '' };

function loadState() {
  return chrome.storage.local.get('synthmk_state').then(function (data) {
    if (data && data.synthmk_state) STATE = data.synthmk_state;
    return STATE;
  });
}

function saveState() {
  return chrome.storage.local.set({ synthmk_state: STATE });
}

// Append a step, collapsing a duplicate fill on the same selector (the debounced
// content-script input can emit twice across a fast blur).
function addStep(step) {
  var last = STATE.steps[STATE.steps.length - 1];
  if (step.action === 'fill' && last && last.action === 'fill' && last.selector === step.selector) {
    last.value = step.value;
  } else {
    STATE.steps.push(step);
  }
  return saveState();
}

// Record a navigation as an open_url step, de-duplicating consecutive same-URL
// hits (SPA history events and the initial load both fire).
function recordNavigation(url) {
  if (!url || url === STATE.lastUrl) return Promise.resolve();
  if (!/^https?:|^file:/.test(url)) return Promise.resolve();
  STATE.lastUrl = url;
  return addStep({ action: 'open_url', url: url });
}

// State is loaded ONCE per worker lifetime and messages are processed on a
// serialized promise chain. Re-loading from chrome.storage on every message
// (the old design) made two back-to-back ADD_STEPs race each other's save —
// the second load saw stale steps and its save dropped the first step (a
// recorded fill could vanish when Enter followed it within milliseconds).
var READY = loadState();
var CHAIN = Promise.resolve();

chrome.runtime.onMessage.addListener(function (message, sender, sendResponse) {
  CHAIN = CHAIN
    .then(function () { return READY; })
    .then(function () { return handleMessage(message, sender, sendResponse); })
    .catch(function () { try { sendResponse({ ok: false }); } catch (e) { /* gone */ } });
  return true; // async sendResponse
});

function handleMessage(message, sender, sendResponse) {
  return new Promise(function (resolve) {
    var respond = function (payload) { try { sendResponse(payload); } catch (e) { /* popup closed */ } resolve(); };
    dispatch(message, sender, respond);
  });
}

function dispatch(message, sender, sendResponse) {
  {
    switch (message.type) {
      case 'START':
        STATE.isRecording = true;
        STATE.tabId = message.tabId || (sender.tab && sender.tab.id) || null;
        STATE.steps = [];
        STATE.lastUrl = '';
        saveState().then(function () {
          if (STATE.tabId != null) {
            chrome.tabs.get(STATE.tabId, function (tab) {
              if (tab && tab.url) recordNavigation(tab.url);
              chrome.tabs.sendMessage(STATE.tabId, { type: 'RECORDING_STARTED' }, function () {
                void chrome.runtime.lastError; // content script may not be injected yet
              });
            });
          }
          sendResponse({ ok: true, state: publicState() });
        });
        return;

      case 'STOP':
        STATE.isRecording = false;
        saveState().then(function () {
          if (STATE.tabId != null) {
            chrome.tabs.sendMessage(STATE.tabId, { type: 'RECORDING_STOPPED' }, function () {
              void chrome.runtime.lastError;
            });
          }
          sendResponse({ ok: true, state: publicState() });
        });
        return;

      case 'CLEAR':
        STATE.steps = [];
        STATE.lastUrl = '';
        saveState().then(function () { sendResponse({ ok: true, state: publicState() }); });
        return;

      case 'ADD_STEP':
        if (STATE.isRecording && message.step) {
          addStep(message.step).then(function () { sendResponse({ ok: true }); });
        } else {
          sendResponse({ ok: false });
        }
        return;

      case 'ADD_ASSERTION':
        // Manual assertion inserted from the popup (text/title/url).
        if (message.step) {
          addStep(message.step).then(function () { sendResponse({ ok: true, state: publicState() }); });
        } else {
          sendResponse({ ok: false });
        }
        return;

      case 'DELETE_STEP':
        // Remove one recorded step from the popup's live step list.
        if (typeof message.index === 'number' && STATE.steps[message.index] != null) {
          STATE.steps.splice(message.index, 1);
          saveState().then(function () { sendResponse({ ok: true, state: publicState() }); });
        } else {
          sendResponse({ ok: false, state: publicState() });
        }
        return;

      case 'GET_STATE':
        sendResponse({ isRecording: STATE.isRecording, state: publicState() });
        return;

      default:
        sendResponse({ ok: false });
    }
  }
}

function publicState() {
  return { isRecording: STATE.isRecording, stepCount: STATE.steps.length, steps: STATE.steps };
}

// Record navigations on the recorded tab.
chrome.tabs.onUpdated.addListener(function (tabId, changeInfo) {
  if (!STATE.isRecording || tabId !== STATE.tabId) return;
  if (changeInfo.url) {
    loadState().then(function () {
      if (STATE.isRecording && tabId === STATE.tabId) recordNavigation(changeInfo.url);
    });
  }
});
