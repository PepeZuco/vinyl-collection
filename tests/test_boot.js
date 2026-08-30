// Boots the real page in a DOM and drives it.
// Run by tests/test_boot.py so `pytest` stays the single command.
//
// Everything else in this suite tests a model in isolation. Nothing tested
// that the page actually RUNS — and the app is one 6,000-line template where a
// deleted function leaves a call site behind, a renamed id leaves a
// getElementById returning null, and neither shows up until the browser hits
// it. That has already happened once: init() kept calling buildConditionList
// after the filter rework deleted it, which would have thrown on every load.
//
// This is not a browser. There is no layout, no paint and no real event loop,
// so it proves the code runs and the DOM comes out right — not that anything
// looks right or is reachable with a mouse.

process.env.TZ = 'America/Sao_Paulo';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');

// jsdom lives outside the repo, installed by tests/test_boot.py into a scratch
// directory — the project has no npm setup and this must not give it one.
const JSDOM_PATH = process.env.VINYL_JSDOM_PATH;
if (!JSDOM_PATH) {
  console.error('VINYL_JSDOM_PATH is not set; run this through tests/test_boot.py');
  process.exit(2);
}
Module.globalPaths.push(JSDOM_PATH);
const { JSDOM, VirtualConsole } = require(path.join(JSDOM_PATH, 'jsdom'));

const ROOT = path.join(__dirname, '..');
const PAGE = process.env.VINYL_PAGE_HTML;   // the rendered template, from Flask
const RECORDS = JSON.parse(fs.readFileSync(process.env.VINYL_RECORDS_JSON, 'utf8'));

/* Every boot gets its own origin. localStorage is keyed by origin, and the app
 * persists the view mode and which crates are collapsed — so without this one
 * test's leftovers decide what the next one opens on, and a test that passes
 * alone fails in company. */
let bootCount = 0;

/* Boot the page with the network stubbed and the CDN libraries replaced by
 * stand-ins. Returns the window plus anything that went wrong on the way. */
async function boot(hash) {
  let html = fs.readFileSync(PAGE, 'utf8');

  // The CDN scripts cannot load here and are not what is under test. Chart.js,
  // d3 and marked get stand-ins below; the tag removal keeps jsdom from trying.
  html = html.replace(/<script src="https:\/\/[^"]+"><\/script>/g, '');
  // Local modules are inlined so no fetch is needed for them either.
  html = html.replace(/<script src="\/static\/([^"]+)"><\/script>/g, (_, file) =>
    '<script>' + fs.readFileSync(path.join(ROOT, 'static', file), 'utf8') + '</script>');

  const errors = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', e => errors.push(String(e && e.message || e)));
  vc.on('error', (...a) => errors.push(a.map(String).join(' ')));

  const dom = new JSDOM(html, {
    runScripts: 'outside-only',
    pretendToBeVisual: true,
    url: 'http://t' + (++bootCount) + '.localhost/' + (hash || ''),
    virtualConsole: vc,
  });
  const win = dom.window;

  // Stand-ins for the drawing libraries: the charts are Chart.js's business,
  // not this test's, and a stub keeps a missing canvas from masking a real
  // reference error elsewhere in renderStats.
  win.Chart = function () { return { destroy() {}, update() {}, data: {}, options: {} }; };
  win.Chart.prototype.destroy = function () {};
  // d3 is used fluently (d3.select(...).attr(...).data(...)), so the stub has
  // to answer anything and stay chainable — including the coercions the map
  // code performs on what it gets back.
  const chain = new Proxy(function () { return chain; }, {
    get: (t, prop) => {
      if (prop === Symbol.toPrimitive) return () => '';
      if (prop === 'then') return undefined;          // not a thenable
      if (prop === Symbol.iterator) return function* () {};
      return chain;
    },
    apply: () => chain,
  });
  win.d3 = chain;
  win.topojson = { feature: () => ({ features: [] }) };
  win.marked = { parse: s => String(s), setOptions() {} };
  win.HTMLCanvasElement.prototype.getContext = () => ({});
  win.matchMedia = win.matchMedia || (q => ({ matches: false, addListener() {}, removeListener() {} }));
  win.confirm = () => true;
  win.scrollTo = () => {};
  win.Element.prototype.scrollIntoView = function () {};
  win.Element.prototype.scrollTo = function () {};
  // jsdom implements neither; both exist in every browser the app runs in, so
  // stubbing them keeps a harness gap from reading as an application error.
  win.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
  win.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };

  win.fetch = async (url, opts) => {
    const u = String(url);
    const json = (body, ok = true) => ({
      ok, status: ok ? 200 : 500, json: async () => body, text: async () => JSON.stringify(body),
    });
    if (u.endsWith('/api/auth/status')) return json({ authed: true });
    if (u.includes('/api/records') && (!opts || !opts.method || opts.method === 'GET')) {
      // A fresh copy: the app mutates records in place, and handing it the
      // fixture's own objects let one test's edit rewrite every later one's
      // expectations.
      return json(JSON.parse(JSON.stringify(RECORDS)));
    }
    if (u.includes('/api/scan/usage')) return json({ month: '2026-08', month_usd: 0, month_scans: 0,
      total_usd: 0, total_scans: 0, estimate: { photo: 0.006, spotify: 0.0004 } });
    if (opts && opts.method === 'PUT') return json({ ok: true });
    return json({ ok: true });
  };

  /* Run the page's own scripts, in order, as ONE unit.
   *
   * They have to share a scope. In a browser every classic script puts its
   * top-level const into the same global lexical environment, so the inline
   * script can see VinylGrouping and the rest; an indirect eval instead scopes
   * each one to itself, and the modules would be invisible to each other. */
  const source = [...win.document.querySelectorAll('script')]
    .map(el => el.textContent)
    .filter(t => t.trim())
    .join('\n;\n')
    /* A reader built INSIDE that scope. The template's top-level `let`s are
     * lexical, so they never reach window and a second eval gets its own fresh
     * scope — only a closure created in here can see them, the way a console
     * opened on the page can. */
    + '\n;window.__peek = function (expr) { return eval(expr); };';
  try {
    win.eval(source);
  } catch (e) {
    errors.push(e && e.stack ? e.stack.split('\n').slice(0, 4).join(' | ') : String(e));
  }

  // init() is async and fetches; give its microtasks a chance to settle.
  for (let i = 0; i < 20; i++) await new Promise(r => setTimeout(r, 0));

  /* The template's top-level `let`s are lexical, so they never land on window
   * — reading them means evaluating in the page's own scope, exactly as a
   * console would. */
  const read = expr => win.__peek(expr);
  return { win, doc: win.document, errors, read };
}

/* Press something the way a person would.
 *
 * jsdom does not compile inline handler attributes under
 * runScripts:'outside-only', and this app wires a great deal of its chrome
 * with onclick="...". So an element carrying one gets its attribute compiled
 * in the page's own scope and called; anything else gets a real click event.
 * Compiled on demand rather than up front, because most of this DOM is
 * replaced by innerHTML on every render. */
function press(win, el) {
  const code = el.getAttribute && el.getAttribute('onclick');
  if (code) {
    win.__peek('(function(event){' + code + '})').call(el, new win.MouseEvent('click'));
    return;
  }
  el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
}

/* The detail drawer changes record on animationend, which jsdom never fires —
 * it has no CSS animations to end. Driving them by hand is what a browser does
 * a frame later. */
function settleAnimations(win, doc) {
  for (let i = 0; i < 4; i++) {
    doc.querySelectorAll('#detailBody').forEach(el =>
      el.dispatchEvent(new win.Event('animationend', { bubbles: true })));
  }
}

const $ = (doc, sel) => doc.querySelector(sel);
const count = (doc, sel) => doc.querySelectorAll(sel).length;

// ── it runs at all ──────────────────────────────────────────────────────────

test('the page boots without throwing', async () => {
  const { errors } = await boot();
  assert.deepStrictEqual(errors, [], 'errors while booting:\n' + errors.join('\n'));
});

test('the collection renders its records', async () => {
  const { doc } = await boot();
  assert.ok(count(doc, '#recordsContainer .vcard') > 0, 'no cards were drawn');
});

/* One count, in the header. The filter bar used to carry a second one saying
 * the same thing a few pixels lower. */
test('the record count agrees with the data', async () => {
  const { doc } = await boot();
  const owned = RECORDS.filter(r => r.have_it).length;
  assert.match($(doc, '#recordCount').textContent, new RegExp('^— ' + owned + '\\b'));
  assert.strictEqual($(doc, '#matchCount'), null, 'the filter bar counts again');
});

// ── the filter bar ──────────────────────────────────────────────────────────

test('the bar shows both ownership options and the add-filter button', async () => {
  const { doc } = await boot();
  const opts = [...doc.querySelectorAll('#filterChips .own-seg .own-opt')];
  assert.deepStrictEqual(opts.map(o => o.textContent.trim()), ['Owned', 'Wishlist']);
  assert.ok(opts.every(o => o.querySelector('i.ti')), 'an option is missing its icon');
  assert.ok($(doc, '#filterChips .chip-add'), 'no way to add a filter');
});

test('the toggle moves the shelf to the wishlist and marks which side is on', async () => {
  const { win, doc, read } = await boot();
  // Re-queried every time: choosing a side re-renders the whole bar.
  const opt = value => $(doc, `#filterChips .own-opt.${value}`);
  assert.strictEqual(read('filterState.ownership'), 'owned');
  assert.strictEqual(opt('owned').getAttribute('aria-pressed'), 'true');

  press(win, opt('wishlist'));

  assert.strictEqual(read('filterState.ownership'), 'wishlist');
  assert.strictEqual(opt('wishlist').getAttribute('aria-pressed'), 'true');
  assert.strictEqual(opt('owned').getAttribute('aria-pressed'), 'false');
  // The exact count, not merely a different one: a before/after diff would
  // also pass if the shelf emptied for the wrong reason.
  assert.strictEqual(count(doc, '#recordsContainer .vcard'),
    RECORDS.filter(r => !r.have_it).length);
});

test('opening the facet picker lists the saved views and the dimensions', async () => {
  const { win, doc } = await boot();
  win.openFacetPicker();
  const items = [...doc.querySelectorAll('#facetPop .facet-item')].map(el => el.textContent);
  assert.ok(items.some(t => /Needs cleaning/.test(t)), 'no saved views');
  assert.ok(items.some(t => /Genre/.test(t)), 'no facets');
});

test('a saved view narrows the shelf and leaves a chip explaining it', async () => {
  const { win, doc } = await boot();
  win.applySavedView('needs-cleaning');
  const expected = RECORDS.filter(r =>
    r.have_it && !(JSON.parse(r.cleaned_dates || '[]') || []).some(Boolean)).length;
  assert.match($(doc, '#recordCount').textContent, new RegExp('^— ' + expected + '\\b'));
  assert.match($(doc, '#filterChips').textContent, /cleaning/i);
});

test('dropping a facet chip puts the records back', async () => {
  const { win, doc } = await boot();
  const before = count(doc, '#recordsContainer .vcard');
  win.applySavedView('needs-cleaning');
  win.dropFacet('cleaning');
  assert.strictEqual(count(doc, '#recordsContainer .vcard'), before);
});

// ── the tabs ────────────────────────────────────────────────────────────────

test('every tab renders without throwing', async () => {
  const { win, doc, errors } = await boot();
  for (const tab of ['timeline', 'stats', 'collection']) {
    win.switchTab(tab);
    assert.deepStrictEqual(errors, [], `${tab} threw:\n` + errors.join('\n'));
  }
  assert.ok($(doc, '#collectionPage'), 'the shelf went missing');
});

test('the timeline switches between its four scales', async () => {
  const { win, doc, errors } = await boot();
  win.switchTab('timeline');
  for (const scale of ['month', 'week', 'day', 'replay']) {
    win.setCalScale(scale);
    assert.deepStrictEqual(errors, [], `scale ${scale} threw:\n` + errors.join('\n'));
  }
  assert.strictEqual($(doc, '#replayBody').hidden, false, 'replay did not show');
  assert.strictEqual($(doc, '#calBody').hidden, true, 'the calendar did not step aside');
});

test('insights draws the health row from the same records', async () => {
  const { win, doc } = await boot();
  win.switchTab('stats');
  const tiles = [...doc.querySelectorAll('#statsCards .kpi-tile')];
  assert.strictEqual(tiles.length, 4);
  assert.match(tiles[0].textContent, /Records/);
  assert.match(tiles[3].textContent, /Never cleaned/);
});

// ── the address bar ─────────────────────────────────────────────────────────

test('a link to a filter arrives already filtered', async () => {
  const { doc } = await boot('#f.cleaning=never');
  const expected = RECORDS.filter(r =>
    r.have_it && !(JSON.parse(r.cleaned_dates || '[]') || []).some(Boolean)).length;
  assert.match($(doc, '#recordCount').textContent, new RegExp('^— ' + expected + '\\b'));
});

test('a link to a tab arrives on it', async () => {
  const { read } = await boot('#tab=timeline');
  assert.strictEqual(read('currentTab'), 'timeline');
});

test('filtering writes itself into the address bar', async () => {
  const { win } = await boot();
  win.applySavedView('needs-cleaning');
  assert.match(win.location.hash, /f\.cleaning=never/);
});

// ── the record drawer ───────────────────────────────────────────────────────

test('opening a record shows it, and says so in the address bar', async () => {
  const { win, doc } = await boot();
  const id = RECORDS.find(r => r.have_it).id;
  win.openDetail(id);
  assert.ok(!$(doc, '#detailOverlay').classList.contains('hidden'), 'the drawer stayed shut');
  assert.match(win.location.hash, new RegExp('rec=' + id));
});

test('the rating segments are the control when you can edit', async () => {
  const { win, doc, read } = await boot();
  const rec = RECORDS.find(r => r.have_it);
  win.openDetail(rec.id);
  const seg = $(doc, '#detailBody [data-rate="my_rating"][data-val="4"]');
  assert.ok(seg, 'the rating bars are not pressable');
  seg.dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
  assert.strictEqual(read('records').find(r => r.id === rec.id).my_rating, 4);
});

test('cleaned today adds a cleaning to the record', async () => {
  const { win, read } = await boot();
  const rec = RECORDS.find(r => r.have_it);
  const before = (JSON.parse(rec.cleaned_dates || '[]') || []).length;
  win.openDetail(rec.id);
  win.logCleaned(rec.id);
  const after = JSON.parse(read('records').find(r => r.id === rec.id).cleaned_dates || '[]');
  assert.strictEqual(after.length, before + 1);
});

// ── the add form ────────────────────────────────────────────────────────────

test('the add form opens on step one with all three steps offered', async () => {
  const { win, doc } = await boot();
  win.openAdd();
  assert.strictEqual(count(doc, '#formSpine .fstep'), 3);
  assert.strictEqual($(doc, '.form-step[data-step="1"]').hidden, false);
  assert.strictEqual($(doc, '.form-step[data-step="2"]').hidden, true);
});

test('stepping through the form shows one step at a time', async () => {
  const { win, doc } = await boot();
  win.openAdd();
  win.setFormStep(3);
  assert.strictEqual($(doc, '.form-step[data-step="1"]').hidden, true);
  assert.strictEqual($(doc, '.form-step[data-step="3"]').hidden, false);
  assert.ok($(doc, '#formNextBtn').disabled, 'next should stop at the last step');
});

test('an untouched form closes without asking', async () => {
  const { win, doc } = await boot();
  win.openAdd();
  let asked = false;
  win.confirm = () => { asked = true; return true; };
  win.closeForm();
  assert.strictEqual(asked, false, 'it asked about a form nobody touched');
  assert.ok($(doc, '#formOverlay').classList.contains('hidden'));
});

test('a form with something in it asks before throwing it away', async () => {
  const { win, doc } = await boot();
  win.openAdd();
  $(doc, '#fAlbum').value = 'Racional';
  let asked = false;
  win.confirm = () => { asked = true; return false; };
  win.closeForm();
  assert.strictEqual(asked, true, 'it discarded typed work silently');
  assert.ok(!$(doc, '#formOverlay').classList.contains('hidden'), 'it closed anyway');
});

// ── arranging the shelf ─────────────────────────────────────────────────────

test('changing the crate regroups the shelf', async () => {
  const { win, doc, read } = await boot();
  win.setGroupBy('genre');
  assert.strictEqual(read('groupBy'), 'genre');
  const heads = [...doc.querySelectorAll('#recordsContainer .crate-head')];
  assert.ok(heads.length > 0, 'no crates were drawn');
  assert.match($(doc, '#groupLabel').textContent, /Genre/);
});

test('no crates draws one flat grid', async () => {
  const { win, doc } = await boot();
  win.setGroupBy('none');
  assert.strictEqual(count(doc, '#recordsContainer .crate-head'), 0);
  assert.ok(count(doc, '#recordsContainer .vcard') > 0);
});

test('changing the sort keeps every record on the shelf', async () => {
  const { win, doc, read } = await boot();
  const before = count(doc, '#recordsContainer .vcard');
  const item = $(doc, '#sortList [data-sort="artist"]');
  assert.ok(item, 'the sort list offers no artist option');
  item.dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
  assert.strictEqual(read('sortBy'), 'artist');
  assert.strictEqual(count(doc, '#recordsContainer .vcard'), before);
});

test('flipping the sort direction keeps every record on the shelf', async () => {
  const { win, doc, read } = await boot();
  const before = count(doc, '#recordsContainer .vcard');
  win.toggleSortDir();
  assert.strictEqual(read('sortDir'), 'asc');
  assert.strictEqual(count(doc, '#recordsContainer .vcard'), before);
});

test('the list view draws rows instead of cards', async () => {
  const { win, doc } = await boot();
  win.setViewMode('list');
  assert.ok(count(doc, '#recordsContainer .list-row') > 0, 'no rows');
  assert.strictEqual(count(doc, '#recordsContainer .vcard'), 0);
});

test('collapsing a crate hides its records but keeps its header', async () => {
  const { win, doc } = await boot();
  win.setGroupBy('genre');
  const head = $(doc, '#recordsContainer .crate-head');
  const id = head.dataset.crate;
  win.toggleCrate(id);
  assert.ok($(doc, `[data-crate="${id}"]`).closest('.crate').classList.contains('collapsed'));
});

// ── the record drawer ───────────────────────────────────────────────────────

test('prev and next walk the filtered shelf', async () => {
  const { win, doc, read } = await boot();
  const shelf = read('filtered()').map(r => r.id);
  win.openDetail(shelf[0]);
  win.navigateDetail(1);
  settleAnimations(win, doc);
  assert.strictEqual(read('currentDetailId'), shelf[1], 'next did not reach the next record');
  win.navigateDetail(-1);
  settleAnimations(win, doc);
  assert.strictEqual(read('currentDetailId'), shelf[0], 'prev did not come back');
});

test('closing the drawer clears the record from the address bar', async () => {
  const { win, doc } = await boot();
  win.openDetail(RECORDS.find(r => r.have_it).id);
  win.closeDetail();
  assert.ok(!/rec=/.test(win.location.hash), 'the record stayed in the url');
  assert.ok($(doc, '#detailOverlay').classList.contains('hidden'));
});

// ── the add and edit form ───────────────────────────────────────────────────

test('editing an existing record fills the form from it', async () => {
  const { win, doc, read } = await boot();
  const rec = RECORDS.find(r => r.have_it && r.album_name);
  win.openEdit(rec.id);
  assert.strictEqual(read('editingId'), rec.id);
  assert.strictEqual($(doc, '#fAlbum').value, rec.album_name);
  assert.strictEqual($(doc, '#fArtist').value, rec.artist);
});

test('an untouched edit form is not dirty, so it will not nag on close', async () => {
  const { win } = await boot();
  win.openEdit(RECORDS.find(r => r.have_it).id);
  assert.strictEqual(win.formIsDirty(), false,
    'opening a record for editing already counts as an edit');
});

test('saving sends what the form holds and closes', async () => {
  const { win, doc } = await boot();
  const rec = RECORDS.find(r => r.have_it);
  win.openEdit(rec.id);
  $(doc, '#fAlbum').value = 'Renamed By The Test';
  let sent = null;
  const realFetch = win.fetch;
  win.fetch = async (url, opts) => {
    if (opts && opts.method === 'PUT') sent = JSON.parse(opts.body);
    return realFetch(url, opts);
  };
  await win.submitForm();
  assert.ok(sent, 'nothing was sent');
  assert.strictEqual(sent.album_name, 'Renamed By The Test');
  assert.ok(!('cover_data' in sent), 'an untouched cover must not be sent, it would wipe it');
  assert.ok($(doc, '#formOverlay').classList.contains('hidden'), 'the form stayed open');
});

test('a draft is kept while typing and offered back on the next add', async () => {
  const { win, doc } = await boot();
  win.openAdd();
  $(doc, '#fAlbum').value = 'Half Typed';
  win.rememberDraft();
  assert.ok(win.localStorage.getItem('vinyl-form-draft'), 'nothing was kept');
  win.closeForm(true);
  win.localStorage.setItem('vinyl-form-draft', JSON.stringify({
    savedAt: Date.now(), editingId: null, draft: { album_name: 'Half Typed', artist: 'Someone' },
  }));
  win.confirm = () => true;
  win.openAdd();
  assert.strictEqual($(doc, '#fAlbum').value, 'Half Typed', 'the draft was not restored');
});

test('declining a draft throws it away rather than asking again', async () => {
  const { win, doc } = await boot();
  win.localStorage.setItem('vinyl-form-draft', JSON.stringify({
    savedAt: Date.now(), editingId: null, draft: { album_name: 'Unwanted' },
  }));
  win.confirm = () => false;
  win.openAdd();
  assert.strictEqual($(doc, '#fAlbum').value, '');
  assert.strictEqual(win.localStorage.getItem('vinyl-form-draft'), null);
});

test('the form records a play date and a cleaning without the modal fighting back', async () => {
  const { win, doc, read } = await boot();
  win.openAdd();
  win.addPlayDate();
  win.addCleanedDate();
  assert.strictEqual(read('formPlayDates').length, 1);
  assert.strictEqual(read('formCleanedDates').length, 1);
  assert.ok(count(doc, '#fPlayDatesList .playdate-row') > 0 ||
            $(doc, '#fPlayDatesList').children.length > 0, 'no play date row drawn');
});

// ── the rest of the chrome ──────────────────────────────────────────────────

test('the theme toggle redraws whatever is on screen', async () => {
  const { win, doc, errors } = await boot();
  win.applyTheme('light');
  assert.strictEqual(doc.documentElement.getAttribute('data-theme'), 'light');
  win.switchTab('stats');
  win.applyTheme('dark');
  assert.deepStrictEqual(errors, [], 'toggling the theme threw:\n' + errors.join('\n'));
});

/* The wood finish — a palette taken from the photo of the actual setup: the
 * teak cabinet top, the walnut floor under it, and the AT-LP70XBT's green
 * VMN95E stylus standing in for the yellow accent.
 *
 * It is deliberately a SECOND AXIS rather than a third theme. data-theme keeps
 * meaning light-or-dark and nothing that reads it has to learn a new value;
 * data-finish carries classic-or-wood. That is what lets the wood-light
 * palette inherit all fourteen [data-theme="light"] component rules for free.
 * These tests pin the two axes staying independent. */

test('a first visit opens on wood, in light', async () => {
  const { doc } = await boot();          // a fresh origin: nothing in localStorage
  assert.strictEqual(doc.documentElement.getAttribute('data-finish'), 'wood');
  assert.strictEqual(doc.documentElement.getAttribute('data-theme'), 'light');
});

test('switching finish leaves the light/dark tone alone', async () => {
  const { win, doc } = await boot();
  win.applyTheme('light');
  const before = doc.documentElement.getAttribute('data-finish');
  $(doc, '#finishBtn').dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
  assert.notStrictEqual(doc.documentElement.getAttribute('data-finish'), before,
    'the finish button did not change the finish');
  assert.strictEqual(doc.documentElement.getAttribute('data-theme'), 'light',
    'toggling the finish also changed the tone');
});

test('switching tone leaves the wood finish alone', async () => {
  const { win, doc } = await boot();
  win.applyFinish('wood');
  win.applyTheme('light');
  $(doc, '#themeBtn').dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
  assert.strictEqual(doc.documentElement.getAttribute('data-theme'), 'dark');
  assert.strictEqual(doc.documentElement.getAttribute('data-finish'), 'wood',
    'toggling the tone dropped the wood finish');
});

test('the finish is remembered separately from the tone', async () => {
  const { win, read } = await boot();
  win.applyFinish('wood');
  win.applyTheme('light');
  assert.strictEqual(read("localStorage.getItem('vinyl-finish')"), 'wood');
  assert.strictEqual(read("localStorage.getItem('vinyl-theme')"), 'light');
});

test('wood keeps the tone the colour logic sees', async () => {
  const { win, read } = await boot();
  win.applyFinish('wood');
  win.applyTheme('dark');
  assert.strictEqual(read('isDark()'), true, 'wood-dark did not read as dark');
  assert.strictEqual(read("genreColor('Rock')"), '#E0453C');
  win.applyTheme('light');
  assert.strictEqual(read('isDark()'), false, 'wood-light did not read as light');
  assert.strictEqual(read("genreColor('Rock')"), '#C0271F',
    'wood-light got the dark-theme genre hue');
});

/* token name -> value for one palette block in the template's <style>. */
function palette(selector, label) {
  const css = fs.readFileSync(PAGE, 'utf8');
  const m = css.match(new RegExp(selector.replace(/[[\]"]/g, '\\$&') + '\\{([^}]*)\\}'));
  assert.ok(m, 'no ' + label + ' palette block in the template');
  return new Map([...m[1].matchAll(/(--[\w-]+)\s*:\s*([^;}]+)/g)].map(x => [x[1], x[2].trim()]));
}
const CLASSIC = tone => palette('[data-theme="' + tone + '"]', 'classic ' + tone);
const WOOD = tone => palette('[data-finish="wood"][data-theme="' + tone + '"]', 'wood ' + tone);

// WCAG relative luminance, so the accent checks below are real numbers rather
// than someone's opinion about whether a colour "looks readable".
function contrast(a, b) {
  const lum = hex => {
    const c = i => {
      const v = parseInt(hex.slice(i, i + 2), 16) / 255;
      return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * c(1) + 0.7152 * c(3) + 0.0722 * c(5);
  };
  const [x, y] = [lum(a), lum(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

test('each wood palette defines every token its classic tone defines', async () => {
  for (const tone of ['dark', 'light']) {
    const missing = [...CLASSIC(tone).keys()].filter(t => !WOOD(tone).has(t));
    assert.deepStrictEqual(missing, [],
      'the wood ' + tone + ' palette is missing: ' + missing.join(', '));
  }
});

test('the wood accent is the gold, not the stylus green', async () => {
  assert.strictEqual(WOOD('dark').get('--accent'), '#f1c23f');
  // the light one has to be deepened to stay readable, but must stay gold:
  // hue in the 30-60 degree band rather than green's ~145
  const hex = WOOD('light').get('--accent');
  const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  const hue = max === min ? 0
    : 60 * (max === r ? (((g - b) / (max - min)) % 6)
    : max === g ? ((b - r) / (max - min)) + 2 : ((r - g) / (max - min)) + 4);
  assert.ok(hue >= 30 && hue <= 60,
    'the wood light accent ' + hex + ' is at hue ' + hue.toFixed(0) + ', outside gold');
});

test('every wood accent stays readable on its own ground', async () => {
  for (const tone of ['dark', 'light']) {
    const p = WOOD(tone);
    const ratio = contrast(p.get('--accent'), p.get('--bg'));
    assert.ok(ratio >= 4.5,
      'wood ' + tone + ' accent ' + p.get('--accent') + ' on ' + p.get('--bg') +
      ' is only ' + ratio.toFixed(2) + ':1');
  }
});


test('the dice opens some record from the current filter', async () => {
  const { win, doc, read } = await boot();
  $(doc, '#randomBtn').dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
  const shown = read('currentDetailId');
  assert.ok(shown !== null, 'the dice opened nothing');
  assert.ok(read('filtered()').some(r => r.id === shown), 'it opened something filtered out');
});

test('a calendar day with events opens its agenda', async () => {
  const { win, doc, errors } = await boot();
  win.switchTab('timeline');
  const day = $(doc, '#calBody .cal-cell.has-ev');
  if (!day) return;                      // this month may be empty in a small sample
  press(win, day);
  assert.ok(!$(doc, '#calDayOverlay').classList.contains('hidden'), 'the day did not open');
  assert.deepStrictEqual(errors, []);
});

test('the replay controls run without throwing', async () => {
  const { win, errors } = await boot();
  win.switchTab('timeline');
  win.setCalScale('replay');
  win.histPlay();
  win.histPause();
  win.histReplay();
  win.histPause();
  assert.deepStrictEqual(errors, [], 'the replay threw:\n' + errors.join('\n'));
});

// ── what the review found ───────────────────────────────────────────────────

test('reading the address bar never writes to it', async () => {
  // The Back loop: applyUrl closed the record on its way through, but the
  // query sync fired first and stamped the still-open record onto the entry
  // just navigated to. Back reopened it, and you were stuck between two
  // entries. Nothing applyUrl does may touch history.
  const { win, read } = await boot();
  win.openDetail(RECORDS.find(r => r.have_it).id);

  let writes = 0;
  const realPush = win.history.pushState.bind(win.history);
  const realReplace = win.history.replaceState.bind(win.history);
  win.history.pushState = (...a) => { writes++; return realPush(...a); };
  win.history.replaceState = (...a) => { writes++; return realReplace(...a); };

  win.applyUrl('');                       // what the hashchange handler does
  assert.strictEqual(writes, 0, `applyUrl wrote history ${writes} time(s)`);
  assert.strictEqual(read('currentDetailId'), null, 'the record stayed open');
});

test('a plain reload keeps the saved list-view preference', async () => {
  const { win, read } = await boot();
  win.setViewMode('list');
  assert.strictEqual(win.localStorage.getItem('vinyl-view-mode'), 'list');
  win.applyUrl('');                       // no view parameter, as on a reload
  assert.strictEqual(win.localStorage.getItem('vinyl-view-mode'), 'list',
    'applying a url with no view parameter destroyed the stored preference');
  assert.strictEqual(read('viewMode'), 'list');
});

test('a link that names a view still wins', async () => {
  const { read } = await boot('#view=list');
  assert.strictEqual(read('viewMode'), 'list');
});

test('the arrange controls write themselves into the address bar', async () => {
  const { win } = await boot();
  win.setGroupBy('genre');
  assert.match(win.location.hash, /crate=genre/);
  win.toggleSortDir();
  assert.match(win.location.hash, /dir=asc/);
});

test('a dir=asc link shows an ascending arrow', async () => {
  const { doc } = await boot('#dir=asc');
  assert.ok($(doc, '#sortDirBtn').classList.contains('asc'));
  assert.match($(doc, '#sortDirBtn').innerHTML, /arrow-up/,
    'the arrow disagreed with the sort it is describing');
});

test('replay describes the same records the calendar scales do', async () => {
  const { win, read } = await boot();
  win.applySavedView('needs-cleaning');
  const shown = read('filtered()').length;
  win.switchTab('timeline');
  win.setCalScale('replay');
  const replayed = read('raceFrames.length ? raceFrames[raceFrames.length - 1].total : 0');
  assert.ok(replayed <= shown,
    `replay covered ${replayed} records while the tab is filtered to ${shown}`);
  assert.ok(replayed > 0, 'replay covered nothing at all');
});

test('plays, cleanings and notes live on the last step, not on all three', async () => {
  const { win, doc } = await boot();
  win.openAdd();
  const step3 = $(doc, '.form-step[data-step="3"]');
  assert.ok(step3.contains($(doc, '#playDatesSection')), 'play dates escaped step 3');
  assert.ok(step3.contains($(doc, '#cleanedDatesSection')), 'cleanings escaped step 3');
  assert.ok(step3.contains($(doc, '#fNotesList')), 'notes escaped step 3');
  assert.strictEqual(step3.hidden, true, 'step 3 shows on step 1');
});

test('the replay lanes get real cover urls, not empty ones', async () => {
  // activity.js kept reading cover_data after covers moved to their own
  // endpoint, so every lane rendered <img src=""> — which re-requests the
  // document and paints a broken image.
  const { win, read } = await boot();
  win.switchTab('timeline');
  win.setCalScale('replay');
  const covers = read('act ? act.lanes.map(function (l) { return l.cover; }) : []');
  assert.ok(covers.length > 0, 'no lanes were built');
  assert.ok(covers.some(c => /\/api\/records\/\d+\/cover/.test(c)),
    'no lane carries a cover url — they are reading a field the API no longer sends');
});

test('a scan filling the form is kept as a draft, not just typing', async () => {
  // The case draft.js exists for: a scan has already been billed by the time
  // it fills the form, and it writes fields with el.value = …, which fires no
  // input event. Listening for typing alone left it unprotected.
  const { win, doc } = await boot();
  win.openAdd();
  win.localStorage.removeItem('vinyl-form-draft');
  win.applyScanResult({ source: 'photo', artist: 'Scanned Artist',
    album_name: 'Scanned Album', genre: '', candidates: [], duplicate_of: null,
    search_string: '' });
  assert.ok(win.localStorage.getItem('vinyl-form-draft'),
    'a completed scan left nothing in the draft');
});


test('the draft flag does not carry over to the next form', async () => {
  const { win, doc } = await boot();
  win.openAdd();
  $(doc, '#fAlbum').value = 'Something';
  win.formChanged();
  assert.strictEqual($(doc, '#draftFlag').hidden, false, 'the flag never lit');
  win.confirm = () => true;
  win.closeForm();
  win.openAdd();
  assert.strictEqual($(doc, '#draftFlag').hidden, true,
    'it still read "draft kept" over an empty form');
});

test('clicking away closes the facet popover on a desktop', async () => {
  // The backdrop that carries the close is display:none above 760px, and the
  // dropdowns this replaced each had an outside-click closer of their own.
  const { win, doc, read } = await boot();
  win.openFacetPicker();
  assert.strictEqual(read('facetPopFor'), 'pick');
  $(doc, '#recordsContainer').dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
  assert.strictEqual(read('facetPopFor'), null, 'the popover would not go away');
});

test('escape closes the facet popover', async () => {
  const { win, doc, read } = await boot();
  win.openFacetPicker();
  doc.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  assert.strictEqual(read('facetPopFor'), null);
});

test('the card play buttons and Played today write the same way', async () => {
  const { win, read } = await boot();
  const rec = RECORDS.find(r => r.have_it);
  const held = () => read('records').find(r => r.id === rec.id);
  const beforeCount = held().play_count;
  const beforeDates = JSON.parse(held().play_dates || '[]').length;
  await win.adjustPlayCount(rec.id, 1);
  assert.strictEqual(held().play_count, beforeCount + 1);
  assert.strictEqual(JSON.parse(held().play_dates || '[]').length, beforeDates + 1,
    'the card button did not stamp a play date');
});

test('typing redraws the shelf at once but makes the charts wait', async () => {
  // Insights rebuilds three Chart.js instances, the country map and the year
  // distribution; Replay rebuilds every frame and drops playback to day one.
  // Per keystroke that was a full rebuild per character.
  const { win, doc, read } = await boot();
  win.switchTab('stats');
  assert.strictEqual(read('heavyRenderTimer'), null, 'something was already queued');

  const box = $(doc, '#searchInput');
  box.value = 'zzzz';
  box.dispatchEvent(new win.Event('input', { bubbles: true }));

  assert.notStrictEqual(read('heavyRenderTimer'), null,
    'the charts rebuilt synchronously on a keystroke');
  // the shelf still keeps up: nothing matches 'zzzz'
  assert.match($(doc, '#recordCount').textContent, /^— 0\b/);
});

test('a queued rebuild does not fire into a tab you have left', async () => {
  const { win, doc, read } = await boot();
  win.switchTab('stats');
  const box = $(doc, '#searchInput');
  box.value = 'zz';
  box.dispatchEvent(new win.Event('input', { bubbles: true }));
  assert.notStrictEqual(read('heavyRenderTimer'), null);
  win.switchTab('collection');
  assert.strictEqual(read('heavyRenderTimer'), null,
    'a stats rebuild was still queued after leaving stats');
});

test('every other control still redraws immediately', async () => {
  const { win, read } = await boot();
  win.switchTab('stats');
  win.applySavedView('needs-cleaning');
  assert.strictEqual(read('heavyRenderTimer'), null,
    'a saved view deferred its redraw, which only the search box should do');
});

// ── the scan results screen tells the truth about an empty result ───────────

/* Both of these render the same empty candidate list. The words have to
 * differ: one is "MusicBrainz has never heard of this record", the other is
 * "MusicBrainz did not answer". Only the second is worth trying again, and
 * telling the user the wrong one is what made the same photo get scanned —
 * and billed — twice. */
const SCAN_MISS = {
  source: 'photo', artist: 'Tim Maia', album_name: 'Racional', genre: '',
  candidates: [], duplicate_of: null, lookup_failed: false,
  search_string: 'Tim Maia Racional vinyl cover',
};

test('a record MusicBrainz does not have says so', async () => {
  const { win, doc } = await boot();
  win.openAdd();
  win.applyScanResult(SCAN_MISS);

  const body = $(doc, '#scanBody').textContent;
  assert.match(body, /no releases matched/);
  assert.doesNotMatch(body, /couldn't reach/i);
});

test('a MusicBrainz outage is not reported as a record it does not have', async () => {
  const { win, doc } = await boot();
  win.openAdd();
  win.applyScanResult({ ...SCAN_MISS, lookup_failed: true });

  const body = $(doc, '#scanBody').textContent;
  assert.match(body, /couldn't reach MusicBrainz/i);
  assert.doesNotMatch(body, /no release group for it/);
});

test('an outage still leaves the sleeve read in the form', async () => {
  const { win, doc } = await boot();
  win.openAdd();
  win.applyScanResult({ ...SCAN_MISS, lookup_failed: true });

  assert.strictEqual($(doc, '#fArtist').value, 'Tim Maia');
  assert.strictEqual($(doc, '#fAlbum').value, 'Racional');
});

test('the outage message does not survive into the next scan', async () => {
  const { win, doc } = await boot();
  win.openAdd();
  win.applyScanResult({ ...SCAN_MISS, lookup_failed: true });
  assert.match($(doc, '#scanBody').textContent, /couldn't reach/i);

  win.applyScanResult(SCAN_MISS);
  assert.match($(doc, '#scanBody').textContent, /no releases matched/);
});

test('a candidate that is not an album says which kind it is', async () => {
  const { win, doc } = await boot();
  win.openAdd();
  win.applyScanResult({
    ...SCAN_MISS, artist: 'AC/DC', album_name: 'Back in Black',
    candidates: [
      {mbid: 'a', year: '1980', country: 'AU', artist: 'AC/DC',
       album_name: 'Back in Black', type: 'Album', cover_data: null},
      {mbid: 'b', year: '1980', country: 'AU', artist: 'AC/DC',
       album_name: 'Back in Black', type: 'Single', cover_data: null},
    ],
  });

  const cards = [...doc.querySelectorAll('.scan-card')].map(c => c.textContent);
  assert.strictEqual(cards.length, 2);
  assert.doesNotMatch(cards[0], /album$|· album/i);   // the LP needs no label
  assert.match(cards[1], /single/i);
});
