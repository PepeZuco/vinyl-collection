/* The backups item in the header's "more actions" menu, booted in a real DOM.
 *
 * Same boot shape as tests/test_phone_dom.js — the page as Flask renders it,
 * CDN scripts stripped, /static inlined, fetch stubbed — and the same
 * discipline: every test closes its window in a finally, or jsdom's
 * requestAnimationFrame loop keeps node's event loop alive and the run hangs
 * instead of reporting.
 *
 * What is worth testing here is the boundary, not the markup: a snapshot is
 * the whole collection, so the item must not exist for a visitor, and every
 * row must point at the endpoint by the snapshot's own name.
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');

const JSDOM_PATH = process.env.VINYL_JSDOM_PATH;
Module.globalPaths.push(JSDOM_PATH);
const { JSDOM, VirtualConsole } = require(path.join(JSDOM_PATH, 'jsdom'));

const ROOT = path.join(__dirname, '..');
const PAGE = process.env.VINYL_PAGE_HTML;

let bootCount = 0;

const SNAPSHOTS = [
  { name: 'vinyl-2026-09-19.db', date: '2026-09-19', bytes: 49 * 1024 * 1024 },
  { name: 'vinyl-2026-09-18.db', date: '2026-09-18', bytes: 48 * 1024 * 1024 },
];

async function boot(opts) {
  const authed = !!(opts && opts.authed);
  const backups = (opts && opts.backups) || SNAPSHOTS;
  const failBackups = !!(opts && opts.failBackups);

  let html = fs.readFileSync(PAGE, 'utf8');
  html = html.replace(/<script src="https:\/\/[^"]+"><\/script>/g, '');
  html = html.replace(/<script src="\/static\/([^"]+)"><\/script>/g, (_, file) =>
    '<script>' + fs.readFileSync(path.join(ROOT, 'static', file), 'utf8') + '</script>');

  const errors = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', e => errors.push(String((e && e.message) || e)));

  const dom = new JSDOM(html, {
    runScripts: 'outside-only',
    pretendToBeVisual: true,
    url: 'http://b' + (++bootCount) + '.localhost/',
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
  win.marked = { Renderer: function () {}, use() {}, setOptions() {}, parse: s => String(s) };
  win.HTMLCanvasElement.prototype.getContext = () => ({});
  win.matchMedia = q => ({ media: q, matches: false, addEventListener() {},
                           removeEventListener() {}, addListener() {}, removeListener() {} });
  win.confirm = () => true;
  win.scrollTo = () => {};
  win.Element.prototype.scrollIntoView = function () {};
  win.Element.prototype.scrollTo = function () {};
  win.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
  win.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };

  const asked = [];
  win.fetch = async (url) => {
    const u = String(url);
    asked.push(u);
    const json = body => ({ ok: true, status: 200, json: async () => body,
                            text: async () => JSON.stringify(body) });
    if (u.endsWith('/api/auth/status')) return json({ authed });
    if (u.endsWith('/api/records')) return json([]);
    if (u.endsWith('/api/places')) return json([]);
    if (u.includes('/api/backups')) {
      if (failBackups) return { ok: false, status: 500, json: async () => ({ error: 'boom' }),
                                text: async () => 'boom' };
      return json({ backups, keep_days: 5 });
    }
    return json({ ok: true });
  };

  const source = [...win.document.querySelectorAll('script')]
    .map(el => el.textContent).filter(t => t.trim()).join('\n;\n')
    + '\n;window.__peek = function (expr) { return eval(expr); };';
  try { win.eval(source); } catch (e) { errors.push(String(e && e.message)); }
  for (let i = 0; i < 20; i++) await new Promise(r => setTimeout(r, 0));

  return { win, doc: win.document, errors, asked, read: expr => win.__peek(expr) };
}

async function settle() {
  for (let i = 0; i < 20; i++) await new Promise(r => setTimeout(r, 0));
}

function press(win, el) {
  const code = el.getAttribute && el.getAttribute('onclick');
  if (code) {
    win.__peek('(function(event){' + code + '})').call(el, new win.MouseEvent('click'));
    return;
  }
  el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
}

test('a visitor is not offered the backups item', async () => {
  const { win, doc } = await boot({ authed: false });
  try {
    assert.strictEqual(doc.getElementById('backupsBtn').style.display, 'none');
  } finally { win.close(); }
});

test('edit mode reveals the backups item', async () => {
  const { win, doc } = await boot({ authed: true });
  try {
    assert.notStrictEqual(doc.getElementById('backupsBtn').style.display, 'none');
  } finally { win.close(); }
});

test('opening backups lists a download link per snapshot, newest first', async () => {
  const { win, doc } = await boot({ authed: true });
  try {
    press(win, doc.getElementById('backupsBtn'));
    await settle();

    assert.ok(!doc.getElementById('backupsOverlay').classList.contains('hidden'),
              'the overlay stayed shut');
    const links = [...doc.querySelectorAll('#backupsBody a')];
    assert.deepStrictEqual(links.map(a => a.getAttribute('href')), [
      '/api/backups/vinyl-2026-09-19.db',
      '/api/backups/vinyl-2026-09-18.db',
    ]);
    const body = doc.getElementById('backupsBody').textContent;
    assert.match(body, /2026-09-19/);
    assert.match(body, /49(\.0)? MB/, `no readable size in: ${body}`);
  } finally { win.close(); }
});

test('an empty backup folder says so instead of showing a blank panel', async () => {
  const { win, doc } = await boot({ authed: true, backups: [] });
  try {
    press(win, doc.getElementById('backupsBtn'));
    await settle();

    assert.strictEqual(doc.querySelectorAll('#backupsBody a').length, 0);
    assert.ok(doc.getElementById('backupsBody').textContent.trim().length > 0,
              'an empty folder rendered an empty panel');
  } finally { win.close(); }
});

test('a failed request says so instead of claiming there are no snapshots', async () => {
  const { win, doc } = await boot({ authed: true, failBackups: true });
  try {
    press(win, doc.getElementById('backupsBtn'));
    await settle();

    const body = doc.getElementById('backupsBody').textContent;
    assert.doesNotMatch(body, /no snapshots yet/,
      'a server error was reported as an empty backup folder');
    assert.match(body, /could not/i, `no failure message in: ${body}`);
  } finally { win.close(); }
});
