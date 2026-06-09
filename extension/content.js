/*
 * SynthMK Recorder — content script.
 *
 * Injected into pages to capture interactions and forward them to the service
 * worker as SynthMK flow steps. The selector ladder is ported from GOAT's
 * chrome-extension/content.js getSelector() (data-testid → stable id → unique
 * name → shortest unique class combo → nth-of-type path), which docs/
 * flow-schema.md calls out as the target strategy.
 */
(function () {
  'use strict';

  var isRecording = false;
  var overlay = null;

  // --- Selector ladder (ported from GOAT getSelector) -----------------------
  function getSelector(element) {
    // 1. data-testid — most stable, app-authored hook.
    if (element.dataset && element.dataset.testid) {
      return '[data-testid="' + element.dataset.testid + '"]';
    }

    // 2. Stable id — reject UUID-ish ids like "btn-3f2a-9c1e".
    if (element.id && !element.id.match(/^[a-z]+-[a-f0-9-]+$/i)) {
      return '#' + cssEscape(element.id);
    }

    // 3. Unique name on form controls.
    var tag = element.tagName.toLowerCase();
    if (element.name && ['input', 'select', 'textarea'].indexOf(tag) !== -1) {
      var nameSel = tag + '[name="' + element.name + '"]';
      if (document.querySelectorAll(nameSel).length === 1) return nameSel;
    }

    // 4. Shortest unique class combination.
    if (element.className && typeof element.className === 'string') {
      var classes = element.className.split(/\s+/).filter(function (c) {
        return c && !c.match(/^(hover|active|focus|disabled|selected)/i);
      });
      for (var i = 1; i <= classes.length; i++) {
        var classSel = tag + '.' + classes.slice(0, i).join('.');
        if (document.querySelectorAll(classSel).length === 1) return classSel;
      }
    }

    // 5. nth-of-type parent path fallback.
    return buildPath(element);
  }

  function buildPath(el) {
    var path = [];
    var current = el;
    while (current && current !== document.body) {
      var selector = current.tagName.toLowerCase();
      if (current.id && !current.id.match(/^[a-z]+-[a-f0-9-]+$/i)) {
        path.unshift('#' + cssEscape(current.id));
        break;
      }
      var parent = current.parentElement;
      if (parent) {
        var siblings = Array.prototype.filter.call(parent.children, function (c) {
          return c.tagName === current.tagName;
        });
        if (siblings.length > 1) {
          selector += ':nth-of-type(' + (siblings.indexOf(current) + 1) + ')';
        }
      }
      path.unshift(selector);
      current = parent;
    }
    return path.join(' > ');
  }

  function cssEscape(s) {
    if (window.CSS && window.CSS.escape) return window.CSS.escape(s);
    return s.replace(/([^a-zA-Z0-9_-])/g, '\\$1');
  }

  // --- Step forwarding ------------------------------------------------------
  function recordStep(step) {
    try {
      chrome.runtime.sendMessage({ type: 'ADD_STEP', step: step });
    } catch (e) {
      /* service worker asleep / page navigating — best effort. */
    }
  }

  function handleClick(event) {
    if (!isRecording) return;
    var element = event.target;
    if (!element || element.id === 'synthmk-recorder-overlay') return;
    var tag = element.tagName.toLowerCase();
    // Inputs are captured via input/change, not click.
    if (['input', 'textarea', 'select'].indexOf(tag) !== -1) return;
    recordStep({ action: 'click', selector: getSelector(element) });
    showFeedback(event.clientX, event.clientY);
  }

  var inputTimeout = null;
  var lastEl = null;
  var lastValue = '';

  function handleInput(event) {
    if (!isRecording) return;
    lastEl = event.target;
    lastValue = lastEl.value;
    if (inputTimeout) clearTimeout(inputTimeout);
    // Debounce so we capture the final value, not every keystroke.
    inputTimeout = setTimeout(function () {
      if (lastEl) {
        recordStep({ action: 'fill', selector: getSelector(lastEl), value: lastValue });
        lastEl = null;
        lastValue = '';
      }
    }, 500);
  }

  function handleChange(event) {
    if (!isRecording) return;
    var element = event.target;
    var tag = element.tagName.toLowerCase();
    if (tag === 'select') {
      recordStep({ action: 'fill', selector: getSelector(element), value: element.value });
    }
  }

  // --- Recording indicator overlay -----------------------------------------
  function createOverlay() {
    overlay = document.createElement('div');
    overlay.id = 'synthmk-recorder-overlay';
    overlay.style.cssText =
      'position:fixed;top:10px;right:10px;background:rgba(0,0,0,0.82);' +
      'border:2px solid #2dd4bf;border-radius:8px;padding:10px 14px;z-index:2147483647;' +
      'font:13px -apple-system,Segoe UI,Roboto,sans-serif;color:#2dd4bf;' +
      'box-shadow:0 0 18px rgba(45,212,191,0.35);pointer-events:none;';
    overlay.textContent = '● SynthMK recording';
    if (document.body) document.body.appendChild(overlay);
  }

  function removeOverlay() {
    if (overlay) {
      overlay.remove();
      overlay = null;
    }
  }

  function showFeedback(x, y) {
    var dot = document.createElement('div');
    dot.style.cssText =
      'position:fixed;left:' + x + 'px;top:' + y + 'px;width:16px;height:16px;' +
      'background:rgba(45,212,191,0.5);border:2px solid #2dd4bf;border-radius:50%;' +
      'pointer-events:none;z-index:2147483647;transition:transform .4s,opacity .4s;';
    if (document.body) {
      document.body.appendChild(dot);
      requestAnimationFrame(function () {
        dot.style.transform = 'scale(2)';
        dot.style.opacity = '0';
      });
      setTimeout(function () { dot.remove(); }, 450);
    }
  }

  // --- Lifecycle ------------------------------------------------------------
  function startRecording() {
    if (isRecording) return;
    isRecording = true;
    createOverlay();
    document.addEventListener('click', handleClick, true);
    document.addEventListener('input', handleInput, true);
    document.addEventListener('change', handleChange, true);
  }

  function stopRecording() {
    isRecording = false;
    removeOverlay();
    document.removeEventListener('click', handleClick, true);
    document.removeEventListener('input', handleInput, true);
    document.removeEventListener('change', handleChange, true);
  }

  chrome.runtime.onMessage.addListener(function (message, sender, sendResponse) {
    switch (message.type) {
      case 'RECORDING_STARTED':
        startRecording();
        sendResponse({ ok: true });
        break;
      case 'RECORDING_STOPPED':
        stopRecording();
        sendResponse({ ok: true });
        break;
      case 'GET_RECORDING_STATE':
        sendResponse({ isRecording: isRecording });
        break;
      default:
        sendResponse({ ok: false });
    }
    return true;
  });

  // On (re)injection, ask the worker whether we should already be recording
  // (e.g. the page navigated mid-recording and the content script reloaded).
  try {
    chrome.runtime.sendMessage({ type: 'GET_STATE' }, function (resp) {
      if (resp && resp.isRecording) startRecording();
    });
  } catch (e) {
    /* worker not ready yet — popup START will re-arm us. */
  }
})();
