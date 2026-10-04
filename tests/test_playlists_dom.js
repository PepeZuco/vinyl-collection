/* The spotify playlists item in the header's "more actions" menu, booted in a real DOM.
 *
 * Same boot shape as tests/test_phone_dom.js — the page as Flask renders it,
 * CDN scripts stripped, /static inlined, fetch stubbed — and the same
 * discipline: every test closes its window in a finally, or jsdom's
 * requestAnimationFrame loop keeps node's event loop alive and the run hangs
 * instead of reporting.
 *
 * What is worth testing: the item is edit-mode only, the panel offers to connect when there is no login, the saved playlists are listed, the form previews its count and name, a create that already exists resyncs that row, a sync keeps asking while the server reports it is still reading albums, create is held while a sync runs, and a delete removes the row.
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
  opts = opts || {};
  const authed = !!opts.authed;
  const connected = !!opts.connected;
  // Answers for successive sync POSTs; the last one repeats.
  const syncs = opts.syncs || [];
  const saved = (opts.saved || []).map(p => Object.assign({}, p));
  const collection = opts.records || [];
  const created = opts.created || null;   // [status, body] for POST /api/spotify/playlists
  const deleted = opts.deleted || [200, { ok: true }];
  const posted = [];

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
    if (u.endsWith('/api/records')) return json(collection);
    if (u.endsWith('/api/places')) return json([]);
    if (u.endsWith('/api/spotify/account')) {
      return json({ configured: true, connected, display_name: 'Me',
                    redirect_uri: 'https://x/api/spotify/callback' });
    }
    const method = (init && init.method) || 'GET';
    const reply = ([status, body]) => ({ ok: status < 300, status, json: async () => body,
                                         text: async () => JSON.stringify(body) });
    if (u.endsWith('/api/spotify/playlists') && method === 'GET') {
      return json({ playlists: saved, genres: ['Jazz', 'Rock'], places: ['Tracks'] });
    }
    if (u.endsWith('/api/spotify/playlists') && method === 'POST') {
      posted.push(JSON.parse(init.body));
      return reply(created);
    }
    if (/\/api\/spotify\/playlists\/\d+\/sync$/.test(u)) {
      return reply(syncs.length > 1 ? syncs.shift() : syncs[0]);
    }
    if (/\/api\/spotify\/playlists\/\d+$/.test(u) && method === 'DELETE') return reply(deleted);
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

const EVERY = { id: 1, name: 'Zucoloto Vinyl Collection', filters: { liked: false },
                summary: 'every track · whole collection', url: '', last_synced_at: null,
                last_total: null, last_records: null };
const LIKED = { id: 2, name: 'Zucoloto Vinyl Collection — Liked', filters: { liked: true },
                summary: 'liked songs · whole collection',
                url: 'https://open.spotify.com/playlist/PL2', last_synced_at: '2026-10-01T10:00:00',
                last_total: 42, last_records: 7 };

const DONE = { spotify_id: 'PL1', name: 'Zucoloto Vinyl Collection', created: true,
               url: 'https://open.spotify.com/playlist/PL1', total: 42, added: 42,
               removed: 0, records: 4,
               bad_links: [{ label: 'C — D', cover_url: '' },
                           { label: 'E — F', cover_url: '/api/records/9/cover?v=h' }],
               unmatched: [{ label: 'A — B', cover_url: '/api/records/7/cover?v=h',
                             songs: ['Lost Song'] }],
               playlist: Object.assign({}, EVERY, { url: 'https://open.spotify.com/playlist/PL1',
                                                    last_synced_at: '2026-10-02T09:00:00',
                                                    last_total: 42, last_records: 4 }) };

const RECS = [
  { have_it: true, spotify_url: 'https://open.spotify.com/album/a', genre: 'Rock', year: '1973',
    tracks: JSON.stringify([{ side: 'A', title: 's', liked_at: '2026-01-01' }]) },
  { have_it: true, spotify_url: 'https://open.spotify.com/album/b', genre: 'Jazz', year: '1991',
    tracks: '' },
];

async function openPanel(opts) {
  const b = await boot(Object.assign({ authed: true, connected: true }, opts));
  press(b.win, b.doc.getElementById('playlistsBtn'));
  await settle(); await settle();
  return b;
}

const row = (doc, id) => doc.querySelector(`.playlist-row[data-id="${id}"]`);

test('without a Spotify login the panel offers to connect', async () => {
  const { win, doc } = await openPanel({ connected: false });
  try {
    assert.ok(doc.getElementById('playlistsPage').classList.contains('visible'));
    assert.ok(doc.getElementById('spotifyConnectBtn'), 'no connect button');
    assert.strictEqual(doc.querySelectorAll('.playlist-row').length, 0);
  } finally { win.close(); }
});

test('connected, the panel lists the saved playlists with their last result', async () => {
  const { win, doc } = await openPanel({ saved: [EVERY, LIKED] });
  try {
    const names = [...doc.querySelectorAll('.playlist-name')].map(e => e.textContent);
    assert.deepStrictEqual(names, ['Zucoloto Vinyl Collection', 'Zucoloto Vinyl Collection — Liked']);
    const tags = id => [...row(doc, id).querySelectorAll('.pl-tag')].map(e => e.textContent);
    assert.deepStrictEqual(tags(1), ['every track', 'whole collection']);
    assert.deepStrictEqual(tags(2), ['liked songs', 'whole collection']);
    assert.ok(row(doc, 2).querySelector('.pl-tag.liked .ti-heart-filled'), 'liked songs has no heart');
    assert.match(row(doc, 1).textContent, /never synced/);
    assert.match(row(doc, 2).textContent, /42 tracks · synced/);
    assert.strictEqual(row(doc, 2).querySelector('a').getAttribute('href'),
                       'https://open.spotify.com/playlist/PL2');
  } finally { win.close(); }
});

test('a synced playlist links to Spotify and shows its cover', async () => {
  const SYNCED = Object.assign({}, LIKED, { url: 'https://open.spotify.com/playlist/PL2',
                                            cover_url: 'https://mosaic.scdn.co/640/PL2' });
  const { win, doc } = await openPanel({ saved: [EVERY, SYNCED] });
  try {
    const r = row(doc, 2);
    assert.strictEqual(r.querySelector('.playlist-open').getAttribute('href'), SYNCED.url);
    assert.strictEqual(r.querySelector('.playlist-name a').getAttribute('href'), SYNCED.url);
    assert.strictEqual(r.querySelector('.playlist-art img').getAttribute('src'), SYNCED.cover_url);
    assert.ok(!row(doc, 1).querySelector('.playlist-open'), 'a never-synced row got a link');
  } finally { win.close(); }
});

test('each filter gets its own chip, and only the first draw pops in', async () => {
  const PICKY = Object.assign({}, LIKED, { id: 3, filters: { liked: true, genres: ['Jazz', 'Rock'],
    decades: [1960, 1970], pepe_min: 4, jenni_min: 3.5, rating_mode: 'or',
    places: ['Shop'], source: 'all' } });
  const { win, doc } = await openPanel({ saved: [PICKY] });
  try {
    const tags = () => row(doc, 3).querySelectorAll('.pl-tag');
    assert.deepStrictEqual([...tags()].map(e => e.textContent),
      ['liked songs', '+ compilations', 'Jazz', 'Rock', '1960s, 1970s', 'Pepe ≥ 4 or Jenni ≥ 3.5', 'Shop']);
    assert.ok(row(doc, 3).querySelector('.playlist-tags.enter'));
    // cover, name and the Spotify logo — no separate "open" text link
    assert.strictEqual(row(doc, 3).querySelectorAll('a[href]').length, 3);
    win.renderPlaylistList();
    assert.ok(!row(doc, 3).querySelector('.playlist-tags.enter'), 'the chips popped in again');
  } finally { win.close(); }
});

test('with nothing saved the new-playlist form starts open', async () => {
  const { win, doc } = await openPanel({ saved: [] });
  try {
    assert.ok(doc.getElementById('playlistNew').open);
    assert.match(doc.getElementById('playlistList').textContent, /no playlists yet/);
  } finally { win.close(); }
});

test('the form previews the match count and the name as filters change', async () => {
  const { win, doc } = await openPanel({ saved: [EVERY], records: RECS });
  try {
    assert.match(doc.getElementById('plCount').textContent, /^1 record matches/);
    assert.strictEqual(doc.getElementById('plName').value, 'Zucoloto Vinyl — Liked');

    const every = doc.querySelector('input[name="plLiked"][value="0"]');
    every.checked = true;
    win.__peek('playlistFormInput')(every);
    assert.match(doc.getElementById('plCount').textContent, /^2 records match/);

    const genre = doc.querySelector('select.pl-add[data-field="genres"]');
    genre.value = 'Jazz';
    win.__peek('playlistChipAdd')(genre);
    assert.match(doc.getElementById('plCount').textContent, /^1 record matches/);
    assert.strictEqual(doc.getElementById('plName').value, 'Zucoloto Vinyl · Jazz');

    const seventies = doc.querySelector('input[data-field="decades"][value="1970"]');
    seventies.checked = true;
    win.__peek('playlistDecadeToggle')(seventies);
    assert.ok(doc.getElementById('plCount').classList.contains('warn'), '0 matches is not flagged');
    assert.strictEqual(doc.querySelectorAll('#plMatches .pl-match').length, 0);
  } finally { win.close(); }
});

test('the decade field picks any set of decades, not a range', async () => {
  const { win, doc } = await openPanel({ saved: [EVERY], records: RECS });
  try {
    const every = doc.querySelector('input[name="plLiked"][value="0"]');
    every.checked = true;
    win.__peek('playlistFormInput')(every);
    assert.strictEqual(doc.querySelectorAll('#plMatches .pl-match').length, 2);
    const pill = d => doc.querySelector(`input[data-field="decades"][value="${d}"]`);
    assert.strictEqual(pill(1970).parentElement.textContent.trim(), '70s');
    const toggle = (d, on) => { pill(d).checked = on; win.__peek('playlistDecadeToggle')(pill(d)); };

    toggle(1970, true);
    assert.match(doc.getElementById('plCount').textContent, /^1 record matches/);
    const shown = doc.querySelectorAll('#plMatches .pl-match');
    assert.strictEqual(shown.length, 1);
    assert.match(shown[0].textContent, /1973/);
    assert.strictEqual(doc.getElementById('plName').value, 'Zucoloto Vinyl · 1970s');

    // The 80s sit between them but stay out; the 90s add the 1991 record.
    toggle(1990, true);
    assert.match(doc.getElementById('plCount').textContent, /^2 records match/);
    assert.strictEqual(doc.getElementById('plName').value, 'Zucoloto Vinyl · 1970s, 1990s');
    toggle(1970, false);
    assert.match(doc.getElementById('plCount').textContent, /^1 record matches/);
    assert.match(doc.querySelector('#plMatches .pl-match').textContent, /1991/);
  } finally { win.close(); }
});

test('a typed name stops following the filters; clearing it resumes', async () => {
  const { win, doc } = await openPanel({ saved: [EVERY], records: RECS });
  try {
    const name = doc.getElementById('plName');
    name.value = 'Road trip';
    win.__peek('playlistFormInput')(name);
    const every = doc.querySelector('input[name="plLiked"][value="0"]');
    every.checked = true;
    win.__peek('playlistFormInput')(every);
    assert.strictEqual(doc.getElementById('plName').value, 'Road trip');

    name.value = '';
    win.__peek('playlistFormInput')(name);
    assert.strictEqual(doc.getElementById('plName').value, 'Zucoloto Vinyl');
  } finally { win.close(); }
});

test('the and/or switch only shows once both ratings are set', async () => {
  const { win, doc } = await openPanel({ saved: [EVERY] });
  try {
    const mode = () => doc.getElementById('plMode');
    assert.ok(mode().hidden);
    const pepe = doc.querySelector('select[data-field="pepe_min"]');
    pepe.value = '4';
    win.__peek('playlistFormInput')(pepe);
    assert.ok(mode().hidden);
    const jenni = doc.querySelector('select[data-field="jenni_min"]');
    jenni.value = '3.5';
    win.__peek('playlistFormInput')(jenni);
    assert.ok(!mode().hidden);
  } finally { win.close(); }
});

test('create posts the filters, adds the row and syncs it', async () => {
  const NEW = Object.assign({}, EVERY, { id: 3, name: 'Zucoloto Vinyl — Liked',
                                         filters: { liked: true }, summary: 'liked songs · whole collection' });
  const { win, doc, asked, posted } = await openPanel({
    saved: [EVERY], records: RECS, created: [201, { playlist: NEW, existed: false }],
    syncs: [[200, Object.assign({}, DONE, { playlist: Object.assign({}, NEW, { last_total: 9,
            last_synced_at: '2026-10-02T09:00:00', url: 'https://open.spotify.com/playlist/PL3' }) })]],
  });
  try {
    press(win, doc.getElementById('plCreate'));
    await settle(); await settle();
    assert.deepStrictEqual(posted[0], { filters: { liked: true }, name: 'Zucoloto Vinyl — Liked' });
    assert.ok(asked.some(u => u.endsWith('/api/spotify/playlists/3/sync')));
    assert.match(row(doc, 3).textContent, /9 tracks · synced/);
  } finally { win.close(); }
});

test('creating filters that already exist highlights and resyncs that row', async () => {
  const { win, doc, asked } = await openPanel({
    saved: [EVERY, LIKED], records: RECS, created: [200, { playlist: LIKED, existed: true }],
    syncs: [[200, Object.assign({}, DONE, { playlist: LIKED })]],
  });
  try {
    press(win, doc.getElementById('plCreate'));
    await settle(); await settle();
    assert.strictEqual(doc.querySelectorAll('.playlist-row').length, 2, 'a duplicate row appeared');
    assert.ok(row(doc, 2).classList.contains('hl'));
    assert.match(row(doc, 2).textContent, /already exists — resynced/);
    assert.ok(asked.some(u => u.endsWith('/api/spotify/playlists/2/sync')));
  } finally { win.close(); }
});

test('a rejected filter shows the server error under the form', async () => {
  const { win, doc } = await openPanel({
    saved: [EVERY], records: RECS, created: [400, { error: 'pepe_min: must be 0.5 to 5', field: 'pepe_min' }] });
  try {
    press(win, doc.getElementById('plCreate'));
    await settle();
    const err = doc.getElementById('plError');
    assert.ok(!err.hidden);
    assert.match(err.textContent, /pepe_min/);
  } finally { win.close(); }
});

test('a sync keeps asking while the server is still reading albums', async () => {
  const { win, doc, asked } = await openPanel({
    saved: [EVERY],
    syncs: [[202, { incomplete: true, done: 100, total: 300 }],
            [202, { incomplete: true, done: 200, total: 300 }],
            [200, DONE]],
  });
  try {
    press(win, row(doc, 1).querySelector('.playlist-sync'));
    await settle(); await settle();
    assert.strictEqual(asked.filter(u => u.endsWith('/api/spotify/playlists/1/sync')).length, 3);
    const text = row(doc, 1).textContent;
    assert.match(text, /created · 42 tracks from 4 records/);
    const groups = [...doc.querySelectorAll('.skipped-group summary')].map(e => e.textContent);
    assert.match(groups[0], /^1 not found/);
    assert.match(groups[1], /^2 bad link/);
    assert.match(text, /A — B\s*Lost Song/);
    const covers = [...doc.querySelectorAll('.skipped-group img.skipped-cover')]
      .map(i => i.getAttribute('src'));
    assert.deepStrictEqual(covers, ['/api/records/7/cover?v=h', '/api/records/9/cover?v=h']);
    assert.match(text, /42 tracks · synced/, 'the row did not take the stored result');
  } finally { win.close(); }
});

test('create stays locked while no record matches', async () => {
  const { win, doc, posted } = await openPanel({ saved: [EVERY], records: RECS });
  try {
    const create = doc.getElementById('plCreate');
    assert.ok(!create.disabled);
    const noughties = doc.querySelector('input[data-field="decades"][value="2000"]');
    noughties.checked = true;
    win.__peek('playlistDecadeToggle')(noughties);
    assert.ok(create.disabled, 'create is clickable with 0 matches');
    press(win, create);
    await settle();
    assert.deepStrictEqual(posted, []);
    noughties.checked = false;
    win.__peek('playlistDecadeToggle')(noughties);
    assert.ok(!create.disabled, 'create stayed locked once records matched again');
  } finally { win.close(); }
});

test('create is held while a sync runs', async () => {
  const { win, doc, posted } = await openPanel({
    saved: [EVERY], records: RECS, syncs: [[202, { incomplete: true, done: 1, total: 300 }]] });
  // Each sync answer waits for the test, so the sync is still running when it looks.
  let release;
  const gate = new Promise(r => { release = r; });
  const answer = win.fetch;
  win.fetch = async (url, init) => {
    if (/\/sync$/.test(String(url))) await gate;
    return answer(url, init);
  };
  try {
    assert.ok(!doc.getElementById('plCreate').disabled);
    press(win, row(doc, 1).querySelector('.playlist-sync'));
    await settle();
    assert.ok(doc.getElementById('plCreate').disabled, 'create stayed clickable mid-sync');
    press(win, doc.getElementById('plCreate'));
    await settle();
    assert.deepStrictEqual(posted, []);
    release();
    await settle(); await settle();
    assert.ok(!doc.getElementById('plCreate').disabled, 'create stayed disabled after the sync');
  } finally { win.close(); }
});

test('a failed sync says so on its row', async () => {
  const { win, doc } = await openPanel({ saved: [EVERY, LIKED],
                                         syncs: [[502, { error: 'Spotify returned 500' }]] });
  try {
    press(win, row(doc, 2).querySelector('.playlist-sync'));
    await settle(); await settle();
    const st = row(doc, 2).querySelector('.playlist-status');
    assert.ok(st.classList.contains('err'));
    assert.match(st.textContent, /Spotify returned 500/);
  } finally { win.close(); }
});

test('delete confirms, calls the server and removes the row', async () => {
  const { win, doc, asked } = await openPanel({ saved: [EVERY, LIKED] });
  try {
    let asked_ = '';
    win.confirm = (m) => { asked_ = m; return true; };
    press(win, row(doc, 2).querySelector('.playlist-delete'));
    await settle(); await settle();
    assert.match(asked_, /Zucoloto Vinyl Collection — Liked/);
    assert.ok(asked.some(u => u.endsWith('/api/spotify/playlists/2')));
    assert.strictEqual(row(doc, 2), null);
    assert.ok(row(doc, 1));
  } finally { win.close(); }
});

test('a failed delete keeps the row and says why', async () => {
  const { win, doc } = await openPanel({ saved: [LIKED], deleted: [502, { error: 'Spotify returned 500' }] });
  try {
    press(win, row(doc, 2).querySelector('.playlist-delete'));
    await settle(); await settle();
    assert.ok(row(doc, 2));
    assert.match(row(doc, 2).querySelector('.playlist-status').textContent, /delete failed/);
  } finally { win.close(); }
});

test('the desktop Spotify tab opens the playlists page, not a modal', async () => {
  const { win, doc } = await boot({ authed: true, connected: true, saved: [LIKED] });
  try {
    doc.getElementById('tabPlaylists').click();
    await settle();
    assert.ok(doc.getElementById('tabPlaylists').classList.contains('active'));
    assert.ok(doc.getElementById('playlistsPage').classList.contains('visible'));
    assert.ok(doc.getElementById('collectionPage').classList.contains('hidden'));
    assert.ok(doc.getElementById('playlistNew'), 'edit mode has the new-playlist form');
    assert.ok(row(doc, 2).querySelector('.playlist-sync'));
  } finally { win.close(); }
});

test('a visitor sees the playlists as links only', async () => {
  const { win, doc, asked } = await boot({ authed: false, saved: [LIKED] });
  try {
    doc.getElementById('tabPlaylists').click();
    await settle();
    assert.ok(!asked.some(u => u.endsWith('/api/spotify/account')), 'visitor asked for the account');
    const r = row(doc, 2);
    assert.strictEqual(r.querySelector('.playlist-name a').getAttribute('href'), LIKED.url);
    assert.ok(!r.querySelector('.playlist-sync'), 'visitor got a sync button');
    assert.ok(!r.querySelector('.playlist-delete'), 'visitor got a delete button');
    assert.ok(!doc.getElementById('playlistNew'), 'visitor got the new-playlist form');
    assert.ok(!doc.querySelector('.playlist-account'), 'visitor got the account bar');
  } finally { win.close(); }
});

test('on the phone bar a visitor gets Spotify in place of Stats', async () => {
  const { win, doc } = await boot({ authed: false, saved: [LIKED] });
  try {
    assert.ok(!doc.getElementById('mtabStats'), 'Stats is still on the visitor bar');
    const btn = doc.getElementById('mtabSpotify');
    assert.ok(!btn.classList.contains('mtab-owner'), 'Spotify is hidden from visitors');
    press(win, btn);
    await settle();
    assert.ok(btn.classList.contains('active'));
    assert.ok(doc.getElementById('playlistsPage').classList.contains('visible'));
    assert.ok(!doc.getElementById('playlistsOverlay'), 'the old modal is still there');
    assert.ok(row(doc, 2).querySelector('.playlist-name a'));
    assert.ok(!row(doc, 2).querySelector('.playlist-sync'));
  } finally { win.close(); }
});
