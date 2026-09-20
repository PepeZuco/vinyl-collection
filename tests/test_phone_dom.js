// Boot the real page in a DOM to check the phone-only wiring Task 2 adds:
// isPhone(), and the focusin handler that scrolls a field clear of the
// keyboard. Run by tests/test_phone_dom.py so `pytest` stays the single
// command.
//
// This is a SEPARATE file from tests/test_boot.js, not an addition to it.
// test_boot.js builds its JSDOM with pretendToBeVisual:true, which starts a
// requestAnimationFrame loop, and never calls window.close() on any of its
// boots — every one of them leaves a live timer pinning node's event loop
// open, so that file's own tests finish but the process never exits. This
// file's boot() is the same shape, but every test below calls win.close()
// when it is done with a window, which is what lets node's test runner exit
// instead of hanging. See .superpowers/sdd/2026-09-19-phone-add-edit-redraw/
// probe_close.js, which proved that a closed boot returns control in well
// under a second.
//
// visualViewport does not exist in jsdom, so syncViewportHeight() always
// takes its early return here — that IS the desktop code path, and passing
// through it without throwing is real coverage. What jsdom can see, and what
// these tests check, is: isPhone() reads the breakpoint through matchMedia,
// and the focusin handler only schedules its scroll on the phone side of it.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');

const JSDOM_PATH = process.env.VINYL_JSDOM_PATH;
Module.globalPaths.push(JSDOM_PATH);
const { JSDOM, VirtualConsole } = require(path.join(JSDOM_PATH, 'jsdom'));

const ROOT = path.join(__dirname, '..');
const PAGE = process.env.VINYL_PAGE_HTML;   // the rendered template, from Flask
const RECORDS = JSON.parse(fs.readFileSync(process.env.VINYL_RECORDS_JSON, 'utf8'));

let bootCount = 0;

/* Boot the page with the network stubbed and the CDN libraries replaced by
 * stand-ins, same as test_boot.js's boot(). The one addition is a steerable
 * matchMedia: boot({phone:true}) makes (max-width:760px) match from the
 * start, and the returned win.__setPhone(on) flips it later and fires
 * change on every listener registered against it — through EITHER listener
 * spelling, since isPhone() is built on whichever the app's own
 * feature-detection picks, and a stub answering only one would hide a break
 * in that detection. */
async function boot(opts) {
  const PHONE = !!(opts && opts.phone);

  let html = fs.readFileSync(PAGE, 'utf8');
  html = html.replace(/<script src="https:\/\/[^"]+"><\/script>/g, '');
  html = html.replace(/<script src="\/static\/([^"]+)"><\/script>/g, (_, file) =>
    '<script>' + fs.readFileSync(path.join(ROOT, 'static', file), 'utf8') + '</script>');

  const errors = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', e => errors.push(String((e && e.message) || e)));
  vc.on('error', (...a) => errors.push(a.map(String).join(' ')));

  const dom = new JSDOM(html, {
    runScripts: 'outside-only',
    pretendToBeVisual: true,
    url: 'http://d' + (++bootCount) + '.localhost/',
    virtualConsole: vc,
  });
  const win = dom.window;

  win.Chart = function () { return { destroy() {}, update() {}, data: {}, options: {} }; };
  win.Chart.prototype.destroy = function () {};
  const chain = new Proxy(function () { return chain; }, {
    get: (t, p) => {
      if (p === Symbol.toPrimitive) return () => '';
      if (p === 'then') return undefined;
      if (p === Symbol.iterator) return function* () {};
      return chain;
    },
    apply: () => chain,
  });
  win.d3 = chain;
  win.topojson = { feature: () => ({ features: [] }) };
  win.marked = {
    Renderer: function () {}, use() {}, setOptions() {}, parse: s => String(s),
  };
  win.HTMLCanvasElement.prototype.getContext = () => ({});

  const mqls = [];
  win.matchMedia = q => {
    const mql = {
      media: q,
      matches: PHONE && /max-width:\s*760px/.test(q),
      addEventListener(_t, fn) { this._fn = fn; },
      removeEventListener() { this._fn = null; },
      addListener(fn) { this._fn = fn; },
      removeListener() { this._fn = null; },
    };
    mqls.push(mql);
    return mql;
  };
  win.__setPhone = on => {                      // drive a breakpoint change
    for (const m of mqls) {
      const next = on && /max-width:\s*760px/.test(m.media);
      if (next !== m.matches) { m.matches = next; if (m._fn) m._fn(m); }
    }
  };

  win.confirm = () => true;
  win.scrollTo = () => {};
  win.Element.prototype.scrollIntoView = function () {};
  win.Element.prototype.scrollTo = function () {};
  win.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
  win.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };

  win.fetch = async (url, opts2) => {
    const u = String(url);
    const json = (body) => ({ ok: true, status: 200, json: async () => body,
                              text: async () => JSON.stringify(body) });
    if (u.endsWith('/api/auth/status')) return json({ authed: true });
    if (u.endsWith('/api/places')) return json([]);
    if (u.includes('/api/records') && (!opts2 || !opts2.method || opts2.method === 'GET')) {
      return json(JSON.parse(JSON.stringify(RECORDS)));
    }
    if (u.includes('/api/scan/usage')) {
      return json({ month: '2026-08', month_usd: 0, month_scans: 0, total_usd: 0,
                    total_scans: 0, estimate: { photo: 0.006, spotify: 0.0004 } });
    }
    return json({ ok: true });
  };

  const source = [...win.document.querySelectorAll('script')]
    .map(el => el.textContent).filter(t => t.trim()).join('\n;\n');
  try { win.eval(source); } catch (e) { errors.push(String(e && e.message)); }
  for (let i = 0; i < 20; i++) await new Promise(r => setTimeout(r, 0));

  return { win, doc: win.document, errors };
}

const $ = (doc, sel) => doc.querySelector(sel);

// ── the breakpoint ───────────────────────────────────────────────────────────

test('isPhone follows the breakpoint', async () => {
  const { win } = await boot();
  assert.strictEqual(win.isPhone(), false);
  win.__setPhone(true);
  assert.strictEqual(win.isPhone(), true);
  win.close();
});

test('the page boots on a phone without throwing', async () => {
  const { win, doc, errors } = await boot({ phone: true });
  assert.deepStrictEqual(errors, [], 'errors while booting:\n' + errors.join('\n'));
  assert.ok(win.isPhone(), 'phone mode should have taken on boot');
  assert.ok(doc.getElementById('formOverlay'), 'the form overlay should exist');
  win.close();
});

// ── the keyboard-clearing scroll ─────────────────────────────────────────────
// The handler is wired unconditionally; isPhone() is what keeps it a no-op on
// desktop, where the layout viewport already shrinks for the keyboard and the
// extra scroll would just be a jump nobody asked for.

test('focusing a form field on a phone schedules a scroll clear of the keyboard', async () => {
  const { win, doc } = await boot({ phone: true });
  win.openAdd();
  const field = $(doc, '#fAlbum');
  assert.ok(field, 'the form did not render its album field');

  const calls = [];
  win.Element.prototype.scrollIntoView = function (opts) { calls.push({ el: this, opts }); };
  field.dispatchEvent(new win.Event('focusin', { bubbles: true }));
  await new Promise(r => setTimeout(r, 350));    // past the 300ms keyboard wait

  assert.strictEqual(calls.length, 1, 'scrollIntoView was not called exactly once');
  assert.strictEqual(calls[0].el, field);
  win.close();
});

test('the same focus does nothing on desktop', async () => {
  const { win, doc } = await boot({ phone: false });
  win.openAdd();
  const field = $(doc, '#fAlbum');

  let called = false;
  win.Element.prototype.scrollIntoView = function () { called = true; };
  field.dispatchEvent(new win.Event('focusin', { bubbles: true }));
  await new Promise(r => setTimeout(r, 350));

  assert.strictEqual(called, false, 'the desktop layout does not need this scroll');
  win.close();
});
