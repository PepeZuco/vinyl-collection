# History Tab Activity Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second chart-box under the History tab's race chart that replays how the collection is *used* — bought, played, cleaned and noted — as a weekly rhythm band over zoomable per-record lanes, all on one playhead.

**Architecture:** All logic that needs no DOM lives in a new pure module `static/activity.js` (`buildActivity`, `dayAt`), tested with `node:test`, exactly like the existing `static/history.js`. Presentation lives in `templates/index.html`. Every event is reduced to an integer day index in the module, so the renderer never parses a date; lane marks are positioned as percentages inside a track element, so zoom is one width change and pan is one custom property on a shared ancestor.

**Tech Stack:** Vanilla ES5-flavoured browser JS (no build step), CSS custom properties and transitions, `node:test` for unit tests wrapped by pytest, Flask/Jinja for the single template.

**Spec:** `docs/superpowers/specs/2026-08-25-history-activity-chart-design.md`

## Global Constraints

- **No build step.** Plain `<script src>` tags, no bundler, no ES modules in the browser. `static/activity.js` uses the same IIFE-with-`module.exports`-tail wrapper as `grouping.js`, `history.js` and `spend.js`.
- **No new dependency, no Python change, no schema change.** Covers are already resident from `loadRecords()`.
- **JS tests run under pytest.** Every `tests/test_*.js` gets a `tests/test_*.py` wrapper shelling out to `node --test`, skipped when node is absent. `pytest` stays the single command.
- **`TZ` is pinned** to `America/Sao_Paulo` at the top of every JS test file, before any `Date` is constructed.
- **Every colour resolves from a CSS variable.** No literal hex in the chart's CSS rules outside the two `[data-theme]` token blocks.
- **Event colours, exact values.** Dark: `--ev-bought:#ac9008; --ev-cleaned:#0b9d9d; --ev-played:#2171cc; --ev-note:#a5397e`. Light: `--ev-bought:#b39609; --ev-cleaned:#07a4a4; --ev-played:#2171cc; --ev-note:#a5397e`. These are validated; do not adjust them.
- **Constants, exact values.** `ACT_ANCHOR = 0.62`, `ACT_QUIET = 60`, `ACT_MAX_RATE = 150`, `ACT_MIN_RATE = 25`, week length `7`.
- **Naming.** Everything new in `index.html` is prefixed `act` / `.act-` / `#act…`, so nothing collides with the race chart's `race` prefix. Never give an activity control a `race-` class that a `document.querySelectorAll` in the race controller reads (`.race-speed-btn` in particular).
- **The race chart is not modified.** Only additions to `index.html`, plus two CSS selectors widened to cover both charts.

## File Structure

| File | Responsibility |
|---|---|
| `static/activity.js` **(create)** | Pure model: records → day-indexed weeks, cumulative counts, per-record lanes, notes. Plus `dayAt(d0, i)`. |
| `tests/test_activity.js` **(create)** | `node:test` unit tests for the module. |
| `tests/test_activity.py` **(create)** | pytest wrapper shelling out to `node --test`. |
| `templates/index.html` **(modify)** | Event-colour tokens; activity chart CSS; the second `.chart-box`; `renderActivity()` and its playback controller; wiring in `renderHistory()` and `switchTab()`; the new `<script>` tag. |
| `docs/history-tab-manual-verification.md` **(modify)** | Manual checks for the animation, which is not unit-testable. |

---

### Task 1: The module's scope and day axis

**Files:**
- Create: `static/activity.js`
- Create: `tests/test_activity.js`
- Create: `tests/test_activity.py`

**Interfaces:**
- Consumes: `VinylGrouping.momentOf(stamp) -> {day, time, at}` from `static/grouping.js`. `day` is `'YYYY-MM-DD'` or `''` when the stamp is not a real moment.
- Produces: `VinylActivity.buildActivity(records)` returning `null` or an object with at least `{ d0: 'YYYY-MM-DD', span: Number }`, and `VinylActivity.dayAt(d0, i) -> 'YYYY-MM-DD'`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_activity.js`:

```js
// Tests for the pure model behind the History tab's activity chart.
// Run by tests/test_activity.py so `pytest` stays the single command.

// Pinned before anything constructs a Date: momentOf moves stamps onto the
// local clock, which says nothing without an offset to move them by. Sao Paulo
// is UTC-3 and the collection's own timezone.
process.env.TZ = 'America/Sao_Paulo';

const test = require('node:test');
const assert = require('node:assert');

const { buildActivity, dayAt } = require('../static/activity.js');

// A record only needs the fields the model reads, so each test builds the
// smallest one that exercises its rule.
let nextId = 1;
function rec(fields) {
  return Object.assign(
    { id: nextId++, artist: 'A', album_name: 'B', have_it: true, cover_data: '' },
    fields);
}
const plays = (...d) => JSON.stringify(d);

// ── scope ───────────────────────────────────────────────────────────────────

test('a collection with nothing in it has no model', () => {
  assert.strictEqual(buildActivity([]), null);
  assert.strictEqual(buildActivity(null), null);
});

test('wishlist records are excluded even when they carry events', () => {
  assert.strictEqual(buildActivity([
    rec({ have_it: false, bought_date: '2026-01-05', play_dates: plays('2026-02-01') }),
  ]), null);
});

test('owned records with no bought date are excluded', () => {
  assert.strictEqual(buildActivity([rec({ bought_date: '' })]), null);
});

test('an unparseable bought date drops the whole record', () => {
  assert.strictEqual(buildActivity([rec({ bought_date: '2026-02-30' })]), null);
});

// ── the day axis ────────────────────────────────────────────────────────────

test('day 0 is the first purchase when nothing predates it', () => {
  const a = buildActivity([
    rec({ bought_date: '2026-01-10' }),
    rec({ bought_date: '2026-01-02' }),
  ]);
  assert.strictEqual(a.d0, '2026-01-02');
  assert.strictEqual(a.span, 9);          // 02 Jan .. 10 Jan inclusive
});

test('day 0 is the earliest event of any kind, not the earliest purchase', () => {
  const a = buildActivity([
    rec({ bought_date: '2026-03-01', play_dates: plays('2026-02-20') }),
  ]);
  assert.strictEqual(a.d0, '2026-02-20');
  assert.strictEqual(a.span, 10);         // 20 Feb .. 01 Mar inclusive
});

test('the span reaches the last event day inclusive', () => {
  const a = buildActivity([
    rec({ bought_date: '2026-01-01', cleaned_dates: plays('2026-01-05') }),
  ]);
  assert.strictEqual(a.span, 5);
});

test('a one-day collection has a span of one and does not throw', () => {
  const a = buildActivity([rec({ bought_date: '2026-01-01' })]);
  assert.strictEqual(a.span, 1);
  assert.strictEqual(a.d0, '2026-01-01');
});

test('a stamp carrying a clock files under its calendar day', () => {
  const a = buildActivity([rec({ bought_date: '2026-01-01T23:30:00' })]);
  assert.strictEqual(a.d0, '2026-01-01');
});

// ── dayAt ───────────────────────────────────────────────────────────────────

test('dayAt walks forward from day zero', () => {
  assert.strictEqual(dayAt('2026-01-01', 0), '2026-01-01');
  assert.strictEqual(dayAt('2026-01-01', 31), '2026-02-01');
  assert.strictEqual(dayAt('2024-02-28', 1), '2024-02-29');   // a leap day
  assert.strictEqual(dayAt('2025-12-31', 1), '2026-01-01');   // a year boundary
});
```

Create `tests/test_activity.py`:

```python
"""Run the JavaScript activity-chart model tests under pytest.

The model rules are pure functions living in static/activity.js, so they are
testable — but only by a JS runtime. Shelling out to node's built-in test runner
keeps `pytest` as the one command that runs everything.
"""

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_activity_js():
    result = subprocess.run(
        ["node", "--test", "tests/test_activity.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test tests/test_activity.js`
Expected: FAIL — `Cannot find module '../static/activity.js'`

- [ ] **Step 3: Write the minimal implementation**

Create `static/activity.js`:

```js
'use strict';

/* How the collection is used, on a calendar clock.
 *
 * The race chart in history.js replays how the collection GREW — one frame per
 * purchase day, genres racing. This is the other half: what happened to each
 * record after it was shelved. Bought, played, cleaned and noted, all indexed
 * by day so the History tab can sweep one playhead across them.
 *
 * Days here are integers counted from d0, never stamps. Everything downstream —
 * column heights, mark positions, the zoom window — is arithmetic on those
 * integers, and the renderer never parses a date.
 *
 * Pure functions of the record list, kept out of index.html so they can be
 * tested directly (tests/test_activity.js).
 *
 * Loaded as a plain script in the browser AFTER grouping.js, whose momentOf
 * this depends on; required as a module by the tests. */

const VinylActivity = (function (grouping) {

  /* Same scope rule as the race chart: owned and dated. Every have_it record
   * in the collection carries a bought_date and every undated one is a
   * wishlist item, so this loses nothing owned. */
  function inScope(r) {
    return !!r.have_it && !!grouping.momentOf(r.bought_date).day;
  }

  /* 'YYYY-MM-DD' -> days since the epoch, and back.
   *
   * Built from the calendar parts through Date.UTC rather than Date.parse, so
   * it is timezone-proof: two stamps on the same local day must land on the
   * same integer no matter where the browser is, and momentOf has already done
   * the work of deciding which local day a stamp belongs to. */
  function dayNumber(iso) {
    const p = String(iso).split('-');
    return Math.round(Date.UTC(+p[0], +p[1] - 1, +p[2]) / 86400000);
  }

  function dayString(n) {
    return new Date(n * 86400000).toISOString().slice(0, 10);
  }

  /* The renderer's only date arithmetic: which calendar day is index i. */
  function dayAt(d0, i) {
    return dayString(dayNumber(d0) + Math.floor(i));
  }

  /* A stamp the calendar could not hold comes back empty from momentOf and is
   * dropped rather than bucketed — one bad row must not take the tab down. */
  function dayOf(stamp) {
    const day = grouping.momentOf(stamp).day;
    return day ? dayNumber(day) : null;
  }

  function buildActivity(records) {
    const scoped = (records || []).filter(inScope);
    if (!scoped.length) return null;

    /* Pass one sizes the axis before anything is indexed against it. d0 is the
     * earliest event of ANY kind, not the earliest purchase: a play dated
     * before its record was bought is odd, but it is what was recorded, and an
     * axis starting at the first purchase would push it off the left edge. */
    let lo = Infinity, hi = -Infinity;
    for (const r of scoped) {
      const bought = dayOf(r.bought_date);
      if (bought < lo) lo = bought;
      if (bought > hi) hi = bought;
    }

    return { d0: dayString(lo), span: hi - lo + 1 };
  }

  return { buildActivity: buildActivity, dayAt: dayAt };
})(typeof module !== 'undefined' && module.exports
     ? require('./grouping.js') : VinylGrouping);

if (typeof module !== 'undefined' && module.exports) module.exports = VinylActivity;
```

- [ ] **Step 4: Run the tests**

Run: `node --test tests/test_activity.js`
Expected: the scope, one-day, clock and `dayAt` tests PASS. The two tests that read play/cleaned dates still FAIL — `day 0 is the earliest event of any kind` and `the span reaches the last event day inclusive` — because pass one only walks bought dates.

- [ ] **Step 5: Extend the axis pass to every event type**

Replace the `buildActivity` body's pass-one block with the version that reads all four columns. Add these helpers above `buildActivity`:

```js
  function isDay(n) { return n !== null && n !== undefined && !isNaN(n); }
  function asc(a, b) { return a - b; }

  /* play_dates and cleaned_dates are JSON arrays of stamps. index.html has its
   * own parsePlayDates, but it lives in the template and cannot be reached
   * from here — so this parses the column itself rather than making the module
   * depend on the page. */
  function parseList(raw) {
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) { return []; }
  }

  /* Notes are [{date, text}], except on legacy rows where the column is a bare
   * string — the same migration parseNotes() does in the template. A note with
   * no text is not an event, matching dmHistoryEvents(). */
  function parseNoteList(raw, fallbackDate) {
    if (!raw) return [];
    let parsed = null;
    try { parsed = JSON.parse(raw); } catch (e) { parsed = null; }
    if (!Array.isArray(parsed)) parsed = [{ date: fallbackDate, text: String(raw) }];
    return parsed.filter(function (n) {
      return n && typeof n.text === 'string' && n.text.trim();
    });
  }

  /* Every event a record carries, as absolute day numbers. */
  function eventsOf(r) {
    return {
      r: r,
      bought: dayOf(r.bought_date),
      plays:  parseList(r.play_dates).map(dayOf).filter(isDay).sort(asc),
      cleans: parseList(r.cleaned_dates).map(dayOf).filter(isDay).sort(asc),
      notes:  parseNoteList(r.notes, r.bought_date)
                .map(function (n) { return { day: dayOf(n.date), text: n.text }; })
                .filter(function (n) { return isDay(n.day); })
                .sort(function (a, b) { return a.day - b.day; }),
    };
  }
```

and rewrite `buildActivity` as:

```js
  function buildActivity(records) {
    const scoped = (records || []).filter(inScope);
    if (!scoped.length) return null;

    const raw = scoped.map(eventsOf);

    let lo = Infinity, hi = -Infinity;
    for (const e of raw) {
      const days = [e.bought].concat(e.plays, e.cleans,
                                     e.notes.map(function (n) { return n.day; }));
      for (const d of days) { if (d < lo) lo = d; if (d > hi) hi = d; }
    }

    return { d0: dayString(lo), span: hi - lo + 1 };
  }
```

- [ ] **Step 6: Run the tests**

Run: `node --test tests/test_activity.js`
Expected: PASS, 10/10.

- [ ] **Step 7: Run the whole suite**

Run: `.venv/bin/python -m pytest -q` (or `python -m pytest -q`)
Expected: PASS, with `tests/test_activity.py::test_activity_js` among them.

- [ ] **Step 8: Commit**

```bash
git add static/activity.js tests/test_activity.js tests/test_activity.py
git commit -m "Reduce a collection's events to a day-indexed axis"
```

---

### Task 2: Lanes, notes and the played-on index

**Files:**
- Modify: `static/activity.js`
- Modify: `tests/test_activity.js`

**Interfaces:**
- Consumes: `eventsOf`, `isDay`, `dayString`, `dayOf` from Task 1.
- Produces: `buildActivity(records)` additionally returns
  `lanes: [{ id, artist, album, cover, bought, plays: [Number], cleans: [Number], notes: [Number], lastPlay: Number }]`,
  `playedOn: [[id, ...]]` indexed by day, and
  `notes: [{ day, text, id, artist, album }]` ascending.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_activity.js`:

```js
// ── lanes ───────────────────────────────────────────────────────────────────

test('a lane carries its events as day indices from d0', () => {
  const a = buildActivity([rec({
    id: 7, artist: 'Tim Maia', album_name: 'Racional',
    bought_date: '2026-01-01',
    play_dates: plays('2026-01-03', '2026-01-02'),
    cleaned_dates: plays('2026-01-05'),
    notes: JSON.stringify([{ date: '2026-01-04', text: 'first spin' }]),
  })]);
  assert.strictEqual(a.lanes.length, 1);
  const lane = a.lanes[0];
  assert.strictEqual(lane.id, 7);
  assert.strictEqual(lane.artist, 'Tim Maia');
  assert.strictEqual(lane.album, 'Racional');
  assert.strictEqual(lane.bought, 0);
  assert.deepStrictEqual(lane.plays, [1, 2]);      // sorted, not input order
  assert.deepStrictEqual(lane.cleans, [4]);
  assert.deepStrictEqual(lane.notes, [3]);
});

test('lastPlay is the final play, or the purchase when never played', () => {
  const a = buildActivity([
    rec({ id: 1, bought_date: '2026-01-01', play_dates: plays('2026-01-04') }),
    rec({ id: 2, bought_date: '2026-01-01' }),
  ]);
  const by = Object.fromEntries(a.lanes.map(l => [l.id, l]));
  assert.strictEqual(by[1].lastPlay, 3);
  assert.strictEqual(by[2].lastPlay, 0);
});

test('an unparseable play date drops only that play, not the record', () => {
  const a = buildActivity([rec({
    bought_date: '2026-01-01',
    play_dates: plays('2026-02-30', '2026-01-03'),
  })]);
  assert.deepStrictEqual(a.lanes[0].plays, [2]);
});

test('a play dated before the purchase is kept where it was recorded', () => {
  const a = buildActivity([rec({
    bought_date: '2026-01-10', play_dates: plays('2026-01-05'),
  })]);
  assert.strictEqual(a.d0, '2026-01-05');
  assert.strictEqual(a.lanes[0].bought, 5);
  assert.deepStrictEqual(a.lanes[0].plays, [0]);
});

test('a malformed events column is empty, not fatal', () => {
  const a = buildActivity([rec({
    bought_date: '2026-01-01', play_dates: 'not json', cleaned_dates: '{}',
  })]);
  assert.deepStrictEqual(a.lanes[0].plays, []);
  assert.deepStrictEqual(a.lanes[0].cleans, []);
});

test('lanes are ordered by play count desc, ties by purchase then id', () => {
  const a = buildActivity([
    rec({ id: 1, bought_date: '2026-01-02', play_dates: plays('2026-01-03') }),
    rec({ id: 2, bought_date: '2026-01-01',
          play_dates: plays('2026-01-03', '2026-01-04') }),
    rec({ id: 3, bought_date: '2026-01-01', play_dates: plays('2026-01-05') }),
  ]);
  assert.deepStrictEqual(a.lanes.map(l => l.id), [2, 3, 1]);
});

// ── notes ───────────────────────────────────────────────────────────────────

test('a note with no text is not an event', () => {
  const a = buildActivity([rec({
    bought_date: '2026-01-01',
    notes: JSON.stringify([{ date: '2026-01-02', text: '   ' },
                           { date: '2026-01-03', text: 'real' }]),
  })]);
  assert.deepStrictEqual(a.lanes[0].notes, [2]);
  assert.strictEqual(a.notes.length, 1);
  assert.strictEqual(a.notes[0].text, 'real');
});

test('a legacy string notes column migrates onto the bought date', () => {
  const a = buildActivity([rec({
    bought_date: '2026-01-01', notes: 'bought at the fair',
  })]);
  assert.deepStrictEqual(a.lanes[0].notes, [0]);
  assert.strictEqual(a.notes[0].text, 'bought at the fair');
});

test('notes come back ascending and name their record', () => {
  const a = buildActivity([
    rec({ id: 4, artist: 'X', album_name: 'Y', bought_date: '2026-01-01',
          notes: JSON.stringify([{ date: '2026-01-09', text: 'later' }]) }),
    rec({ id: 5, bought_date: '2026-01-01',
          notes: JSON.stringify([{ date: '2026-01-03', text: 'earlier' }]) }),
  ]);
  assert.deepStrictEqual(a.notes.map(n => n.text), ['earlier', 'later']);
  assert.deepStrictEqual(a.notes[1], { day: 8, text: 'later', id: 4,
                                       artist: 'X', album: 'Y' });
});

// ── playedOn ────────────────────────────────────────────────────────────────

test('playedOn indexes every play by day and holds nothing else', () => {
  const a = buildActivity([
    rec({ id: 1, bought_date: '2026-01-01', play_dates: plays('2026-01-03') }),
    rec({ id: 2, bought_date: '2026-01-01', play_dates: plays('2026-01-03') }),
  ]);
  assert.deepStrictEqual(a.playedOn[2], [1, 2]);
  assert.strictEqual(a.playedOn[0], undefined);
  assert.strictEqual(a.playedOn[1], undefined);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test tests/test_activity.js`
Expected: the ten new tests FAIL — `Cannot read properties of undefined (reading 'length')` on `a.lanes`.

- [ ] **Step 3: Build the lanes**

In `static/activity.js`, replace the `return { d0: ..., span: ... };` at the end of `buildActivity` with:

```js
    const span = hi - lo + 1;
    const playedOn = [];
    const noteList = [];

    const lanes = raw.map(function (e) {
      const shift = function (d) { return d - lo; };
      const bought = shift(e.bought);
      const plays  = e.plays.map(shift);
      const cleans = e.cleans.map(shift);

      plays.forEach(function (d) {
        if (!playedOn[d]) playedOn[d] = [];
        playedOn[d].push(e.r.id);
      });

      const noteDays = e.notes.map(function (n) {
        const day = shift(n.day);
        noteList.push({ day: day, text: n.text, id: e.r.id,
                        artist: e.r.artist || '', album: e.r.album_name || '' });
        return day;
      });

      return {
        id: e.r.id,
        artist: e.r.artist || '',
        album: e.r.album_name || '',
        cover: e.r.cover_data || '',
        bought: bought,
        plays: plays,
        cleans: cleans,
        notes: noteDays,
        /* Falling back to the purchase day rather than -1 means the quiet fade
         * measures silence from the day the record arrived, so one that was
         * never played goes quiet on schedule instead of never. */
        lastPlay: plays.length ? plays[plays.length - 1] : bought,
      };
    });

    noteList.sort(function (a, b) { return a.day - b.day; });

    /* Play count desc, ties by purchase order then id. A defined order means
     * "top N" is meaningful before the user has touched the sort control, and
     * makes the ordering assertable in tests. */
    lanes.sort(function (a, b) {
      if (a.plays.length !== b.plays.length) return b.plays.length - a.plays.length;
      if (a.bought !== b.bought) return a.bought - b.bought;
      return (Number(a.id) || 0) - (Number(b.id) || 0);
    });

    return { d0: dayString(lo), span: span, lanes: lanes,
             playedOn: playedOn, notes: noteList };
  }
```

- [ ] **Step 4: Run the tests**

Run: `node --test tests/test_activity.js`
Expected: PASS, 20/20.

- [ ] **Step 5: Commit**

```bash
git add static/activity.js tests/test_activity.js
git commit -m "Give every record a lane of day-indexed events"
```

---

### Task 3: Weekly buckets, cumulative counts and totals

**Files:**
- Modify: `static/activity.js`
- Modify: `tests/test_activity.js`
- Modify: `templates/index.html` (one line: the `<script>` tag)

**Interfaces:**
- Consumes: everything from Tasks 1–2.
- Produces: `buildActivity` additionally returns
  `weeks: [{ b, p, c, n, total }]` (`weeks.length === Math.ceil(span / 7)`),
  `cum: { b: [], p: [], c: [], n: [] }` (each of length `span`, monotonic), and
  `totals: { b, p, c, n }`. The module is loaded in the browser as `VinylActivity`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_activity.js`:

```js
// ── weeks ───────────────────────────────────────────────────────────────────

test('a week holds seven days, day 6 in the first and day 7 in the second', () => {
  const a = buildActivity([rec({
    bought_date: '2026-01-01',
    play_dates: plays('2026-01-07', '2026-01-08'),   // day 6 and day 7
  })]);
  assert.strictEqual(a.weeks.length, 2);
  assert.strictEqual(a.weeks[0].p, 1);
  assert.strictEqual(a.weeks[1].p, 1);
});

test('a week total is the sum of its four series', () => {
  const a = buildActivity([rec({
    bought_date: '2026-01-01',
    play_dates: plays('2026-01-02'),
    cleaned_dates: plays('2026-01-03'),
    notes: JSON.stringify([{ date: '2026-01-04', text: 'n' }]),
  })]);
  assert.deepStrictEqual(a.weeks[0], { b: 1, p: 1, c: 1, n: 1, total: 4 });
});

// ── cumulative counts ───────────────────────────────────────────────────────

test('cum runs the length of the axis and never decreases', () => {
  const a = buildActivity([rec({
    bought_date: '2026-01-01', play_dates: plays('2026-01-03', '2026-01-05'),
  })]);
  assert.strictEqual(a.cum.p.length, a.span);
  assert.deepStrictEqual(a.cum.p, [0, 0, 1, 1, 2]);
  assert.deepStrictEqual(a.cum.b, [1, 1, 1, 1, 1]);
});

test('the last cumulative value equals the total for every series', () => {
  const a = buildActivity([
    rec({ bought_date: '2026-01-01', play_dates: plays('2026-01-02', '2026-01-03') }),
    rec({ bought_date: '2026-01-04', cleaned_dates: plays('2026-01-05') }),
  ]);
  ['b', 'p', 'c', 'n'].forEach(k => {
    assert.strictEqual(a.cum[k][a.span - 1], a.totals[k], 'series ' + k);
  });
  assert.deepStrictEqual(a.totals, { b: 2, p: 2, c: 1, n: 0 });
});

test('every play in the model is counted exactly once', () => {
  const a = buildActivity([rec({
    bought_date: '2026-01-01', play_dates: plays('2026-01-02', '2026-01-02'),
  })]);
  assert.strictEqual(a.totals.p, 2);
  assert.strictEqual(a.lanes[0].plays.length, 2);
  assert.deepStrictEqual(a.playedOn[1].length, 2);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test tests/test_activity.js`
Expected: the five new tests FAIL on `a.weeks` / `a.cum` / `a.totals` being undefined.

- [ ] **Step 3: Count into weeks and days**

In `static/activity.js`, add a `WEEK` constant just inside the IIFE, above `inScope`:

```js
  const WEEK = 7;
```

Inside `buildActivity`, declare the accumulators immediately after `const span = hi - lo + 1;`:

```js
    const weeks = [];
    for (let i = 0; i < Math.ceil(span / WEEK); i++) {
      weeks.push({ b: 0, p: 0, c: 0, n: 0, total: 0 });
    }
    const perDay = [];
    for (let i = 0; i < span; i++) perDay.push({ b: 0, p: 0, c: 0, n: 0 });

    function count(day, key) {
      perDay[day][key]++;
      weeks[(day / WEEK) | 0][key]++;
    }
```

Then add the `count` calls inside the `lanes = raw.map(...)` callback — `count(bought, 'b');` right after `bought` is computed, `count(d, 'p')` inside the existing `plays.forEach`, a new `cleans.forEach(function (d) { count(d, 'c'); });`, and `count(day, 'n')` inside the `e.notes.map` callback.

Finally, before the `noteList.sort(...)` line:

```js
    const cum = { b: [], p: [], c: [], n: [] };
    const totals = { b: 0, p: 0, c: 0, n: 0 };
    ['b', 'p', 'c', 'n'].forEach(function (k) {
      let running = 0;
      for (let i = 0; i < span; i++) { running += perDay[i][k]; cum[k][i] = running; }
      totals[k] = running;
    });
    weeks.forEach(function (w) { w.total = w.b + w.p + w.c + w.n; });
```

and widen the return:

```js
    return { d0: dayString(lo), span: span, weeks: weeks, cum: cum,
             lanes: lanes, playedOn: playedOn, notes: noteList, totals: totals };
```

- [ ] **Step 4: Run the tests**

Run: `node --test tests/test_activity.js`
Expected: PASS, 25/25.

- [ ] **Step 5: Load the module in the browser**

In `templates/index.html`, after the `history.js` tag on line 1820:

```html
<script src="/static/activity.js"></script>
```

It must come after `grouping.js`, whose `VinylGrouping` it closes over.

- [ ] **Step 6: Verify the module loads**

Run: `.venv/bin/python app.py`, open the app, and in the browser console:

```js
VinylActivity.buildActivity(records).totals
```

Expected: `{b: 112, p: 399, c: 60, n: 38}` against the live collection. (38, not 28: ten owned records carry a legacy plain-string `notes` column that the module migrates the same way the template's `parseNotes()` does.)

- [ ] **Step 7: Run the whole suite and commit**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

```bash
git add static/activity.js tests/test_activity.js templates/index.html
git commit -m "Bucket the collection's events by week and by day"
```

---

### Task 4: Tokens, styles and markup

**Files:**
- Modify: `templates/index.html` — theme blocks (lines 20–33), stylesheet (after the race chart block ending ~line 725), `#historyPage` (after the race `.chart-box` closes, ~line 1356)

**Interfaces:**
- Consumes: nothing — this task adds no JS.
- Produces: the DOM ids `renderActivity()` will drive: `actBox actEmpty actBody actBandWrap actBand actWinRect actSolo actPin actBandAxis actNote actLanes actScroll actTail actTailName actTailTrack actTailCt actHead actLaneAxis actLaneAxisTrack actDay actCaption actPlayBtn actScrub actReplayBtn`, the totals `actTotB actTotP actTotC actTotN`, and the control attributes `data-act-zoom data-act-show data-act-sort data-act-speed`.

- [ ] **Step 1: Add the event-colour tokens**

In the `[data-theme="dark"]` block, after the `--sh-gray` line:

```css
  --ev-bought:#ac9008; --ev-cleaned:#0b9d9d; --ev-played:#2171cc; --ev-note:#a5397e;
```

and in `[data-theme="light"]`, in the same position:

```css
  --ev-bought:#b39609; --ev-cleaned:#07a4a4; --ev-played:#2171cc; --ev-note:#a5397e;
```

- [ ] **Step 2: Widen the two shared control selectors**

The activity chart reuses `.race-controls`, `.race-btn` and `.race-speeds` as-is, but two rules are keyed to the race chart's own ids and classes. Change:

```css
#raceScrub{flex:1;min-width:0;accent-color:var(--accent);cursor:pointer}
#raceScrub:disabled{opacity:.4;cursor:default}
```

to:

```css
#raceScrub,#actScrub{flex:1;min-width:0;accent-color:var(--accent);cursor:pointer}
#raceScrub:disabled,#actScrub:disabled{opacity:.4;cursor:default}
```

and:

```css
.race-speed-btn{height:26px;padding:0 8px;border:1px solid var(--border);
```

to:

```css
.race-speed-btn,.act-speed-btn{height:26px;padding:0 8px;border:1px solid var(--border);
```

Apply the same widening to the `.race-speed-btn` colour and `.active` rules that follow it. Do **not** give the activity buttons the `race-speed-btn` class — `raceSyncControls()` selects on it and would fight them.

- [ ] **Step 3: Add the activity chart stylesheet**

Immediately after the race chart's CSS block (before the `stats/history segment` comment):

```css
/* activity chart — the same days at two scales: a weekly band over per-record
   lanes. Pan and reveal are two custom properties on .act-lanes, so playback
   costs two style writes however many lanes are on screen. */
.act-empty{color:var(--muted);font-size:13px;padding:20px 2px}
.act-legend{display:flex;gap:13px;flex-wrap:wrap}
.act-lg{display:inline-flex;align-items:center;gap:5px;font-size:11px;
  color:var(--label);text-transform:none;letter-spacing:0;font-weight:400}
.act-lg i{font-size:12px;flex-shrink:0}
.act-lg b{font-family:var(--font-mono);font-weight:700;color:var(--text);
  min-width:2.4ch;text-align:right;font-variant-numeric:tabular-nums}

/* the band doubles as the scrubber, hence the grab cursor and touch-action */
.act-band-wrap{position:relative;cursor:ew-resize;touch-action:none;user-select:none}
.act-band{position:relative;height:78px;display:flex;align-items:flex-end;gap:1px;
  border-bottom:1px solid var(--border);transition:opacity .18s}
.act-band-wrap.dim .act-band{opacity:.22}
.act-wk{flex:1;min-width:0;display:flex;flex-direction:column-reverse;height:100%}
.act-seg{width:100%;flex-shrink:0;transition:height 90ms linear}
.act-seg.b{background:var(--ev-bought)} .act-seg.p{background:var(--ev-played)}
.act-seg.c{background:var(--ev-cleaned)} .act-seg.n{background:var(--ev-note)}
.act-wk .act-seg + .act-seg{box-shadow:0 2px 0 0 var(--surface)}
.act-win{position:absolute;top:-2px;bottom:0;pointer-events:none;opacity:0;
  transition:opacity .2s;border-left:1px solid var(--accent);
  border-right:1px solid var(--accent);
  background:color-mix(in srgb, var(--accent) 9%, transparent)}
.act-win.on{opacity:1}
.act-solo{position:absolute;inset:0;pointer-events:none;opacity:0;transition:opacity .18s}
.act-solo.on{opacity:1}
.act-solo .sm{position:absolute;bottom:0;width:2px;height:100%;margin-left:-1px}
.act-pin{position:absolute;top:-2px;bottom:0;width:1px;background:var(--accent);
  pointer-events:none;z-index:3}

.act-axis{position:relative;height:19px;margin-top:2px}
#actLaneAxis{overflow:hidden}
#actLaneAxis.wide .act-tick:not(.q3){display:none}
/* the band never zooms — it always shows the whole arc — so it is permanently
   at the density the lane rule only reaches when wide, and thins to match */
#actBandAxis .act-tick:not(.q3){display:none}
.act-tick{position:absolute;top:0;font-family:var(--font-mono);font-size:9.5px;
  color:var(--muted);transform:translateX(-50%);white-space:nowrap;letter-spacing:.04em}
.act-tick.yr{color:var(--label);font-weight:700}

.act-note{margin-top:10px;background:var(--card);border:1px solid var(--border);
  border-left:2px solid var(--ev-note);padding:7px 10px;font-size:12px;
  line-height:1.45;color:var(--text);opacity:0;transition:opacity .3s;min-height:44px}
.act-note.on{opacity:1}
.act-note .who{font-family:var(--font-mono);font-size:9.5px;letter-spacing:.09em;
  text-transform:uppercase;color:var(--ev-note);display:block;margin-bottom:3px}
.act-note .txt{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

.act-strip{display:flex;align-items:center;gap:14px;flex-wrap:wrap;
  margin:13px 0 9px;padding-top:11px;border-top:1px solid var(--border)}
.act-grp{display:flex;align-items:center;gap:5px}
.act-grp > span{font-family:var(--font-mono);font-size:9.5px;font-weight:700;
  letter-spacing:.11em;text-transform:uppercase;color:var(--muted);margin-right:2px}
.act-pill{height:24px;padding:0 9px;border:1px solid var(--border);
  background:transparent;color:var(--label);font-size:11px;
  font-family:var(--font-mono);cursor:pointer;line-height:1}
.act-pill.active{border-color:var(--accent);color:var(--accent)}

/* pan lives on the body, an ancestor of BOTH the lanes and the month rule that
   sits below them, so the two move together; the reveal lives on the lanes
   alone, so the rule is panned but never clipped */
.act-body{--act-pan:0px}
.act-lanes{position:relative;--act-rev:100%}
.act-scroll{position:relative}
.act-scroll.scroll{max-height:430px;overflow-y:auto;overflow-x:hidden;
  scrollbar-width:thin;scrollbar-color:var(--border) transparent}
.act-row{display:grid;grid-template-columns:20px minmax(0,150px) minmax(0,1fr) 28px;
  gap:9px;align-items:center;height:18px;transition:opacity .45s;cursor:pointer}
.act-row.gone{opacity:.34}
.act-row:hover{background:var(--card-hover)}
.act-cover{width:18px;height:18px;object-fit:cover;background:var(--search-bg);
  filter:grayscale(1) opacity(.3);transition:filter .35s}
.act-cover.owned{filter:none}
.act-name{font-size:11px;line-height:1.15;overflow:hidden;white-space:nowrap;
  text-overflow:ellipsis;color:var(--label)}
.act-name b{color:var(--text);font-weight:600}
.act-lane{position:relative;height:18px;overflow:hidden}
/* the baseline sits outside the track, so an unrevealed lane still reads as a
   lane rather than as empty space */
.act-lane::before{content:'';position:absolute;left:0;right:0;top:8px;height:1px;
  background:var(--border)}
.act-track{position:absolute;top:0;bottom:0;left:0;width:100%;
  transform:translateX(var(--act-pan));
  /* the fallback is what leaves the month rule unclipped: it never inherits
     --act-rev, because that is defined on .act-lanes, which is not its parent */
  clip-path:inset(0 var(--act-rev,0%) 0 0);will-change:transform}
.act-mk{position:absolute;top:4px;height:10px;width:2px;border-radius:1px;margin-left:-1px}
.act-mk.p{background:var(--ev-played)}
.act-mk.c{background:var(--ev-cleaned);top:2px;height:14px}
.act-mk.n{background:var(--ev-note);top:0;height:18px;width:3px}
.act-mk.b{background:var(--ev-bought);top:6px;height:6px;width:6px;
  border-radius:50%;margin-left:-3px}
.act-quiet{position:absolute;top:8px;height:1px;
  background:repeating-linear-gradient(90deg,var(--border) 0 3px,transparent 3px 6px)}
.act-ct{font-family:var(--font-mono);font-size:11px;font-weight:700;text-align:right;
  color:var(--label);font-variant-numeric:tabular-nums}
.act-tail{margin-top:8px;padding-top:8px;border-top:1px solid var(--border)}
.act-tail .act-row{height:24px;cursor:default}
.act-tail .act-row:hover{background:transparent}
.act-tail .act-lane{height:24px}
.act-tail .act-lane::before{top:11px}
.act-tail .act-mk{opacity:.4;top:6px;height:12px}
.act-tail .act-mk.b{top:9px;height:6px;width:6px}
.act-tail .act-name{font-style:italic}
.act-head{position:absolute;top:0;bottom:0;width:1px;background:var(--accent);
  opacity:.8;pointer-events:none;z-index:2}

.act-readout{display:flex;align-items:flex-end;justify-content:space-between;
  gap:14px;margin-top:11px;flex-wrap:wrap}
.act-day{font-family:var(--font-mono);font-size:26px;font-weight:700;
  font-variant-numeric:tabular-nums;letter-spacing:-.01em;line-height:1}
.act-caption{font-size:12px;color:var(--label);min-height:1.4em;text-align:right;
  flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

@media (max-width:640px){
  .act-band{height:62px}
  .act-row{grid-template-columns:16px minmax(0,88px) minmax(0,1fr) 24px;gap:7px}
  .act-cover{width:15px;height:15px}
  .act-day{font-size:19px}
  .act-strip{gap:10px}
}
@media (prefers-reduced-motion:reduce){
  .act-seg{transition:none}
  .act-row{transition:none}
  .act-cover{transition:none}
}
```

- [ ] **Step 4: Add the markup**

In `#historyPage`, immediately after the race chart's `.chart-box` closing `</div>` and before `</div>` closing the page:

```html
      <!-- how the collection is used — the same days at two scales -->
      <div class="chart-box" id="actBox">
        <div class="chart-title" style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap">
          <span>how the collection is used</span>
          <div class="act-legend">
            <span class="act-lg"><i class="ti ti-shopping-bag" style="color:var(--ev-bought)"></i>bought <b id="actTotB">0</b></span>
            <span class="act-lg"><i class="ti ti-headphones" style="color:var(--ev-played)"></i>played <b id="actTotP">0</b></span>
            <span class="act-lg"><i class="ti ti-droplet" style="color:var(--ev-cleaned)"></i>cleaned <b id="actTotC">0</b></span>
            <span class="act-lg"><i class="ti ti-note" style="color:var(--ev-note)"></i>noted <b id="actTotN">0</b></span>
          </div>
        </div>

        <p class="act-empty" id="actEmpty" hidden>nothing to replay yet — records need a bought date to appear here.</p>

        <div class="act-body" id="actBody">
          <div class="act-band-wrap" id="actBandWrap">
            <div class="act-band" id="actBand"></div>
            <div class="act-win" id="actWinRect"></div>
            <div class="act-solo" id="actSolo"></div>
            <div class="act-pin" id="actPin"></div>
          </div>
          <div class="act-axis" id="actBandAxis"></div>
          <div class="act-note" id="actNote"><span class="who"></span><span class="txt"></span></div>

          <div class="act-strip">
            <div class="act-grp"><span>zoom</span>
              <button class="act-pill active" data-act-zoom="0">all</button>
              <button class="act-pill" data-act-zoom="365">1 yr</button>
              <button class="act-pill" data-act-zoom="90">90 d</button>
              <button class="act-pill" data-act-zoom="30">30 d</button>
            </div>
            <div class="act-grp"><span>show</span>
              <button class="act-pill active" data-act-show="21">top 21</button>
              <button class="act-pill" data-act-show="50">top 50</button>
              <button class="act-pill" data-act-show="0">all</button>
            </div>
            <div class="act-grp"><span>order</span>
              <button class="act-pill active" data-act-sort="plays">most played</button>
              <button class="act-pill" data-act-sort="recent">in rotation</button>
              <button class="act-pill" data-act-sort="bought">bought</button>
            </div>
          </div>

          <div class="act-lanes" id="actLanes">
            <div class="act-scroll" id="actScroll"></div>
            <div class="act-tail" id="actTail" hidden>
              <div class="act-row">
                <span></span>
                <span class="act-name" id="actTailName"></span>
                <span class="act-lane"><span class="act-track" id="actTailTrack"></span></span>
                <span class="act-ct" id="actTailCt">0</span>
              </div>
            </div>
            <span class="act-head" id="actHead"></span>
          </div>
          <div class="act-axis" id="actLaneAxis"><span class="act-track" id="actLaneAxisTrack"></span></div>

          <div class="act-readout">
            <span class="act-day" id="actDay"></span>
            <span class="act-caption" id="actCaption"></span>
          </div>
          <div class="race-controls">
            <button class="race-btn" id="actPlayBtn" aria-label="play" aria-pressed="false"><i class="ti ti-player-play"></i></button>
            <input type="range" id="actScrub" min="0" max="0" step="1" value="0" aria-label="day">
            <div class="race-speeds">
              <button class="act-speed-btn" data-act-speed="0.5">0.5&times;</button>
              <button class="act-speed-btn active" data-act-speed="1">1&times;</button>
              <button class="act-speed-btn" data-act-speed="2">2&times;</button>
            </div>
            <button class="race-btn hidden" id="actReplayBtn" aria-label="replay"><i class="ti ti-refresh"></i></button>
          </div>
        </div>
      </div>
```

- [ ] **Step 5: Verify it renders**

Run: `.venv/bin/python app.py`, open the History tab.
Expected: the race chart unchanged; below it a second box titled "how the collection is used" with a legend reading `bought 0 / played 0 / cleaned 0 / noted 0`, an empty band area, the three control groups, an empty lane area, and a transport row. Check both themes with the theme toggle — no unstyled or invisible text.

- [ ] **Step 6: Commit**

```bash
git add templates/index.html
git commit -m "Give the activity chart its colours, its box and its controls"
```

---

### Task 5: Build the chart from the model

**Files:**
- Modify: `templates/index.html` — new JS after the race chart's `raceSetSpeed()`, plus edits to `renderHistory()` (~line 4369) and `switchTab()` (~line 4344)

**Interfaces:**
- Consumes: `VinylActivity.buildActivity(records)`, `VinylActivity.dayAt(d0, i)`, and the DOM ids from Task 4. `openDetail(id)` and the global `records` array already exist.
- Produces: module-level state `act actRows actLive actCols actPos actWin actWinStart actShow actSort actLaneW actLaneL`; functions `actLast() actPct(i) actClamp(v,a,b) renderActivity() actMeasure() actApplyZoom() actSetVisible(n) actPause()`.

- [ ] **Step 1: Add the state and geometry helpers**

After `raceSetSpeed()` in `templates/index.html`:

```js
// ── history: how the collection is used ────────────────────────────────────
const ACT_ANCHOR = 0.62;    // where the playhead rides while the window flies
const ACT_QUIET  = 60;      // days of silence before a lane dims. 60, not 120:
                            // at 120 the class never fires once on this
                            // collection — its most-played records are never
                            // untouched for four months.
const ACT_MAX_RATE = 150;   // days per second at 1x, full span — ~5.4s end to end
const ACT_MIN_RATE = 25;

let act = null;             // the built model, or null when nothing is in scope
let actCols = [];           // one entry per week column in the band
let actRows = [];           // one entry per lane, every record, in DOM order
let actLive = [];           // the subset currently displayed
let actPos = 0;             // playhead, in days, fractional
let actWin = 1;             // zoom window width in days
let actWinStart = 0;
let actShow = 21;
let actSort = 'plays';
let actLaneW = 0, actLaneL = 0;

/* The axis is [0, span-1]. A one-day collection would make that a zero-width
 * range and every percentage NaN, so the denominator floors at 1. */
function actLast() { return act ? Math.max(1, act.span - 1) : 1; }
function actPct(i) { return i / actLast() * 100; }
function actClamp(v, a, b) { return v < a ? a : v > b ? b : v; }

const ACT_SORTS = {
  plays:  function (a, b) { return b.plays.length - a.plays.length || a.bought - b.bought; },
  recent: function (a, b) { return b.lastPlay - a.lastPlay || a.bought - b.bought; },
  bought: function (a, b) { return a.bought - b.bought; },
};
```

- [ ] **Step 2: Build the band, the lanes and the month rule**

```js
/* Every mark is a percentage of the full span, so widening the track re-lays
 * them all out with no JS and marks keep their 2px width. */
function actMarksHTML(lane) {
  let h = '<span class="act-mk b" style="left:' + actPct(lane.bought) + '%"></span>';
  if (actLast() - lane.lastPlay > ACT_QUIET) {
    h += '<span class="act-quiet" style="left:' + actPct(lane.lastPlay) +
         '%;width:' + actPct(actLast() - lane.lastPlay) + '%"></span>';
  }
  lane.plays.forEach(function (d)  { h += '<span class="act-mk p" style="left:' + actPct(d) + '%"></span>'; });
  lane.cleans.forEach(function (d) { h += '<span class="act-mk c" style="left:' + actPct(d) + '%"></span>'; });
  lane.notes.forEach(function (d)  { h += '<span class="act-mk n" style="left:' + actPct(d) + '%"></span>'; });
  return h;
}

/* One label per month; every third gets .q3 so the lane rule can thin itself
 * out when the window is wide and the labels would collide. */
function actTicks(host, d0) {
  host.innerHTML = '';
  const first = new Date(d0 + 'T00:00:00');
  let d = new Date(first.getFullYear(), first.getMonth() + 1, 1), n = 0;
  const end = new Date(first.getFullYear(), first.getMonth(), first.getDate() + actLast());
  while (d <= end) {
    const off = Math.round((d - first) / 86400000);
    const t = document.createElement('span');
    t.className = 'act-tick' + (d.getMonth() === 0 ? ' yr' : '') + (n % 3 === 0 ? ' q3' : '');
    t.style.left = actPct(off) + '%';
    if (actPct(off) < 4) { t.style.transform = 'none'; t.style.left = '0'; }
    t.textContent = d.toLocaleDateString('en', { month: 'short' }) + ' ' +
                    String(d.getFullYear()).slice(2);
    host.appendChild(t);
    d = new Date(d.getFullYear(), d.getMonth() + 1, 1); n++;
  }
}

function actBuildBand() {
  const band = document.getElementById('actBand');
  band.innerHTML = '';
  const max = act.weeks.reduce(function (m, w) { return Math.max(m, w.total); }, 1);
  actCols = act.weeks.map(function (w) {
    const el = document.createElement('div');
    el.className = 'act-wk';
    /* column-reverse, so the first child sits on the baseline */
    ['p', 'c', 'n', 'b'].forEach(function (k) {
      const s = document.createElement('div');
      s.className = 'act-seg ' + k;
      s.dataset.h = (w[k] / max * 100).toFixed(3);
      s.style.height = '0%';
      el.appendChild(s);
    });
    band.appendChild(el);
    return { segs: Array.prototype.slice.call(el.children), rev: -1 };
  });
}

function actBuildLanes() {
  const scroll = document.getElementById('actScroll');
  scroll.innerHTML = '';
  actRows = act.lanes.map(function (lane) {
    const el = document.createElement('div');
    el.className = 'act-row';
    el.innerHTML =
      '<img class="act-cover" src="' + esc(lane.cover) + '" alt="" loading="lazy">' +
      '<span class="act-name"><b>' + esc(lane.artist) + '</b> · ' + esc(lane.album) + '</span>' +
      '<span class="act-lane"><span class="act-track">' + actMarksHTML(lane) + '</span></span>' +
      '<span class="act-ct">0</span>';
    scroll.appendChild(el);
    return { lane: lane, el: el, cover: el.children[0], track: el.children[2].firstChild,
             ct: el.children[3], owned: false, count: -1, gone: false };
  });
}
```

`esc()` already exists at `templates/index.html:3986` and is the right helper — it escapes `&<>"`, which covers both the text nodes and the `src` attribute the cover is written into.

- [ ] **Step 3: Size the tracks and pick what is visible**

```js
/* The lane column's width, measured from a real lane rather than assumed, so
 * the playhead and the month rule sit on the same scale the marks do. */
function actMeasure() {
  const lane = document.querySelector('#actLanes .act-lane');
  if (!lane) return;
  const a = lane.getBoundingClientRect();
  const b = document.getElementById('actLanes').getBoundingClientRect();
  actLaneW = a.width; actLaneL = a.left - b.left;
  const axis = document.getElementById('actLaneAxis');
  axis.style.marginLeft = actLaneL + 'px';
  axis.style.width = actLaneW + 'px';
}

/* Zoom is one width: the track holds the whole span, the lane shows actWin
 * days of it. */
function actApplyZoom() {
  const w = (100 * actLast() / actWin).toFixed(3) + '%';
  actRows.forEach(function (o) { o.track.style.width = w; });
  document.getElementById('actTailTrack').style.width = w;
  document.getElementById('actLaneAxisTrack').style.width = w;
  document.getElementById('actWinRect').classList.toggle('on', actWin < actLast());
  document.getElementById('actLaneAxis').classList.toggle('wide', actWin > 400);
}

let actTailPlays = [];

/* Whatever is not on screen is folded into the density band below, so nothing
 * is ever hidden — only compressed. */
function actSetVisible(n) {
  actShow = n > 0 ? Math.min(n, actRows.length) : actRows.length;
  actRows.forEach(function (o, i) {
    o.el.style.display = i < actShow ? '' : 'none';
  });
  actLive = actRows.slice(0, actShow);
  const rest = actRows.slice(actShow);
  const tail = document.getElementById('actTail');
  tail.hidden = !rest.length;
  if (rest.length) {
    document.getElementById('actTailTrack').innerHTML =
      rest.map(function (o) { return actMarksHTML(o.lane); }).join('');
    document.getElementById('actTailName').textContent =
      'the other ' + rest.length + ' records';
    actTailPlays = rest.reduce(function (all, o) { return all.concat(o.lane.plays); }, [])
                       .sort(function (a, b) { return a - b; });
  } else actTailPlays = [];
  document.getElementById('actScroll').classList.toggle('scroll', actShow > 30);
  actApplyZoom();
  actMeasure();
}
```

- [ ] **Step 4: Write `renderActivity()` and wire it up**

```js
function renderActivity() {
  act = VinylActivity.buildActivity(records);
  const empty = !act;
  document.getElementById('actEmpty').hidden = !empty;
  document.getElementById('actBody').hidden = empty;
  if (empty) { actPause(); return; }

  actPos = 0;
  actWin = actLast();
  actSort = 'plays';
  actBuildBand();
  actBuildLanes();
  actTicks(document.getElementById('actBandAxis'), act.d0);
  actTicks(document.getElementById('actLaneAxisTrack'), act.d0);
  const scrub = document.getElementById('actScrub');
  scrub.max = String(actLast());
  scrub.disabled = false;
  actSetVisible(21);
}

function actPause() { /* filled in by Task 6 */ }
```

In `renderHistory()`, call it as the **first** statement — before the race chart's early return for an empty timeline, so the activity chart always renders its own state:

```js
function renderHistory() {
  renderActivity();          // the second chart on this tab, its own clock
  raceFrames = VinylHistory.buildTimeline(records);
  ...
```

In `switchTab()`, extend the line that stops the race:

```js
  // Leaving the tab stops both charts — no timer runs behind the collection view.
  if (leaving === 'history' && tab !== 'history') { racePause(); actPause(); }
```

- [ ] **Step 5: Verify it draws**

Run: `.venv/bin/python app.py`, open the History tab.
Expected: the band shows 117 week columns at zero height; 21 lane rows with covers, names and dotted quiet tails; the folded band reads `the other 91 records`; the month rule runs `Jul 24` … `Aug 26`. The legend still reads 0 — nothing drives it yet.

In the console: `actRows.length` → `112`; `actLive.length` → `21`.

- [ ] **Step 6: Commit**

```bash
git add templates/index.html
git commit -m "Draw the activity chart's band, lanes and month rule"
```

---

### Task 6: The clock

**Files:**
- Modify: `templates/index.html`

**Interfaces:**
- Consumes: everything from Task 5.
- Produces: `actPaint() actSetTotals(day) actCaptionFor(day) actSeek(day) actPlay() actPause() actReplay() actSyncControls() actRate() actReducedMotion()`, and module state `actPlaying actRaf actLastT actSpeed`. Replaces the Task 5 stub `actPause()`.

- [ ] **Step 1: Write the frame painter**

```js
function actSetTotals(day) {
  const ids = { b: 'actTotB', p: 'actTotP', c: 'actTotC', n: 'actTotN' };
  ['b', 'p', 'c', 'n'].forEach(function (k) {
    const el = document.getElementById(ids[k]);
    const v = String(act.cum[k][day]);
    if (el.textContent !== v) el.textContent = v;
  });
}

function actCaptionFor(day) {
  let rec = null;
  for (let d = day; d >= 0 && d > day - 30; d--) {
    if (act.playedOn[d]) { rec = act.playedOn[d][0]; break; }
  }
  if (rec === null) return 'nothing played yet';
  const lane = actRows.find(function (o) { return o.lane.id === rec; });
  return lane ? '▸ ' + lane.lane.artist + ' — ' + lane.lane.album : '';
}

function actPaint() {
  if (!act) return;
  const day = Math.min(act.span - 1, Math.floor(actPos));

  /* The band grows as the head crosses each week. Only columns whose fill
   * actually moved are touched. */
  for (let i = 0; i < actCols.length; i++) {
    const rv = actClamp((actPos - i * 7) / 7, 0, 1);
    if (Math.abs(rv - actCols[i].rev) < 0.004) continue;
    actCols[i].rev = rv;
    const segs = actCols[i].segs;
    for (let j = 0; j < segs.length; j++) {
      segs[j].style.height = (segs[j].dataset.h * rv).toFixed(3) + '%';
    }
  }
  actSetTotals(day);
  document.getElementById('actPin').style.left = actPct(actPos) + '%';
  document.getElementById('actDay').textContent = VinylActivity.dayAt(act.d0, day);

  /* Pan and reveal are one write each on the shared ancestor, so this costs
   * the same whether 21 lanes are on screen or 112. */
  actWinStart = actWin >= actLast() ? 0
              : actClamp(actPos - actWin * ACT_ANCHOR, 0, actLast() - actWin);
  document.getElementById('actBody').style.setProperty(
    '--act-pan', (-(actLaneW * actWinStart / actWin)) + 'px');
  document.getElementById('actLanes').style.setProperty(
    '--act-rev', (100 - actPct(actPos)).toFixed(3) + '%');
  const win = document.getElementById('actWinRect');
  win.style.left = actPct(actWinStart) + '%';
  win.style.width = (actWin / actLast() * 100) + '%';
  document.getElementById('actHead').style.left =
    (actLaneL + actLaneW * (actPos - actWinStart) / actWin) + 'px';

  /* Per-row state is written only when it changes. */
  for (const o of actLive) {
    const own = actPos >= o.lane.bought;
    if (own !== o.owned) { o.owned = own; o.cover.classList.toggle('owned', own); }
    let n = 0, lp = o.lane.bought;
    const plays = o.lane.plays;
    for (let i = 0; i < plays.length && plays[i] <= day; i++) { n++; lp = plays[i]; }
    if (n !== o.count) { o.count = n; o.ct.textContent = n; }
    const gone = own && (actPos - lp) > ACT_QUIET;
    if (gone !== o.gone) { o.gone = gone; o.el.classList.toggle('gone', gone); }
  }
  let tn = 0;
  for (let i = 0; i < actTailPlays.length && actTailPlays[i] <= day; i++) tn++;
  const tct = document.getElementById('actTailCt');
  if (tct.textContent !== String(tn)) tct.textContent = tn;

  const cap = document.getElementById('actCaption');
  const text = actCaptionFor(day);
  if (cap.textContent !== text) cap.textContent = text;
}
```

- [ ] **Step 2: Write the transport**

```js
let actPlaying = false, actRaf = 0, actLastT = 0, actSpeed = 1;

function actReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/* Tied to zoom so the visible window always takes about two and a half seconds
 * to cross, whatever the magnification. */
function actRate() {
  return Math.min(ACT_MAX_RATE, Math.max(ACT_MIN_RATE, actWin / 2.5));
}

function actSeek(day) {
  actPos = actClamp(day, 0, actLast());
  const scrub = document.getElementById('actScrub');
  if (Number(scrub.value) !== Math.round(actPos)) scrub.value = Math.round(actPos);
  actPaint();
}

/* A continuous day clock, not the race chart's setTimeout frame chain: this
 * axis is continuous calendar time, and a frame-per-event-day clock would hop
 * unevenly and stutter the band. */
function actTick(t) {
  if (!actPlaying) return;
  if (!actLastT) actLastT = t;
  const dt = Math.min(0.12, (t - actLastT) / 1000);
  actLastT = t;
  actSeek(actPos + actRate() * actSpeed * dt);
  if (actPos >= actLast()) { actPause(); return; }
  actRaf = requestAnimationFrame(actTick);
}

function actPlay() {
  if (!act || actPlaying) return;
  if (actPos >= actLast()) actSeek(0);
  actPlaying = true;
  actLastT = 0;
  actSyncControls();
  actRaf = requestAnimationFrame(actTick);
}

function actPause() {
  actPlaying = false;
  cancelAnimationFrame(actRaf);
  actRaf = 0;
  actSyncControls();
}

function actReplay() { actSeek(0); actPlay(); }

function actSyncControls() {
  const btn = document.getElementById('actPlayBtn');
  btn.innerHTML = actPlaying ? '<i class="ti ti-player-pause"></i>'
                             : '<i class="ti ti-player-play"></i>';
  btn.setAttribute('aria-pressed', actPlaying ? 'true' : 'false');
  btn.setAttribute('aria-label', actPlaying ? 'pause' : 'play');
  const atEnd = !!act && actPos >= actLast();
  document.getElementById('actReplayBtn').classList.toggle('hidden', !atEnd || actPlaying);
  btn.classList.toggle('hidden', atEnd && !actPlaying);
  document.querySelectorAll('.act-speed-btn').forEach(function (b) {
    b.classList.toggle('active', Number(b.dataset.actSpeed) === actSpeed);
  });
}
```

Delete the Task 5 stub `function actPause() { }`.

- [ ] **Step 3: Bind the controls and start**

In the `DOMContentLoaded` block where the race chart's listeners are bound (near `document.getElementById('racePlayBtn').addEventListener`):

```js
  document.getElementById('actPlayBtn').addEventListener('click', function () {
    actPlaying ? actPause() : actPlay();
  });
  document.getElementById('actReplayBtn').addEventListener('click', actReplay);
  document.getElementById('actScrub').addEventListener('input', function () {
    /* Seek FIRST. actPause() syncs the transport from actPos, so pausing
       before the seek would sync the position being left rather than the one
       being landed on — visibly wrong the moment a drag crosses the end, and
       wrong in the other direction on the drag back. actSeek() deliberately
       does not sync on its own: actTick calls it every frame, and
       actSyncControls' querySelectorAll would be per-frame DOM work. */
    actSeek(Number(this.value));
    actPause();
  });
  document.querySelectorAll('.act-speed-btn').forEach(function (b) {
    b.addEventListener('click', function () {
      actSpeed = Number(b.dataset.actSpeed);
      actSyncControls();
    });
  });
  /* Guarded: #historyPage is display:none while another tab is current, so
     every getBoundingClientRect() would return 0 and zero out actLaneW —
     silently breaking the playhead and the pan until the next render. */
  window.addEventListener('resize', function () {
    if (!act || currentTab !== 'history') return;
    actMeasure();
    actPaint();
  });
```

At the end of `renderActivity()`, replace `actSetVisible(21);` with:

```js
  actSetVisible(21);
  /* Reduced motion opens on the finished chart instead — a statistic, not a
   * replay. Everything still works; you just start it yourself. */
  if (actReducedMotion()) { actSeek(actLast()); actPause(); }
  else { actSeek(0); actPlay(); }
```

- [ ] **Step 4: Verify playback**

Run: `.venv/bin/python app.py`, open the History tab.
Expected: the activity chart autoplays alongside the race chart and finishes in roughly 5–6 seconds. The band fills left to right; the legend counts up and lands on `bought 112 / played 399 / cleaned 60 / noted 38`; the lane counts land on `16, 15, 14, …`; the date reads `2026-08-21` at the end; the replay button appears. Scrub, pause and speed all respond. Switch to the Collection tab mid-play and back — playback must not still be running behind it.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html
git commit -m "Sweep one playhead across both of the activity chart's scales"
```

---

### Task 7: Zoom, and the band as the scrubber

**Files:**
- Modify: `templates/index.html`

**Interfaces:**
- Consumes: `actApplyZoom() actSeek() actPause() actPaint() actLast()` from Tasks 5–6.
- Produces: pointer handlers on `#actBandWrap` and a click handler on `[data-act-zoom]`. No new functions other than `actSeekAt(e)`.

- [ ] **Step 1: Bind the zoom control**

In the same `DOMContentLoaded` block:

```js
  document.querySelectorAll('[data-act-zoom]').forEach(function (b) {
    b.addEventListener('click', function () {
      document.querySelectorAll('[data-act-zoom]').forEach(function (x) {
        x.classList.toggle('active', x === b);
      });
      const d = Number(b.dataset.actZoom);
      actWin = d > 0 ? Math.min(actLast(), d) : actLast();
      actApplyZoom();
      actPaint();
    });
  });
```

- [ ] **Step 2: Make the band the scrubber**

```js
  /* The band is the control, not a picture of one: drag it to scrub. The range
   * input stays for keyboard and assistive access; both write through
   * actSeek(). */
  let actDragging = false;
  const actBandWrap = document.getElementById('actBandWrap');
  function actSeekAt(e) {
    const r = actBandWrap.getBoundingClientRect();
    actSeek(actClamp((e.clientX - r.left) / r.width, 0, 1) * actLast());
    /* Sync AFTER the seek, for the same reason the scrubber seeks before it
       pauses: actSyncControls() reads actPos, so syncing first would render
       the position being left. A drag is user-paced, not per-frame, so the
       querySelectorAll here costs nothing — unlike inside actSeek(). */
    actSyncControls();
  }
  actBandWrap.addEventListener('pointerdown', function (e) {
    if (!act) return;
    actPause();
    actDragging = true;
    actBandWrap.setPointerCapture(e.pointerId);
    actSeekAt(e);
    e.preventDefault();
  });
  actBandWrap.addEventListener('pointermove', function (e) {
    if (actDragging) actSeekAt(e);
  });
  actBandWrap.addEventListener('pointerup', function () { actDragging = false; });
  actBandWrap.addEventListener('pointercancel', function () { actDragging = false; });
```

- [ ] **Step 3: Reset the zoom on re-render**

`renderActivity()` already sets `actWin = actLast()`. Add the matching control reset just before `actSetVisible(21)`:

```js
  document.querySelectorAll('[data-act-zoom]').forEach(function (x) {
    x.classList.toggle('active', x.dataset.actZoom === '0');
  });
```

- [ ] **Step 4: Verify**

Run: `.venv/bin/python app.py`, History tab.
Expected: clicking `90 d` rescales the lanes so individual ticks separate, and a highlighted window appears on the band. Pressing play flies the window along with the playhead held at about 62% of the lane width, clamped at both ends. Dragging anywhere on the band scrubs both panels and pauses playback. Clicking `all` returns to the full span and the window highlight disappears.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html
git commit -m "Zoom the lanes while the band keeps the whole arc"
```

---

### Task 8: The show and order controls

**Files:**
- Modify: `templates/index.html`

**Interfaces:**
- Consumes: `actSetVisible(n)`, `ACT_SORTS`, `actRows`, `actPaint()`.
- Produces: click handlers on `[data-act-show]` and `[data-act-sort]`. No new functions.

- [ ] **Step 1: Bind both controls**

First add the helper, beside `actApplyZoom()`:

```js
/* One pill in a group is lit at a time. Zoom, show and order all want this,
   and so does the reset every render does — four call sites, one rule. */
function actActivate(attr, value) {
  document.querySelectorAll('[' + attr + ']').forEach(function (x) {
    x.classList.toggle('active', x.getAttribute(attr) === String(value));
  });
}
```

Then rewrite Task 7's two existing copies to call it — the zoom click handler's inner loop becomes `actActivate('data-act-zoom', b.dataset.actZoom);` and the reset in `renderActivity()` becomes `actActivate('data-act-zoom', 0);`. Then bind the two new controls:

```js
  document.querySelectorAll('[data-act-show]').forEach(function (b) {
    b.addEventListener('click', function () {
      actActivate('data-act-show', b.dataset.actShow);
      actSetVisible(Number(b.dataset.actShow));
      actPaint();
    });
  });

  /* All three orders are computed from the whole timeline, never from the
   * playhead, so rows do not re-rank while it plays — the race chart directly
   * above already owns rank animation, and a row that moves cannot be
   * followed. Re-sorting re-applies the current cut, so the folded band always
   * holds exactly the records that are not on screen. */
  document.querySelectorAll('[data-act-sort]').forEach(function (b) {
    b.addEventListener('click', function () {
      actActivate('data-act-sort', b.dataset.actSort);
      actSort = b.dataset.actSort;
      const scroll = document.getElementById('actScroll');
      actRows.sort(function (x, y) { return ACT_SORTS[actSort](x.lane, y.lane); })
             .forEach(function (o) { scroll.appendChild(o.el); });
      actSetVisible(actShow);
      actPaint();
    });
  });
```

- [ ] **Step 2: Reset both controls on re-render**

In `renderActivity()`, beside the zoom reset from Task 7:

```js
  actActivate('data-act-show', 21);
  actActivate('data-act-sort', 'plays');
```

- [ ] **Step 3: Reset the stale row state when the visible set changes**

A row that was hidden still carries the `count`, `owned` and `gone` values it had when it was last painted, and `actPaint()` skips writes when nothing changed — so a newly revealed row would keep a stale count. At the end of `actSetVisible(n)`, before `actApplyZoom()`:

```js
  actLive.forEach(function (o) { o.count = -1; o.owned = null; o.gone = null; });
```

The sentinel has to sit **outside** each field's real domain, exactly as `-1`
does for `count`. Flipping the booleans instead (`o.owned = !o.owned`) is
inverted: the model and the DOM are always written together, so the stale model
value is what the DOM currently shows. Flipping it makes the next paint's
`own !== o.owned` guard true only when the row was already correct, and false
in precisely the case that needed the write — leaving the row stuck. Measured
against the live collection, that left 91 of 112 covers grey when they should
have been full colour, and 43 rows with the wrong quiet state.

- [ ] **Step 4: Verify**

Run: `.venv/bin/python app.py`, History tab, let it finish.
Expected: `all` shows 112 lanes in a scroll pane with no folded band; `top 50` shows 50 with `the other 62 records` below; `top 21` returns to the default. Counts are correct immediately after every switch — no row stuck on `0`. `in rotation` puts the most recently played first; `bought` puts the oldest purchase first and the gold dots form a descending staircase. The visible counts plus the folded band's count always total 399.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html
git commit -m "Let the tail open, and let the lanes be reordered"
```

---

### Task 9: Solo on hover, click through, and the note card

**Files:**
- Modify: `templates/index.html`

**Interfaces:**
- Consumes: `actRows`, `actPaint()`, `actPct()`, the existing global `openDetail(id)`.
- Produces: `actSolo(o) actPaintNote(day)`, module state `actSoloCaption actNoteIdx`. `actPaint()` gains two calls.

- [ ] **Step 1: Write the solo overlay**

```js
let actSoloCaption = null;

/* Pointing at a lane dims the band to just that record's events, drawn across
 * the whole span. It answers what neither panel can alone: where does this one
 * album sit inside the overall habit? */
function actSolo(o) {
  const el = document.getElementById('actSolo');
  const wrap = document.getElementById('actBandWrap');
  if (!o) {
    el.classList.remove('on');
    wrap.classList.remove('dim');
    actSoloCaption = null;
    actPaint();
    return;
  }
  const lane = o.lane, m = [];
  function mark(d, v) {
    m.push('<span class="sm" style="left:' + actPct(d) + '%;background:var(--' + v + ')"></span>');
  }
  mark(lane.bought, 'ev-bought');
  lane.plays.forEach(function (d)  { mark(d, 'ev-played'); });
  lane.cleans.forEach(function (d) { mark(d, 'ev-cleaned'); });
  lane.notes.forEach(function (d)  { mark(d, 'ev-note'); });
  el.innerHTML = m.join('');
  el.classList.add('on');
  wrap.classList.add('dim');
  actSoloCaption = lane.artist + ' — ' + lane.album + ' · ' +
    lane.plays.length + ' plays · ' +
    (lane.plays.length ? 'last ' + VinylActivity.dayAt(act.d0, lane.lastPlay)
                       : 'never played');
  actPaint();
}
```

In `actPaint()`, change the caption block to prefer the hovered lane:

```js
  const cap = document.getElementById('actCaption');
  const text = actSoloCaption || actCaptionFor(day);
  if (cap.textContent !== text) cap.textContent = text;
```

- [ ] **Step 2: Bind hover and click on every lane**

In `actBuildLanes()`, after `scroll.appendChild(el);` and before the `return`:

```js
    const entry = { lane: lane, el: el, cover: el.children[0],
                    track: el.children[2].firstChild, ct: el.children[3],
                    owned: false, count: -1, gone: false };
    el.addEventListener('mouseenter', function () { actSolo(entry); });
    el.addEventListener('mouseleave', function () { actSolo(null); });
    el.addEventListener('click', function () { openDetail(lane.id); });
    return entry;
```

replacing the object literal that was returned directly.

- [ ] **Step 3: Write the note card**

```js
let actNoteIdx = -1;

/* The most recent note as of the playhead, held rather than flashed: with 28
 * notes over a five-second run, anything timer-driven is a flicker. */
function actPaintNote(day) {
  let idx = -1;
  for (let i = 0; i < act.notes.length && act.notes[i].day <= day; i++) idx = i;
  if (idx === actNoteIdx) return;
  actNoteIdx = idx;
  const card = document.getElementById('actNote');
  if (idx < 0) { card.classList.remove('on'); return; }
  const n = act.notes[idx];
  card.querySelector('.who').textContent =
    n.artist + ' — ' + n.album + ' · ' + VinylActivity.dayAt(act.d0, n.day);
  card.querySelector('.txt').textContent = n.text;
  card.classList.add('on');
}
```

Call it from `actPaint()`, just before the caption block:

```js
  actPaintNote(day);
```

and reset it in `renderActivity()`, beside `actPos = 0;`:

```js
  actNoteIdx = -1;
  document.getElementById('actNote').classList.remove('on');
```

- [ ] **Step 4: Verify**

Run: `.venv/bin/python app.py`, History tab.
Expected: hovering a lane dims the band and draws that record's ticks across it, with the caption naming the record, its play count and its last play. Leaving restores the band. Clicking a lane opens that record's detail view. The note card fills in as the playhead passes the first note and thereafter always shows the latest one; scrubbing back to before the first note clears it. Six of the 21 default rows are dimmed at the end of the timeline.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html
git commit -m "Solo a record in the band, and hold the last note on screen"
```

---

### Task 10: Reduced motion, the empty states, and the manual checklist

**Files:**
- Modify: `templates/index.html`
- Modify: `docs/history-tab-manual-verification.md`

**Interfaces:**
- Consumes: everything above.
- Produces: no new functions — verification and documentation only.

- [ ] **Step 1: Verify the empty state**

With the app running, in the console:

```js
const saved = records; records = []; renderActivity();
```

Expected: the box shows "nothing to replay yet — records need a bought date to appear here." and nothing else; no console error. Then:

```js
records = saved; renderActivity();
```

Expected: the chart rebuilds and autoplays.

- [ ] **Step 2: Verify the purchases-only state**

```js
const saved = records;
records = saved.map(r => Object.assign({}, r, { play_dates:'', cleaned_dates:'', notes:'' }));
renderActivity();
records = saved; renderActivity();
```

Expected: a valid chart — the band shows only gold columns, every lane is a gold dot with a dotted tail, the legend reads `bought 112 / played 0 / cleaned 0 / noted 0`, and every lane dims as it goes quiet. No error, no divide-by-zero, no `NaN` anywhere on screen.

- [ ] **Step 3: Verify reduced motion**

In Chrome DevTools, Rendering → "Emulate CSS prefers-reduced-motion: reduce", then reopen the History tab.

Expected: the activity chart opens finished at `2026-08-21` with every total at its final value and does not autoplay. The play button still works. Band segments and row fades snap rather than transition.

- [ ] **Step 4: Append the checklist**

Add to the end of `docs/history-tab-manual-verification.md`:

```markdown
## Activity chart — "how the collection is used"

The model is unit-tested (`tests/test_activity.js`); the animation is not, and
cannot be. Run this list against `.venv/bin/python app.py` after any change.

Expected shape of the live collection: **112 lanes**, `2024-05-31` →
`2026-08-21`, **813 days**, **399 plays**, **60 cleanings** (none before
`2026-03-07`), **38 notes** (28 JSON + 10 legacy plain-string). Default cut: 21 lanes holding 214 plays, the
folded band holding the other 91 records and 185 plays.

### Correctness

- [ ] The legend's four totals end at `112 / 399 / 60 / 38` and match the
      figures on the record detail views.
- [ ] Visible lane counts plus the folded band's count equal 399 at every
      `show` setting.
- [ ] The lane counts under `most played` end `16, 15, 14, 13, 13, 12, …`.
- [ ] The cleaned series is absent until March 2026, then appears — this is the
      data, not a bug.
- [ ] No wishlist record appears.
- [ ] Clicking any lane opens that record's detail view.

### Motion

- [ ] Opening the tab autoplays from day 0 and finishes in about 5–6 seconds.
- [ ] The band grows smoothly week by week; nothing jumps.
- [ ] Dragging the band scrubs both panels and pauses playback.
- [ ] At `90 d` the window follows the playhead, held at about 62% of the lane
      width, and clamps at both ends without overshooting.
- [ ] Leaving the History tab stops playback — no frame loop runs behind the
      collection view.

### State

- [ ] Six of the 21 default lanes are dimmed at the end of the timeline, and a
      dimmed lane lights back up when scrubbed to a moment it was in rotation.
- [ ] Hovering a lane dims the band to that record's events; leaving restores it.
- [ ] The note card holds the most recent note and clears when scrubbed before
      the first one.
- [ ] Switching `show` or `order` leaves no lane stuck on a stale count.
- [ ] Switching `show` or `order` leaves no lane stuck on a stale *class*
      either — for every visible row, the cover carries `owned` iff the
      playhead has passed its purchase day, and the row carries `gone` iff it
      has been silent longer than the quiet threshold. Totals alone do not
      catch this: the inverted-sentinel bug left 91 covers wrong while every
      count was right.

### Both themes

- [ ] Every mark, tick, label and control is legible in dark and in light.
- [ ] `prefers-reduced-motion` opens the chart finished instead of autoplaying.
```

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add templates/index.html docs/history-tab-manual-verification.md
git commit -m "Hold the activity chart's edges: empty, unplayed, reduced motion"
```

---

## Self-Review

**Spec coverage.** Every numbered section maps to a task: §1 data layer → Tasks 1–3; §2 placement → Task 4; §3 rendering and the two-write frame → Tasks 4–6; §4.1 transport → Task 6; §4.2 band-as-scrubber and §4.3 zoom → Task 7; §4.4 show and §4.5 order → Task 8; §4.6 solo, click-through, §4.7 quiet fade and §4.8 note card → Task 9 (the fade's threshold and the dotted tail are set in Tasks 5–6, where the marks and per-row state are written); §5 colour → Task 4; §6 wiring → Task 5; §7 empty and reduced-motion states → Tasks 5, 6 and 10; §8 tests → Tasks 1–3 and 10; §9 files → all.

**Gap found and closed.** The spec does not mention that hidden rows keep stale per-row state across a `show` change, which the change-detection in `actPaint()` would otherwise preserve. Task 8 Step 3 handles it.

**Naming.** `actWin` is the zoom window everywhere, `actLast()` the axis maximum, `actShow` the visible count. The module returns `lanes[].plays/cleans/notes` and the renderer reads exactly those. `ACT_SORTS` keys match the `data-act-sort` values (`plays`, `recent`, `bought`). `dayAt(d0, i)` is defined in Task 1 and used in Tasks 6 and 9.

**Names verified against the tree.** `esc()` is at `templates/index.html:3986`. `openDetail(id)` is at `:2572`. `momentOf` is exported from `static/grouping.js`. The race chart's `raceSyncControls()` selects `.race-speed-btn`, which is why the activity speed buttons are `.act-speed-btn` — Task 4 Step 2 widens the shared CSS rules instead of sharing the class.

**Declaration order.** `actTailPlays` (Task 5) and `actNoteIdx` (Task 9) are declared above the functions that assign them, not below, so neither sits in a temporal dead zone if the render path is ever called earlier than expected.
