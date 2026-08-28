# History Tab Shared Clock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the History tab's two independent playback engines with one calendar clock, one playhead and one transport pinned to the bottom of the tab.

**Architecture:** A new pure builder in `static/activity.js` turns the day-indexed model into a weight table — empty days cost almost nothing, event days cost 1, purchase days cost 6 — and two binary-search lookups convert between wall-clock progress and calendar day. The renderer's `hist*` transport advances progress on `requestAnimationFrame`, derives the day, and paints both charts from it. The playhead's position stays linear in calendar time; only the rate of travel varies.

**Tech Stack:** Vanilla ES5-flavoured browser JS (no build step), CSS custom properties and transitions, `node:test` wrapped by pytest, Flask/Jinja for the single template.

**Spec:** `docs/superpowers/specs/2026-08-28-history-shared-clock-design.md`

## Global Constraints

- **No build step.** Plain `<script src>` tags, no bundler, no ES modules in the browser. `static/activity.js` keeps its IIFE-with-`module.exports`-tail wrapper.
- **No new dependency, no Python change, no schema change.**
- **Weight constants, exact values:** `CLOCK_W_BUY = 6`, `CLOCK_W_EVENT = 1`, `CLOCK_W_EMPTY = 0.04`.
- **Timing constants, exact values:** `HIST_TOTAL_MS = 30000`, `HIST_DUR_MIN = 120`, `HIST_DUR_MAX = 900`.
- **A day that is both a purchase day and an event day weighs `CLOCK_W_BUY`, not the sum.**
- **The axis never warps.** Only the rate of travel varies. No mark, tick, lane or week column changes position as a result of this work.
- **`TZ` is pinned** to `America/Sao_Paulo` at the top of `tests/test_activity.js`, before any `Date` is constructed.
- **The float epsilon for weight assertions is `1e-9`.** `CLOCK_W_EMPTY` is not exactly representable in binary; never assert accumulated weights with `strictEqual`.
- **One reduced-motion helper.** `raceReducedMotion()` and `actReducedMotion()` both exist today; they collapse into `histReducedMotion()`.

## File Structure

| File | Responsibility |
|---|---|
| `static/activity.js` **(modify)** | The pure clock: `buildClock`, `dayAtProgress`, `progressAtDay`, three weight constants. |
| `tests/test_activity.js` **(modify)** | `node:test` coverage for the clock, added to the existing 26 tests. |
| `templates/index.html` **(modify)** | The `hist*` transport replacing both engines; the race chart driven by day; the transport markup moved and pinned; the sticky CSS. |
| `docs/history-tab-manual-verification.md` **(modify)** | Shared-clock checks, which the animation cannot get from unit tests. |

---

### Task 1: The weight table

**Files:**
- Modify: `static/activity.js`
- Modify: `tests/test_activity.js`

**Interfaces:**
- Consumes: `buildActivity(records)` → `{d0, span, lanes:[{bought, plays, cleans, notes}], ...}`, already in the module.
- Produces: `VinylActivity.buildClock(act)` → `{cum: [Number], total: Number}` or `null`. `cum` has length `span + 1`, starts at 0, is monotonically non-decreasing, and `cum[span] === total`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_activity.js`:

```js
// ── the clock ───────────────────────────────────────────────────────────────

// CLOCK_W_EMPTY is 0.04, which binary floats cannot hold exactly, so weights
// are compared with a tolerance rather than strictEqual.
const near = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-9,
  (msg || '') + ' expected ' + b + ', got ' + a);
const weightOf = (clock, d) => clock.cum[d + 1] - clock.cum[d];

test('no model means no clock', () => {
  assert.strictEqual(buildClock(null), null);
});

test('the table runs one longer than the axis and starts at zero', () => {
  const a = buildClock(buildActivity([rec({ bought_date: '2026-01-01',
    play_dates: plays('2026-01-05') })]));
  assert.strictEqual(a.cum.length, 6);       // span 5, plus the closing edge
  assert.strictEqual(a.cum[0], 0);
  assert.strictEqual(a.total, a.cum[a.cum.length - 1]);
});

test('the table never decreases', () => {
  const a = buildClock(buildActivity([
    rec({ bought_date: '2026-01-01', play_dates: plays('2026-01-09') }),
  ]));
  for (let i = 1; i < a.cum.length; i++) assert.ok(a.cum[i] >= a.cum[i - 1]);
});

test('a purchase day, an event day and an empty day weigh 6, 1 and 0.04', () => {
  const a = buildClock(buildActivity([rec({
    bought_date: '2026-01-01',                 // day 0 — purchase
    play_dates: plays('2026-01-03'),           // day 2 — event
  })]));                                       // day 1 — empty
  near(weightOf(a, 0), 6,    'purchase day');
  near(weightOf(a, 1), 0.04, 'empty day');
  near(weightOf(a, 2), 1,    'event day');
});

test('a day that is both bought on and played on weighs 6, not 7', () => {
  const a = buildClock(buildActivity([rec({
    bought_date: '2026-01-01', play_dates: plays('2026-01-01'),
  })]));
  near(weightOf(a, 0), 6);
});

test('a cleaning and a note each make a day an event day', () => {
  const a = buildClock(buildActivity([rec({
    bought_date: '2026-01-01',
    cleaned_dates: plays('2026-01-03'),
    notes: JSON.stringify([{ date: '2026-01-05', text: 'n' }]),
  })]));
  near(weightOf(a, 2), 1, 'cleaning day');
  near(weightOf(a, 4), 1, 'note day');
});

test('a one-day collection still yields a usable clock', () => {
  const a = buildClock(buildActivity([rec({ bought_date: '2026-01-01' })]));
  assert.strictEqual(a.cum.length, 2);
  near(a.total, 6);
});

// The whole point of the weighting: quiet stretches must not eat the run.
test('a long empty stretch takes a small share of the clock', () => {
  // bought on day 0, played once 200 days later: 199 empty days between.
  const a = buildClock(buildActivity([rec({
    bought_date: '2026-01-01', play_dates: plays('2026-07-20'),
  })]));
  const empty = a.cum[a.cum.length - 2] - a.cum[1];   // everything between
  /* Unweighted those 199 empty days would be 99% of the run; weighted they are
     about 53%. The thresholds are deliberately loose — they exist to catch a
     weighting that has stopped working, not to pin one exact ratio. */
  assert.ok(empty / a.total < 0.70,
    'empty stretch took ' + (empty / a.total * 100).toFixed(0) + '% of the run');
  const eventful = (6 + 1) / a.total;
  assert.ok(eventful > 0.30,
    'event days took only ' + (eventful * 100).toFixed(0) + '% of the run');
});
```

Add `buildClock` to the destructured require at the top of the file:

```js
const { buildActivity, dayAt, buildClock } = require('../static/activity.js');
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test tests/test_activity.js`
Expected: FAIL — `buildClock is not a function`.

- [ ] **Step 3: Implement the builder**

In `static/activity.js`, add the constants just below `const WEEK = 7;`:

```js
  /* How much wall clock each day is worth. The axis stays linear in calendar
   * time — every mark keeps its place — but the RATE of travel varies, so a
   * run does not spend 43% of itself on the 352 empty days between this
   * collection's first purchase and its second. A purchase day is a race-chart
   * frame and must be on screen long enough for bars to visibly move; a day
   * carrying only plays or cleanings is worth seeing but cheaper; an empty day
   * passes almost for free. */
  const CLOCK_W_BUY   = 6;
  const CLOCK_W_EVENT = 1;
  const CLOCK_W_EMPTY = 0.04;
```

and the builder after `buildActivity`:

```js
  /* A running total of weight, one entry per day plus a closing edge. Because
   * it never decreases, both lookups over it are a binary search. */
  function buildClock(act) {
    if (!act) return null;
    const span = act.span;
    const buy = new Array(span).fill(false);
    const ev  = new Array(span).fill(false);
    act.lanes.forEach(function (lane) {
      buy[lane.bought] = true;
      lane.plays.forEach(function (d)  { ev[d] = true; });
      lane.cleans.forEach(function (d) { ev[d] = true; });
      lane.notes.forEach(function (d)  { ev[d] = true; });
    });
    const cum = new Array(span + 1);
    cum[0] = 0;
    for (let d = 0; d < span; d++) {
      /* bought wins outright — a day you bought and played on is still one
       * race frame, and paying for both would give it seven days' worth of
       * screen time for one transition. */
      cum[d + 1] = cum[d] + (buy[d] ? CLOCK_W_BUY
                          : ev[d]  ? CLOCK_W_EVENT
                          :          CLOCK_W_EMPTY);
    }
    return { cum: cum, total: cum[span] };
  }
```

Add it to the module's return: `return { buildActivity: buildActivity, dayAt: dayAt, buildClock: buildClock };`

- [ ] **Step 4: Run the tests**

Run: `node --test tests/test_activity.js`
Expected: PASS, 34/34.

- [ ] **Step 5: Run the whole suite and commit**

Run: `.venv/bin/python -m pytest -q` — use `.venv/bin/python`; the venv's console scripts carry a stale shebang and system `python3` has no pytest. Expected: 124 passed.

```bash
git add static/activity.js tests/test_activity.js
git commit -m "Weight each day by how much happens on it"
```

---

### Task 2: Progress and day, in both directions

**Files:**
- Modify: `static/activity.js`
- Modify: `tests/test_activity.js`

**Interfaces:**
- Consumes: `buildClock(act)` → `{cum, total}` from Task 1.
- Produces: `VinylActivity.dayAtProgress(clock, p)` → fractional day, and `VinylActivity.progressAtDay(clock, day)` → weight units. Both clamp out-of-range input; neither throws or returns `NaN`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_activity.js`:

```js
// ── progress <-> day ────────────────────────────────────────────────────────

const clockOf = recs => buildClock(buildActivity(recs));

test('zero progress is day zero and full progress is the last day', () => {
  const c = clockOf([rec({ bought_date: '2026-01-01',
    play_dates: plays('2026-01-05') })]);
  assert.strictEqual(dayAtProgress(c, 0), 0);
  assert.strictEqual(dayAtProgress(c, c.total), 4);
});

test('progress and day round-trip at every day boundary', () => {
  const c = clockOf([rec({ bought_date: '2026-01-01',
    play_dates: plays('2026-01-04', '2026-01-09') })]);
  for (let d = 0; d < c.cum.length - 1; d++) {
    assert.strictEqual(dayAtProgress(c, progressAtDay(c, d)), d, 'day ' + d);
  }
});

test('progress interpolates inside a day so the playhead glides', () => {
  const c = clockOf([rec({ bought_date: '2026-01-01',
    play_dates: plays('2026-01-03') })]);
  const half = progressAtDay(c, 1) + (progressAtDay(c, 2) - progressAtDay(c, 1)) / 2;
  const d = dayAtProgress(c, half);
  assert.ok(d > 1 && d < 2, 'expected a fractional day, got ' + d);
});

test('an empty day costs far less progress than a purchase day', () => {
  const c = clockOf([rec({ bought_date: '2026-01-01',
    play_dates: plays('2026-01-05') })]);
  const buy   = progressAtDay(c, 1) - progressAtDay(c, 0);
  const empty = progressAtDay(c, 2) - progressAtDay(c, 1);
  assert.ok(buy > empty * 100, 'buy ' + buy + ' vs empty ' + empty);
});

test('out-of-range input clamps instead of throwing or going NaN', () => {
  const c = clockOf([rec({ bought_date: '2026-01-01',
    play_dates: plays('2026-01-05') })]);
  assert.strictEqual(dayAtProgress(c, -5), 0);
  assert.strictEqual(dayAtProgress(c, c.total * 10), 4);
  assert.strictEqual(dayAtProgress(c, NaN), 0);
  assert.strictEqual(progressAtDay(c, -5), 0);
  assert.strictEqual(progressAtDay(c, 999), c.cum[4]);
});

test('a null clock answers zero rather than throwing', () => {
  assert.strictEqual(dayAtProgress(null, 5), 0);
  assert.strictEqual(progressAtDay(null, 5), 0);
});
```

Extend the require: `const { buildActivity, dayAt, buildClock, dayAtProgress, progressAtDay } = require('../static/activity.js');`

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test tests/test_activity.js`
Expected: FAIL — `dayAtProgress is not a function`.

- [ ] **Step 3: Implement both lookups**

In `static/activity.js`, after `buildClock`:

```js
  /* The largest day whose running total has not yet passed p, plus the
   * fraction of the way through that day — so the playhead glides rather than
   * stepping from day to day. */
  function dayAtProgress(clock, p) {
    if (!clock) return 0;
    const last = clock.cum.length - 2;
    if (!(p > 0)) return 0;                 // also catches NaN
    if (p >= clock.total) return last;
    let lo = 0, hi = last;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (clock.cum[mid] <= p) lo = mid; else hi = mid - 1;
    }
    const w = clock.cum[lo + 1] - clock.cum[lo];
    return lo + (w > 0 ? (p - clock.cum[lo]) / w : 0);
  }

  /* The inverse, so a seek in calendar days lands on the right progress. */
  function progressAtDay(clock, day) {
    if (!clock) return 0;
    const last = clock.cum.length - 2;
    const d = Math.max(0, Math.min(last, Math.floor(day) || 0));
    const frac = Math.max(0, Math.min(1, (day - d) || 0));
    return clock.cum[d] + (clock.cum[d + 1] - clock.cum[d]) * frac;
  }
```

Extend the module's return to `{ buildActivity, dayAt, buildClock, dayAtProgress, progressAtDay }` (written out longhand in the file's existing style).

- [ ] **Step 4: Run the tests**

Run: `node --test tests/test_activity.js`
Expected: PASS, 40/40.

- [ ] **Step 5: Check the clock against the live collection**

```bash
.venv/bin/python - <<'PY'
import json, sqlite3
db = sqlite3.connect('instance/vinyl.db'); db.row_factory = sqlite3.Row
recs = [dict(r) for r in db.execute("select * from record")]
for r in recs: r['have_it'] = bool(r['have_it']); r['cover_data'] = ''
open('/tmp/claude-1000/recs.json','w').write(json.dumps(recs))
PY
node -e "
process.env.TZ='America/Sao_Paulo';
const A=require('./static/activity.js');
const a=A.buildActivity(JSON.parse(require('fs').readFileSync('/tmp/claude-1000/recs.json','utf8')));
const c=A.buildClock(a);
const ms=30000/c.total;
const buyDays=[...new Set(a.lanes.map(l=>l.bought))].sort((x,y)=>x-y);
const per=buyDays.map(d=>(c.cum[d+1]-c.cum[d])*ms);
const gap=(A.progressAtDay(c,buyDays[1])-A.progressAtDay(c,buyDays[0]+1))*ms/1000;
console.log('total weight', c.total.toFixed(1));
console.log('purchase transition ms:', Math.round(Math.min(...per)));
console.log('352-day gap seconds   :', gap.toFixed(1));
"
```

Expected: purchase transition ≈ **465ms**, the gap ≈ **1.8s**. These are the spec's headline numbers; a large deviation means a weight was mistyped.

- [ ] **Step 6: Run the whole suite and commit**

Run: `.venv/bin/python -m pytest -q` → 124 passed.

```bash
git add static/activity.js tests/test_activity.js
git commit -m "Map wall-clock progress onto calendar days, and back"
```

---

### Task 3: One transport driving both charts

**Files:**
- Modify: `templates/index.html`

**Interfaces:**
- Consumes: `VinylActivity.buildClock/dayAtProgress/progressAtDay/dayAt`, `buildActivity`; the existing `racePaint(i, animate)`, `raceFrames[].day` (a `'YYYY-MM-DD'` string), `actPaint()`, `actPos`, `actLast()`, `actClamp(v,a,b)`, `actMeasure()`, `renderActivity()`.
- Produces: `histPlay() histPause() histSeek(day, seeking) histReplay() histSyncControls() histPaint(seeking) histTick(t) histSetSpeed(s) histReducedMotion() raceBuildFrameMap() raceApplyDuration(f)`, and state `histClock histProgress histSpeed histPlaying histRaf histLastT histFrameShown raceFrameOfDay raceFrameDay`.

**Note:** the activity chart's transport *markup* is left in place by this task and simply stops being wired up. Task 4 removes it. Splitting it this way means the app is fully working at the end of this task — one clock, both charts — with one dead control row still on screen.

- [ ] **Step 1: Delete the two old playback engines**

In `templates/index.html`, delete these whole functions and variables:

- `let racePlaying`, `let raceSpeed`, `let raceTimer`
- `raceReducedMotion()`, `raceFrameMs()`, `raceSchedule()`, `racePlay()`, `racePause()`, `raceSeek()`, `raceReplay()`, `raceSyncControls()`, `raceSetSpeed()`
- the `RACE_BASE_MS` constant
- `let actPlaying, actRaf, actLastT, actSpeed`
- `actReducedMotion()`, `actRate()`, `actSeek()`, `actTick()`, `actPlay()`, `actPause()`, `actReplay()`, `actSyncControls()`

Keep `raceSnapTo()` and `raceApplyDuration()` — both are rewritten below. Keep `racePaint()`, `actPaint()` and everything else untouched.

- [ ] **Step 2: Add the shared transport**

Where the race transport used to be, add:

```js
// ── history: one clock for both charts ─────────────────────────────────────
const HIST_TOTAL_MS = 30000;   // the whole timeline at 1x
const HIST_DUR_MIN  = 120;     // floor and ceiling for the race chart's bar
const HIST_DUR_MAX  = 900;     // growth, because the gaps are wildly uneven

let histClock = null;
let histProgress = 0;          // in weight units, not days
let histSpeed = 1;
let histPlaying = false;
let histRaf = 0;
let histLastT = 0;
let histFrameShown = -2;       // -2 so the first paint always writes
let raceFrameOfDay = [];       // day index -> race frame index, -1 before day one
let raceFrameDay = [];         // race frame index -> day index

function histReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/* Which frame the race chart shows on each day, and which day each frame
 * begins on. Built once per render rather than searched per frame: at 60fps
 * for thirty seconds a search would run eighteen hundred times for an answer
 * that never changes. */
function raceBuildFrameMap() {
  raceFrameOfDay = []; raceFrameDay = [];
  if (!act || !raceFrames.length) return;
  let f = -1;
  for (let d = 0; d < act.span; d++) {
    const iso = VinylActivity.dayAt(act.d0, d);
    while (f + 1 < raceFrames.length && raceFrames[f + 1].day <= iso) {
      f++; raceFrameDay[f] = d;
    }
    raceFrameOfDay[d] = f;
  }
}

/* The bars grow for exactly as long as the frame is on screen, which is what
 * makes the race read as one continuous move rather than a slideshow. Under
 * one clock that span is the wall-clock time until the NEXT purchase, and the
 * gaps run from one day to three hundred and fifty-two — hence the clamp. */
function raceApplyDuration(f) {
  let ms = HIST_DUR_MAX;
  if (histClock && f >= 0 && f + 1 < raceFrameDay.length) {
    const msPerUnit = HIST_TOTAL_MS / histClock.total / histSpeed;
    ms = actClamp(
      (VinylActivity.progressAtDay(histClock, raceFrameDay[f + 1]) -
       VinylActivity.progressAtDay(histClock, raceFrameDay[f])) * msPerUnit,
      HIST_DUR_MIN, HIST_DUR_MAX);
  }
  document.getElementById('racePlot').style.setProperty(
    '--race-dur', (histReducedMotion() ? 0 : ms) + 'ms');
}

/* Jump to a frame without sliding there. Replaying from the end would
 * otherwise run every bar backwards before the race restarts on top of it.
 * Restoring the duration has to wait for a reflow, or the browser coalesces
 * both writes and animates anyway. */
function raceSnapTo(f) {
  const plot = document.getElementById('racePlot');
  plot.style.setProperty('--race-dur', '0ms');
  racePaint(f, false);
  void plot.offsetWidth;
  raceApplyDuration(f);
}

/* One paint drives both charts from one day. */
function histPaint(seeking) {
  if (!act) return;
  const day = Math.min(actLast(), Math.floor(actPos));

  const f = raceFrames.length && raceFrameOfDay[day] !== undefined
    ? raceFrameOfDay[day] : -1;
  if (f !== histFrameShown) {
    histFrameShown = f;
    if (f >= 0) {
      if (seeking) raceSnapTo(f);
      else { raceApplyDuration(f); racePaint(f, true); }
    }
  }
  /* The date belongs to the playhead, not to the frame. Between purchases the
   * frame's own day can be up to fifty-six days behind. */
  const dayEl = document.getElementById('raceDay');
  const iso = VinylActivity.dayAt(act.d0, day);
  if (dayEl.textContent !== iso) dayEl.textContent = iso;

  actPaint();
}

function histSeek(day, seeking) {
  if (!act) return;
  actPos = actClamp(day, 0, actLast());
  histProgress = VinylActivity.progressAtDay(histClock, actPos);
  const scrub = document.getElementById('raceScrub');
  if (Number(scrub.value) !== Math.round(actPos)) scrub.value = Math.round(actPos);
  histPaint(seeking);
}

function histTick(t) {
  if (!histPlaying) return;
  if (!histLastT) histLastT = t;
  const dt = Math.min(0.12, (t - histLastT) / 1000);
  histLastT = t;
  histProgress += histClock.total / (HIST_TOTAL_MS / 1000) * histSpeed * dt;
  if (histProgress >= histClock.total) {
    histSeek(actLast());
    histPause();
    return;
  }
  histSeek(VinylActivity.dayAtProgress(histClock, histProgress));
  histRaf = requestAnimationFrame(histTick);
}

function histPlay() {
  if (!act || histPlaying) return;
  if (actPos >= actLast()) histSeek(0, true);
  histPlaying = true;
  histLastT = 0;
  histSyncControls();
  histRaf = requestAnimationFrame(histTick);
}

function histPause() {
  histPlaying = false;
  cancelAnimationFrame(histRaf);
  histRaf = 0;
  histSyncControls();
}

function histReplay() { histSeek(0, true); histPlay(); }

function histSyncControls() {
  const btn = document.getElementById('racePlayBtn');
  btn.innerHTML = histPlaying ? '<i class="ti ti-player-pause"></i>'
                              : '<i class="ti ti-player-play"></i>';
  btn.setAttribute('aria-pressed', histPlaying ? 'true' : 'false');
  btn.setAttribute('aria-label', histPlaying ? 'pause' : 'play');
  const atEnd = !!act && actPos >= actLast();
  document.getElementById('raceReplayBtn').classList.toggle('hidden', !atEnd || histPlaying);
  btn.classList.toggle('hidden', atEnd && !histPlaying);
  document.querySelectorAll('.race-speed-btn').forEach(function (b) {
    b.classList.toggle('active', Number(b.dataset.speed) === histSpeed);
  });
}

function histSetSpeed(s) {
  histSpeed = s;
  histSyncControls();
  /* the new rate applies from the next frame; nothing else needs restarting
     because the clock advances by elapsed time, not by a fixed interval */
}
```

- [ ] **Step 3: Point the callers at the shared transport**

Three edits.

**`renderActivity()`** — strip its playback tail. Delete the `actPause();` first statement and the closing block:

```js
  if (actReducedMotion()) { actSeek(actLast()); actPause(); }
  else { actSeek(0); actPlay(); }
```

so the function ends at `actSetVisible(21);`. It renders; it no longer plays.

**`renderHistory()`** — becomes the one place playback starts. Replace the whole function with:

```js
function renderHistory() {
  histPause();
  renderActivity();                          // builds `act`, the band and the lanes
  raceFrames = VinylHistory.buildTimeline(records);
  raceRows = new Map();
  raceIndex = 0;
  histFrameShown = -2;

  const plot = document.getElementById('racePlot');
  const scrub = document.getElementById('raceScrub');
  plot.innerHTML = '';

  if (!raceFrames.length) {
    plot.style.height = '';
    plot.innerHTML = '<p class="race-empty">nothing bought yet — records need a bought date to appear here.</p>';
    document.getElementById('raceDay').textContent = '';
    document.getElementById('raceTotal').textContent = '';
  } else {
    // Height is fixed at every genre that ever appears, not at the current
    // frame's bar count — sizing it to the frame would make the box jump
    // taller each time a genre enters and shove the page around mid-playback.
    plot.style.height = 'calc(var(--race-row-h) * ' +
      raceFrames[raceFrames.length - 1].bars.length + ')';
  }

  histClock = VinylActivity.buildClock(act);
  raceBuildFrameMap();
  scrub.disabled = !act;
  scrub.max = act ? String(actLast()) : '0';
  if (!act) { histSyncControls(); return; }

  // Reduced motion opens on the finished chart instead — a statistic, not a
  // replay. Everything still works; you just start it yourself.
  if (histReducedMotion()) { histSeek(actLast(), true); histPause(); }
  else { histSeek(0, true); histPlay(); }
}
```

**The event bindings** — in the `DOMContentLoaded` block, replace the race chart's four bindings and delete the activity chart's four. The race bindings become:

```js
  document.getElementById('racePlayBtn').addEventListener('click', function () {
    histPlaying ? histPause() : histPlay();
  });
  document.getElementById('raceReplayBtn').addEventListener('click', histReplay);
  document.getElementById('raceScrub').addEventListener('input', function () {
    /* seek before pausing: histPause() syncs the transport from actPos, so
       pausing first would render the position being left, not the one being
       landed on */
    histSeek(Number(this.value), true);
    histPause();
  });
  document.querySelectorAll('.race-speed-btn').forEach(function (b) {
    b.addEventListener('click', function () { histSetSpeed(Number(b.dataset.speed)); });
  });
```

Delete the four `#actPlayBtn` / `#actReplayBtn` / `#actScrub` / `.act-speed-btn` listeners entirely.

**Every remaining call site of a deleted function.** Enumerated from the tree, so none is missed:

| Where | Change |
|---|---|
| `switchTab()` | `{ racePause(); actPause(); }` → `histPause();` |
| `racePlot` click delegation — cover click | `racePause(); openDetail(...)` → `histPause(); openDetail(...)` |
| `racePlot` click delegation — bar click | `if (e.target.closest('.race-bar')) racePause();` → `histPause();` |
| `actSeekAt()` body | `actSeek(...)` → `histSeek(..., true)`, and `actSyncControls()` → `histSyncControls()` |
| `actBandWrap` `pointerdown` | `actPause();` → `histPause();` |

The `racePlot` `mousemove` tooltip reads `raceFrames[raceIndex]`. Leave it: `racePaint` still assigns `raceIndex`, so the tooltip keeps naming the records in the bar being shown.

Update `actSeekAt`'s comment, which still names the old functions:

```js
  /* The band is the control, not a picture of one: drag it to scrub. The range
   * input stays for keyboard and assistive access; both write through
   * histSeek(). */
```

**Take the duplicate date write out of `actPaint()`.** It currently ends with

```js
  document.getElementById('actDay').textContent = VinylActivity.dayAt(act.d0, day);
```

Delete that line. `histPaint` now writes the date, to `#raceDay`. Removing it
here rather than in Task 4 matters: Task 4 deletes the `#actDay` element, and
if this write outlived it every frame would throw on a null element and take
the whole chart down.

Finally, the zoom, show and order handlers each end with `actPaint();` — leave them. They change only the activity chart, and repainting the race chart on a zoom click would be wasted work.

- [ ] **Step 4: Verify in the browser**

A Flask server with the real collection runs on port 5055; the harness is at `.superpowers/sdd/<plan>/verify.sh` if the controller has provided one, otherwise start `.venv/bin/python app.py` and drive it yourself.

Confirm, on the History tab:
- one playhead: the race chart's frame and the activity chart's playhead advance together
- `#raceDay` shows the **playhead's** day and keeps counting between purchases, rather than freezing on the last purchase date
- the run takes about 30 seconds at 1×, and the long empty stretch near the start passes in about two seconds rather than thirteen
- dragging `#raceScrub` moves both charts; dragging the band does the same
- the speed pills change both; the replay button appears when the *timeline* ends
- the activity chart's own control row is still on screen but inert — Task 4 removes it

- [ ] **Step 5: Commit**

```bash
git add templates/index.html
git commit -m "Drive both History charts from one clock"
```

---

### Task 4: One bar, pinned to the tab

**Files:**
- Modify: `templates/index.html`

**Interfaces:**
- Consumes: the `hist*` transport from Task 3. No JS behaviour changes here.
- Produces: `.history-transport` as the last child of `#historyPage`; `#actDay` no longer exists.

- [ ] **Step 1: Delete the activity chart's dead control row**

In `#actBox`, delete the whole `<div class="race-controls">…</div>` block containing `#actPlayBtn`, `#actScrub`, the three `.act-speed-btn` buttons and `#actReplayBtn`. Nothing references them after Task 3.

- [ ] **Step 2: Remove the duplicate date readout**

In `.act-readout`, delete `<span class="act-day" id="actDay"></span>`, leaving the caption. Task 3 already removed the only JavaScript that wrote to it, so nothing references it. Delete the now-unused `.act-day` CSS rule and its `@media(max-width:640px)` override.

Confirm the write really is gone before deleting the element — a leftover
`getElementById('actDay').textContent` would throw on every frame:

```bash
grep -n "actDay" templates/index.html
```

Expected after your edit: no output.

- [ ] **Step 3: Move the surviving transport out to the page**

Cut the race chart's `<div class="race-controls">…</div>` out of its `.chart-box` and paste it as the **last child of `#historyPage`**, after `#actBox` closes, changing the wrapper class and the scrubber's attributes:

```html
      <div class="history-transport" id="histTransport">
        <button class="race-btn" id="racePlayBtn" aria-label="play" aria-pressed="false"><i class="ti ti-player-play"></i></button>
        <input type="range" id="raceScrub" min="0" max="0" step="1" value="0" aria-label="day">
        <div class="race-speeds">
          <button class="race-speed-btn" data-speed="0.5">0.5&times;</button>
          <button class="race-speed-btn active" data-speed="1">1&times;</button>
          <button class="race-speed-btn" data-speed="2">2&times;</button>
        </div>
        <button class="race-btn hidden" id="raceReplayBtn" aria-label="replay"><i class="ti ti-refresh"></i></button>
      </div>
```

The only attribute change is `aria-label="purchase day"` → `aria-label="day"`; `renderHistory` sets `max` at runtime.

- [ ] **Step 4: Pin it**

Add after the `.race-controls` rule in the stylesheet:

```css
/* One transport for the whole tab, pinned so it stays reachable while the
   lanes scroll. Sticky rather than fixed: it keeps its place in the flow, so
   the last lane is never trapped underneath it. */
.history-transport{
  position:sticky;bottom:0;z-index:4;
  display:flex;align-items:center;gap:12px;
  padding:12px 0 14px;
  background:var(--bg);
  border-top:1px solid var(--border);
}
@media(max-width:760px){
  /* clear .mobile-tabbar, which is fixed, 58px tall and adds the safe-area
     inset on notched phones */
  .history-transport{bottom:calc(58px + env(safe-area-inset-bottom, 0px))}
}
```

`--bg` and not `--surface`: the bar sits on the page ground between chart boxes, not inside one. `z-index:4` puts it above the charts and below `.mobile-tabbar`'s `80`.

- [ ] **Step 5: Drop the now-dead halves of the shared selectors**

The previous build widened two rules to cover both charts. The activity halves are gone, so narrow them back:

- `#raceScrub,#actScrub{…}` → `#raceScrub{…}`
- `#raceScrub:disabled,#actScrub:disabled{…}` → `#raceScrub:disabled{…}`
- `.race-speed-btn,.act-speed-btn{…}` → `.race-speed-btn{…}`
- `.race-speed-btn.active,.act-speed-btn.active{…}` → `.race-speed-btn.active{…}`

Then confirm no `act-speed-btn`, `actPlayBtn`, `actReplayBtn`, `actScrub` or `actDay` reference survives anywhere:

```bash
grep -n "act-speed-btn\|actPlayBtn\|actReplayBtn\|actScrub\|actDay\|act-day" templates/index.html
```

Expected: no output.

- [ ] **Step 6: Verify in the browser**

Confirm:
- exactly one control bar on the tab, below both charts
- it stays pinned to the bottom of the viewport while scrolling the lanes, and settles into place at the end of the page
- it does not appear on the Collection, Calendar or Statistics tabs
- at a phone width (~430px) it sits above the bottom tab bar rather than behind it
- both themes: the bar's background matches the page, and the top border reads
- everything still plays, scrubs and replays

- [ ] **Step 7: Commit**

```bash
git add templates/index.html
git commit -m "Pin one transport to the History tab"
```

---

### Task 5: Edges and the checklist

**Files:**
- Modify: `templates/index.html` (only if a check finds a defect)
- Modify: `docs/history-tab-manual-verification.md`

**Interfaces:**
- Consumes: everything above. Produces no new interface.

- [ ] **Step 1: Verify the empty collection**

With the app running, in the console:

```js
const saved = records; records = []; renderHistory();
```

Expected: the race chart shows its "nothing bought yet" message, the activity chart shows its own empty message, the scrubber is disabled, the play button does nothing, and no error reaches the console. Then `records = saved; renderHistory();` recovers and autoplays.

- [ ] **Step 2: Verify the purchases-only collection**

```js
const saved = records;
records = saved.map(r => Object.assign({}, r, { play_dates:'', cleaned_dates:'', notes:'' }));
renderHistory();
records = saved; renderHistory();
```

Expected: a valid clock where every day is either a purchase or empty, the race chart still races, the activity chart's band shows only gold columns, and no `NaN` reaches the screen. This is the case where `CLOCK_W_EVENT` never applies.

- [ ] **Step 3: Verify reduced motion**

In Chrome DevTools, Rendering → "Emulate CSS prefers-reduced-motion: reduce", then reopen the History tab.

Expected: the tab opens on the finished state — the race chart on its final frame, the activity chart on its last day, the replay button showing — and does not autoplay. Every control still works. Bars snap rather than sliding.

- [ ] **Step 4: Rewrite the checklist's playback section**

In `docs/history-tab-manual-verification.md`, the race chart's and activity chart's sections each describe their own transport. Replace both playback lists with one shared section, placed after the two chart-specific correctness sections:

```markdown
## One clock — both charts

The two charts share a single playhead, clock and transport. The clock is
weighted: empty days pass almost for free, event days cost one unit, purchase
days cost six, so a run does not spend 43% of itself on the 352 empty days
between the first purchase and the second.

- [ ] Opening the tab autoplays both charts from day 0 and finishes in about
      30 seconds at 1×.
- [ ] The race chart's frame and the activity chart's playhead always agree —
      pause anywhere and the bars show the collection as of the date on screen.
- [ ] The date readout counts up continuously and does **not** freeze on the
      last purchase date between purchases.
- [ ] The long quiet stretch near the start passes in about two seconds, not
      thirteen.
- [ ] No purchase transition is so fast it reads as a flicker; the closest
      pair still takes about 120ms.
- [ ] The race chart holds its final frame for the last 20 days of the
      timeline, because the last purchase was `2026-08-01` and the last play
      `2026-08-21`.
- [ ] Dragging the scrubber and dragging the band move both charts, and agree
      with each other — both are in calendar days.
- [ ] The speed pills change both charts at once, and the race chart's bar
      growth speeds up to match rather than staying at its old duration.
- [ ] The replay button appears when the whole timeline ends, not when the
      race chart runs out of purchases.
- [ ] Leaving the History tab stops playback — no frame loop runs behind the
      collection view.

### The pinned bar

- [ ] There is exactly one control bar on the tab, below both charts.
- [ ] It stays pinned to the bottom of the viewport while the lanes scroll,
      and settles into place at the end of the page.
- [ ] It appears on no other tab.
- [ ] At a phone width (~430px) it sits above the bottom tab bar, not behind it.
- [ ] Its background matches the page ground in both themes, and its top
      border reads against the lanes above it.
```

Delete the superseded playback bullets from the two chart sections: the race chart's "Opening the tab autoplays from the first frame", its scrubber and speed lines, and the activity chart's "Opening the tab autoplays from day 0 and finishes in about 5–6 seconds", "Dragging the band scrubs both panels and pauses playback" and the transport-button line. Everything about rendering, ordering, zoom, solo, notes and the quiet fade stays.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: 124 passed.

- [ ] **Step 6: Commit**

```bash
git add templates/index.html docs/history-tab-manual-verification.md
git commit -m "Hold the shared clock's edges, and say what to check"
```

---

## Self-Review

**Spec coverage.** Every section maps to a task: §"The fix" weights → Task 1; §1 clock module → Tasks 1–2; §2 transport rename and deletions → Task 3; §3 race chart following the clock, `raceFrameForDay`, `--race-dur` from the real gap, the `#raceDay` meaning change, the 20-day tail → Task 3; §4 one bar, pinned, scrub in days, selector narrowing → Task 4; §5 `#actDay` removal → Task 4; §6 reduced motion → Tasks 3 and 5; §7 tests → Tasks 1, 2 and 5; §8 files → all.

**Naming.** The spec calls the frame lookup `raceFrameForDay(day)`; the plan implements it as the precomputed array `raceFrameOfDay[day]` plus its inverse `raceFrameDay[f]`, because the spec itself requires the mapping be "computed once per render into an array indexed by day, not searched per frame". Same contract, and the array form is what the spec asks for.

**A gap this review found and closed.** The first draft listed only `switchTab` and `actSeekAt` as call sites to move. A sweep of every caller of the fourteen deleted functions turned up three more: two `racePause()` calls in the race plot's click delegation (clicking a cover, and clicking a bar) and one in the band's `pointerdown`. All three are now in Task 3's table. Left as-is deliberately: the tooltip's `raceFrames[raceIndex]` read, since `racePaint` still assigns `raceIndex`.

**Two things the spec left implicit that the plan pins down.** `histSeek` takes a second `seeking` argument, so a scrub snaps the race chart while playback slides it — without it, every scrub would animate 31 frames of bars. And the scrub handler seeks before pausing, which is the ordering defect a review caught in the previous build; repeating it here would reintroduce it.

**Placeholder scan.** No TBD, TODO, "handle edge cases", or "similar to Task N". Every code step carries the code.

**Type consistency.** `buildClock` returns `{cum, total}` in Task 1 and is consumed as `{cum, total}` in Tasks 2 and 3. `dayAtProgress(clock, p)` and `progressAtDay(clock, day)` keep that argument order at all six call sites. `histSeek(day, seeking)`, `histPaint(seeking)` and `raceApplyDuration(f)` each keep one signature throughout.
