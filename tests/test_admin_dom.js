/* The admin page (places, data, spotify) opened from the header's menu, booted in a real DOM.
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
  opts = opts || {};
  let resolveCalls = 0;
  const posted = [];
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
  win.fetch = async (url, init) => {
    const u = String(url);
    asked.push(u);
    const json = body => ({ ok: true, status: 200, json: async () => body,
                            text: async () => JSON.stringify(body) });
    if (u.endsWith('/api/auth/status')) return json({ authed });
    const body = init && init.body && typeof init.body === 'string' ? JSON.parse(init.body) : null;
    if (u.endsWith('/api/spotify/wishlist-scan')) return json(opts.scanResult);
    if (u.endsWith('/api/spotify/wishlist-scan/resolve')) {
      if (opts.failResolveAfter !== undefined && ++resolveCalls > opts.failResolveAfter)
        return { ok: false, status: 502, json: async () => ({ error: "Couldn't reach MusicBrainz" }) };
      return json({ albums: body.albums.map(a => Object.assign({}, a,
        a.duplicate_of ? {} : { vinyl: opts.vinyl ? opts.vinyl(a) : 'confirmed', cover_data: '' })) });
    }
    if (u.endsWith('/api/search/genres')) return json({ genres: body.releases.map(() => 'Rock') });
    if (u.endsWith('/api/records') && init && init.method === 'POST') {
      posted.push(body);
      return json(Object.assign({ id: 100 + posted.length }, body));
    }
    if (u.endsWith('/api/records')) return json([]);
    if (u.endsWith('/api/places')) return json([]);
    if (u.includes('/api/backups')) {
      if (failBackups) return { ok: false, status: 500, json: async () => ({ error: 'boom' }),
                                text: async () => 'boom' };
      return json({ backups, keep_days: 5 });
    }
    if (u.endsWith('/api/spotify/account') && opts.failAccount)
      return { ok: false, status: 500, json: async () => ({}), text: async () => '' };
    if (u.endsWith('/api/spotify/account')) return json(opts && opts.account || { configured: true, connected: false });
    if (u.endsWith('/api/spotify/me/playlists')) return json({ playlists: (opts && opts.playlists) || [] });
    if (u.endsWith('/api/spotify/playlists')) return json({ playlists: [], genres: [], places: [] });
    return json({ ok: true });
  };

  const source = [...win.document.querySelectorAll('script')]
    .map(el => el.textContent).filter(t => t.trim()).join('\n;\n')
    + '\n;window.__peek = function (expr) { return eval(expr); };';
  try { win.eval(source); } catch (e) { errors.push(String(e && e.message)); }
  for (let i = 0; i < 20; i++) await new Promise(r => setTimeout(r, 0));

  return { win, doc: win.document, errors, asked, posted, read: expr => win.__peek(expr) };
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

test('a visitor is offered no admin item', async () => {
  const { win, doc } = await boot({ authed: false });
  try {
    assert.strictEqual(doc.getElementById('adminBtn').style.display, 'none');
  } finally { win.close(); }
});

test('the old places, export, backups and import items are gone from the menu', async () => {
  const { win, doc } = await boot({ authed: true });
  try {
    const menu = doc.getElementById('morePanel');
    for (const id of ['placesBtn', 'backupsBtn', 'exportBtn', 'importLabel'])
      assert.strictEqual(menu.querySelector('#' + id), null, id + ' is still in the menu');
    assert.strictEqual(doc.getElementById('placesOverlay'), null);
    assert.strictEqual(doc.getElementById('backupsOverlay'), null);
  } finally { win.close(); }
});

test('edit mode opens the admin page from the menu with all three sections', async () => {
  const { win, doc } = await boot({ authed: true });
  try {
    assert.notStrictEqual(doc.getElementById('adminBtn').style.display, 'none');
    press(win, doc.getElementById('adminBtn'));
    await settle();
    assert.ok(doc.getElementById('adminPage').classList.contains('visible'));
    assert.ok(doc.getElementById('collectionPage').classList.contains('hidden'));
    assert.ok(doc.getElementById('morePanel').classList.contains('hidden'), 'menu stayed open');
    for (const id of ['placesBody', 'exportBtn', 'importInput', 'backupsBody', 'adminSpotifyBody'])
      assert.ok(doc.querySelector('#adminPage #' + id), id + ' is not on the admin page');
    assert.strictEqual(doc.getElementById('filterBar').style.display, 'none');
  } finally { win.close(); }
});

test('the admin page lists a download link per snapshot, newest first', async () => {
  const { win, doc } = await boot({ authed: true });
  try {
    press(win, doc.getElementById('adminBtn'));
    await settle();
    const links = [...doc.querySelectorAll('#backupsBody a')];
    assert.deepStrictEqual(links.map(a => a.getAttribute('href')),
      ['/api/backups/vinyl-2026-09-19.db', '/api/backups/vinyl-2026-09-18.db']);
  } finally { win.close(); }
});

test('an unanswered backups request says so instead of looking empty', async () => {
  const { win, doc } = await boot({ authed: true, failBackups: true });
  try {
    press(win, doc.getElementById('adminBtn'));
    await settle();
    assert.match(doc.getElementById('backupsBody').textContent, /could not read the backups/);
  } finally { win.close(); }
});

test('the places editor renders on the admin page', async () => {
  const { win, doc } = await boot({ authed: true });
  try {
    press(win, doc.getElementById('adminBtn'));
    await settle();
    assert.match(doc.getElementById('placesBody').textContent, /No places yet|add a new place/);
  } finally { win.close(); }
});

test('locking while on admin goes back to the collection', async () => {
  const { win, doc } = await boot({ authed: true });
  try {
    press(win, doc.getElementById('adminBtn'));
    await settle();
    win.setAuthed(false);
    await settle();
    assert.ok(!doc.getElementById('adminPage').classList.contains('visible'));
    assert.ok(!doc.getElementById('collectionPage').classList.contains('hidden'));
  } finally { win.close(); }
});

const CONNECTED = { configured: true, connected: true, display_name: 'Me' };
const PLAYLISTS = [{ id: 'PL', name: 'Road trip', image_url: '', track_count: 3, owner: 'Me' }];
const album = (name, extra) => Object.assign({ key: 'a|' + name.toLowerCase(), artist: 'A',
  album_name: name, year: '1970', songs: ['s1'], spotify_image: '', unverified: false,
  duplicate_of: null, have_it: null }, extra);

async function openSpotifyTool(opts) {
  const ctx = await boot(Object.assign({ authed: true, account: CONNECTED, playlists: PLAYLISTS }, opts));
  press(ctx.win, ctx.doc.getElementById('adminBtn'));
  await settle();
  return ctx;
}

async function runScan(ctx) {
  press(ctx.win, ctx.doc.querySelector('#adminSpotifyBody [data-playlist="PL"]'));
  await settle();
  press(ctx.win, ctx.doc.getElementById('adminScanBtn'));
  for (let i = 0; i < 5; i++) await settle();
}

test('not connected shows the connect button and no playlists', async () => {
  const { win, doc } = await openSpotifyTool({ account: { configured: true, connected: false } });
  try {
    const body = doc.getElementById('adminSpotifyBody');
    assert.ok(body.querySelector('[onclick*="/api/spotify/connect"]'), 'no connect button');
    assert.strictEqual(body.querySelectorAll('[data-playlist]').length, 0);
  } finally { win.close(); }
});

test('connected lists the playlists with their song counts', async () => {
  const { win, doc } = await openSpotifyTool();
  try {
    const row = doc.querySelector('#adminSpotifyBody [data-playlist="PL"]');
    assert.ok(row, 'playlist row missing');
    assert.match(row.textContent, /Road trip/);
    assert.match(row.textContent, /3 songs/);
  } finally { win.close(); }
});

test('a scan shows one row per album with the review rules applied', async () => {
  const scanResult = { song_count: 4, unplaced: 1, truncated: false, albums: [
    album('Confirmed'), album('Likely'), album('Never'),
    album('Owned', { duplicate_of: { id: 7, artist: 'A', album_name: 'Owned' }, have_it: true })] };
  const vinyl = a => ({ Confirmed: 'confirmed', Likely: 'likely', Never: 'none' })[a.album_name];
  const { win, doc } = await openSpotifyTool({ scanResult, vinyl });
  try {
    await runScan({ win, doc });
    const box = name => doc.querySelector(`#adminSpotifyBody [data-album="a|${name.toLowerCase()}"] input[type=checkbox]`);
    assert.strictEqual(box('Confirmed').checked, true);
    assert.strictEqual(box('Confirmed').disabled, false);
    assert.strictEqual(box('Likely').checked, false);
    assert.strictEqual(box('Likely').disabled, false);
    assert.strictEqual(box('Never').disabled, true);
    assert.strictEqual(box('Owned').disabled, true);
    assert.match(doc.querySelector('#adminSpotifyBody [data-album="a|owned"]').textContent, /in collection/);
    assert.match(doc.getElementById('adminSpotifyBody').textContent, /1 song.*could not be placed/);
    assert.match(doc.getElementById('adminAddBtn').textContent, /add 1 to wishlist/);
  } finally { win.close(); }
});

test('adding posts the ticked albums as wishlist records', async () => {
  const scanResult = { song_count: 1, unplaced: 0, truncated: false, albums: [album('Confirmed')] };
  const ctx = await openSpotifyTool({ scanResult });
  try {
    await runScan(ctx);
    press(ctx.win, ctx.doc.getElementById('adminAddBtn'));
    for (let i = 0; i < 5; i++) await settle();
    assert.strictEqual(ctx.posted.length, 1);
    assert.deepStrictEqual(
      { artist: ctx.posted[0].artist, album_name: ctx.posted[0].album_name,
        have_it: ctx.posted[0].have_it, genre: ctx.posted[0].genre },
      { artist: 'A', album_name: 'Confirmed', have_it: false, genre: 'Rock' });
    assert.match(ctx.doc.querySelector('[data-album="a|confirmed"]').textContent, /on wishlist/);
  } finally { ctx.win.close(); }
});

test('a failed chunk keeps what was resolved and shows the error', async () => {
  const albums = Array.from({ length: 30 }, (_, i) => album('Album ' + i));
  const scanResult = { song_count: 30, unplaced: 0, truncated: false, albums };
  const ctx = await openSpotifyTool({ scanResult, failResolveAfter: 1 });
  try {
    await runScan(ctx);
    const body = ctx.doc.getElementById('adminSpotifyBody');
    assert.match(body.textContent, /Couldn't reach MusicBrainz/);
    assert.strictEqual(ctx.doc.querySelector('[data-album="a|album 0"] input').disabled, false);
    assert.strictEqual(ctx.doc.querySelector('[data-album="a|album 29"] input').disabled, true);
  } finally { ctx.win.close(); }
});

test('a cut playlist says how many songs were read', async () => {
  const scanResult = { song_count: 500, unplaced: 0, truncated: true, albums: [album('X')] };
  const ctx = await openSpotifyTool({ scanResult });
  try {
    await runScan(ctx);
    assert.match(ctx.doc.getElementById('adminSpotifyBody').textContent, /first 500 songs/);
  } finally { ctx.win.close(); }
});

test('an unreadable Spotify account says so instead of loading forever', async () => {
  const ctx = await openSpotifyTool({ failAccount: true });
  try {
    const text = ctx.doc.getElementById('adminSpotifyBody').textContent;
    assert.match(text, /could not read the Spotify account/);
    assert.doesNotMatch(text, /loading/);
  } finally { ctx.win.close(); }
});

test('the mobile More sheet opens the admin page in edit mode', async () => {
  const { win, doc } = await boot({ authed: true });
  try {
    const btn = doc.querySelector('#mtabMorePanel #mtabAdmin');
    assert.ok(btn, 'no Admin item in the More sheet');
    press(win, btn);
    await settle();
    assert.ok(doc.getElementById('adminPage').classList.contains('visible'));
    assert.ok(doc.getElementById('mtabAdmin').classList.contains('active'));
    assert.ok(doc.getElementById('mtabMoreBtn').classList.contains('active'));
  } finally { win.close(); }
});
