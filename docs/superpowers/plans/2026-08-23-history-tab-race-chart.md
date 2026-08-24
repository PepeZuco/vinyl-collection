# History Tab — Collection Growth Race Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fourth "History" tab that replays the collection's growth as a horizontal bar chart race — one frame per purchase day, bars ranked by cumulative records per genre, with album covers flying in and riding inside each bar as they arrive.

**Architecture:** All logic that needs no DOM lives in a new pure module `static/history.js` (`buildTimeline`), tested with `node:test`, exactly like the existing `static/grouping.js`. Presentation lives in `templates/index.html` as HTML rows whose bar width, row position and cover entry are interpolated entirely by CSS transitions — a `setTimeout` chain only advances the frame. Covers are ordinary `<img>` elements so the browser owns decode and caching, and clicking one through to `openDetail(id)` is free.

**Tech Stack:** Vanilla ES5-flavoured browser JS (no build step), CSS custom properties and transitions, `node:test` for unit tests wrapped by pytest, Flask/Jinja for the single template.

**Spec:** `docs/superpowers/specs/2026-08-23-history-tab-race-chart-design.md`

## Global Constraints

- **No build step.** `templates/index.html` is served as-is; `static/*.js` are plain `<script>` tags. No bundler, no modules, no JSX.
- **No new dependencies.** d3 and Chart.js are already loaded but this feature uses neither.
- **Module shape** for `static/history.js` matches `grouping.js` and `spend.js` exactly: an IIFE assigned to a `const`, with `if (typeof module !== 'undefined' && module.exports) module.exports = X;` as the last line.
- **JS tests run under pytest.** Every `tests/test_*.js` gets a `tests/test_*.py` wrapper shelling out to `node --test`, skipped when node is absent. `pytest` stays the single command.
- **`TZ` is pinned** to `America/Sao_Paulo` at the top of every JS test file, before any `Date` is constructed. The collection's stamps are local wall clocks; without a fixed offset the assertions are meaningless.
- **Date parsing is delegated** to `VinylGrouping.momentOf()`. Never re-implement stamp parsing — the three stamp shapes are decided in one place.
- **Scope rule, verbatim from the spec:** a record is in scope when `have_it` is truthy and `momentOf(r.bought_date).day` is non-empty. Everything else is silently dropped, never bucketed into a catch-all.
- **Genre hues** come from the existing `genreColor(genre)`; never hard-code a genre colour.
- **Every commit message** ends with the two trailers this repo uses:
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01LdqMmBP3P43FfxMcuuPgMQ
  ```
- **Expected live data** (for eyeballing correctness): 31 frames, `2024-05-31` → `2026-08-01`, 112 records, 11 genres, final leader MPB & Samba at 34, opening frame has exactly 3 bars (Easy Listening, Folk, Soul & Funk).

---

## File Structure

| File | Responsibility |
|---|---|
| `static/history.js` **(create)** | `buildTimeline(records)` — the only logic that can be decided without a DOM. Pure, no globals beyond the module const. |
| `tests/test_history.js` **(create)** | `node:test` unit tests for `buildTimeline`. |
| `tests/test_history.py` **(create)** | pytest wrapper that shells out to `node --test`. |
| `templates/index.html` **(modify)** | CSS block, `.history-page` markup, `<script src>` tag, the `renderHistory` / `racePaint` / playback controller, and four small edits to existing functions (`switchTab`, `syncMobileTabbar`, `bindEvents`, the theme toggle). |
| `docs/history-tab-manual-verification.md` **(create)** | The animation checks that cannot be unit tested. |

---

### Task 1: `buildTimeline` — scope, frames, cumulative counts

Builds the pure data layer with everything except the rank-stability tie-break (Task 2). Bars come out ordered by count descending, name ascending.

**Files:**
- Create: `static/history.js`
- Create: `tests/test_history.js`
- Create: `tests/test_history.py`

**Interfaces:**
- Consumes: `VinylGrouping.momentOf(raw)` from `static/grouping.js`, which returns `{ day, time, at }` — `day` is `'YYYY-MM-DD'` or `''` when unparseable, `at` is a sortable local stamp.
- Produces: `VinylHistory.buildTimeline(records)` → `[Frame]`, where
  `Frame = { day: String, index: Number, total: Number, bars: [Bar] }` and
  `Bar = { genre: String, label: String, count: Number, records: [record], added: [record] }`.
  Task 2 refines the ordering of `bars`. Tasks 4–8 consume this shape.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_history.js`:

```js
// Tests for the pure timeline builder behind the History tab's race chart.
// Run by tests/test_history.py so `pytest` stays the single command.

// Pinned before anything constructs a Date: momentOf moves stamps onto the
// local clock, which says nothing without an offset to move them by. Sao Paulo
// is UTC-3 and the collection's own timezone.
process.env.TZ = 'America/Sao_Paulo';

const test = require('node:test');
const assert = require('node:assert');

const { buildTimeline } = require('../static/history.js');

// A record only needs the fields the timeline reads, so each test builds the
// smallest one that exercises its rule.
let nextId = 1;
function rec(fields) {
  return Object.assign(
    { id: nextId++, artist: 'A', album_name: 'A', have_it: true, genre: 'Rock' },
    fields);
}

// ── scope ───────────────────────────────────────────────────────────────────

test('a collection with nothing in it has no timeline', () => {
  assert.deepStrictEqual(buildTimeline([]), []);
});

test('wishlist records are excluded even when they carry a date', () => {
  const frames = buildTimeline([
    rec({ have_it: false, genre: 'Jazz', bought_date: '2026-01-05' }),
  ]);
  assert.deepStrictEqual(frames, []);
});

test('owned records with no date are excluded', () => {
  assert.deepStrictEqual(buildTimeline([rec({ bought_date: '' })]), []);
});

test('an unparseable date is dropped rather than thrown on', () => {
  const frames = buildTimeline([
    rec({ genre: 'Jazz', bought_date: '2026-02-30' }),
    rec({ genre: 'Rock', bought_date: '2026-02-11' }),
  ]);
  assert.strictEqual(frames.length, 1);
  assert.strictEqual(frames[0].total, 1);
  assert.strictEqual(frames[0].bars[0].label, 'Rock');
});

// ── frames ──────────────────────────────────────────────────────────────────

test('one frame per distinct purchase day, ascending', () => {
  const frames = buildTimeline([
    rec({ bought_date: '2026-03-04' }),
    rec({ bought_date: '2026-01-02' }),
    rec({ bought_date: '2026-03-04T18:30:00' }),
  ]);
  assert.deepStrictEqual(frames.map(f => f.day), ['2026-01-02', '2026-03-04']);
  assert.deepStrictEqual(frames.map(f => f.index), [0, 1]);
});

test('days with no purchase get no frame — the timeline hops', () => {
  const frames = buildTimeline([
    rec({ bought_date: '2024-05-31' }),
    rec({ bought_date: '2026-08-01' }),
  ]);
  assert.strictEqual(frames.length, 2);
});

// ── cumulative ──────────────────────────────────────────────────────────────

test('counts are running totals, never per-day counts', () => {
  const frames = buildTimeline([
    rec({ genre: 'Rock', bought_date: '2026-01-01' }),
    rec({ genre: 'Rock', bought_date: '2026-01-02' }),
    rec({ genre: 'Rock', bought_date: '2026-01-03' }),
  ]);
  assert.deepStrictEqual(frames.map(f => f.bars[0].count), [1, 2, 3]);
});

test('frame total counts every genre through that day', () => {
  const frames = buildTimeline([
    rec({ genre: 'Rock', bought_date: '2026-01-01' }),
    rec({ genre: 'Jazz', bought_date: '2026-01-02' }),
    rec({ genre: 'Pop', bought_date: '2026-01-02' }),
  ]);
  assert.deepStrictEqual(frames.map(f => f.total), [1, 3]);
});

test('the final frame matches a plain group-by over the scoped records', () => {
  const frames = buildTimeline([
    rec({ genre: 'Rock', bought_date: '2026-01-01' }),
    rec({ genre: 'Rock', bought_date: '2026-02-01' }),
    rec({ genre: 'Jazz', bought_date: '2026-02-01' }),
  ]);
  const last = frames[frames.length - 1];
  const counts = Object.fromEntries(last.bars.map(b => [b.label, b.count]));
  assert.deepStrictEqual(counts, { Rock: 2, Jazz: 1 });
});

// ── entry ───────────────────────────────────────────────────────────────────

test('a genre is absent until the frame it first has a record', () => {
  const frames = buildTimeline([
    rec({ genre: 'Rock', bought_date: '2026-01-01' }),
    rec({ genre: 'Jazz', bought_date: '2026-02-01' }),
  ]);
  assert.deepStrictEqual(frames[0].bars.map(b => b.label), ['Rock']);
  assert.deepStrictEqual(frames[1].bars.map(b => b.label).sort(), ['Jazz', 'Rock']);
});

// ── added ───────────────────────────────────────────────────────────────────

test('added holds only that day arrivals', () => {
  const frames = buildTimeline([
    rec({ genre: 'Rock', bought_date: '2026-01-01' }),
    rec({ genre: 'Rock', bought_date: '2026-02-01' }),
    rec({ genre: 'Rock', bought_date: '2026-02-01' }),
  ]);
  assert.strictEqual(frames[1].bars[0].count, 3);
  assert.strictEqual(frames[1].bars[0].added.length, 2);
});

test('a genre that gained nothing that day has an empty added list', () => {
  const frames = buildTimeline([
    rec({ genre: 'Rock', bought_date: '2026-01-01' }),
    rec({ genre: 'Jazz', bought_date: '2026-02-01' }),
  ]);
  const rock = frames[1].bars.find(b => b.label === 'Rock');
  assert.deepStrictEqual(rock.added, []);
});

test('records within a bar run oldest purchase first', () => {
  const frames = buildTimeline([
    rec({ id: 9, genre: 'Rock', bought_date: '2026-02-01' }),
    rec({ id: 8, genre: 'Rock', bought_date: '2026-01-01' }),
  ]);
  assert.deepStrictEqual(frames[1].bars[0].records.map(r => r.id), [8, 9]);
});

// ── untagged ────────────────────────────────────────────────────────────────

test('a record with no genre surfaces as unknown', () => {
  const frames = buildTimeline([rec({ genre: '', bought_date: '2026-01-01' })]);
  assert.strictEqual(frames[0].bars[0].genre, '');
  assert.strictEqual(frames[0].bars[0].label, 'unknown');
});
```

Create `tests/test_history.py`:

```python
"""Run the JavaScript race-chart timeline tests under pytest.

The timeline rules are pure functions living in static/history.js, so they are
testable — but only by a JS runtime. Shelling out to node's built-in test runner
keeps `pytest` as the one command that runs everything.
"""

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_history_js():
    result = subprocess.run(
        ["node", "--test", "tests/test_history.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_history.py -v`
Expected: FAIL — `Cannot find module '../static/history.js'`

- [ ] **Step 3: Write the implementation**

Create `static/history.js`:

```js
'use strict';

/* The collection's growth, as frames for the History tab's bar chart race.
 *
 * One frame per day the collection was bought on — days with no purchase get
 * no frame, so the timeline hops between shopping trips rather than crawling
 * through the ~96% of calendar days where nothing changed.
 *
 * Pure functions of the record list, kept out of index.html so they can be
 * tested directly (tests/test_history.js).
 *
 * Loaded as a plain script in the browser AFTER grouping.js, whose momentOf
 * this depends on; required as a module by the tests. */

const VinylHistory = (function (grouping) {

  /* Owned and dated. Every have_it record in the collection carries a
   * bought_date and every undated one is a wishlist item, so this loses
   * nothing owned — and it makes the final frame's counts equal the
   * Statistics tab's genre chart exactly.
   *
   * Anything unparseable is dropped rather than bucketed: momentOf already
   * returns empty for a stamp the calendar could not hold, and one bad row
   * must not take the whole tab down. */
  function inScope(r) {
    return !!r.have_it && !!grouping.momentOf(r.bought_date).day;
  }

  function buildTimeline(records) {
    const scoped = (records || []).filter(inScope);
    if (!scoped.length) return [];

    /* Oldest purchase first, ties broken by id — so a bar's cover strip is in
     * a stable order and never reshuffles between frames. */
    scoped.sort(function (a, b) {
      const at = grouping.momentOf(a.bought_date).at;
      const bt = grouping.momentOf(b.bought_date).at;
      if (at !== bt) return at < bt ? -1 : 1;
      return (Number(a.id) || 0) - (Number(b.id) || 0);
    });

    const byDay = new Map();
    for (const r of scoped) {
      const day = grouping.momentOf(r.bought_date).day;
      if (!byDay.has(day)) byDay.set(day, []);
      byDay.get(day).push(r);
    }

    const cumulative = new Map();   // genre -> records so far, oldest first
    const frames = [];
    let total = 0;

    [...byDay.keys()].sort().forEach(function (day, index) {
      const added = new Map();
      for (const r of byDay.get(day)) {
        const g = (r.genre || '').trim();
        if (!cumulative.has(g)) cumulative.set(g, []);
        if (!added.has(g)) added.set(g, []);
        cumulative.get(g).push(r);
        added.get(g).push(r);
        total++;
      }

      /* Only genres that have appeared get a bar — no row sits at zero
       * waiting its turn. */
      const bars = [...cumulative.entries()].map(function (entry) {
        const genre = entry[0], recs = entry[1];
        return {
          genre: genre,
          label: genre || 'unknown',
          count: recs.length,
          records: recs.slice(),
          added: (added.get(genre) || []).slice(),
        };
      });

      bars.sort(function (a, b) {
        if (a.count !== b.count) return b.count - a.count;
        return a.label < b.label ? -1 : a.label > b.label ? 1 : 0;
      });

      frames.push({ day: day, index: index, total: total, bars: bars });
    });

    return frames;
  }

  return { buildTimeline: buildTimeline };
})(typeof module !== 'undefined' && module.exports
     ? require('./grouping.js') : VinylGrouping);

if (typeof module !== 'undefined' && module.exports) module.exports = VinylHistory;
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_history.py -v`
Expected: PASS

- [ ] **Step 5: Run the whole suite — nothing else may have moved**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add static/history.js tests/test_history.js tests/test_history.py
git commit -m "Add buildTimeline: the collection's growth as per-day frames

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LdqMmBP3P43FfxMcuuPgMQ"
```

---

### Task 2: Rank-stability tie-break

Two genres sitting level must not trade places. Without this, Rock and Pop — within a record of each other for long stretches of the real collection — swap rows every time one gains and the other catches up, animating a swap that means nothing. After this task, a swap on screen always means a real overtake.

**Files:**
- Modify: `static/history.js` — the `bars.sort` comparator
- Modify: `tests/test_history.js` — append the ordering tests

**Interfaces:**
- Consumes: the `Frame`/`Bar` shape from Task 1.
- Produces: no signature change. `bars` ordering becomes: count descending, then the genre's rank in the **previous** frame ascending (a genre absent from it sorts last among ties), then `label` ascending. On frame 0 there is no previous frame, so ties fall to `label`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_history.js`:

```js
// ── ordering ────────────────────────────────────────────────────────────────

/* Blues and Jazz enter together and stay level, then Jazz takes the lead, then
 * Blues draws level again, then Blues genuinely overtakes. The interesting
 * frame is the fourth: Blues sorts first alphabetically, so a naive tie-break
 * would swap the rows there even though nothing overtook anything. */
function seesaw() {
  return buildTimeline([
    rec({ id: 1, genre: 'Blues', bought_date: '2026-01-01' }),
    rec({ id: 2, genre: 'Jazz',  bought_date: '2026-01-01' }),
    rec({ id: 3, genre: 'Rock',  bought_date: '2026-01-02' }),
    rec({ id: 4, genre: 'Jazz',  bought_date: '2026-01-03' }),
    rec({ id: 5, genre: 'Blues', bought_date: '2026-01-04' }),
    rec({ id: 6, genre: 'Blues', bought_date: '2026-01-05' }),
  ]);
}

test('the opening frame breaks ties by name, having no previous frame', () => {
  assert.deepStrictEqual(seesaw()[0].bars.map(b => b.label), ['Blues', 'Jazz']);
});

test('a genre entering later sorts last among equals', () => {
  assert.deepStrictEqual(seesaw()[1].bars.map(b => b.label),
                         ['Blues', 'Jazz', 'Rock']);
});

test('a real overtake reorders the bars', () => {
  assert.deepStrictEqual(seesaw()[2].bars.map(b => b.label),
                         ['Jazz', 'Blues', 'Rock']);
});

test('drawing level does not swap rows — the leader holds its place', () => {
  const frame = seesaw()[3];
  assert.strictEqual(frame.bars[0].count, frame.bars[1].count, 'they are level');
  assert.deepStrictEqual(frame.bars.map(b => b.label),
                         ['Jazz', 'Blues', 'Rock']);
});

test('passing the leader outright does swap rows', () => {
  assert.deepStrictEqual(seesaw()[4].bars.map(b => b.label),
                         ['Blues', 'Jazz', 'Rock']);
});
```

- [ ] **Step 2: Run the tests to verify the tie-break one fails**

Run: `.venv/bin/python -m pytest tests/test_history.py -v`
Expected: FAIL — `drawing level does not swap rows` gets `['Blues','Jazz','Rock']`, expected `['Jazz','Blues','Rock']`

- [ ] **Step 3: Write the implementation**

In `static/history.js`, add a `prevRank` map above the day loop:

```js
    const cumulative = new Map();   // genre -> records so far, oldest first
    let prevRank = new Map();       // genre -> its row index in the last frame
    const frames = [];
    let total = 0;
```

Replace the `bars.sort` comparator, and record the new ranking after it:

```js
      /* Ties are broken by who held the higher row last frame, not by name.
       * Genres sit level for long stretches, and an alphabetical tie-break
       * makes them trade rows every time one gains and the other catches up —
       * a swap animation that means nothing. Holding position means a swap on
       * screen is always a real overtake. A genre with no previous rank sorts
       * last among equals, so an entrant slots in below the incumbents. */
      bars.sort(function (a, b) {
        if (a.count !== b.count) return b.count - a.count;
        const ar = prevRank.has(a.genre) ? prevRank.get(a.genre) : Infinity;
        const br = prevRank.has(b.genre) ? prevRank.get(b.genre) : Infinity;
        if (ar !== br) return ar - br;
        return a.label < b.label ? -1 : a.label > b.label ? 1 : 0;
      });

      prevRank = new Map(bars.map(function (bar, i) { return [bar.genre, i]; }));
      frames.push({ day: day, index: index, total: total, bars: bars });
```

Note `ar !== br` guards the `Infinity - Infinity` case: two entrants both
missing from the previous frame fall through to the name comparison rather
than comparing `NaN`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_history.py -v`
Expected: PASS — all of them, including the Task 1 tests

- [ ] **Step 5: Sanity-check against the live collection**

Run:
```bash
node -e "
const h = require('./static/history.js');
const rows = require('child_process').execSync(
  \".venv/bin/python -c \\\"import sqlite3,json;c=sqlite3.connect('instance/vinyl.db');print(json.dumps([dict(zip(['id','genre','bought_date','have_it'],r)) for r in c.execute('select id,genre,bought_date,have_it from record')]))\\\"\",
  {encoding:'utf8', maxBuffer: 1<<28});
const f = h.buildTimeline(JSON.parse(rows));
console.log('frames', f.length, f[0].day, '->', f[f.length-1].day);
console.log('total', f[f.length-1].total, 'genres', f[f.length-1].bars.length);
console.log('leader', f[f.length-1].bars[0].label, f[f.length-1].bars[0].count);
console.log('opening', f[0].bars.map(b=>b.label).join(', '));
"
```
Expected exactly:
```
frames 31 2024-05-31 -> 2026-08-01
total 112 genres 11
leader MPB & Samba 34
opening Easy Listening, Folk, Soul & Funk
```

- [ ] **Step 6: Commit**

```bash
git add static/history.js tests/test_history.js
git commit -m "Hold row order when genres are level, so a swap means an overtake

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LdqMmBP3P43FfxMcuuPgMQ"
```

---

### Task 3: Navigation shell — the tab, the page, the mobile segment

The tab exists, switches, and shows an empty chart box. No chart yet. This is the whole navigation surface in one reviewable change.

**Files:**
- Modify: `templates/index.html:642-645` (CSS, after the `.stats-page` block)
- Modify: `templates/index.html:1156-1160` (the `.nav-tabs` block)
- Modify: `templates/index.html:1189` (top of `.stats-page`, add the segment)
- Modify: `templates/index.html:1189` (insert the new `.history-page` before the collection page)
- Modify: `templates/index.html:1693-1694` (script tags)
- Modify: `templates/index.html:1721` (theme toggle)
- Modify: `templates/index.html:4155-4174` (`switchTab`, `syncMobileTabbar`)
- Modify: `templates/index.html:3691-3693` (`bindEvents`)

**Interfaces:**
- Consumes: `VinylHistory.buildTimeline` (loaded, not yet called), the existing `currentTab` global, `switchTab(tab)`, `syncMobileTabbar()`.
- Produces: `currentTab === 'history'` as a valid state; DOM ids `historyPage`, `tabHistory`, `racePlot`, `raceDay`, `raceTotal`, `raceScrub`, `racePlayBtn`, `raceReplayBtn`, `raceTooltip`; a `renderHistory()` stub and `racePause()` stub that Tasks 4–8 fill in.

- [ ] **Step 1: Add the CSS**

After the `.collection-page.hidden{display:none}` line (currently `templates/index.html:645`), insert:

```css
/* history page — the collection's growth as a bar chart race */
.history-page{display:none}
.history-page.visible{display:block}

/* stats/history segment — mobile only. The bottom bar already carries four
   items plus the centre FAB, and a fifth would land underneath it, so on a
   phone History is reached from inside the Stats tab instead. */
.stats-seg{display:none}
@media(max-width:760px){
  .stats-seg{display:flex;gap:5px;margin-bottom:16px}
  .stats-seg-btn{flex:1;height:34px;border:1px solid var(--border);border-radius:var(--radius-sm);
    background:transparent;color:var(--muted);font:600 12px var(--font);cursor:pointer}
  .stats-seg-btn.active{border-color:var(--accent);color:var(--accent);
    background:color-mix(in srgb, var(--accent) 10%, transparent)}
}
```

- [ ] **Step 2: Add the nav tab**

Replace the `.nav-tabs` block (currently `templates/index.html:1156-1160`) with:

```html
  <div class="nav-tabs">
    <button class="nav-tab active" id="tabCollection"><i class="ti ti-layout-grid"></i> Collection</button>
    <button class="nav-tab" id="tabCalendar"><i class="ti ti-calendar-month"></i> Calendar</button>
    <button class="nav-tab" id="tabStats"><i class="ti ti-chart-bar"></i> Statistics</button>
    <button class="nav-tab" id="tabHistory"><i class="ti ti-timeline"></i> History</button>
  </div>
```

- [ ] **Step 3: Add the segment to the stats page and create the history page**

Change the opening of the stats page (currently `templates/index.html:1189`) from:

```html
  <div class="stats-page" id="statsPage">
    <div class="stats-split" id="statsCards"></div>
```

to:

```html
  <div class="stats-page" id="statsPage">
    <div class="stats-seg">
      <button class="stats-seg-btn active" data-seg="stats" onclick="switchTab('stats')">stats</button>
      <button class="stats-seg-btn" data-seg="history" onclick="switchTab('history')">history</button>
    </div>
    <div class="stats-split" id="statsCards"></div>
```

Then insert the whole history page immediately before `<!-- collection page -->`:

```html
  <!-- history page — the collection's growth, replayed -->
  <div class="history-page" id="historyPage">
    <div class="stats-seg">
      <button class="stats-seg-btn" data-seg="stats" onclick="switchTab('stats')">stats</button>
      <button class="stats-seg-btn active" data-seg="history" onclick="switchTab('history')">history</button>
    </div>
    <div class="chart-box" style="margin-bottom:28px">
      <div class="chart-title" style="display:flex;align-items:center;justify-content:space-between;gap:12px">
        <span>how the collection grew</span>
        <span class="race-total" id="raceTotal"></span>
      </div>
      <div class="race-plot-wrap">
        <div class="race-plot" id="racePlot"></div>
        <div class="chart-tooltip" id="raceTooltip"></div>
      </div>
      <div class="race-day" id="raceDay"></div>
      <div class="race-controls">
        <button class="race-btn" id="racePlayBtn" aria-label="play" aria-pressed="false"><i class="ti ti-player-play"></i></button>
        <input type="range" id="raceScrub" min="0" max="0" step="1" value="0" aria-label="purchase day">
        <div class="race-speeds">
          <button class="race-speed-btn" data-speed="0.5">0.5&times;</button>
          <button class="race-speed-btn active" data-speed="1">1&times;</button>
          <button class="race-speed-btn" data-speed="2">2&times;</button>
        </div>
        <button class="race-btn hidden" id="raceReplayBtn" aria-label="replay"><i class="ti ti-refresh"></i></button>
      </div>
    </div>
  </div>
```

- [ ] **Step 4: Load the module**

After the `grouping.js` script tag (currently `templates/index.html:1693`), add — order matters, `history.js` reads `VinylGrouping` at load time:

```html
<script src="/static/history.js"></script>
```

- [ ] **Step 5: Wire the tab into switchTab and the mobile bar**

Replace `switchTab` and `syncMobileTabbar` (currently `templates/index.html:4155-4174`) with:

```js
function switchTab(tab) {
  const leaving = currentTab;
  currentTab = tab;
  document.getElementById('collectionPage').classList.toggle('hidden', tab !== 'collection');
  document.getElementById('statsPage').classList.toggle('visible', tab === 'stats');
  document.getElementById('calendarPage').classList.toggle('visible', tab === 'calendar');
  document.getElementById('historyPage').classList.toggle('visible', tab === 'history');
  document.getElementById('tabCollection').classList.toggle('active', tab === 'collection');
  document.getElementById('tabStats').classList.toggle('active', tab === 'stats');
  document.getElementById('tabCalendar').classList.toggle('active', tab === 'calendar');
  document.getElementById('tabHistory').classList.toggle('active', tab === 'history');
  document.querySelectorAll('.stats-seg-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.seg === tab);
  });
  syncMobileTabbar();

  // Leaving the tab stops the race — no timer runs behind the collection view.
  if (leaving === 'history' && tab !== 'history') racePause();

  if (tab === 'stats') renderStats();
  if (tab === 'calendar') renderCalendar();
  if (tab === 'history') renderHistory();
}

// ── mobile bottom tab bar — mirrors haveItMode + currentTab, no separate state ─
function syncMobileTabbar() {
  const onCollection = currentTab === 'collection';
  document.getElementById('mtabCollection').classList.toggle('active', onCollection && haveItMode === 'collection');
  document.getElementById('mtabWishlist').classList.toggle('active', onCollection && haveItMode === 'wishlist');
  document.getElementById('mtabCalendar').classList.toggle('active', currentTab === 'calendar');
  // History has no item of its own on the phone — it lives inside Stats, so
  // the Stats item stays lit while you are on it.
  document.getElementById('mtabStats').classList.toggle('active',
    currentTab === 'stats' || currentTab === 'history');
}
```

- [ ] **Step 6: Add the stubs Tasks 4–8 will fill**

Immediately after `syncMobileTabbar`, add:

```js
// ── history: the collection's growth as a bar chart race ───────────────────
function renderHistory() {}
function racePause() {}
```

- [ ] **Step 7: Bind the tab button and re-render on theme change**

In `bindEvents` (currently `templates/index.html:3692`), after the `tabStats` line add:

```js
  document.getElementById('tabHistory').addEventListener('click', () => switchTab('history'));
```

And on the theme toggle line (currently `templates/index.html:1721`), extend the tail so the race repaints in the new palette:

```js
document.getElementById('themeBtn').addEventListener('click', () => { applyTheme(theme === 'dark' ? 'light' : 'dark'); render(); if(currentTab==='stats') renderStats(); if(currentTab==='history') renderHistory(); });
```

- [ ] **Step 8: Verify in the browser**

Run: `.venv/bin/python app.py` and open `http://localhost:5000`

Check, with the devtools console open:
- A fourth "History" tab appears and switching to it shows an empty chart box titled "how the collection grew", with play/scrub/speed controls.
- Switching between all four tabs leaves **no console errors**.
- `VinylHistory.buildTimeline(records).length` typed in the console returns `31`.
- Narrow the window under 760px: the bottom bar still has four items, the Stats page shows a stats/history segment, tapping "history" switches to the race page with the Stats item still lit, and tapping "stats" comes back.

- [ ] **Step 9: Run the suite and commit**

Run: `.venv/bin/python -m pytest -q` — expected: all pass

```bash
git add templates/index.html
git commit -m "Add the History tab shell, with a stats/history segment for mobile

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LdqMmBP3P43FfxMcuuPgMQ"
```

---

### Task 4: Static render — rows, bars, covers, one frame at a time

`renderHistory()` builds the frames and paints the **final** one, with no motion and no playback. The chart is correct before it is animated.

**Files:**
- Modify: `templates/index.html` — the CSS block from Task 3, and the `renderHistory` stub

**Interfaces:**
- Consumes: `VinylHistory.buildTimeline(records)`, `genreColor(genre)`, the global `records`.
- Produces: `raceFrames` / `raceIndex` / `raceRows` globals, `racePaint(i, animate)`, `raceCovers(strip, bar, animate)`, and the constants `RACE_BASE_MS`, `RACE_COVER_CAP`. Task 5 drives `racePaint`; Task 7 uses its `animate` argument; Task 8 reads `raceFrames[raceIndex]`.

- [ ] **Step 1: Add the chart CSS**

Append to the history CSS block added in Task 3, before the `.stats-seg` rules:

```css
.race-total{color:var(--label);font-size:11px;font-variant-numeric:tabular-nums;
  text-transform:none;letter-spacing:0}
.race-plot-wrap{position:relative}
.race-plot{position:relative;--race-row-h:34px;--race-dur:1000ms;margin:6px 0 2px}
.race-empty{color:var(--muted);font-size:13px;padding:20px 2px}

/* Rows are absolutely positioned and moved by transform, not by reflow —
   that is what makes an overtake animate as a swap. */
.race-row{position:absolute;left:0;right:0;height:var(--race-row-h);
  display:flex;align-items:center;gap:10px;
  transition:transform var(--race-dur) cubic-bezier(.4,0,.2,1),opacity .25s}
.race-row.gone{opacity:0;pointer-events:none}
.race-label{width:112px;flex-shrink:0;text-align:right;font-size:12px;font-weight:600;
  color:var(--label);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.race-track{flex:1;min-width:0;display:flex;align-items:center;gap:8px}
.race-bar{position:relative;height:calc(var(--race-row-h) - 8px);border-radius:2px;
  flex-shrink:0;cursor:pointer;
  background:color-mix(in srgb, var(--gc) 22%, transparent);
  border-left:3px solid var(--gc);
  transition:width var(--race-dur) cubic-bezier(.4,0,.2,1)}
.race-bar:hover{background:color-mix(in srgb, var(--gc) 34%, transparent)}

/* The strip is pinned to the bar's growing tip and clipped at the left, so a
   new cover always lands where the eye already is and older ones dissolve
   under the fade. No cap arithmetic, no width measurement, no resize handler.
   Safari still needs the -webkit- twin. */
.race-covers{position:absolute;inset:2px 3px 2px 0;display:flex;justify-content:flex-end;
  align-items:center;gap:2px;overflow:hidden;
  -webkit-mask-image:linear-gradient(to right,transparent 0,#000 34px);
  mask-image:linear-gradient(to right,transparent 0,#000 34px)}
.race-cover{width:calc(var(--race-row-h) - 12px);height:calc(var(--race-row-h) - 12px);
  flex-shrink:0;border-radius:2px;object-fit:cover;background:#111;cursor:pointer}
[data-theme="light"] .race-cover{background:#eee}
.race-count{font-size:12.5px;font-weight:700;color:var(--text);
  font-variant-numeric:tabular-nums;min-width:26px}

/* The date ticker — a scoreboard clock, deliberately oversized and greyed. */
.race-day{text-align:right;font-family:var(--font-mono);font-size:26px;font-weight:700;
  color:var(--muted);margin:4px 0 14px;font-variant-numeric:tabular-nums}

.race-controls{display:flex;align-items:center;gap:12px;
  border-top:1px solid var(--border);padding-top:12px}
.race-btn{width:34px;height:34px;flex-shrink:0;display:flex;align-items:center;
  justify-content:center;border:1px solid var(--border);border-radius:var(--radius-sm);
  background:transparent;color:var(--text);font-size:15px;cursor:pointer}
.race-btn:hover{border-color:var(--accent);color:var(--accent)}
.race-btn.hidden{display:none}
#raceScrub{flex:1;min-width:0;accent-color:var(--accent);cursor:pointer}
#raceScrub:disabled{opacity:.4;cursor:default}
.race-speeds{display:flex;gap:3px;flex-shrink:0}
.race-speed-btn{height:26px;padding:0 8px;border:1px solid var(--border);
  border-radius:var(--radius-sm);background:transparent;color:var(--muted);
  font:600 11px var(--font);cursor:pointer;font-variant-numeric:tabular-nums}
.race-speed-btn.active{border-color:var(--accent);color:var(--accent)}

@media(max-width:760px){
  .race-plot{--race-row-h:28px}
  .race-label{width:76px;font-size:11px}
  .race-day{font-size:19px}
  .race-controls{gap:8px}
}
```

- [ ] **Step 2: Replace the `renderHistory` stub**

Replace `function renderHistory() {}` with:

```js
const RACE_BASE_MS = 1000;    // one purchase day at 1× — ~31s end to end
const RACE_COVER_CAP = 24;    // covers put in the DOM per bar; more than any
                              // bar can display, so the visible result is the
                              // same while node count stays bounded

let raceFrames = [];
let raceIndex = 0;
let raceRows = new Map();     // genre -> its row element, kept across frames
                              // so transforms transition instead of redrawing

function renderHistory() {
  raceFrames = VinylHistory.buildTimeline(records);
  raceRows = new Map();
  raceIndex = 0;

  const plot = document.getElementById('racePlot');
  const scrub = document.getElementById('raceScrub');
  plot.innerHTML = '';

  if (!raceFrames.length) {
    plot.style.height = '';
    plot.innerHTML = '<p class="race-empty">nothing bought yet — records need a bought date to appear here.</p>';
    document.getElementById('raceDay').textContent = '';
    document.getElementById('raceTotal').textContent = '';
    scrub.max = '0';
    scrub.disabled = true;
    return;
  }

  // Height is fixed for the whole race at every genre that ever appears, not
  // at the current frame's bar count — sizing it to the frame would make the
  // box jump taller each time a genre enters and shove the controls down the
  // page mid-playback.
  const rows = raceFrames[raceFrames.length - 1].bars.length;
  plot.style.height = 'calc(var(--race-row-h) * ' + rows + ')';
  scrub.disabled = false;
  scrub.max = String(raceFrames.length - 1);

  racePaint(raceFrames.length - 1, false);
}

function racePaint(i, animate) {
  const frame = raceFrames[i];
  if (!frame) return;
  raceIndex = i;

  const plot = document.getElementById('racePlot');
  const lead = frame.bars.length ? frame.bars[0].count : 1;

  frame.bars.forEach(function (bar, rank) {
    let row = raceRows.get(bar.genre);
    if (!row) {
      row = document.createElement('div');
      row.className = 'race-row';
      row.dataset.genre = bar.genre;
      row.style.setProperty('--gc', genreColor(bar.genre));
      row.innerHTML =
        '<div class="race-label"></div>' +
        '<div class="race-track">' +
          '<div class="race-bar"><div class="race-covers"></div></div>' +
          '<span class="race-count"></span>' +
        '</div>';
      row.querySelector('.race-label').textContent = bar.label;
      plot.appendChild(row);
      raceRows.set(bar.genre, row);
    }
    row.classList.remove('gone');
    row.style.transform = 'translateY(calc(var(--race-row-h) * ' + rank + '))';
    // Bars scale to the current leader, so the leader always fills the row and
    // the axis rescales as the collection grows.
    row.querySelector('.race-bar').style.width =
      Math.max(2, (bar.count / lead) * 100) + '%';
    row.querySelector('.race-count').textContent = bar.count;
    raceCovers(row.querySelector('.race-covers'), bar, animate);
  });

  // Seeking backwards can land before a genre existed — its row stays in the
  // DOM (so its covers survive) but must not be on screen.
  const present = new Set(frame.bars.map(function (b) { return b.genre; }));
  raceRows.forEach(function (row, genre) {
    if (!present.has(genre)) row.classList.add('gone');
  });

  document.getElementById('raceDay').textContent = frame.day;
  document.getElementById('raceTotal').textContent =
    frame.total + (frame.total === 1 ? ' record' : ' records');
  const scrub = document.getElementById('raceScrub');
  if (scrub.value !== String(i)) scrub.value = String(i);
}

/* Reconcile the strip against the bar's most recent covers, keyed by record
 * id. Elements are reused rather than rebuilt so each cover decodes once and
 * survives all 31 frames — rebuilding would re-decode 112 images per frame. */
function raceCovers(strip, bar, animate) {
  const want = bar.records.slice(-RACE_COVER_CAP);
  const wantIds = new Set(want.map(function (r) { return String(r.id); }));

  Array.prototype.slice.call(strip.children).forEach(function (img) {
    if (!wantIds.has(img.dataset.id)) img.remove();
  });

  want.forEach(function (r, idx) {
    let img = strip.querySelector('[data-id="' + r.id + '"]');
    if (!img) {
      img = document.createElement('img');
      img.className = 'race-cover';
      img.dataset.id = String(r.id);
      img.loading = 'lazy';
      img.alt = '';
      img.src = r.cover_data || '';
      img.title = (r.artist || 'unknown') + ' – ' + (r.album_name || 'untitled');
    }
    // Only touch the DOM when the element is actually out of place: seeking
    // backwards past the cap and forward again can re-admit a cover that must
    // land at the front, but a plain re-append every frame churns the strip.
    if (strip.children[idx] !== img) {
      strip.insertBefore(img, strip.children[idx] || null);
    }
  });
}
```

- [ ] **Step 3: Verify in the browser**

Run: `.venv/bin/python app.py` and open the History tab.

Check:
- 11 rows, MPB & Samba on top at 34 with a full-width bar, Reggae last at 1.
- Every row's counts match the Statistics tab's "records by genre" chart exactly.
- Each bar is tinted with that genre's colour and carries a left edge in the full hue — the same hues as the collection cards.
- Covers fill each bar right-aligned, clipped at the left with a soft fade, the count sitting outside the bar's right end.
- The date reads `2026-08-01`, the header reads `112 records`.
- No console errors. Toggle the theme — the chart repaints in the light palette.
- Under 760px the rows shrink and nothing overflows horizontally.

- [ ] **Step 4: Run the suite and commit**

Run: `.venv/bin/python -m pytest -q` — expected: all pass

```bash
git add templates/index.html
git commit -m "Render the race chart's rows, bars and cover strips

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LdqMmBP3P43FfxMcuuPgMQ"
```

---

### Task 5: Playback — play, pause, autoplay, replay

The chart moves. Frames advance on a `setTimeout` chain; every visual is interpolated by the CSS transitions already in place from Task 4.

**Files:**
- Modify: `templates/index.html` — `renderHistory`, the `racePause` stub, `bindEvents`

**Interfaces:**
- Consumes: `racePaint(i, animate)` and `raceFrames` from Task 4.
- Produces: `racePlaying` / `raceSpeed` / `raceTimer` globals, `raceFrameMs()`, `raceApplyDuration()`, `raceReducedMotion()`, `raceSnapTo(i)`, `racePlay()`, `racePause()`, `raceSeek(i)`, `raceReplay()`, `raceSyncControls()`. Task 6 calls `raceSeek` and adds `raceSetSpeed`; Task 8 calls `racePause`.

- [ ] **Step 1: Replace the `racePause` stub with the controller**

Replace `function racePause() {}` with:

```js
let racePlaying = false;
let raceSpeed = 1;
let raceTimer = null;

function raceReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function raceFrameMs() { return RACE_BASE_MS / raceSpeed; }

/* The transition duration equals the frame interval, so each day's growth
 * takes exactly as long as the day is on screen — that is what makes it read
 * as one continuous race rather than a slideshow. Set inline rather than in
 * the stylesheet because the scrubber has to override it to 0 while dragging,
 * and an inline value cannot be beaten by a class. */
function raceApplyDuration() {
  document.getElementById('racePlot').style.setProperty(
    '--race-dur', (raceReducedMotion() ? 0 : raceFrameMs()) + 'ms');
}

/* Jump to a frame without sliding there. Replaying from the end would
 * otherwise run every bar backwards for a full second before the race
 * restarts on top of it. Restoring the duration has to wait for a reflow,
 * or the browser coalesces both writes and animates anyway. */
function raceSnapTo(i) {
  const plot = document.getElementById('racePlot');
  plot.style.setProperty('--race-dur', '0ms');
  racePaint(i, false);
  void plot.offsetWidth;
  raceApplyDuration();
}

function raceSchedule() {
  clearTimeout(raceTimer);
  raceTimer = setTimeout(function () {
    if (!racePlaying) return;
    if (raceIndex >= raceFrames.length - 1) { racePause(); return; }
    racePaint(raceIndex + 1, true);
    raceSchedule();
  }, raceFrameMs());
}

function racePlay() {
  if (!raceFrames.length) return;
  if (raceIndex >= raceFrames.length - 1) raceSnapTo(0);
  racePlaying = true;
  raceApplyDuration();
  raceSyncControls();
  raceSchedule();
}

/* Clears the timer and nothing else. The day in flight finishes settling —
 * pause stops the race advancing, it does not freeze a bar mid-slide. */
function racePause() {
  racePlaying = false;
  clearTimeout(raceTimer);
  raceTimer = null;
  raceSyncControls();
}

function raceSeek(i) {
  if (!raceFrames.length) return;
  raceSnapTo(Math.max(0, Math.min(raceFrames.length - 1, i)));
  raceSyncControls();
}

function raceReplay() { raceSnapTo(0); racePlay(); }

function raceSyncControls() {
  const btn = document.getElementById('racePlayBtn');
  btn.innerHTML = racePlaying ? '<i class="ti ti-player-pause"></i>'
                              : '<i class="ti ti-player-play"></i>';
  btn.setAttribute('aria-pressed', racePlaying ? 'true' : 'false');
  btn.setAttribute('aria-label', racePlaying ? 'pause' : 'play');
  const atEnd = raceFrames.length > 0 && raceIndex >= raceFrames.length - 1;
  document.getElementById('raceReplayBtn').classList.toggle('hidden', !atEnd || racePlaying);
  document.querySelectorAll('.race-speed-btn').forEach(function (b) {
    b.classList.toggle('active', Number(b.dataset.speed) === raceSpeed);
  });
}
```

- [ ] **Step 2: Autoplay from the start on entering the tab**

In `renderHistory`, replace the final line `racePaint(raceFrames.length - 1, false);` with the following. Note it now enters on frame 0 rather than the last, so Task 4's static final-frame view is replaced by the race:

```js
  raceApplyDuration();
  // Reduced motion opens on the finished chart instead — a statistic, not a
  // race. Everything still works; you just start it yourself.
  if (raceReducedMotion()) { raceSnapTo(raceFrames.length - 1); raceSyncControls(); }
  else { raceSnapTo(0); racePlay(); }
```

And in the empty-collection branch, before `return;`, add:

```js
    racePause();
```

- [ ] **Step 3: Bind the buttons**

In `bindEvents`, after the `tabHistory` line from Task 3, add:

```js
  document.getElementById('racePlayBtn').addEventListener('click', () => {
    racePlaying ? racePause() : racePlay();
  });
  document.getElementById('raceReplayBtn').addEventListener('click', raceReplay);
```

- [ ] **Step 4: Verify in the browser**

Run: `.venv/bin/python app.py`, open History.

Check:
- It autoplays from `2024-05-31`, three bars, and runs to `2026-08-01` in roughly 31 seconds.
- Bars grow smoothly and rows slide past each other on real overtakes — no jitter on level stretches.
- The header count climbs 3 → 112 as it runs.
- Pause mid-race: advancing stops, and the day in flight finishes settling rather than freezing halfway.
- Resume continues from where it stopped.
- At the end the play button becomes a replay button; pressing it restarts from the first frame.
- Switch to Collection mid-race, wait, come back: it restarts from the beginning and the old timer is gone (the day does not jump forward while you were away).
- In devtools, emulate `prefers-reduced-motion: reduce` and reload: History opens on the finished chart, paused, and pressing play still works.

- [ ] **Step 5: Run the suite and commit**

Run: `.venv/bin/python -m pytest -q` — expected: all pass

```bash
git add templates/index.html
git commit -m "Play the race: frame chain, pause, autoplay and replay

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LdqMmBP3P43FfxMcuuPgMQ"
```

---

### Task 6: Scrubber and speed

**Files:**
- Modify: `templates/index.html` — `bindEvents`, and one new function beside the controller

**Interfaces:**
- Consumes: `raceSeek(i)` (which already snaps via `raceSnapTo`), `racePause()`, `raceApplyDuration()`, `raceSchedule()`, `racePlaying`, `raceSpeed` from Task 5.
- Produces: `raceSetSpeed(s)`.

- [ ] **Step 1: Add the speed function**

Dragging needs no special casing: `raceSeek` goes through `raceSnapTo`, which
already zeroes the duration for the paint and restores it after, so the chart
tracks the thumb instead of chasing it a second behind.

After `raceSyncControls`, add:

```js
function raceSetSpeed(s) {
  raceSpeed = s;
  raceApplyDuration();
  raceSyncControls();
  if (racePlaying) raceSchedule();   // the change applies from the next frame
}
```

- [ ] **Step 2: Bind the scrubber and the speed buttons**

In `bindEvents`, after the replay button binding, add:

```js
  const raceScrub = document.getElementById('raceScrub');
  raceScrub.addEventListener('input', () => {
    racePause();
    raceSeek(Number(raceScrub.value));
  });
  document.querySelectorAll('.race-speed-btn').forEach(b => {
    b.addEventListener('click', () => raceSetSpeed(Number(b.dataset.speed)));
  });
```

- [ ] **Step 3: Verify in the browser**

Run: `.venv/bin/python app.py`, open History.

Check:
- Dragging the scrubber pauses playback and the chart snaps frame to frame, tracking the thumb with no lag, in both directions.
- Scrubbing back to the first frame shows exactly three bars — genres that had not yet appeared are gone, not sitting at zero.
- Scrubbing far back then forward again leaves each bar's covers in chronological order with the newest at the tip.
- Releasing the scrubber and pressing play resumes from that day with motion restored.
- Pressing 2× mid-race visibly doubles the pace from the next frame; 0.5× halves it; the active chip is highlighted.
- The scrubber is keyboard-operable — tab to it, arrow keys step days.

- [ ] **Step 4: Run the suite and commit**

Run: `.venv/bin/python -m pytest -q` — expected: all pass

```bash
git add templates/index.html
git commit -m "Add the scrubber and speed control to the race

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LdqMmBP3P43FfxMcuuPgMQ"
```

---

### Task 7: The cover fly-in

The covers arrive rather than appear. This is the feature's whole point, and it is one CSS keyframe plus four lines in `raceCovers`.

**Files:**
- Modify: `templates/index.html` — the history CSS block and `raceCovers`

**Interfaces:**
- Consumes: `raceCovers(strip, bar, animate)` and the `animate` flag threaded through `racePaint` from Task 4; `bar.added` from Task 1.
- Produces: no new functions.

- [ ] **Step 1: Add the keyframe**

In the history CSS block, after the `.race-cover` rules, add:

```css
/* A cover flies in at the bar's growing tip. Five arrivals — the busiest
   genre-day in the collection — stagger over 240ms, comfortably inside a
   1000ms frame at 1×. */
@keyframes raceIn{
  from{opacity:0;transform:translateX(18px) scale(1.35)}
  to{opacity:1;transform:none}
}
.race-cover.new{animation:raceIn 420ms ease-out both;
  animation-delay:calc(var(--i) * 60ms)}
@media(prefers-reduced-motion:reduce){
  .race-cover.new{animation:none}
}
```

- [ ] **Step 2: Mark this day's arrivals in `raceCovers`**

Replace the body of `raceCovers` with:

```js
function raceCovers(strip, bar, animate) {
  const want = bar.records.slice(-RACE_COVER_CAP);
  const wantIds = new Set(want.map(function (r) { return String(r.id); }));
  const arriving = new Set(
    animate ? bar.added.map(function (r) { return String(r.id); }) : []);

  Array.prototype.slice.call(strip.children).forEach(function (img) {
    if (!wantIds.has(img.dataset.id)) img.remove();
  });

  let stagger = 0;
  want.forEach(function (r, idx) {
    let img = strip.querySelector('[data-id="' + r.id + '"]');
    if (!img) {
      img = document.createElement('img');
      img.className = 'race-cover';
      img.dataset.id = String(r.id);
      img.loading = 'lazy';
      img.alt = '';
      img.src = r.cover_data || '';
      img.title = (r.artist || 'unknown') + ' – ' + (r.album_name || 'untitled');
    }
    if (strip.children[idx] !== img) {
      strip.insertBefore(img, strip.children[idx] || null);
    }
    // Re-adding the class only restarts the animation after the browser has
    // seen it removed, hence the forced reflow between the two.
    img.classList.remove('new');
    if (arriving.has(String(r.id))) {
      img.style.setProperty('--i', stagger++);
      void img.offsetWidth;
      img.classList.add('new');
    }
  });
}
```

- [ ] **Step 3: Verify in the browser**

Run: `.venv/bin/python app.py`, open History.

Check:
- On each frame, only that day's new covers animate — they scale down and slide left into the bar's tip. Covers already on the bar sit still.
- The 2026-01-27 frame (13 records across several genres) staggers its arrivals rather than popping them all at once.
- Scrubbing does **not** animate covers — seek to a day and nothing flies.
- Under `prefers-reduced-motion: reduce`, no covers fly at any point.
- Let it run twice via replay: the second pass animates the same way, with no covers stuck mid-animation.

- [ ] **Step 4: Run the suite and commit**

Run: `.venv/bin/python -m pytest -q` — expected: all pass

```bash
git add templates/index.html
git commit -m "Fly the day's covers into the bar as they are bought

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LdqMmBP3P43FfxMcuuPgMQ"
```

---

### Task 8: Interaction, and the manual verification doc

Clicking through to a record, and the hover tooltip. Then the checks that no unit test can make.

**Files:**
- Modify: `templates/index.html` — `bindEvents`
- Create: `docs/history-tab-manual-verification.md`

**Interfaces:**
- Consumes: `openDetail(id)` (`templates/index.html:2445`), `chartTooltipHTML(title, recs, cap)` (`templates/index.html:4187`), `racePause()`, `raceFrames`, `raceIndex`.
- Produces: nothing further consumes this task.

- [ ] **Step 1: Bind delegated click and hover**

In `bindEvents`, after the speed-button binding, add:

```js
  // Delegated, so it survives rows and covers being created and removed as
  // the race runs. A cover click both pauses and opens — pausing before a
  // record opens is what you want anyway.
  const racePlot = document.getElementById('racePlot');
  racePlot.addEventListener('click', e => {
    const cover = e.target.closest('.race-cover');
    if (cover) { racePause(); openDetail(Number(cover.dataset.id)); return; }
    if (e.target.closest('.race-bar')) racePause();
  });
  racePlot.addEventListener('mousemove', e => {
    const tip = document.getElementById('raceTooltip');
    const row = e.target.closest('.race-row');
    const frame = raceFrames[raceIndex];
    const bar = row && frame &&
      frame.bars.find(b => b.genre === row.dataset.genre);
    if (!bar || !e.target.closest('.race-bar')) { tip.style.opacity = 0; return; }
    // Newest first — the tooltip answers "what is in this bar", and the most
    // recent arrivals are what you just watched land.
    tip.innerHTML = chartTooltipHTML(bar.label, bar.records.slice().reverse(), 12);
    const box = tip.offsetParent.getBoundingClientRect();
    tip.style.left = (e.clientX - box.left + 14) + 'px';
    tip.style.top  = (e.clientY - box.top + 14) + 'px';
    tip.style.opacity = 1;
  });
  racePlot.addEventListener('mouseleave', () => {
    document.getElementById('raceTooltip').style.opacity = 0;
  });
```

- [ ] **Step 2: Verify in the browser**

Run: `.venv/bin/python app.py`, open History.

Check:
- Hovering a bar shows a tooltip with the genre, its count, and up to 12 records newest first, styled like the year chart's tooltip.
- Moving off the plot hides the tooltip.
- Clicking a bar pauses the race.
- Clicking a cover pauses **and** opens that record's detail — and it is the right record.
- Closing the detail leaves the race paused on the same day, not restarted.

- [ ] **Step 3: Write the manual verification doc**

Create `docs/history-tab-manual-verification.md`:

```markdown
# History Tab — Manual Verification

The timeline builder is unit-tested (`tests/test_history.js`). The animation
is not, and cannot be. Run this list against `.venv/bin/python app.py` after
any change to the race chart.

Expected shape of the live collection: **31 frames**, `2024-05-31` →
`2026-08-01`, **112 records**, **11 genres**, leader MPB & Samba at **34**,
opening frame exactly three bars (Easy Listening, Folk, Soul & Funk).

## Correctness

- [ ] The final frame's per-genre counts equal the Statistics tab's "records
      by genre" chart, genre for genre.
- [ ] The header total ends at `112 records` and climbs from `3` as it runs.
- [ ] Every bar carries its genre's colour from the collection cards.
- [ ] No wishlist record ever appears.

## Motion

- [ ] Opening the tab autoplays from the first frame.
- [ ] Bars grow smoothly; rows slide on overtakes.
- [ ] Level genres do **not** trade rows — a swap on screen always follows a
      count actually passing another.
- [ ] Only the current day's covers animate; the rest sit still.
- [ ] The 2026-01-27 frame staggers its arrivals rather than popping them
      together.

## Controls

- [ ] Pause stops the advance; the day in flight finishes settling.
- [ ] Resume continues from the paused day.
- [ ] Scrubbing snaps frame to frame with no lag, both directions.
- [ ] Scrubbing to frame 0 shows exactly three bars.
- [ ] Scrubbing far back then forward leaves covers in chronological order.
- [ ] 0.5× / 1× / 2× change the pace from the next frame; the active chip lights.
- [ ] Replay appears only at the end and restarts from the first frame.

## Around the edges

- [ ] Toggling the theme mid-race repaints in the new palette.
- [ ] Leaving the tab mid-race and returning restarts cleanly, with no timer
      left running (the day must not have advanced while you were away).
- [ ] Clicking a cover pauses and opens the right record; closing the detail
      leaves the race paused on the same day.
- [ ] Under 760px: the bottom bar still has four items, the stats/history
      segment switches between the two pages, the Stats item stays lit on
      History, and nothing scrolls sideways.
- [ ] With `prefers-reduced-motion: reduce`, the tab opens on the finished
      chart, paused, no covers fly, and play still works.
- [ ] Console is clean throughout.
```

- [ ] **Step 4: Walk the doc**

Work through every checkbox in `docs/history-tab-manual-verification.md`
against the running app. Fix anything that fails before committing.

- [ ] **Step 5: Run the suite and commit**

Run: `.venv/bin/python -m pytest -q` — expected: all pass

```bash
git add templates/index.html docs/history-tab-manual-verification.md
git commit -m "Click a cover to open its record, hover a bar to see what is in it

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LdqMmBP3P43FfxMcuuPgMQ"
```
