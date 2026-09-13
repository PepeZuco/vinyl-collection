# History Tab — Collection Growth Race Chart

## Problem

The Statistics tab answers "what is in the collection" — 34 MPB & Samba, 20
Rock, 18 Pop. It cannot answer "how did it get that way". The collection was
bought over 31 shopping days across two years, and the order those records
arrived in is a story the app currently throws away: Soul & Funk and Folk led
on day one and both finished mid-table, while MPB & Samba started from nothing
and ended up nearly double the runner-up.

A new **History** tab replays that. A horizontal bar chart race, one frame per
purchase day, bars ranked by cumulative record count and re-ordering as genres
overtake each other — with the actual album covers flying in and riding along
inside each bar as they are bought.

Not to be confused with `2026-08-10-record-history-timeline-design.md`, which
is the per-record life story inside the detail view. This is the collection's
history, not a record's.

## The data this runs on

Measured against the live collection, not assumed:

| | |
|---|---|
| Frames (distinct purchase days) | 31, `2024-05-31` → `2026-08-01` |
| Records in scope | 112 |
| Genres | 11 |
| Final ranking | MPB & Samba 34, Rock 20, Pop 18, Soul & Funk 9, Easy Listening 8, Jazz 7, Classical 6, Blues 4, Folk 3, Hip Hop 2, Reggae 1 |
| Busiest genre-day | 5 records |
| Opening frame | 3 genres — Easy Listening, Folk, Soul & Funk |
| Cover payload | 18.9 MB base64, avg 165 KB, max 2.8 MB |

Two properties of the collection make the scope rule unambiguous:

- Every `have_it` record has a `bought_date`. Nothing owned is undated.
- Every record without a `bought_date` is a wishlist item (`have_it = 0`).

So filtering to owned-and-dated loses nothing and drops nothing owned, and the
final frame's counts equal the Statistics tab's genre chart exactly. There is
no "unknown date" bucket to design around.

Covers are already resident: `loadRecords()` fetches the whole collection at
startup, so the chart adds no network cost. What it must not do is force the
browser to decode 112 full-size images repeatedly — see §3.

## Architecture

```
static/grouping.js   momentOf()          ── existing, reused for date parsing
        │
        ▼
static/history.js    buildTimeline()     ── new, pure, node-testable
        │
        ▼
templates/index.html renderHistory()     ── DOM paint + playback controller
                     CSS transitions     ── every visual interpolation
```

The split follows the existing `grouping.js` / `spend.js` precedent: all logic
that can be decided without a DOM lives in a `static/*.js` module and is tested
with `node:test`; presentation stays in `index.html`.

Rendering is **HTML rows with CSS transitions**, not SVG and not canvas. The
covers are the point of the feature, and this is the only approach where a
cover is an ordinary `<img>` — the browser owns decoding and caching, each
image decodes once and is reused across all 31 frames, and clicking one
through to `openDetail(id)` costs nothing.

## 1. Data layer — `static/history.js`

Exposes one function, in the module shape both consumers already use:

```js
const VinylHistory = (function (grouping) {
  /* ... */
  return { buildTimeline };
})(typeof module !== 'undefined' && module.exports
     ? require('./grouping.js') : VinylGrouping);

if (typeof module !== 'undefined' && module.exports) module.exports = VinylHistory;
```

`grouping.js` is already loaded before this file in `index.html`, so the
browser branch reads the global; the test branch requires it. Date parsing is
delegated to `momentOf()` rather than re-implemented — the same three stamp
shapes and the same local-clock handling, decided in one place.

### Contract

```
buildTimeline(records) → [Frame]

Frame = {
  day:   'YYYY-MM-DD',   // the purchase day this frame sits on
  index: Number,         // 0-based position in the timeline
  total: Number,         // cumulative records across all genres through this day
  bars:  [Bar],          // ranked, leader first; only genres that have appeared
}

Bar = {
  genre:   String,       // raw genre value, '' when untagged
  label:   String,       // genre, or 'unknown' when untagged
  count:   Number,       // cumulative through this day
  records: [record],     // cumulative, oldest purchase first
  added:   [record],     // bought on this day only, oldest first
}
```

`added` drives the cover fly-in; its order sets the stagger order.

### Rules

**Scope.** A record is in scope when `have_it` is truthy and
`momentOf(r.bought_date).day` is non-empty. Everything else — wishlist items,
unparseable stamps — is silently dropped, never bucketed into a catch-all. One
bad row must not take the tab down, matching `momentOf`'s own contract.

**Frames.** One per distinct `day` in scope, ascending. No frames for days
without a purchase: the timeline hops. (Decided against walking all ~793
calendar days — 96 % of those frames would show nothing changing.)

**Cumulative.** `count` and `records` are running totals through the day, never
per-day counts. Bars only grow.

**Entry.** A genre appears in `bars` from the first frame it has a record, not
before. No row sits at zero waiting its turn.

**Ordering** — the one rule with a non-obvious reason. Sort by:

1. `count` descending
2. the genre's **rank in the previous frame** ascending (a genre absent from
   the previous frame sorts last among ties)
3. `label` ascending

On frame 0 there is no previous frame, so step 2 is skipped and the opening
order is decided by count then label.

Step 2 is what stops bars jittering. Rock and Pop sit within one record of each
other for long stretches; with a plain alphabetical tie-break they would trade
places every time one gains and the other catches up, producing a row swap
animation that means nothing. Ranking ties by who held the position keeps a
level stretch visually still, so a swap on screen always means a real overtake.

**Record order within a bar.** Ascending by `momentOf(r.bought_date).at`, ties
broken by `id` ascending. Deterministic, so the cover strip never reshuffles
between frames.

**Empty input.** No records, or none in scope, returns `[]`. The tab renders an
empty state, not a broken chart.

## 2. Markup

A new page sibling to the existing three, following their exact pattern
(`.history-page` / `.history-page.visible`, toggled by `switchTab`):

```html
<div class="history-page" id="historyPage">
  <div class="stats-seg" id="historySeg">…</div>   <!-- mobile only, §5 -->
  <div class="chart-box">
    <div class="chart-title">
      <span>how the collection grew</span>
      <span class="race-total" id="raceTotal">112 records</span>  <!-- frame.total -->
    </div>
    <div class="race-plot" id="racePlot"></div>     <!-- rows injected here -->
    <div class="race-day" id="raceDay">2026-08-01</div>
    <div class="race-controls">
      <button id="racePlayBtn">…</button>
      <input type="range" id="raceScrub" min="0" max="30" step="1">
      <div class="race-speeds">0.5× 1× 2×</div>
      <button id="raceReplayBtn">…</button>
    </div>
  </div>
</div>
```

One row per bar:

```html
<div class="race-row" style="--gc:#2FB673; transform:translateY(114px)">
  <div class="race-label">MPB &amp; Samba</div>
  <div class="race-track">
    <div class="race-bar" style="width:100%">
      <div class="race-covers">
        <img class="race-cover" src="…"><img class="race-cover new" style="--i:0" src="…">
      </div>
    </div>
    <span class="race-count">34</span>
  </div>
</div>
```

`#raceTotal` shows the **current frame's** `total`, counting up to 112 as the
race runs — not a fixed final figure.

The genre hue is passed down as a `--gc` custom property from
`genreColor(genre)`, so one inline value drives fill, edge and glow, and the
CSS stays declarative.

## 3. Visual spec

**Scale.** Bar width is a percentage of the **current leader**, so the leader
always fills the row and the axis rescales as the collection grows. Rejected
scaling to the final maximum of 34: the first twenty frames would be slivers.

**Rows.** Absolutely positioned inside a `position:relative` plot, each row
placed by `transform:translateY()`. Transform is what makes an overtake animate
as a swap rather than a reflow.

Plot height is fixed for the whole race at `all-genres-that-ever-appear ×
row-height` — 11 rows — not at the current frame's bar count. Sizing it to the
current frame would make the box jump taller every time a genre enters, and
shove the controls down the page mid-playback. Early frames simply have empty
space below the three opening bars.

The left-edge fade uses `mask-image` with a `-webkit-mask-image` twin; Safari
still needs the prefix.

**Cover strip.** Inside the bar, `display:flex`, `justify-content:flex-end`,
`overflow:hidden`, with a left-edge `mask-image` fade. The newest cover always
lands at the bar's growing tip — where the eye already is — and older ones
slide left and dissolve under the fade.

This replaces the "+N overflow badge" idea. MPB's final 34 covers need ~880 px
and cannot fit any real bar, so *something* must be hidden. Clipping with a
fade needs no width measurement, no cap arithmetic, and no resize handler, and
it degrades correctly at every viewport. The count number sits **outside** the
bar's right end, so a 1-record genre stays legible at 3 % width.

`RACE_COVER_CAP = 48` most recent covers are put in the DOM per bar — more than
any bar can display, so the visible result is identical, but node count stays
bounded.

**Fly-in.** A cover in `added` renders with `.new` and `--i` set to its index:

```css
@keyframes raceIn {
  from { opacity: 0; transform: translateX(18px) scale(1.35) }
  to   { opacity: 1; transform: none }
}
.race-cover.new { animation: raceIn 420ms ease-out both;
                  animation-delay: calc(var(--i) * 60ms) }
```

Five arrivals — the busiest genre-day — stagger over 240 ms, comfortably inside
a 1000 ms frame.

**Theme.** Colours come from the existing `--card` / `--border` / `--muted`
variables and `genreColor()`, which already returns a light-theme hue. The
theme toggle re-runs `renderHistory()` the way it already re-runs
`renderStats()`.

## 4. Playback

State, alongside the existing `currentTab` / `chartInstances` block:

```js
let raceFrames = [], raceIndex = 0, racePlaying = false, raceSpeed = 1, raceTimer = null;
const RACE_BASE_MS = 1000;   // per frame at 1× — ~31s end to end
```

A `setTimeout` chain advances the frame; `--race-dur`
(`RACE_BASE_MS / raceSpeed`) drives every CSS transition. No `requestAnimation-
Frame` loop and no interpolation code: bar width, row position and cover entry
are all interpolated by the browser.

- **Pause** clears the timer only. The day in flight finishes settling, which
  is what pause should mean — it stops advancing, it does not freeze mid-slide.
- **Scrub** sets `raceIndex` directly. Dragging adds `.scrubbing` to the plot,
  setting `--race-dur: 0ms`, so frames snap instead of chasing the pointer;
  removed on release.
- **Speed** rewrites `--race-dur` live; a change mid-flight applies from the
  next frame.
- **End** stops on the final frame and swaps the play button for replay.
- **Leaving the tab** pauses, so no timer runs behind the collection view.
- **Entering the tab** rebuilds frames from `records`, paints frame 0, and
  autoplays.

Functions: `renderHistory()`, `racePaint(i, animate)`, `racePlay()`,
`racePause()`, `raceSeek(i)`, `raceSetSpeed(s)`, `raceReplay()`.

## 5. Navigation

**Desktop** — a fourth `.nav-tab` after Statistics, and a fourth branch in
`switchTab()`.

**Mobile** — the bottom bar already carries four items plus a centre FAB; a
fifth item would land underneath the FAB. So the bar is left alone, and both
the Statistics and History pages carry an identical segmented control at the
top, visible only under 760 px:

```
┌───────┐┌───────┐
│ stats ││history│
└───────┘└───────┘
```

`syncMobileTabbar()` treats `currentTab === 'history'` as the Stats item being
active, so the bar stays truthful about where you are. Rejected moving the FAB
to the header (changes the add-record flow, used often) and displacing Wishlist
from the bar (costs it one-tap access).

## 6. Interaction

- Clicking a bar pauses playback, so the chart holds still while you look at
  what you just stopped on.
- Clicking a cover pauses **and** opens `openDetail(id)` — the same record
  detail the collection grid opens, already adaptive to mobile and desktop. A
  cover sits inside its bar, so the click bubbles and the pause is the bar's
  doing; nothing calls `stopPropagation`, because pausing before opening a
  record is what you want anyway.
- Hovering a bar shows its genre and count via the existing `.chart-tooltip`
  pattern used by the year chart and world map.

## 7. Accessibility

- `prefers-reduced-motion: reduce` disables autoplay and the fly-in animation,
  and sets `--race-dur: 0ms`. The chart still works — scrubbing and stepping
  paint frames instantly.
- The scrubber is a real `<input type="range">` with an `aria-label`, so it is
  keyboard-operable.
- The play/pause button carries `aria-pressed` and a label that tracks state.

## 8. Testing

`tests/test_history.js` under `node:test`, wrapped by `tests/test_history.py`
exactly as `test_grouping.py` wraps `test_grouping.js`, so `pytest` stays the
single command. `TZ` pinned to `America/Sao_Paulo` before any `Date` is
constructed, for the same reason `test_grouping.js` pins it.

Cases:

1. Frame count and days match the distinct purchase days, ascending.
2. Cumulative counts are running totals; the final frame equals a plain
   group-by over the scoped records.
3. Wishlist records are excluded even when dated.
4. Undated and unparseable-date records are excluded, and do not throw.
5. A genre is absent from `bars` until its first record.
6. `added` holds only that day's records; empty for genres that gained nothing.
7. The rank tie-break holds order steady across a level stretch — two genres
   tied over several frames do not swap.
8. A real overtake does reorder.
9. An untagged record surfaces as `label: 'unknown'`.
10. `buildTimeline([])` and an all-wishlist collection both return `[]`.

The animation cannot be unit tested. It gets a manual verification doc at
`docs/history-tab-manual-verification.md`, in the style of the existing
`group-view-manual-verification.md`: play through, pause mid-frame, scrub both
directions, switch speed mid-flight, toggle theme while playing, leave and
re-enter the tab, click a cover, and run it under reduced-motion.

## 9. Out of scope

- Play and cleaning history — this races purchases only.
- Racing by artist, country or decade. The timeline builder takes a keying
  function's worth of shape to generalise later; nothing is built for it now.
- Exporting the animation as a video or GIF.
- Wishlist items appearing as ghost bars.
- Server-side aggregation. 112 records is trivial in the browser, and the data
  is already loaded.
