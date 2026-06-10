#!/usr/bin/env python3
"""SynthMK visual step builder — the live-browser half.

A small JSON-lines worker owned by admin_server.py: it keeps ONE Playwright
page open so the dashboard can offer point-and-click authoring against the
real page (think Chrome inspect, but producing SynthMK steps):

    {"id":1,"cmd":"start","url":"https://portal/login"}   open the page
    {"id":2,"cmd":"shot"}                                  current screenshot
    {"id":3,"cmd":"pick","x":412,"y":300}                  element at point ->
                                                           selector ladder +
                                                           suggested action
    {"id":4,"cmd":"step","step":{"action":"click",...}}    EXECUTE a SynthMK
                                                           step on the live
                                                           page (same dispatch
                                                           as the runner, so
                                                           "added" == "tested")
    {"id":5,"cmd":"quit"}

One response line per request: {"id":N,"ok":true,...} — errors come back as
{"ok":false,"error":"..."} and never kill the worker. All outgoing text passes
the runner's secret redaction. The worker exits when stdin closes, so a dead
admin server can never leak a headless browser.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

HOME = Path(os.environ.get("SYNTHMK_HOME", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(HOME / "runner"))
import runner as R  # noqa: E402
import secret_source  # noqa: E402

VIEWPORT = {"width": 1280, "height": 800}
STEP_TIMEOUT_MS = 10000

# Element inspection at a point: build a selector fallback ladder the same way
# the recorder extension does (test attributes > id > name > aria > classes >
# structural path), each candidate verified UNIQUE on the page before offered.
PICK_JS = """
(pt) => {
  const el = document.elementFromPoint(pt.x, pt.y);
  if (!el || el === document.documentElement) return null;
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s;
  const uniq = (sel) => {
    try { return document.querySelectorAll(sel).length === 1; }
    catch (e) { return false; }
  };
  const cands = [];
  const push = (s) => { if (s && uniq(s) && !cands.includes(s)) cands.push(s); };
  for (const a of ['data-testid', 'data-test', 'data-qa', 'data-cy']) {
    if (el.hasAttribute(a)) push('[' + a + '="' + el.getAttribute(a) + '"]');
  }
  if (el.id) push('#' + esc(el.id));
  const tag = el.tagName.toLowerCase();
  if (el.getAttribute('name')) push(tag + '[name="' + el.getAttribute('name') + '"]');
  if (el.getAttribute('aria-label')) push(tag + '[aria-label="' + el.getAttribute('aria-label') + '"]');
  if (el.classList.length && el.classList.length <= 4)
    push(tag + '.' + [...el.classList].map(esc).join('.'));
  // Structural path — always resolvable, least stable, so it goes last.
  let n = el; const parts = [];
  while (n && n.nodeType === 1 && parts.length < 6) {
    if (n.id) { parts.unshift('#' + esc(n.id)); break; }
    let sel = n.tagName.toLowerCase();
    const parent = n.parentElement;
    if (parent) {
      const sibs = [...parent.children].filter(c => c.tagName === n.tagName);
      if (sibs.length > 1) sel += ':nth-of-type(' + (sibs.indexOf(n) + 1) + ')';
    }
    parts.unshift(sel);
    n = parent;
  }
  push(parts.join(' > '));
  const text = (el.innerText || el.value || '').trim().slice(0, 80);
  const options = tag === 'select'
    ? [...el.options].map(o => ({value: o.value, label: o.label})) : [];
  return {
    tag, text,
    type: (el.getAttribute('type') || '').toLowerCase(),
    isPassword: el.type === 'password',
    isCheckbox: el.type === 'checkbox' || el.type === 'radio',
    isInput: ['input', 'textarea'].includes(tag) &&
             !['checkbox', 'radio', 'button', 'submit'].includes(el.type),
    isSelect: tag === 'select',
    checked: !!el.checked,
    href: el.getAttribute('href') || '',
    candidates: cands.slice(0, 4),
    options: options.slice(0, 30),
  };
}
"""

HIGHLIGHT_JS = """
(sel) => {
  const prev = document.getElementById('__synthmk_hl');
  if (prev) prev.remove();
  let el = null;
  try { el = document.querySelector(sel); } catch (e) {}
  if (!el) return false;
  const r = el.getBoundingClientRect();
  const hl = document.createElement('div');
  hl.id = '__synthmk_hl';
  hl.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;' +
    'border:2px solid #2dd4bf;border-radius:3px;box-shadow:0 0 0 4000px rgba(13,148,136,.08);' +
    'left:' + (r.left - 2) + 'px;top:' + (r.top - 2) + 'px;' +
    'width:' + r.width + 'px;height:' + r.height + 'px;';
  document.body.appendChild(hl);
  return true;
}
"""

CLEAR_HIGHLIGHT_JS = """
() => { const p = document.getElementById('__synthmk_hl'); if (p) p.remove(); }
"""


def shot_payload(page) -> dict:
    png = page.screenshot(full_page=False)
    return {
        "png": base64.b64encode(png).decode(),
        "url": page.url,
        "title": page.title(),
        "viewport": VIEWPORT,
    }


def main() -> int:
    # Secrets: best-effort load so builder-tested fills can resolve
    # {{ secret.X }} exactly like a scheduled run would.
    secrets_path = secret_source.secrets_file_path(None)
    if secrets_path is not None:
        try:
            R._SECRETS = secret_source.load_secrets(secrets_path)
        except secret_source.SecretError:
            pass  # steps that need secrets will fail with the clear message

    from playwright.sync_api import sync_playwright

    launch_args = {}
    if os.environ.get("SYNTHMK_NO_SANDBOX"):
        launch_args["args"] = ["--no-sandbox", "--disable-dev-shm-usage"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, **launch_args)
        # bypass_csp: element inspection (PICK_JS/HIGHLIGHT_JS) runs in the
        # page's main world, which a strict target-site CSP would veto. The
        # builder is an authoring tool, not the monitor; scheduled runs use a
        # normal page so checks see the site's real policy behavior.
        page = browser.new_page(viewport=VIEWPORT, bypass_csp=True)
        ctx = {"sensitive_used": False}
        print(json.dumps({"ready": True}), flush=True)

        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                req = json.loads(raw)
            except json.JSONDecodeError:
                print(json.dumps({"ok": False, "error": "bad request json"}), flush=True)
                continue
            rid = req.get("id")
            cmd = req.get("cmd")
            out: dict = {"id": rid}
            try:
                if cmd == "start":
                    page.goto(str(req["url"]), timeout=30000,
                              wait_until="domcontentloaded")
                    try:
                        page.wait_for_load_state("networkidle", timeout=3000)
                    except Exception:
                        pass  # busy pages still screenshot fine
                    out.update(ok=True, **shot_payload(page))
                elif cmd == "shot":
                    page.evaluate(CLEAR_HIGHLIGHT_JS)
                    out.update(ok=True, **shot_payload(page))
                elif cmd == "pick":
                    page.evaluate(CLEAR_HIGHLIGHT_JS)
                    info = page.evaluate(PICK_JS, {"x": int(req["x"]), "y": int(req["y"])})
                    if not info or not info.get("candidates"):
                        out.update(ok=False, error="no element at that point")
                    else:
                        page.evaluate(HIGHLIGHT_JS, info["candidates"][0])
                        out.update(ok=True, element=info, **shot_payload(page))
                elif cmd == "step":
                    page.evaluate(CLEAR_HIGHLIGHT_JS)
                    step = req.get("step") or {}
                    try:
                        R._run_step(page, step, STEP_TIMEOUT_MS, ctx)
                        out.update(ok=True, **shot_payload(page))
                    except R.FlowError as fe:
                        out.update(ok=False, error=R._oneline(str(fe)),
                                   **shot_payload(page))
                    except Exception as exc:
                        first = str(exc).strip().splitlines()[0] if str(exc).strip() \
                            else exc.__class__.__name__
                        out.update(ok=False, error=R._oneline(first),
                                   **shot_payload(page))
                elif cmd == "quit":
                    print(json.dumps({"id": rid, "ok": True}), flush=True)
                    break
                else:
                    out.update(ok=False, error=f"unknown cmd '{cmd}'")
            except Exception as exc:  # navigation errors etc — never die
                first = str(exc).strip().splitlines()[0] if str(exc).strip() \
                    else exc.__class__.__name__
                out.update(ok=False, error=R._oneline(first))
            print(json.dumps(out), flush=True)

        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
