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
    .map(el => el.textContent).filter(t => t.trim()).join('\n;\n')
    /* A reader built INSIDE that scope. FORM_STEPS and VinylPhoneForm are
     * top-level `const`s, which are lexical, so they never reach window and a
     * second eval gets its own fresh scope — only a closure created in here
     * can see them, the way a console opened on the page can. See
     * tests/test_boot.js's own __peek for the same pattern. Do not "simplify"
     * this back to win.FORM_STEPS; it will read undefined. */
    + '\n;window.__peek = function (expr) { return eval(expr); };';
  try { win.eval(source); } catch (e) { errors.push(String(e && e.message)); }
  for (let i = 0; i < 20; i++) await new Promise(r => setTimeout(r, 0));

  const read = expr => win.__peek(expr);
  return { win, doc: win.document, errors, read };
}

const $ = (doc, sel) => doc.querySelector(sel);

/* Press something the way a person would.
 *
 * jsdom does not compile inline handler attributes under
 * runScripts:'outside-only', and this app wires a great deal of its chrome
 * with onclick="...". So an element carrying one gets its attribute compiled
 * in the page's own scope and called; anything else gets a real click event.
 * Compiled on demand rather than up front, because most of this DOM is
 * replaced by innerHTML on every render. Ported from tests/test_boot.js's
 * own press() — that file is off limits to run or edit, but this helper is
 * plain data, not one of its leaking-window tests. */
function press(win, el) {
  const code = el.getAttribute && el.getAttribute('onclick');
  if (code) {
    win.__peek('(function(event){' + code + '})').call(el, new win.MouseEvent('click'));
    return;
  }
  el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
}

// ── the breakpoint ───────────────────────────────────────────────────────────

// Every test below wraps its assertions in try/finally so win.close() always
// runs, even when an assertion throws. Without that, a failing assertion
// skips win.close(), the jsdom window's requestAnimationFrame loop keeps
// node's event loop alive, and the whole run hangs instead of reporting the
// one failure — see the file header for why that matters here.

test('isPhone follows the breakpoint', async () => {
  const { win } = await boot();
  try {
    assert.strictEqual(win.isPhone(), false);
    win.__setPhone(true);
    assert.strictEqual(win.isPhone(), true);
  } finally {
    win.close();
  }
});

test('the page boots on a phone without throwing', async () => {
  const { win, doc, errors } = await boot({ phone: true });
  try {
    assert.deepStrictEqual(errors, [], 'errors while booting:\n' + errors.join('\n'));
    assert.ok(win.isPhone(), 'phone mode should have taken on boot');
    assert.ok(doc.getElementById('formOverlay'), 'the form overlay should exist');
  } finally {
    win.close();
  }
});

// ── the keyboard-clearing scroll ─────────────────────────────────────────────
// The handler is wired unconditionally; isPhone() is what keeps it a no-op on
// desktop, where the layout viewport already shrinks for the keyboard and the
// extra scroll would just be a jump nobody asked for.

test('focusing a form field on a phone schedules a scroll clear of the keyboard', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    const field = $(doc, '#fAlbum');
    assert.ok(field, 'the form did not render its album field');

    const calls = [];
    win.Element.prototype.scrollIntoView = function (opts) { calls.push({ el: this, opts }); };
    field.dispatchEvent(new win.Event('focusin', { bubbles: true }));
    await new Promise(r => setTimeout(r, 350));    // past the 300ms keyboard wait

    assert.strictEqual(calls.length, 1, 'scrollIntoView was not called exactly once');
    assert.strictEqual(calls[0].el, field);
  } finally {
    win.close();
  }
});

test('the same focus does nothing on desktop', async () => {
  const { win, doc } = await boot({ phone: false });
  try {
    win.openAdd();
    const field = $(doc, '#fAlbum');

    let called = false;
    win.Element.prototype.scrollIntoView = function () { called = true; };
    field.dispatchEvent(new win.Event('focusin', { bubbles: true }));
    await new Promise(r => setTimeout(r, 350));

    assert.strictEqual(called, false, 'the desktop layout does not need this scroll');
  } finally {
    win.close();
  }
});

// ── the nav bar, the rail and the footer ─────────────────────────────────────
// Task 4's rebuildFormChrome renders the desktop spine and the phone's rail
// from one function, branching on isPhone(). These check that the branch
// actually keeps the two modes apart, that the save button is moved rather
// than duplicated, and that a live breakpoint change re-renders the chrome.

test('desktop keeps the four-step spine', async () => {
  const { win, doc } = await boot({ phone: false });
  try {
    win.openAdd();
    const steps = doc.querySelectorAll('#formSpine .fstep');
    assert.strictEqual(steps.length, 4);
    assert.match(steps[0].textContent, /Identify/);
    assert.strictEqual(doc.querySelectorAll('#formRail .rail-seg').length, 0);
  } finally {
    win.close();
  }
});

test('the phone gets a rail instead of the spine', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    assert.strictEqual(doc.querySelectorAll('#formSpine .fstep').length, 0);
    assert.strictEqual(doc.querySelectorAll('#formRail .rail-seg').length, 4);
  } finally {
    win.close();
  }
});

test('the rail marks the steps behind the current one done', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    win.setFormStep(3);
    const cls = [...doc.querySelectorAll('#formRail .rail-seg')]
      .map(s => s.className.replace('rail-seg', '').trim());
    assert.deepStrictEqual(cls, ['done', 'done', 'now', 'ahead']);
  } finally {
    win.close();
  }
});

test('the rail names the step the phone is on', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    win.setFormStep(2);
    assert.match(doc.getElementById('formRailLabel').textContent, /The purchase/);
    assert.match(doc.getElementById('formRailCount').textContent, /2\s*\/\s*4/);
  } finally {
    win.close();
  }
});

test('rail segments are not reachable by a thumb or a tab', async () => {
  // A 3px strip is not a touch target; Back and the rail label carry navigation.
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    for (const seg of doc.querySelectorAll('#formRail .rail-seg')) {
      assert.strictEqual(seg.tagName, 'I');
      assert.strictEqual(seg.getAttribute('onclick'), null);
      assert.strictEqual(seg.getAttribute('tabindex'), null);
    }
  } finally {
    win.close();
  }
});

test('the save button exists exactly once in both modes', async () => {
  for (const phone of [false, true]) {
    const { win, doc } = await boot({ phone });
    try {
      win.openAdd();
      assert.strictEqual(doc.querySelectorAll('#formSaveBtn').length, 1,
        `#formSaveBtn duplicated on ${phone ? 'phone' : 'desktop'}`);
    } finally {
      win.close();
    }
  }
});

test('the phone moves save into the nav bar', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    assert.ok(doc.querySelector('.modal-head #formSaveBtn'),
              'save should live in the nav bar on a phone');
  } finally {
    win.close();
  }
});

// jsdom does not lay pages out, so this cannot check that the × actually
// renders on the right and the title actually renders centred — that was the
// review's Critical finding on task 4 (a third, empty flex child pushed both
// off their intended spot under space-between). What jsdom CAN check is the
// DOM structure the CSS fix depends on: the head's three children keep this
// fixed order, and the desktop save button really is in the foot, not just
// styled to look that way while still sitting in the head.
test('desktop keeps the head save slot empty and save in the foot', async () => {
  const { win, doc } = await boot({ phone: false });
  try {
    win.openAdd();
    const head = doc.querySelector('#formOverlay .modal-head');
    assert.deepStrictEqual([...head.children].map(el => el.id),
      ['formHeadCancel', 'formTitle', 'formHeadSaveSlot']);
    assert.strictEqual(doc.getElementById('formHeadSaveSlot').children.length, 0,
      'the head save slot should carry no content on desktop');
    assert.ok(doc.querySelector('#formFootSaveSlot #formSaveBtn'),
      'save should live in the foot slot on desktop');
  } finally {
    win.close();
  }
});

test('the wishlist relabel still finds the button after the move', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    win.setHaveIt(false);
    assert.match(doc.getElementById('formSaveBtn').textContent, /wishlist/i);
  } finally {
    win.close();
  }
});

test('a breakpoint change while the form is open swaps the chrome', async () => {
  const { win, doc } = await boot({ phone: false });
  try {
    win.openAdd();
    assert.strictEqual(doc.querySelectorAll('#formSpine .fstep').length, 4);
    win.__setPhone(true);
    assert.strictEqual(doc.querySelectorAll('#formRail .rail-seg').length, 4);
    assert.strictEqual(doc.querySelectorAll('#formSpine .fstep').length, 0);
  } finally {
    win.close();
  }
});

test('the last step turns the next button into the save action', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    win.setFormStep(4);
    const next = doc.getElementById('formNextBtn');
    assert.strictEqual(next.disabled, false);
    assert.match(next.textContent, /save/i);
  } finally {
    win.close();
  }
});

test('the two step lists agree on how many steps there are', async () => {
  // rebuildFormChrome indexes VinylPhoneForm.STEPS by a step number that
  // setFormStep clamps to FORM_STEPS.length. A fifth step added to one list
  // and not the other reads undefined.phone and throws.
  const { win, read } = await boot({ phone: false });
  try {
    assert.strictEqual(read('FORM_STEPS').length, read('VinylPhoneForm.STEPS').length);
  } finally {
    win.close();
  }
});

// ── step 1: the lookup rows and the identity strip ──────────────────────────
// Every add actually starts with a lookup — camera, search, or a pasted
// Spotify link — and never with typing, so step 1 opens on those three as
// full-height rows rather than on an empty artist field. Once anything
// identifies the record (an artist, an album, or a cover) the lookup gives
// way to an 84px identity strip sitting above the fields.

test('step 1 opens on the three lookups, not on the fields', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    const rows = [...doc.querySelectorAll('#phoneLookup .frow')];
    assert.strictEqual(rows.length, 3);
    assert.deepStrictEqual(rows.map(r => r.dataset.lookup), ['camera', 'search', 'spotify']);
  } finally {
    win.close();
  }
});

test('each lookup row calls the function that already does that job', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    const called = [];
    for (const fn of ['openCamera', 'openSearchOverlay', 'openSpotifyOverlay']) {
      win[fn] = () => called.push(fn);
    }
    for (const r of doc.querySelectorAll('#phoneLookup .frow')) press(win, r);
    assert.deepStrictEqual(called, ['openCamera', 'openSearchOverlay', 'openSpotifyOverlay']);
  } finally {
    win.close();
  }
});

test('filling artist and album replaces the lookups with the identity strip', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    doc.getElementById('fArtist').value = 'Tim Maia';
    doc.getElementById('fAlbum').value = 'Racional Vol. 1';
    win.renderStep1Phone();
    assert.strictEqual(doc.getElementById('phoneLookup').hidden, true);
    assert.strictEqual(doc.getElementById('phoneIdentity').hidden, false);
    assert.match(doc.getElementById('phoneIdentity').textContent, /Tim Maia/);
  } finally {
    win.close();
  }
});

test('fill it in myself reveals the fields with no match', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    press(win, doc.getElementById('phoneLookupSkip'));
    assert.strictEqual(doc.getElementById('phoneLookup').hidden, true);
    assert.strictEqual(doc.getElementById('fArtist').closest('.form-section').hidden, false);
  } finally {
    win.close();
  }
});

test('the identity strip follows the fields as they are typed', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    doc.getElementById('fArtist').value = 'Tim Maia';
    doc.getElementById('fAlbum').value = 'Racional';
    win.renderStep1Phone();
    doc.getElementById('fYear').value = '1975';
    win.renderStep1Phone();
    assert.match(doc.getElementById('phoneIdentity').textContent, /1975/);
  } finally {
    win.close();
  }
});

test('the sensitive-cover checkbox only appears once there is a cover', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    const row = doc.getElementById('fCensored').closest('.check-row');
    assert.strictEqual(row.hidden, true);
    win.showCover('data:image/png;base64,iVBORw0KGgo=');
    win.renderStep1Phone();
    assert.strictEqual(row.hidden, false);
  } finally {
    win.close();
  }
});

test('opening a fresh record forgets that the last one skipped the lookup', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    press(win, doc.getElementById('phoneLookupSkip'));
    win.openAdd();
    assert.strictEqual(doc.getElementById('phoneLookup').hidden, false);
  } finally {
    win.close();
  }
});

test('desktop never renders the lookup rows', async () => {
  const { win, doc } = await boot({ phone: false });
  try {
    win.openAdd();
    assert.strictEqual(doc.getElementById('phoneLookup').hidden, true);
  } finally {
    win.close();
  }
});

// ── step 2: bought-at chips ──────────────────────────────────────────────────
// Safari draws a <datalist> as a thin strip under the keyboard — unusable
// one-handed. renderPlaceChips offers the same places as chips instead,
// ranked by VinylPhoneForm.rankPlaces. The fixture (tests/test_phone_dom.py)
// carries 11 records at "Benedito Calixto" and one at "Amazon" so the
// ranking has something real to prove.

test('bought at offers the places you actually use, most-used first', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    win.setFormStep(2);
    const chips = [...doc.querySelectorAll('#wherePhoneChips .chip')].map(c => c.textContent);
    assert.strictEqual(chips[0], 'Benedito Calixto');
    assert.ok(chips.includes('Amazon'));
    assert.ok(chips.length <= 4);
  } finally {
    win.close();
  }
});

test('tapping a place chip writes the field', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    win.setFormStep(2);
    press(win, doc.querySelector('#wherePhoneChips .chip'));
    assert.strictEqual(doc.getElementById('fWhere').value, 'Benedito Calixto');
  } finally {
    win.close();
  }
});

test('the datalist is still there for desktop, and the chip box stays hidden', async () => {
  const { win, doc } = await boot({ phone: false });
  try {
    win.openAdd();
    assert.ok(doc.querySelectorAll('#whereList option').length > 0);
    assert.strictEqual(doc.getElementById('wherePhoneChips').hidden, true);
  } finally {
    win.close();
  }
});

// ── step 3: collapsed log sections ───────────────────────────────────────────
// Plays, cleanings and notes were three open cards on a step whose own lead
// text says it is almost always empty. On a phone they collapse to one row
// each; a section that already has entries opens expanded, so the collapse
// only ever hides what really is empty.

test('empty log sections start collapsed on a phone', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    win.setFormStep(3);
    assert.strictEqual(doc.getElementById('playDatesSection').dataset.collapsed, 'true');
    assert.match(doc.getElementById('playDatesCount').textContent, /none/);
  } finally {
    win.close();
  }
});

test('cleanings and notes also start collapsed when empty on a phone', async () => {
  // LOG_SECTIONS drives all three sections from the same loop; this is the
  // check that a bug specific to the other two would not hide behind
  // playDatesSection alone passing.
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    win.setFormStep(3);
    assert.strictEqual(doc.getElementById('cleanedDatesSection').dataset.collapsed, 'true');
    assert.strictEqual(doc.getElementById('notesSection').dataset.collapsed, 'true');
  } finally {
    win.close();
  }
});

test('a section with entries starts open, so the collapse never hides anything', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openEdit(1);                       // fixture record 1 has a play date
    win.setFormStep(3);
    assert.strictEqual(doc.getElementById('playDatesSection').dataset.collapsed, 'false');
  } finally {
    win.close();
  }
});

test('the plus on a collapsed section opens it rather than navigating', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    win.setFormStep(3);
    press(win, doc.querySelector('#playDatesSection .log-plus'));
    assert.strictEqual(doc.getElementById('playDatesSection').dataset.collapsed, 'false');
  } finally {
    win.close();
  }
});

test('adding the first play date expands the section it just went into', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    win.setFormStep(3);
    assert.strictEqual(doc.getElementById('playDatesSection').dataset.collapsed, 'true');
    win.addPlayDate();
    assert.strictEqual(doc.getElementById('playDatesSection').dataset.collapsed, 'false');
  } finally {
    win.close();
  }
});

test('desktop leaves every log section expanded', async () => {
  const { win, doc } = await boot({ phone: false });
  try {
    win.openAdd();
    win.setFormStep(3);
    assert.strictEqual(doc.getElementById('playDatesSection').dataset.collapsed, 'false');
  } finally {
    win.close();
  }
});

test('notes keep their static "markdown" label on desktop', async () => {
  // renderLogCollapse only overwrites a count's textContent on a phone;
  // desktop's notesCount has no other writer, so it should still read
  // exactly what the markup shipped it with.
  const { win, doc } = await boot({ phone: false });
  try {
    win.openAdd();
    assert.strictEqual(doc.getElementById('notesCount').textContent, 'markdown');
  } finally {
    win.close();
  }
});

// ── step 4: full-width pickers ───────────────────────────────────────────────

test('size and discs are full width on a phone', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openAdd();
    win.setFormStep(4);
    // the pickers come out of the 2-up grid; each sits in its own full-width row
    const grid = doc.querySelector('#fSizePick').closest('.form-grid');
    assert.ok(grid.classList.contains('stack-phone'));
  } finally {
    win.close();
  }
});
