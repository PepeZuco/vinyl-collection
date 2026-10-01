/* The spotify playlists item in the header's "more actions" menu, booted in a real DOM.
 *
 * Same boot shape as tests/test_phone_dom.js — the page as Flask renders it,
 * CDN scripts stripped, /static inlined, fetch stubbed — and the same
 * discipline: every test closes its window in a finally, or jsdom's
 * requestAnimationFrame loop keeps node's event loop alive and the run hangs
 * instead of reporting.
 *
 * What is worth testing: the item is edit-mode only, the panel offers to
 * connect when there is no login, and a sync keeps asking while the server
 * reports it is still reading albums.
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

async function boot(opts) {
  const authed = !!(opts && opts.authed);
  const connected = !!(opts && opts.connected);
  // Answers for successive sync POSTs; the last one repeats.
  const syncs = (opts && opts.syncs) || [];

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
  win.fetch = async (url, init) => {
    const u = String(url);
    asked.push(u);
    const json = body => ({ ok: true, status: 200, json: async () => body,
                            text: async () => JSON.stringify(body) });
    if (u.endsWith('/api/auth/status')) return json({ authed });
    if (u.endsWith('/api/records')) return json([]);
    if (u.endsWith('/api/places')) return json([]);
    if (u.endsWith('/api/spotify/account')) {
      return json({ configured: true, connected, display_name: 'Me',
                    redirect_uri: 'https://x/api/spotify/callback',
                    playlists: { all: 'Zucoloto Vinyl Collection',
                                 liked: 'Zucoloto Vinyl Collection — Liked' } });
    }
    if (u.includes('/api/spotify/playlists/')) {
      const [status, body] = syncs.length > 1 ? syncs.shift() : syncs[0];
      return { ok: status < 300, status, json: async () => body,
               text: async () => JSON.stringify(body) };
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


const DONE = { kind: 'all', name: 'Zucoloto Vinyl Collection', created: true,
               url: 'https://open.spotify.com/playlist/PL1', total: 42, added: 42,
               removed: 0, records: 4, bad_links: [], unmatched: ['A — B: Lost Song'] };

test('a visitor is not offered the spotify playlists item', async () => {
  const { win, doc } = await boot({ authed: false });
  try {
    assert.strictEqual(doc.getElementById('playlistsBtn').style.display, 'none');
  } finally { win.close(); }
});

test('edit mode reveals the spotify playlists item', async () => {
  const { win, doc } = await boot({ authed: true });
  try {
    assert.notStrictEqual(doc.getElementById('playlistsBtn').style.display, 'none');
  } finally { win.close(); }
});

test('without a Spotify login the panel offers to connect', async () => {
  const { win, doc } = await boot({ authed: true, connected: false });
  try {
    press(win, doc.getElementById('playlistsBtn'));
    await settle();
    assert.ok(!doc.getElementById('playlistsOverlay').classList.contains('hidden'));
    assert.ok(doc.getElementById('spotifyConnectBtn'), 'no connect button');
    assert.strictEqual(doc.querySelectorAll('.playlist-row').length, 0);
  } finally { win.close(); }
});

test('connected, the panel lists both playlists', async () => {
  const { win, doc } = await boot({ authed: true, connected: true });
  try {
    press(win, doc.getElementById('playlistsBtn'));
    await settle();
    const names = [...doc.querySelectorAll('.playlist-name')].map(e => e.textContent);
    assert.deepStrictEqual(names, ['Zucoloto Vinyl Collection',
                                   'Zucoloto Vinyl Collection — Liked']);
  } finally { win.close(); }
});

test('a sync keeps asking while albums are being read, then shows the result', async () => {
  const { win, doc, asked } = await boot({
    authed: true, connected: true,
    syncs: [[202, { incomplete: true, done: 100, total: 300 }],
            [202, { incomplete: true, done: 200, total: 300 }],
            [200, DONE]],
  });
  try {
    press(win, doc.getElementById('playlistsBtn'));
    await settle();
    press(win, doc.querySelector('.playlist-row[data-kind="all"] button'));
    await settle(); await settle();

    assert.strictEqual(asked.filter(u => u.includes('/api/spotify/playlists/all')).length, 3);
    const row = doc.querySelector('.playlist-row[data-kind="all"]').textContent;
    assert.match(row, /created · 42 tracks from 4 records/);
    assert.match(row, /1 skipped/);
    assert.strictEqual(doc.querySelector('.playlist-status a').getAttribute('href'),
                       'https://open.spotify.com/playlist/PL1');
  } finally { win.close(); }
});

test('a failed sync says so on its row', async () => {
  const { win, doc } = await boot({ authed: true, connected: true,
                                    syncs: [[502, { error: 'Spotify returned 500' }]] });
  try {
    press(win, doc.getElementById('playlistsBtn'));
    await settle();
    press(win, doc.querySelector('.playlist-row[data-kind="liked"] button'));
    await settle(); await settle();
    const st = doc.querySelector('.playlist-row[data-kind="liked"] .playlist-status');
    assert.ok(st.classList.contains('err'));
    assert.match(st.textContent, /Spotify returned 500/);
  } finally { win.close(); }
});
