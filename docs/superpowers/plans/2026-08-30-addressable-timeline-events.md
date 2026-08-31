# Addressable Timeline Events Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the Timeline to one entry per record per day across Week, Month and Day, and make a click land on the event you clicked rather than the record it belongs to.

**Architecture:** Two pure functions join `static/timeline.js` — `keyOf` names an event, `recordDays` collapses a day's events by record. The three calendar renderers draw record-days instead of events, each carrying a rail of activity icons. A click passes an event key to `openDetail(id, focus)`, which stores it in a variable the drawer's render reads, so the highlight survives the wholesale re-render `dmSetCurrent` performs.

**Tech Stack:** Vanilla JS in a Flask template (`templates/index.html`, ~7400 lines), plain-script modules in `static/`, `node --test` for pure functions, jsdom for DOM behaviour, `pytest` as the single entry point.

**Spec:** `docs/superpowers/specs/2026-08-30-addressable-timeline-events-design.md`

## Global Constraints

- **The count rule, entire:** the icon is always drawn; a numeral joins it only when that action happened more than once that day. Nothing in the grid ever prints a `1`. `bought` needs no exception in code — `bought_date` is one column, so its count cannot reach two and the `> 1` test never fires.
- **Type order is `bought, cleaned, played, note`** — the existing `TYPE_ORDER` in `static/timeline.js:25`. A record is bought before it is cleaned, cleaned before it is played, and a note comes after the thing it describes.
- **The four icons are `ti-shopping-bag`, `ti-droplet`, `ti-headphones`, `ti-note`** — the set the Timeline's own type filter bar already draws (`templates/index.html:1736`).
- **No new dependencies.** The project has no `package.json` and must not gain one. jsdom is installed to a scratch dir by `tests/test_boot.py`.
- **`esc()` does not escape single quotes** (`templates/index.html:5239`). Event keys are built from stored date strings, so they must never be interpolated into an inline `onclick="...('${focus}')"`. Use `data-` attributes and a delegated listener.
- **Every test runs under `pytest`.** `pytest tests/test_timeline.py -v` and `pytest tests/test_boot.py -v`.
- Timers created in the page must pass through `idleUnref()` (`templates/index.html:7298`), or jsdom keeps the node process alive after the boot tests finish.
- **`2026-08-30-note-pictures-design.md` is in flight** and touches `dmHistoryEntryHTML` (a thumbnail strip in the note branch) and the note object (an optional `images` key). Neither collides: note keys index the `parseNotes` array, whose shape and order are unchanged, and the two edits land in different parts of the same function. If that work merged first, rebase Task 4's replacement of `dmHistoryEntryHTML` onto it rather than overwriting the thumbnail strip.

---

### Task 1: `keyOf` — an event's name

**Files:**
- Modify: `static/timeline.js:20-66`
- Test: `tests/test_timeline.js`

**Interfaces:**
- Consumes: nothing.
- Produces: `keyOf(type, at, i) -> string`, exported from `VinylTimeline`. Every event `eventsByDay` returns now also carries `key` (string), `at` (the raw date string it was filed from) and `day` (`'YYYY-MM-DD'`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_timeline.js`, after the "how a day reads" block:

```js
// ── an event's name ─────────────────────────────────────────────────────────

const { keyOf } = require('../static/timeline.js');

test('bought keys carry no index, because bought_date is one column', () => {
  assert.strictEqual(keyOf('bought', '2026-08-23'), 'bought:2026-08-23');
});

test('a list-backed event is named by its type, stamp and position', () => {
  assert.strictEqual(keyOf('played', '2026-08-23T21:12:00', 0),
    'played:2026-08-23T21:12:00:0');
});

test('two clockless cleanings on one day get different keys', () => {
  // Rows written before times were kept carry a bare date, so the stamp alone
  // would collide. This is why every list-backed type is indexed.
  const r = rec({ cleaned_dates: json('2026-08-23', '2026-08-23') });
  const got = on([r], '2026-08-23').map(e => e.key);
  assert.strictEqual(new Set(got).size, 2, 'keys collided: ' + got.join(' '));
});

test('every event carries its key, its raw stamp and its day', () => {
  const r = rec({ play_dates: json('2026-08-23T21:12:00') });
  const ev = on([r], '2026-08-23')[0];
  assert.strictEqual(ev.key, 'played:2026-08-23T21:12:00:0');
  assert.strictEqual(ev.at, '2026-08-23T21:12:00');
  assert.strictEqual(ev.day, '2026-08-23');
});

test('a note is indexed by its position in the raw notes array', () => {
  // The empty note still occupies index 0, so the note that follows it is 1.
  // Filtering first would renumber it and break the key the drawer expects.
  const r = rec({ notes: json({ date: '2026-08-23', text: '' },
                              { date: '2026-08-23', text: 'clicky side B' }) });
  assert.strictEqual(on([r], '2026-08-23')[0].key, 'note:2026-08-23:1');
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test tests/test_timeline.js`
Expected: FAIL — `keyOf is not a function`.

- [ ] **Step 3: Add `keyOf` and stamp events with it**

In `static/timeline.js`, add above `eventsByDay`:

```js
  /* An event's name.
   *
   * nowStamp() keeps seconds, so anything logged through the app is already
   * unique on its stamp alone — but rows written before times were kept carry
   * a bare 'YYYY-MM-DD', and two clockless cleanings on one day would collide.
   * Indexing every list-backed type is uniform and costs nothing.
   *
   * bought takes no index: bought_date is one column and cannot hold two.
   *
   * `at` is the RAW stored string, not a normalised moment. The drawer builds
   * its own history from the same parsers and must arrive at the same keys, so
   * both sides pass what the parser handed them and nothing in between. */
  function keyOf(type, at, i) {
    return type === 'bought' ? 'bought:' + at : type + ':' + at + ':' + i;
  }
```

Replace the `add` closure and the record loop inside `eventsByDay`:

```js
    const add = (date, event) => {
      const moment = grouping.momentOf(date);
      if (!moment.day) return;            // undated, or a stamp no calendar holds
      if (!map.has(moment.day)) map.set(moment.day, []);
      map.get(moment.day).push(Object.assign(
        { time: moment.time, day: moment.day, at: String(date),
          key: keyOf(event.type, String(date), event.i) },
        event));
    };

    (records || []).forEach(r => {
      if (on.bought) add(r.bought_date, { type: 'bought', r });
      if (on.cleaned) parseCleans(r.cleaned_dates).forEach((d, i) => add(d, { type: 'cleaned', r, i }));
      if (on.played) parsePlays(r.play_dates).forEach((d, i) => add(d, { type: 'played', r, i }));
      if (on.note) parseNotes(r.notes, r.bought_date).forEach((n, i) => {
        // The index is the position in the RAW array: an empty note still holds
        // its slot, so filtering first would renumber everything after it.
        if (n && n.text && n.text.trim()) add(n.date, { type: 'note', r, i, text: n.text });
      });
    });
```

Add `keyOf` to the returned object:

```js
  return { ALL_TYPES, TYPE_ORDER, keyOf, eventsByDay };
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test tests/test_timeline.js`
Expected: PASS, including every pre-existing test — `eventsByDay`'s output gained fields but lost none.

- [ ] **Step 5: Commit**

```bash
git add static/timeline.js tests/test_timeline.js
git commit -m "feat: name every timeline event"
```

---

### Task 2: `recordDays` — the collapse

**Files:**
- Modify: `static/timeline.js`
- Test: `tests/test_timeline.js`

**Interfaces:**
- Consumes: `eventsByDay` from Task 1, whose per-day lists are already sorted.
- Produces: `recordDays(dayEvents) -> [{ r, day, acts: [{type, evs}], evs }]`, exported from `VinylTimeline`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_timeline.js`:

```js
// ── one entry per record, per day ───────────────────────────────────────────

const { recordDays } = require('../static/timeline.js');

const collapse = (records, day) => recordDays(on(records, day));

test('four kinds on one day collapse to one entry with four acts', () => {
  const r = rec({
    bought_date: '2026-08-23',
    cleaned_dates: json('2026-08-23T18:20:00'),
    play_dates: json('2026-08-23T19:04:00'),
    notes: json({ date: '2026-08-23', text: 'seam split' }),
  });
  const got = collapse([r], '2026-08-23');
  assert.strictEqual(got.length, 1);
  assert.deepStrictEqual(got[0].acts.map(a => a.type),
    ['bought', 'cleaned', 'played', 'note']);
  assert.strictEqual(got[0].r, r);
  assert.strictEqual(got[0].day, '2026-08-23');
});

test('acts come back in type order however the day arrived', () => {
  // Clocks put the note first; TYPE_ORDER must still win in the rail.
  const r = rec({
    notes: json({ date: '2026-08-23T08:00:00', text: 'early thought' }),
    bought_date: '2026-08-23T20:00:00',
  });
  assert.deepStrictEqual(collapse([r], '2026-08-23')[0].acts.map(a => a.type),
    ['bought', 'note']);
});

test('two plays on one day are one act holding two events', () => {
  const r = rec({ play_dates: json('2026-08-23T19:04:00', '2026-08-23T21:47:00') });
  const acts = collapse([r], '2026-08-23')[0].acts;
  assert.strictEqual(acts.length, 1);
  assert.strictEqual(acts[0].evs.length, 2);
  assert.deepStrictEqual(acts[0].evs.map(e => e.time), ['19:04', '21:47']);
});

test('an entry keeps the day flat and chronological too', () => {
  const r = rec({ bought_date: '2026-08-23',
                  play_dates: json('2026-08-23T19:04:00') });
  assert.strictEqual(collapse([r], '2026-08-23')[0].evs.length, 2);
});

test('two records on one day are two entries', () => {
  const records = [rec({ bought_date: '2026-08-23' }), rec({ bought_date: '2026-08-23' })];
  assert.strictEqual(collapse(records, '2026-08-23').length, 2);
});

test('entries follow the record whose day started earliest', () => {
  const records = [
    rec({ album_name: 'Later', play_dates: json('2026-08-23T21:00:00') }),
    rec({ album_name: 'Earlier', play_dates: json('2026-08-23T09:00:00') }),
  ];
  assert.deepStrictEqual(collapse(records, '2026-08-23').map(g => g.r.album_name),
    ['Earlier', 'Later']);
});

test('an empty day collapses to nothing', () => {
  assert.deepStrictEqual(recordDays([]), []);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test tests/test_timeline.js`
Expected: FAIL — `recordDays is not a function`.

- [ ] **Step 3: Implement `recordDays`**

In `static/timeline.js`, add after `eventsByDay`:

```js
  /* One day's events, collapsed to one entry per record.
   *
   * The Week grid drew one chip per event, so a record bought, cleaned, played
   * twice and noted on one Sunday came out as five identical covers in one
   * 150-pixel column — the column counting events while the eye counts records.
   *
   * Order is inherited, not recomputed: eventsByDay hands back a day already
   * sorted by clock, then type, then album, so a record's FIRST appearance in
   * that list is the moment its day started. Insertion order is therefore
   * exactly "earliest event first", with the same tiebreaks the day already
   * uses. Sorting again here would only be a second, disagreeing opinion. */
  function recordDays(dayEvents) {
    const out = [], byRecord = new Map();
    (dayEvents || []).forEach(ev => {
      let g = byRecord.get(ev.r.id);
      if (!g) {
        g = { r: ev.r, day: ev.day, acts: [], evs: [] };
        byRecord.set(ev.r.id, g);
        out.push(g);
      }
      g.evs.push(ev);
      let a = g.acts.find(x => x.type === ev.type);
      if (!a) { a = { type: ev.type, evs: [] }; g.acts.push(a); }
      a.evs.push(ev);
    });
    // Within a record the rail reads bought, cleaned, played, note — the order
    // the day happened in, not the order the clock reported it.
    out.forEach(g => g.acts.sort((a, b) => TYPE_ORDER[a.type] - TYPE_ORDER[b.type]));
    return out;
  }
```

Add it to the returned object:

```js
  return { ALL_TYPES, TYPE_ORDER, keyOf, eventsByDay, recordDays };
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test tests/test_timeline.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add static/timeline.js tests/test_timeline.js
git commit -m "feat: collapse a timeline day to one entry per record"
```

---

### Task 3: One palette for the four facts

**Files:**
- Modify: `templates/index.html:26-41` (theme tokens), `:487-497` (`.dm-hist-entry` dots), `:1494-1497` (`.cal-dot`), `:1525-1528` (`.cal-event`), `:1539-1542` (`.cal-badge`), `:1555-1558` (`.cal-week-chip`)
- Test: `tests/test_boot.js`

**Interfaces:**
- Consumes: nothing.
- Produces: `--ev-bought`, `--ev-cleaned`, `--ev-played`, `--ev-note` as the single source for all four activity colours, in both themes.

**Note on values:** the spec says the Timeline's values move into `--ev-*`. Dark takes them verbatim. Light takes deepened variants of the same hues — the light ground is `#e1ddd3`, where full-saturation `#5FBF7A` washes out, and the app already deepens its accent for exactly this reason (`templates/index.html:21-24`). These are the values the approved mockup shows.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_boot.js`, after `test('the accent is the gold, dark and light', ...)`:

```js
test('one palette answers for the four activities, dark and light', async () => {
  const { win, doc } = await boot();
  for (const theme of ['dark', 'light']) {
    win.applyTheme(theme);
    const root = win.getComputedStyle(doc.documentElement);
    for (const t of ['bought', 'cleaned', 'played', 'note']) {
      const v = root.getPropertyValue('--ev-' + t).trim();
      assert.match(v, /^#[0-9a-fA-F]{6}$/, `--ev-${t} is not a colour in ${theme}: "${v}"`);
    }
    // bought used to BE the accent, which in light mode is a dark olive —
    // not what "gold means bought" is trying to say.
    assert.notStrictEqual(root.getPropertyValue('--ev-bought').trim(),
      root.getPropertyValue('--accent').trim(),
      `bought is still riding the accent in ${theme}`);
  }
});

test('nothing in the timeline paints an activity colour by hand', async () => {
  // Two palettes for one set of four facts is how they drifted apart the first
  // time. The literals live in :root now, and only there.
  const css = fs.readFileSync(path.join(ROOT, 'templates', 'index.html'), 'utf8');
  const body = css.slice(css.indexOf('.cal-dot{'));
  for (const hex of ['#4AA3C4', '#5FBF7A', '#9B7FD4']) {
    assert.strictEqual(body.includes(hex), false,
      `${hex} is still hard-coded below :root`);
  }
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_boot.py -v`
Expected: FAIL — `--ev-bought` equals `--accent` is false only after the change; the literal scan finds `#4AA3C4`.

- [ ] **Step 3: Move the four colours into the tokens**

In `[data-theme="dark"]` (`templates/index.html:31`), replace the `--ev-*` line with:

```css
  --ev-bought:#F5C518; --ev-cleaned:#4AA3C4; --ev-played:#5FBF7A; --ev-note:#9B7FD4;
```

In `[data-theme="light"]` (`templates/index.html:39`), replace it with:

```css
  --ev-bought:#b39609; --ev-cleaned:#2b7f99; --ev-played:#3d8a55; --ev-note:#6f4fae;
```

Then replace every hand-painted activity colour with its token. `.cal-dot` (`:1494`):

```css
.cal-dot.bought{background:var(--ev-bought)}
.cal-dot.cleaned{background:var(--ev-cleaned)}
.cal-dot.played{background:var(--ev-played)}
.cal-dot.note{background:var(--ev-note)}
```

`.cal-event` (`:1525`):

```css
.cal-event.bought{border-left-color:var(--ev-bought)}
.cal-event.cleaned{border-left-color:var(--ev-cleaned)}
.cal-event.played{border-left-color:var(--ev-played)}
.cal-event.note{border-left-color:var(--ev-note)}
```

`.cal-badge` (`:1539`) — the `rgba()` fills become `color-mix`, which the app already uses:

```css
.cal-badge.bought{color:var(--ev-bought);border-color:color-mix(in srgb, var(--ev-bought) 45%, transparent);background:color-mix(in srgb, var(--ev-bought) 7%, transparent)}
.cal-badge.cleaned{color:var(--ev-cleaned);border-color:color-mix(in srgb, var(--ev-cleaned) 45%, transparent);background:color-mix(in srgb, var(--ev-cleaned) 7%, transparent)}
.cal-badge.played{color:var(--ev-played);border-color:color-mix(in srgb, var(--ev-played) 45%, transparent);background:color-mix(in srgb, var(--ev-played) 7%, transparent)}
.cal-badge.note{color:var(--ev-note);border-color:color-mix(in srgb, var(--ev-note) 45%, transparent);background:color-mix(in srgb, var(--ev-note) 7%, transparent)}
```

`.dm-hist-entry` dots (`:486-490`):

```css
.dm-hist-entry .dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;margin-top:5px;background:var(--ev-note)}
.dm-hist-entry.bought .dot{background:var(--ev-bought)}
.dm-hist-entry.cleaned .dot{background:var(--ev-cleaned)}
.dm-hist-entry.played .dot{background:var(--ev-played)}
.dm-hist-entry.note .dot{background:var(--ev-note)}
```

And `.dm-hist-entry.bought .dm-hist-icon` (`:497`) becomes `color:var(--ev-bought)`. Check the lines that follow it for `cleaned` / `played` icon colours and give them the matching tokens.

Leave the `.cal-week-chip` rules (`:1553-1560`) alone — Task 6 replaces that block entirely.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_boot.py -v`
Expected: PASS, including the pre-existing theme tests.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html tests/test_boot.js
git commit -m "refactor: one palette for bought, cleaned, played and noted"
```

---

### Task 4: `openDetail(id, focus)` and the focus the render reads

**Files:**
- Modify: `templates/index.html:3218-3262` (`dmHistoryEvents`, `dmHistoryEntryHTML`, `dmHistoryGroupHTML`), `:3500-3513` (`openDetail`), `:3560` (`goToDetailRecord`), `:3588` (`closeDetail`)
- Test: `tests/test_boot.js`

**Interfaces:**
- Consumes: `VinylTimeline.keyOf` from Task 1.
- Produces: `openDetail(id, focus)` where `focus` is optional and takes one of three shapes — `'note:2026-03-08:0'` (one event), `'2026-03-08~played'` (one day's events of one kind), `'2026-03-08'` (the whole day). Also `focusMatches(focus, ev) -> boolean`, and the module variable `detailFocus`. Every `.dm-hist-entry` gains `data-ev` and `data-day`; every `.hd` gains `data-day`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_boot.js`:

```js
// ── the timeline sends you to an event, not just a record ───────────────────

/* A record with a whole Sunday on it: bought, cleaned, played twice, noted.
 * Built here rather than in the fixture so the sibling tests' counts stand. */
function busySunday(read) {
  const r = read('records')[0];
  r.bought_date = '2026-08-09';
  r.cleaned_dates = JSON.stringify(['2026-08-09T18:20:11']);
  r.play_dates = JSON.stringify(['2026-08-09T19:04:33', '2026-08-09T21:47:02']);
  r.notes = JSON.stringify([{ date: '2026-08-09', text: 'seam split' }]);
  return r;
}

const litKeys = doc => [...doc.querySelectorAll('#detailBody .dm-hist-entry.hit')]
  .map(el => el.dataset.ev);

test('a focused note lights that note and its date, and nothing else', async () => {
  const { win, doc, read } = await boot();
  const r = busySunday(read);
  win.openDetail(r.id, 'note:2026-08-09:0');
  assert.deepStrictEqual(litKeys(doc), ['note:2026-08-09:0']);
  const heads = [...doc.querySelectorAll('#detailBody .hd.hit')].map(el => el.dataset.day);
  assert.deepStrictEqual(heads, ['2026-08-09']);
});

test('a repeated action lights its own kind, not the whole day', async () => {
  // Two plays cannot resolve to one play — but they should not drag the
  // cleaning and the purchase in with them either.
  const { win, doc, read } = await boot();
  const r = busySunday(read);
  win.openDetail(r.id, '2026-08-09~played');
  assert.deepStrictEqual(litKeys(doc).sort(),
    ['played:2026-08-09T19:04:33:0', 'played:2026-08-09T21:47:02:1']);
});

test('a focused day lights all five of its entries', async () => {
  const { win, doc, read } = await boot();
  const r = busySunday(read);
  win.openDetail(r.id, '2026-08-09');
  assert.strictEqual(litKeys(doc).length, 5);
});

test('the whole history is still there, with one entry lit', async () => {
  // The highlight is additive. The surrounding history is usually why the
  // click was worth making.
  const { win, doc, read } = await boot();
  const r = busySunday(read);
  r.play_dates = JSON.stringify(['2026-08-01T10:00:00', '2026-08-09T19:04:33']);
  win.openDetail(r.id, 'played:2026-08-01T10:00:00:0');
  assert.strictEqual(doc.querySelectorAll('#detailBody .dm-hist-entry').length, 4);
  assert.deepStrictEqual(litKeys(doc), ['played:2026-08-01T10:00:00:0']);
});

test('opening a record with no focus lights nothing', async () => {
  const { win, doc, read } = await boot();
  const r = busySunday(read);
  win.openDetail(r.id);
  assert.deepStrictEqual(litKeys(doc), []);
});

test('the highlight survives the re-render the carousel triggers', async () => {
  // openDetail centres the carousel; its scroll handler calls dmSetCurrent,
  // which rewrites #dmInfo and #ddInfo wholesale a frame later. A class
  // stamped on after render would be gone.
  const { win, doc, read } = await boot();
  const r = busySunday(read);
  win.openDetail(r.id, 'note:2026-08-09:0');
  win.dmSetCurrent(read('dmIdx'));
  assert.deepStrictEqual(litKeys(doc), ['note:2026-08-09:0']);
});

test('walking to another record drops the highlight', async () => {
  const { win, doc, read } = await boot();
  const r = busySunday(read);
  win.openDetail(r.id, 'note:2026-08-09:0');
  win.navigateDetail(1);
  settleAnimations(win, doc);
  assert.deepStrictEqual(litKeys(doc), []);
  assert.strictEqual(read('detailFocus'), null);
});

test('closing the drawer clears the focus', async () => {
  const { win, read } = await boot();
  const r = busySunday(read);
  win.openDetail(r.id, '2026-08-09');
  win.closeDetail();
  assert.strictEqual(read('detailFocus'), null);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_boot.py -v`
Expected: FAIL — no `.hit` elements, no `data-ev` attributes.

- [ ] **Step 3: Give the drawer's history the same keys, and a focus to read**

Replace `dmHistoryEvents` (`templates/index.html:3219`):

```js
// merges bought/played/cleaned/notes into one chronological (oldest-first) timeline
//
// The keys have to be the ones eventsByDay produces, or a click in the Timeline
// names an event this list does not recognise. Both sides run the same parsers
// and hand keyOf what the parser gave them, so they agree by construction.
function dmHistoryEvents(r) {
  const events = [];
  const add = (type, date, extra) => {
    const m = momentOf(date);
    // a bought date or a note has no clock; it still needs a day to file under
    if (!m.day && !/^\d{4}-\d{2}-\d{2}/.test(date || '')) return;
    events.push(Object.assign({ type, day: m.day || String(date).slice(0,10),
                                time: m.time, at: m.at || String(date).slice(0,10),
                                key: VinylTimeline.keyOf(type, String(date),
                                                         extra && extra.i) }, extra));
  };
  if (r.bought_date) add('bought', r.bought_date);
  parseCleanedDates(r.cleaned_dates).forEach((dt, i) => { if (dt) add('cleaned', dt, { i }); });
  parsePlayDates(r.play_dates).forEach((dt, i) => { if (dt) add('played', dt, { i }); });
  // The raw index again: an empty note holds its slot, so filtering first would
  // renumber every note after it and break keys the Timeline already handed out.
  if (r.notes) parseNotes(r.notes, r.bought_date||today()).forEach((n, i) => {
    if (n.text) add('note', n.date, { i, text: n.text });
  });
  // by day AND time, so two plays on one evening read in the order they happened
  return events.sort((a,b) => a.at.localeCompare(b.at));
}
```

Add, just above `dmHistoryEntryHTML`:

```js
/* Which event the Timeline sent us to, if any.
 *
 * This must be state the RENDER reads, never a class applied afterwards.
 * openDetail centres the carousel, whose scroll handler calls dmSetCurrent,
 * which rewrites #dmInfo and #ddInfo wholesale a frame later — anything
 * stamped on after the fact is gone before you have finished reading it. */
let detailFocus = null;

/* Three widths of focus, narrowest first:
 *   'note:2026-03-08:0'   one event
 *   '2026-03-08~played'   one day's events of one kind
 *   '2026-03-08'          the whole day
 *
 * The middle one earns its place: two plays cannot resolve to one play, but
 * routing them to the whole day drags the cleaning in with them. */
function focusMatches(focus, ev) {
  if (!focus) return false;
  const scoped = /^(\d{4}-\d{2}-\d{2})~(\w+)$/.exec(focus);
  if (scoped) return ev.day === scoped[1] && ev.type === scoped[2];
  if (/^\d{4}-\d{2}-\d{2}$/.test(focus)) return ev.day === focus;
  return ev.key === focus;
}
```

Replace `dmHistoryEntryHTML` and `dmHistoryGroupHTML`:

```js
function dmHistoryEntryHTML(ev) {
  // no clock on entries recorded before times were kept — the icon or the note
  // just sits alone, rather than the timeline claiming it happened at midnight
  const clock = ev.time ? `<span class="dm-hist-time">${esc(ev.time)}</span>` : '';
  const body = ev.type === 'note'
    ? `<div class="ht detail-notes-body">${typeof marked !== 'undefined' ? marked.parse(ev.text) : esc(ev.text)}` +
      `<span class="dm-hist-time"><i class="ti ${DM_HIST_ICON.note} dm-hist-icon"></i>${ev.time ? ' ' + esc(ev.time) : ''}</span></div>`
    : `<div class="ht"><i class="ti ${DM_HIST_ICON[ev.type]} dm-hist-icon" title="${DM_HIST_LABEL[ev.type]}"></i>${clock}</div>`;
  const lit = focusMatches(detailFocus, ev) ? ' hit' : '';
  return `<div class="dm-hist-entry ${ev.type}${lit}" data-ev="${esc(ev.key)}" data-day="${esc(ev.day)}"><span class="dot"></span>${body}</div>`;
}

function dmHistoryGroupHTML(group) {
  const hitTypes = [...new Set(group.items.filter(ev => focusMatches(detailFocus, ev))
                                          .map(ev => ev.type))];
  // One kind, one colour: a single event or a single type lets the date wear
  // the colour of the thing that happened to it. A whole-day focus cannot —
  // there is no one colour four kinds of fact could share — so it takes gold.
  const lit = hitTypes.length === 0 ? ''
            : hitTypes.length === 1 ? ` hit hit-${hitTypes[0]}` : ' hit';
  return `<div class="dm-hist-group"><div class="hd${lit}" data-day="${esc(group.day)}">${dmFormatNoteDate(group.day)}</div>${group.items.map(dmHistoryEntryHTML).join('')}</div>`;
}
```

Add `note` to the icon and label maps (`templates/index.html:3247`):

```js
const DM_HIST_LABEL = { bought:'Added to the collection', played:'Played', cleaned:'Cleaned', note:'Note' };
const DM_HIST_ICON = { bought:'ti-shopping-bag', played:'ti-headphones', cleaned:'ti-droplet', note:'ti-note' };
```

Give `openDetail` the second argument:

```js
function openDetail(id, focus) {
  const r = records.find(x=>x.id===id); if(!r)return;
  confirmDeleteId = null;
  currentDetailId = id;
  detailFocus = focus || null;
  renderDetailContent(r);
  updateDetailNavVisibility();
  document.getElementById('detailOverlay').classList.remove('hidden');
  syncUrl(true);
  if (window.matchMedia('(max-width:760px)').matches) {
    dmCenterSlide(dmIdx, false);
    dmCenterCrateThumb(dmIdx, false);
  } else {
    ddCenterSlide(dmIdx, false);
  }
  // .overlay.hidden is display:none, so there is no layout to scroll until the
  // line above. Doing it here, in the same task, means the browser paints once
  // with the entry already in view — rather than painting the top of a long
  // history and then sliding it, which spends the first of the five seconds.
  scrollFocusIntoView();
}

// The history sits below the cover carousel, the crate strip and the metadata
// grid, which on a phone is a long way down.
function scrollFocusIntoView() {
  const el = document.querySelector('#detailBody .dm-hist-entry.hit, #detailBody .hd.hit');
  if (el && el.scrollIntoView) el.scrollIntoView({ block: 'center' });
}
```

Clear it in `closeDetail`:

```js
function closeDetail(){
  document.getElementById('detailOverlay').classList.add('hidden');
  confirmDeleteId=null;currentDetailId=null;detailFocus=null;
  syncUrl(true);
}
```

And at the top of `goToDetailRecord`, so walking to a neighbour never carries a stale highlight:

```js
function goToDetailRecord(nextRecord, delta) {
  detailFocus = null;
  const body = document.getElementById('detailBody');
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_boot.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html tests/test_boot.js
git commit -m "feat: open a record on the event you clicked"
```

---

### Task 5: The highlight, and letting go of it

**Files:**
- Modify: `templates/index.html:473-497` (history CSS), and the focus block from Task 4
- Test: `tests/test_boot.js`

**Interfaces:**
- Consumes: `detailFocus`, `focusMatches` and the `hit` / `hit-<type>` classes from Task 4.
- Produces: `focusDetail(focus)`, which sets `detailFocus` and starts the five-second clock. `openDetail` calls it instead of assigning `detailFocus` directly.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_boot.js`:

```js
test('the highlight lets go after five seconds', async () => {
  const { win, doc, read } = await boot();
  const r = busySunday(read);
  win.openDetail(r.id, 'note:2026-08-09:0');
  assert.strictEqual(litKeys(doc).length, 1);

  // 4.2s held, then 800ms fading. Driven by hand: jsdom has no clock of its own
  // worth waiting on, and a real five-second sleep in a unit test is a tax.
  read('focusLetGo()');
  assert.strictEqual(read('detailFocus'), null,
    'the focus outlived its hold, so a later re-render would light it again');
  assert.strictEqual(doc.querySelectorAll('#detailBody .letting-go').length, 1);

  read('focusForget()');
  assert.deepStrictEqual(litKeys(doc), []);
});

test('a closed drawer leaves no timer pointing at a detached node', async () => {
  const { win, read } = await boot();
  const r = busySunday(read);
  win.openDetail(r.id, '2026-08-09');
  win.closeDetail();
  assert.strictEqual(read('detailFocusTimer'), null);
  assert.strictEqual(read('detailFadeTimer'), null);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_boot.py -v`
Expected: FAIL — `focusLetGo is not defined`.

- [ ] **Step 3: Add the clock and the CSS**

Replace the `let detailFocus = null;` line from Task 4 with:

```js
let detailFocus = null;
let detailFocusTimer = null, detailFadeTimer = null;

// Five seconds: held, then let go over the last 800ms.
const FOCUS_HOLD_MS = 4200, FOCUS_FADE_MS = 800;

/* Light the event, then stop lighting it.
 *
 * Letting go does NOT re-render. detailFocus is cleared so that any later
 * render draws the history plain, and the nodes already on screen fade rather
 * than snap — which is also why the fade is two steps and not one. */
function focusDetail(focus) {
  clearTimeout(detailFocusTimer); clearTimeout(detailFadeTimer);
  detailFocusTimer = detailFadeTimer = null;
  detailFocus = focus || null;
  if (!detailFocus) return;
  detailFocusTimer = idleUnref(setTimeout(focusLetGo, FOCUS_HOLD_MS));
}

function focusLetGo() {
  detailFocus = null;
  detailFocusTimer = null;
  document.querySelectorAll('#detailBody .hit').forEach(el => el.classList.add('letting-go'));
  detailFadeTimer = idleUnref(setTimeout(focusForget, FOCUS_FADE_MS));
}

function focusForget() {
  detailFadeTimer = null;
  document.querySelectorAll('#detailBody .hit').forEach(el =>
    el.classList.remove('hit', 'letting-go',
      'hit-bought', 'hit-cleaned', 'hit-played', 'hit-note'));
}
```

In `openDetail`, replace `detailFocus = focus || null;` with `focusDetail(focus);`.

In `closeDetail`, replace `detailFocus=null;` with `focusDetail(null);` — which also clears both timers.

In `goToDetailRecord`, replace `detailFocus = null;` with `focusDetail(null);`.

Add the CSS after `.dm-hist-entry .ht p:last-child` (`templates/index.html:493`):

```css
/* The Timeline sent you here — say which event, for five seconds.
   Additive on purpose: the history stays whole, nothing is filtered or dimmed,
   because the surrounding history is usually why the click was worth making. */
.dm-hist-entry.hit,.dm-hist-group .hd.hit{--hc:var(--accent);
  background:color-mix(in srgb, var(--hc) 20%, transparent);
  border-radius:3px;transition:background .8s ease,box-shadow .8s ease}
.dm-hist-entry.hit{box-shadow:inset 3px 0 0 var(--hc);padding:2px 6px;margin:-2px -6px 4px}
.dm-hist-group .hd.hit{padding:2px 5px;margin-left:-5px;display:inline-block}
.dm-hist-entry.bought.hit{--hc:var(--ev-bought)}
.dm-hist-entry.cleaned.hit{--hc:var(--ev-cleaned)}
.dm-hist-entry.played.hit{--hc:var(--ev-played)}
.dm-hist-entry.note.hit{--hc:var(--ev-note)}
/* One kind of thing happened, so the date can wear its colour. A whole-day
   focus carries no hit-<type> and keeps the gold above. */
.hd.hit-bought{--hc:var(--ev-bought)} .hd.hit-cleaned{--hc:var(--ev-cleaned)}
.hd.hit-played{--hc:var(--ev-played)} .hd.hit-note{--hc:var(--ev-note)}
.dm-hist-entry.hit.letting-go,.dm-hist-group .hd.hit.letting-go{
  background:transparent;box-shadow:inset 3px 0 0 transparent}
@media(prefers-reduced-motion:reduce){
  .dm-hist-entry.hit,.dm-hist-group .hd.hit{transition:none}
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_boot.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html tests/test_boot.js
git commit -m "feat: hold the highlight five seconds, then let go"
```

---

### Task 6: The week chip — cover plus icon rail

**Files:**
- Modify: `templates/index.html:1553-1592` (chip CSS), `:7116-7127` (`calWeekChip`), `:7160-7186` (`renderCalWeek`), `:7216` (`openDetailFromCal`)
- Test: `tests/test_boot.js`

**Interfaces:**
- Consumes: `VinylTimeline.recordDays` (Task 2), `openDetail(id, focus)` (Task 4).
- Produces: `calRecordDayChip(g) -> string`, `calActBtn(g, act, cls) -> string`, `calActsLabel(g) -> string`, `CAL_TYPE_ICON`, `openDetailFromCal(id, focus)`, and a delegated click handler on `#calBody` reading `data-rec` / `data-focus`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_boot.js`:

```js
const weekChips = doc => [...doc.querySelectorAll('#calBody .cal-week-chip')];

async function busyWeek() {
  const b = await boot();
  busySunday(b.read);
  b.win.switchTab('timeline');
  b.win.setCalScale('week');
  b.win.calJumpToDate('2026-08-09');   // the Sunday itself
  return b;
}

test('a record with five events on one day draws one chip', async () => {
  const { doc } = await busyWeek();
  assert.strictEqual(weekChips(doc).length, 1);
});

test('the chip rails the day in bought-cleaned-played-note order', async () => {
  const { doc } = await busyWeek();
  const rail = [...weekChips(doc)[0].querySelectorAll('.cal-act')];
  assert.deepStrictEqual(rail.map(b => b.dataset.type),
    ['bought', 'cleaned', 'played', 'note']);
});

test('a numeral appears only where the action happened more than once', async () => {
  const { doc } = await busyWeek();
  const rail = [...weekChips(doc)[0].querySelectorAll('.cal-act')];
  assert.deepStrictEqual(rail.map(b => b.querySelector('b') ? b.querySelector('b').textContent : ''),
    ['', '', '2', '']);
});

test('nothing in the grid ever prints a 1', async () => {
  const { doc } = await busyWeek();
  const ones = [...doc.querySelectorAll('#calBody .cal-act b')]
    .filter(b => b.textContent.trim() === '1');
  assert.deepStrictEqual(ones, []);
});

test('every rail icon is one of the four the type bar draws', async () => {
  const { doc } = await busyWeek();
  const bar = [...doc.querySelectorAll('#calTypesBar .cal-type-btn i')]
    .map(i => [...i.classList].find(c => c.startsWith('ti-')));
  const rail = [...doc.querySelectorAll('#calBody .cal-act i')]
    .map(i => [...i.classList].find(c => c.startsWith('ti-')));
  rail.forEach(c => assert.ok(bar.includes(c), `${c} is not on the type bar`));
});

test('the cover opens the record on the whole day', async () => {
  const { win, doc, read } = await busyWeek();
  press(win, weekChips(doc)[0].querySelector('.cal-week-chip-art'));
  assert.strictEqual(read('detailFocus'), '2026-08-09');
});

test('a once-only icon opens the record on that one event', async () => {
  const { win, doc, read } = await busyWeek();
  const clean = [...weekChips(doc)[0].querySelectorAll('.cal-act')]
    .find(b => b.dataset.type === 'cleaned');
  press(win, clean);
  assert.strictEqual(read('detailFocus'), 'cleaned:2026-08-09T18:20:11:0');
});

test('a numeral icon opens the record on that day of that kind', async () => {
  const { win, doc, read } = await busyWeek();
  const played = [...weekChips(doc)[0].querySelectorAll('.cal-act')]
    .find(b => b.dataset.type === 'played');
  press(win, played);
  assert.strictEqual(read('detailFocus'), '2026-08-09~played');
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_boot.py -v`
Expected: FAIL — the week still draws one chip per event, and `.cal-act` does not exist.

- [ ] **Step 3: Draw record-days**

Replace `calWeekChip` (`templates/index.html:7116`) with:

```js
// The four glyphs are the ones the type bar already draws, so the icon on a
// chip and the icon on the switch that hides it are the same shape.
const CAL_TYPE_ICON = { bought:'ti-shopping-bag', cleaned:'ti-droplet',
                        played:'ti-headphones', note:'ti-note' };

function calActsLabel(g) {
  return g.acts.map(a => CAL_TYPE_LABEL[a.type] + (a.evs.length > 1 ? ' ×' + a.evs.length : ''))
               .join(', ');
}

/* One activity, as a button.
 *
 * The icon is always drawn; a numeral joins it only when that action happened
 * more than once. A lone icon means once — nothing in the grid prints a 1, and
 * bought needs no exception because bought_date is one column and its count
 * cannot reach two.
 *
 * The focus is a data attribute rather than an inline onclick argument: keys
 * are built from stored date strings, and esc() does not escape single quotes. */
function calActBtn(g, a, cls) {
  const n = a.evs.length;
  const focus = n > 1 ? g.day + '~' + a.type : a.evs[0].key;
  const when = a.evs[0].time ? ' · ' + a.evs[0].time : '';
  return `<button type="button" class="${cls} ${a.type}" data-rec="${g.r.id}"
    data-type="${a.type}" data-focus="${esc(focus)}"
    title="${CAL_TYPE_LABEL[a.type]}${n > 1 ? ' ×' + n : ''}${esc(when)}">
    <i class="ti ${CAL_TYPE_ICON[a.type]}"></i>${n > 1 ? `<b>${n}</b>` : ''}</button>`;
}

// one record's day — the cover, then what happened to it
function calRecordDayChip(g) {
  const label = esc(g.r.album_name) || esc(artistDisplay(g.r)) || 'untitled';
  const cover = g.r.cover_url
    ? `<img src="${g.r.cover_url}" alt="" loading="lazy" onerror="this.remove()">`
    : `<i class="ti ti-disc"></i>`;
  return `<div class="cal-week-chip">
    <button type="button" class="cal-week-chip-art" data-rec="${g.r.id}"
      data-focus="${esc(g.day)}" title="${esc(artistDisplay(g.r))} — ${label} (${esc(calActsLabel(g))})">
      ${cover}</button>
    <span class="cal-rail">${g.acts.map(a => calActBtn(g, a, 'cal-act')).join('')}</span>
  </div>`;
}
```

In `renderCalWeek` (`:7176`), replace the body line:

```js
        ${evs.length ? VinylTimeline.recordDays(evs).map(calRecordDayChip).join('') : '<div class="cal-week-empty">—</div>'}
```

Replace `openDetailFromCal` (`:7216`):

```js
function openDetailFromCal(id, focus) {
  closeCalDay();
  openDetail(id, focus);
}
```

Add the delegated listener next to the other calendar wiring, at the end of the calendar section:

```js
/* One listener for every chip, pill and row the calendar draws.
 *
 * Delegated rather than inline: an event key is built from stored date strings
 * and esc() leaves single quotes alone, so a key must never be interpolated
 * into an onclick argument. */
['calBody', 'calDayBody'].forEach(id => {
  document.getElementById(id).addEventListener('click', e => {
    const hit = e.target.closest('[data-rec][data-focus]');
    if (!hit) return;
    e.stopPropagation();
    openDetailFromCal(Number(hit.dataset.rec), hit.dataset.focus);
  });
});
```

Replace the `.cal-week-chip` CSS block (`:1553-1560`):

```css
/* One record's day. The cover keeps a neutral border — it used to spend its
   only channel saying which single event this was — and the day's actions
   line up beneath it in the order the day reads. */
.cal-week-chip{display:flex;flex-direction:column;gap:4px}
.cal-week-chip-art{width:100%;aspect-ratio:1;padding:0;border:1px solid var(--border);
  border-radius:4px;overflow:hidden;background:var(--bg-alt);cursor:pointer;
  display:flex;align-items:center;justify-content:center;color:var(--muted);
  font-size:14px;transition:border-color .12s,filter .12s}
.cal-week-chip-art:hover{filter:brightness(1.1);border-color:var(--accent)}
.cal-week-chip-art img{width:100%;height:100%;object-fit:cover;display:block}
.cal-rail{display:flex;gap:2px;align-items:center;justify-content:center;flex-wrap:wrap}
.cal-act{display:inline-flex;align-items:center;gap:1px;padding:2px 3px;border:0;
  border-radius:3px;background:none;cursor:pointer;font-family:var(--font-mono);
  font-size:9.5px;font-weight:700;line-height:1;transition:background .12s}
.cal-act:hover{background:color-mix(in srgb, currentColor 16%, transparent)}
.cal-act i{font-size:15px}
.cal-act.bought{color:var(--ev-bought)} .cal-act.cleaned{color:var(--ev-cleaned)}
.cal-act.played{color:var(--ev-played)} .cal-act.note{color:var(--ev-note)}
```

And in the `@media(max-width:760px)` block (`:1585`), replace the `.cal-week-chip-cover` line with:

```css
  .cal-week-chip{gap:2px}
  /* 46px of column leaves about 40 for the rail: four icons at 10px each.
     Readable, and nowhere near tappable. So the rail becomes a legend and the
     cover takes the tap, through to the day list where each action is a row. */
  .cal-rail{gap:1px;pointer-events:none}
  .cal-act{padding:0}
  .cal-act i{font-size:10px}
  .cal-act b{display:none}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_boot.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html tests/test_boot.js
git commit -m "feat: one cover per record per day in the week grid"
```

---

### Task 7: Month pills

**Files:**
- Modify: `templates/index.html:7132-7156` (`renderCalMonth`), `:1509-1512` (pill CSS)
- Test: `tests/test_boot.js`

**Interfaces:**
- Consumes: `VinylTimeline.recordDays` (Task 2), `calActBtn` and `CAL_TYPE_ICON` (Task 6).
- Produces: nothing new; month cells emit `.cal-pill` elements carrying `.cal-act` buttons.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_boot.js`:

```js
test('a month cell counts record-days, not events', async () => {
  const { win, doc, read } = await boot();
  busySunday(read);
  win.switchTab('timeline');
  win.setCalScale('month');
  win.calJumpToDate('2026-08-09');   // renderCalendar honours the scale already set
  // The grid pads with the neighbouring months, which carry a 9 of their own.
  const cell = [...doc.querySelectorAll('#calBody .cal-cell:not(.cal-out)')]
    .find(c => c.querySelector('.cal-cell-num').textContent === '9');
  assert.strictEqual(cell.querySelectorAll('.cal-pill').length, 1,
    'five events on one record should be one pill');
});

test('month pills carry icons but no numerals', async () => {
  // A pill is a line of text in a cell about 120px wide; the numerals are the
  // first thing that stops fitting. The count is one zoom away.
  const { win, doc, read } = await boot();
  busySunday(read);
  win.switchTab('timeline');
  win.setCalScale('month');
  win.calJumpToDate('2026-08-09');
  assert.ok(doc.querySelectorAll('#calBody .cal-pill .cal-act i').length >= 4);
  assert.strictEqual(doc.querySelectorAll('#calBody .cal-pill .cal-act b').length, 0);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_boot.py -v`
Expected: FAIL — five pills, and no `.cal-act` inside them.

- [ ] **Step 3: Draw record-days in the month grid**

In `renderCalMonth` (`templates/index.html:7139`), replace the three lines that build `shown` and the pills:

```js
    const days = VinylTimeline.recordDays(evs);
    const shown = days.slice(0, 3);
    const typesPresent = [...new Set(evs.map(e => e.type))];
    cells += `<div class="cal-cell${cur.getMonth() !== m ? ' cal-out' : ''}${k === todayK ? ' cal-today' : ''}${evs.length ? ' has-ev' : ''}"${evs.length ? ` onclick="openCalDay('${k}')"` : ''}>
      <div class="cal-cell-num">${cur.getDate()}</div>
      <div class="cal-cell-evs">
        ${shown.map(g => `<div class="cal-pill">${g.acts.map(a => calActBtn(g, a, 'cal-act pill')).join('')}<span class="cal-pill-txt">${esc(g.r.album_name || artistDisplay(g.r))}</span></div>`).join('')}
        ${days.length > 3 ? `<div class="cal-more">+${days.length-3} more</div>` : ''}
      </div>
      <div class="cal-cell-dots">${typesPresent.map(t => `<span class="cal-dot ${t}"></span>`).join('')}</div>
    </div>`;
```

`+N more` now counts record-days, so fewer cells reach the three-entry ceiling than before. `cal-cell-dots` keeps one dot per distinct type, unchanged.

Add the pill-size rail rules after `.cal-pill-txt` (`:1511`):

```css
/* At pill size the rail is icons only — a numeral is the first thing that
   stops fitting in a 120px cell, and the count is one zoom away. */
.cal-act.pill{padding:0;gap:0}
.cal-act.pill i{font-size:11px}
.cal-act.pill b{display:none}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_boot.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html tests/test_boot.js
git commit -m "feat: month cells count record-days"
```

---

### Task 8: The day agenda and the day modal

**Files:**
- Modify: `templates/index.html:7089-7114` (`calEventRow`), `:7188-7199` (`renderCalDayView`), `:7201-7209` (`openCalDay`), `:1521-1542` (`.cal-event` CSS)
- Test: `tests/test_boot.js`

**Interfaces:**
- Consumes: `VinylTimeline.recordDays` (Task 2), `calActBtn` (Task 6).
- Produces: `calRecordDayRow(g) -> string`, replacing `calEventRow(ev, fullNote)`. Both `renderCalDayView` and `openCalDay` call it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_boot.js`:

```js
test('the day agenda draws one row per record, not per event', async () => {
  const { win, doc, read } = await boot();
  busySunday(read);
  win.switchTab('timeline');
  win.setCalScale('day');
  win.calJumpToDate('2026-08-09');
  win.setCalScale('day');
  assert.strictEqual(doc.querySelectorAll('#calBody .cal-event').length, 1);
  assert.strictEqual(doc.querySelectorAll('#calBody .cal-event .cal-act').length, 4);
});

test('a day row still shows the notes written that day', async () => {
  const { win, doc, read } = await boot();
  busySunday(read);
  win.switchTab('timeline');
  win.setCalScale('day');
  win.calJumpToDate('2026-08-09');
  win.setCalScale('day');
  assert.match($(doc, '#calBody .cal-ev-note').textContent, /seam split/);
});

test('the day modal opens from a month cell and rails the same way', async () => {
  const { win, doc, read } = await boot();
  busySunday(read);
  win.switchTab('timeline');
  win.openCalDay('2026-08-09');
  assert.strictEqual(doc.querySelectorAll('#calDayBody .cal-event').length, 1);
  assert.strictEqual(doc.querySelectorAll('#calDayBody .cal-act').length, 4);
});

test('an icon in the day modal opens the record on that event', async () => {
  const { win, doc, read } = await boot();
  busySunday(read);
  win.switchTab('timeline');
  win.openCalDay('2026-08-09');
  const note = [...doc.querySelectorAll('#calDayBody .cal-act')]
    .find(b => b.dataset.type === 'note');
  press(win, note);
  assert.strictEqual(read('detailFocus'), 'note:2026-08-09:0');
  assert.strictEqual($(doc, '#calDayOverlay').classList.contains('hidden'), true,
    'the modal should step aside when the drawer opens');
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_boot.py -v`
Expected: FAIL — five `.cal-event` rows, no `.cal-act`.

- [ ] **Step 3: Draw one row per record-day**

Replace `calEventRow` (`templates/index.html:7089`) with:

```js
// one record's day — shared by the day view and the day modal
//
// This was one row per event, so a record bought, cleaned, played twice and
// noted on one day filled the agenda with its own cover five times. The row is
// now the record; the rail is what happened to it.
function calRecordDayRow(g) {
  const r = g.r;
  const cover = r.cover_url
    ? `<div class="cal-ev-cover-wrap"><img src="${r.cover_url}" alt="" loading="lazy" onerror="this.parentElement.innerHTML='<i class=&quot;ti ti-disc&quot;></i>'"></div>`
    : `<div class="cal-ev-cover-wrap"><i class="ti ti-disc"></i></div>`;
  // Every note written that day, each still reachable by its own key.
  const notes = g.acts.filter(a => a.type === 'note')
    .flatMap(a => a.evs)
    .map(ev => `<div class="cal-ev-note detail-notes-body" data-ev="${esc(ev.key)}">${
      typeof marked !== 'undefined' ? marked.parse(ev.text)
                                    : esc(ev.text).replace(/\n/g, '<br>')}</div>`)
    .join('');
  const first = g.evs[0];
  return `<div class="cal-event">
    <button type="button" class="cal-ev-open" data-rec="${r.id}" data-focus="${esc(g.day)}">
      ${cover}
      <div class="cal-ev-main">
        <div class="cal-ev-title">${esc(r.album_name) || 'untitled'}</div>
        <div class="cal-ev-artist">${esc(artistDisplay(r))}</div>
      </div>
    </button>
    ${notes}
    ${first.time ? `<span class="cal-ev-time">${esc(first.time)}</span>` : ''}
    <span class="cal-rail">${g.acts.map(a => calActBtn(g, a, 'cal-act')).join('')}</span>
  </div>`;
}
```

In `renderCalDayView` (`:7194`), replace the events line:

```js
      ${evs.length ? VinylTimeline.recordDays(evs).map(calRecordDayRow).join('') : '<div class="cal-day-empty">nothing on this day</div>'}
```

In `openCalDay` (`:7203`), the same:

```js
  document.getElementById('calDayBody').innerHTML = evs.length
    ? VinylTimeline.recordDays(evs).map(calRecordDayRow).join('')
    : '<div class="cal-day-empty">nothing on this day</div>';
```

Update the `.cal-event` CSS (`:1521`). The row no longer wears one type's colour on its left border, because it is no longer one type:

```css
.cal-event{display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap;padding:11px 0 11px 10px;
  border-bottom:1px solid var(--border);border-left:3px solid var(--border)}
.cal-ev-open{display:flex;gap:12px;align-items:flex-start;flex:1;min-width:0;
  padding:0;border:0;background:none;cursor:pointer;text-align:left;font-family:var(--font)}
.cal-ev-open:hover .cal-ev-title{color:var(--accent)}
.cal-event .cal-ev-note{flex-basis:100%}
```

Delete the four `.cal-event.bought/.cleaned/.played/.note` rules (`:1525-1528`) — nothing sets those classes any more.

Delete the five `.cal-badge` rules (`:1538-1542`) as well. `calEventRow` was their only caller (`:7111`), and this task replaces it, so they are dead the moment the row above lands. Confirm with `grep -n 'cal-badge' templates/index.html` and expect no hits outside the rules themselves before removing them.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_boot.py -v`
Expected: PASS.

- [ ] **Step 5: Run the whole suite**

Run: `pytest -q`
Expected: PASS. Every zoom now draws record-days, and `tests/test_timeline.js` covers the model underneath them.

- [ ] **Step 6: Commit**

```bash
git add templates/index.html tests/test_boot.js
git commit -m "feat: one row per record per day in the agenda and the day modal"
```

---

## Manual verification

The suite proves the DOM comes out right; it cannot prove anything looks right, because jsdom has no layout and no paint. Follow `docs/history-tab-manual-verification.md` in shape and check, in a browser:

1. A week with a record bought, cleaned, played twice and noted on one day draws **one** cover with four icons beneath it, the third carrying a `2`.
2. At 390px the same column is legible, the icons read as a legend, and tapping the cover opens the day list.
3. Clicking the note icon opens the record with the note and its date tinted purple, already scrolled into view, letting go after five seconds.
4. Clicking the cover tints all five entries and the date in gold.
5. Both themes: the four colours hold on `#0c0c0c` and on `#e1ddd3`, and bought is gold in both rather than olive in light.
6. The Insights activity strip has changed colour to match the Timeline — this is the intended consequence of one palette instead of two.
