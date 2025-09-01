// ==UserScript==
// @name         UI Diagnostic Gatherer (proximapp.net)
// @namespace    http://tampermonkey.net/
// @version      0.1.1
// @description  Gather CSS/DOM/network environment info for UI debugging and share as JSON/screenshot
// @match        https://proximapp.net/*
// @match        https://*.proximapp.net/*
// @match        http://proximapp.net/*
// @match        http://*.proximapp.net/*
// @grant        GM_setClipboard
// @grant        GM_download
// @grant        GM_registerMenuCommand
// @require      https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js
// ==/UserScript==

/*
Install
- In Tampermonkey: Create a new userscript and paste this file's contents.
- Or open this file in your browser and click "Raw" to let Tampermonkey offer install.

Use
- Visit any page on proximapp.net.
- Click the floating "UI Diag" button (bottom-right), or use Tampermonkey menu "Run UI Diagnostics".
- Copy/Download the JSON payload, or open a best-effort screenshot.

What it captures
- Environment: URL, UA, viewport, DPR, screen metrics, document mode.
- DOM: body class list and presence of page-image-generate.
- Styles: stylesheet links and inline styles; document.styleSheets with rule counts and media rules.
- Media queries: match state for max-width: 640px, prefers-color-scheme, reduced motion.
- Elements: computed styles and bounding boxes for body, header, nav, form.gen, .bubble, #feed.
- Resources: performance entries related to CSS/links (sizes and durations).
- CSP (meta): meta tag value if present (note: headers not available to JS).
- Console: log/warn/error since this script loaded (ring buffer).
- Screenshot: html2canvas best-effort rasterization (may be limited by CORS).

Limitations
- Cross-origin stylesheets may be unreadable and are flagged readable:false (SecurityError).
- Response header CSP cannot be read by JS; only meta CSP is captured.
- Screenshot can fail if canvas is tainted by cross-origin images without CORS.
*/

(function() {
  'use strict';

  // Ring buffer for console logs since script load
  const consoleBuffer = [];
  // Safely wrap console methods; skip if getter-only/non-writable (e.g., Firefox/Tampermonkey)
  const wrapConsole = (type) => {
    const orig = console[type];
    if (typeof orig !== 'function') return; // nothing to wrap
    const wrapper = function(...args) {
      try {
        consoleBuffer.push({
          type,
          time: new Date().toISOString(),
          args: args.map(a => serializeForJSON(a)).slice(0, 10)
        });
      } catch {}
      // Ensure correct receiver
      return orig.apply(console, args);
    };
    try {
      const desc = Object.getOwnPropertyDescriptor(console, type);
      if (!desc || desc.writable) {
        console[type] = wrapper; // simple path
        return;
      }
      if (desc.configurable) {
        Object.defineProperty(console, type, {
          value: wrapper,
          configurable: desc.configurable,
          enumerable: desc.enumerable,
          writable: desc.writable
        });
        return;
      }
      // Non-writable and not configurable: skip wrapping to avoid runtime error
    } catch {
      // Accessing descriptor or defining may throw in some environments; skip wrapping
    }
  };
  ['log','warn','error'].forEach(wrapConsole);

  function serializeForJSON(v) {
    try {
      if (v == null) return v;
      if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') return v;
      if (v instanceof Error) return { name: v.name, message: v.message, stack: v.stack };
      if (v instanceof Node) return `<${v.nodeName.toLowerCase()}…>`;
      return JSON.parse(JSON.stringify(v, (k, val) => typeof val === 'function' ? `fn(${val.name||'anon'})` : val));
    } catch (e) {
      return String(v);
    }
  }

  function gatherStylesheets() {
    const sheets = [];
    for (const s of Array.from(document.styleSheets)) {
      const rec = {
        href: s.href || '(inline)',
        disabled: !!s.disabled,
        owner: (s.ownerNode && s.ownerNode.tagName || '').toLowerCase(),
        readable: true,
        ruleCounts: { total: 0, style: 0, media: 0, fontface: 0, import: 0, other: 0 },
        mediaRules: []
      };
      try {
        const rules = s.cssRules || [];
        rec.ruleCounts.total = rules.length;
        for (const r of Array.from(rules)) {
          const t = r.constructor && r.constructor.name || '';
          if (t === 'CSSStyleRule') rec.ruleCounts.style++;
          else if (t === 'CSSMediaRule') {
            rec.ruleCounts.media++;
            rec.mediaRules.push({
              condition: r.media && r.media.mediaText || '',
              rules: (r.cssRules && r.cssRules.length) || 0,
              matches: r.media ? matchMedia(String(r.media.mediaText||'all')).matches : null
            });
          } else if (t === 'CSSFontFaceRule') rec.ruleCounts.fontface++;
          else if (t === 'CSSImportRule') rec.ruleCounts.import++;
          else rec.ruleCounts.other++;
        }
      } catch (e) {
        rec.readable = false; // likely cross-origin or blocked
        rec.error = String(e && e.message || e);
      }
      sheets.push(rec);
    }
    return sheets;
  }

  function gatherLinks() {
    return Array.from(document.querySelectorAll('link[rel~=stylesheet],style')).map(n => {
      if (n.tagName.toLowerCase() === 'style') {
        return { tag: 'style', disabled: !!n.disabled, media: n.media || '', length: (n.textContent||'').length };
      }
      return {
        tag: 'link',
        href: n.href,
        rel: n.rel,
        media: n.media || '',
        disabled: !!n.disabled,
        as: n.as || ''
      };
    });
  }

  function gatherResources() {
    const entries = performance.getEntriesByType('resource') || [];
    return entries
      .filter(e => (e.initiatorType === 'link' || /\.css(\?|$)/.test(e.name)) )
      .map(e => ({
        name: e.name,
        initiatorType: e.initiatorType,
        duration: Math.round(e.duration),
        transferSize: e.transferSize,
        encodedBodySize: e.encodedBodySize,
        decodedBodySize: e.decodedBodySize
      }));
  }

  function gatherComputedFor(selector) {
    const el = document.querySelector(selector);
    if (!el) return null;
    const cs = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    const pick = (p) => cs.getPropertyValue(p);
    return {
      exists: true,
      node: el.tagName.toLowerCase(),
      rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
      styles: {
        display: pick('display'),
        position: pick('position'),
        backgroundColor: pick('background-color'),
        color: pick('color'),
        fontSize: pick('font-size'),
        padding: [pick('padding-top'), pick('padding-right'), pick('padding-bottom'), pick('padding-left')].join(' '),
        margin: [pick('margin-top'), pick('margin-right'), pick('margin-bottom'), pick('margin-left')].join(' '),
        borderTop: [pick('border-top-width'), pick('border-top-style'), pick('border-top-color')].join(' '),
        borderBottom: [pick('border-bottom-width'), pick('border-bottom-style'), pick('border-bottom-color')].join(' '),
        maxWidth: pick('max-width')
      }
    };
  }

  function gatherMediaQueries() {
    const queries = [
      '(max-width: 640px)',
      '(prefers-color-scheme: dark)',
      '(prefers-reduced-motion: reduce)'
    ];
    return queries.map(q => ({ query: q, matches: matchMedia(q).matches }));
  }

  async function gatherServiceWorker() {
    const sw = {
      controller: !!(navigator.serviceWorker && navigator.serviceWorker.controller),
      controllerScript: (navigator.serviceWorker && navigator.serviceWorker.controller && navigator.serviceWorker.controller.scriptURL) || null,
      registrations: []
    };
    try {
      if (navigator.serviceWorker && navigator.serviceWorker.getRegistrations) {
        const regs = await navigator.serviceWorker.getRegistrations();
        sw.registrations = regs.map(r => ({
          scope: r.scope,
          active: !!r.active,
          installing: !!r.installing,
          waiting: !!r.waiting
        }));
      }
    } catch (e) { sw.error = String(e && e.message || e); }
    return sw;
  }

  function gatherMetaCSP() {
    const m = document.querySelector('meta[http-equiv="Content-Security-Policy"]');
    return m ? m.getAttribute('content') : null; // Note: response header CSP not accessible here
  }

  async function captureScreenshot() {
    try {
      const canvas = await html2canvas(document.body, {
        logging: false,
        useCORS: true,
        allowTaint: true,
        windowWidth: document.documentElement.scrollWidth,
        windowHeight: document.documentElement.scrollHeight
      });
      return canvas.toDataURL('image/png'); // may fail if canvas is tainted
    } catch (e) {
      return { error: String(e && e.message || e) };
    }
  }

  async function gather() {
    const info = {
      page: {
        url: location.href,
        title: document.title,
        referrer: document.referrer || null,
        timestamp: new Date().toISOString(),
        doctype: document.doctype ? document.doctype.name : null,
        mode: document.compatMode // CSS1Compat vs BackCompat
      },
      env: {
        ua: navigator.userAgent,
        platform: navigator.platform,
        language: navigator.language,
        devicePixelRatio: window.devicePixelRatio,
        viewport: { w: window.innerWidth, h: window.innerHeight },
        screen: { w: screen.width, h: screen.height, aw: screen.availWidth, ah: screen.availHeight, colorDepth: screen.colorDepth }
      },
      dom: {
        bodyClass: document.body && document.body.className || '',
        hasPageImageGenerate: document.body && document.body.classList.contains('page-image-generate') || false
      },
      links: gatherLinks(),
      stylesheets: gatherStylesheets(),
      mediaQueries: gatherMediaQueries(),
      resources: gatherResources(),
      metaCSP: gatherMetaCSP(),
      consoleSinceLoad: consoleBuffer.slice(-200),
      elements: {
        body: gatherComputedFor('body'),
        header: gatherComputedFor('header'),
        nav: gatherComputedFor('header nav, nav'),
        formGen: gatherComputedFor('form.gen'),
        bubble: gatherComputedFor('.bubble'),
        feed: gatherComputedFor('#feed')
      }
    };
    info.summary = {
      stylesheetCount: info.stylesheets.length,
      readableStylesheets: info.stylesheets.filter(s => s.readable).length,
      inlineStyleBlocks: info.links.filter(l => l.tag === 'style').length,
      cssLinks: info.links.filter(l => l.tag === 'link').length,
      mobileBreakpointMatched: info.mediaQueries.find(q => q.query.includes('max-width: 640px'))?.matches || false
    };
    // Optional: include service worker state, but do not block if it errors
    try { info.serviceWorker = await gatherServiceWorker(); } catch {}
    const screenshot = await captureScreenshot(); // string or {error}
    return { info, screenshot };
  }

  function buildUI() {
    const style = document.createElement('style');
    style.textContent = `
      .uidiag-btn{position:fixed;right:12px;bottom:12px;z-index:999999;background:#2a2a2a;color:#fff;border:1px solid #666;padding:.45rem .7rem;border-radius:6px;cursor:pointer;font:14px system-ui}
      .uidiag-btn:hover{background:#3a3a3a}
      .uidiag-modal{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:999998;display:none;align-items:center;justify-content:center}
      .uidiag-card{background:#1e1e1e;color:#eee;border:1px solid #666;border-radius:8px;max-width:min(92vw,920px);width: min(92vw,920px);max-height:80vh;overflow:auto;padding:.75rem}
      .uidiag-actions{display:flex;gap:.5rem;margin:.5rem 0}
      .uidiag-pre{white-space:pre-wrap;max-height:52vh;overflow:auto;background:#111;border:1px solid #444;padding:.5rem;border-radius:6px}
      .uidiag-note{opacity:.8;font-size:.9em}
    `;
    document.head.appendChild(style);

    const btn = document.createElement('button');
    btn.className = 'uidiag-btn';
    btn.textContent = 'UI Diag';
    btn.title = 'Gather UI diagnostics';
    document.body.appendChild(btn);

    const modal = document.createElement('div');
    modal.className = 'uidiag-modal';
    modal.innerHTML = `
      <div class="uidiag-card">
        <div class="uidiag-actions">
          <button id="uid-copy">Copy JSON</button>
          <button id="uid-download">Download JSON</button>
          <button id="uid-screenshot">Open Screenshot</button>
          <button id="uid-close" style="margin-left:auto;">Close</button>
        </div>
        <div class="uidiag-note">Data includes environment, stylesheets, media queries, computed styles, resources, and recent console logs. Screenshot is best-effort.</div>
        <pre id="uid-pre" class="uidiag-pre">Click “UI Diag” to gather…</pre>
      </div>
    `;
    document.body.appendChild(modal);

    let latest = null;

    const run = async () => {
      const pre = modal.querySelector('#uid-pre');
      pre.textContent = 'Gathering…';
      try {
        latest = await gather();
        const payload = {
          page: latest.info.page,
          env: latest.info.env,
          dom: latest.info.dom,
          summary: latest.info.summary,
          mediaQueries: latest.info.mediaQueries,
          elements: latest.info.elements,
          links: latest.info.links,
          stylesheets: latest.info.stylesheets,
          resources: latest.info.resources,
          metaCSP: latest.info.metaCSP,
          consoleSinceLoad: latest.info.consoleSinceLoad,
          serviceWorker: latest.info.serviceWorker,
          screenshot: (typeof latest.screenshot === 'string') ? { dataUrlPrefix: latest.screenshot.slice(0, 32), length: latest.screenshot.length } : latest.screenshot
        };
        pre.textContent = JSON.stringify(payload, null, 2);
      } catch (e) {
        pre.textContent = `Error: ${e && e.message || e}`;
      }
    };

    btn.addEventListener('click', () => { modal.style.display = 'flex'; run(); });
    modal.querySelector('#uid-close').addEventListener('click', () => { modal.style.display = 'none'; });
    modal.querySelector('#uid-copy').addEventListener('click', () => {
      const text = modal.querySelector('#uid-pre').textContent;
      try { GM_setClipboard(text, 'text'); } catch {}
    });
    modal.querySelector('#uid-download').addEventListener('click', () => {
      const text = modal.querySelector('#uid-pre').textContent;
      const name = `ui-diagnostics-${new Date().toISOString().replace(/[:.]/g,'-')}.json`;
      try { GM_download({ url: URL.createObjectURL(new Blob([text], {type:'application/json'})), name }); } catch {
        // fallback
        const a = document.createElement('a'); a.href = 'data:application/json;charset=utf-8,' + encodeURIComponent(text); a.download = name; a.click();
      }
    });
    modal.querySelector('#uid-screenshot').addEventListener('click', async () => {
      if (!latest) return;
      if (typeof latest.screenshot === 'string') {
        const win = open(); if (win) win.document.write(`<img style="max-width:100%" src="${latest.screenshot}">`);
      } else {
        alert('Screenshot unavailable: ' + (latest.screenshot && latest.screenshot.error || 'unknown'));
      }
    });

    if (typeof GM_registerMenuCommand === 'function') {
      GM_registerMenuCommand('Run UI Diagnostics', () => { modal.style.display = 'flex'; run(); });
    }
  }

  // Initialize when DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', buildUI);
  } else {
    buildUI();
  }
})();
