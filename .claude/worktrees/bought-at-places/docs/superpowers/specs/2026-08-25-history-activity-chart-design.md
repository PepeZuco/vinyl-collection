# History Tab — Activity Chart ("how the collection is used")

## Problem

The History tab answers one question: **how the collection grew**. The race
chart replays 32 shopping days and ranks genres by cumulative record count.

It has nothing to say about what happened to a record *after* it was shelved.
Every play, cleaning and note is already stored — `play_dates`, `cleaned_dates`
and `notes` on `Record` — and already merged chronologically by
`dmHistoryEvents()` in `templates/index.html`. That merge never leaves the
detail view, so the app can tell you a record was played sixteen times but not
when, and cannot tell you that 65 of 112 records have been played twice or
less.

A second chart-box under the race chart replays that. **One clock, two
scales**: a weekly rhythm band on top that doubles as the scrubber, and
per-record lanes below it that zoom.

Not to be confused with `2026-08-10-record-history-timeline-design.md`, the
per-record life story inside the detail view. This is the collection's use, on
a shared calendar axis.

## The data this runs on

Measured against the live collection (`instance/vinyl.db`), not assumed:

| | |
|---|---|
| Records in scope | 112 (owned and dated) |
| Plays | 399 |
| Cleanings | 60, none before `2026-03-07` |
| Notes with text | 38, across 33 records — 28 in JSON `notes` columns plus 10 legacy plain-string columns the app's `parseNotes()` migrates |
| Day range | `2024-05-31` → `2026-08-21`, **813 days** |
| Days with any event | 212 |
| Records with 7+ plays | 21 (214 plays); the other 91 hold 185 |
| Records played ≤2 times | 65, of which 43 once or never |
| Busiest month | 2026-05, 65 plays |

Two properties matter for the design:

- **Cleaning is younger than the collection.** Nothing was cleaned before March
  2026, so the cleaned series appears from nothing two-thirds of the way in.
  That is true, not a bug, and the chart must not look broken when it happens.
- **The most-played records never go quiet.** The longest silence among the top
  21 is 93 days (Tim Maia). Every abandoned record is in the tail. This is why
  the row count is a control rather than a fixed 21 — see §4.3.

## Architecture

```
static/grouping.js    momentOf()        ── existing, reused for date parsing
        │
        ▼
static/activity.js    buildActivity()   ── new, pure, node-testable
        │
        ▼
templates/index.html  renderActivity()  ── DOM paint + playback controller
                      CSS transitions   ── every visual interpolation
```

Same split as `history.js` / `grouping.js` / `spend.js`: everything decidable
without a DOM lives in `static/*.js` and is tested with `node:test`;
presentation stays in `index.html`.

Rendering is **HTML elements with CSS transitions**, not SVG and not canvas —
the same reasoning as the race chart, plus one more: lane marks are positioned
as percentages inside a track element, so zooming is a single width change and
the browser re-lays every mark out for free.

## 1. Data layer — `static/activity.js`

Exposes one function, in the module shape both existing consumers use:

```js
const VinylActivity = (function (grouping) {
  /* ... */
  return { buildActivity };
})(typeof module !== 'undefined' && module.exports
     ? require('./grouping.js') : VinylGrouping);
```

### 1.1 Scope

Identical to the race chart: `have_it` **and** a parseable `bought_date`.
Every owned record in this collection carries a bought date and every undated
record is a wishlist item, so this drops nothing owned.

Within a record in scope, each event is kept if `momentOf(stamp).day` is
non-empty. An unparseable play date drops that play, not the record. Notes
follow `dmHistoryEvents()`: a note with no `text` is not an event.

A play or cleaning dated **before** the record's `bought_date` is kept as-is.
It is unusual but it is what the user recorded, and silently moving it would
be a lie. It shows as a mark to the left of the lane's gold dot.

### 1.2 The day axis

`day 0` is the earliest day carrying **any** event, not the earliest purchase —
otherwise an event predating its record would fall off the left edge. The last
day is the latest day carrying any event.

```js
{
  d0:   'YYYY-MM-DD',   // day 0
  span: 813,            // number of days; the last day index is span - 1
  ...
}
```

### 1.3 Return shape

```js
{
  d0, span,

  // 7-day buckets from day 0. weeks.length === ceil(span / 7).
  weeks: [{ b, p, c, n, total }],

  // cumulative event counts, indexed by day. cum.p[i] is every play on or
  // before day i. Length === span.
  cum: { b: [], p: [], c: [], n: [] },

  // one per record in scope, sorted by play count desc then bought asc
  lanes: [{
    id, artist, album, cover,
    bought,            // day index
    plays:  [dayIdx],  // ascending
    cleans: [dayIdx],
    notes:  [dayIdx],
    lastPlay,          // last play's day index, or bought when never played
  }],

  // day index -> lane ids played that day, for the caption
  playedOn: [[id, ...]],

  // every note with text, ascending, for the note card
  notes: [{ day, text, id, artist, album }],

  totals: { b, p, c, n },
}
```

`buildActivity([])` returns `null`. So does a collection where nothing is in
scope. The renderer treats `null` as the empty state — this keeps the
`span - 1` divisions in the renderer from ever seeing a degenerate axis.

**A one-day collection is not degenerate.** `span` is 1, the axis has a single
day, and `pct()` in the renderer must not divide by `span - 1 === 0`. The
renderer guards this by clamping the denominator to at least 1 (§3.1).

### 1.4 Sort order

`lanes` comes back sorted by play count descending, ties by bought date
ascending. The renderer re-sorts on demand (§4.4); shipping a defined default
order from the module means the "top N" cut is meaningful before any user
interaction, and makes the order assertable in tests.

## 2. Placement

A second `.chart-box` inside `#historyPage`, directly below the race chart's
box, with its own title, legend, controls and transport.

**Not one shared transport.** The race chart's clock hops between 32 purchase
days; this one runs 813 consecutive calendar days. They are different clocks
and a single scrubber cannot address both.

The phone reaches this the same way it reaches the rest of the History tab —
through the stats/history segment control, unchanged.

## 3. Rendering

### 3.1 Coordinates

One helper does all the mapping:

```js
const ACT_LAST = () => Math.max(1, act.span - 1);   // never divide by zero
const actPct = i => i / ACT_LAST() * 100;
```

Every mark, tick and window edge is a percentage of the full span. Nothing is
laid out in pixels, so zoom is a width change and pan is a transform.

### 3.2 The two panels

**Band** (`.act-band`) — one column per week, four stacked segments in
bottom-up order played → cleaned → noted → bought, heights as a percentage of
the busiest week. `flex-direction: column-reverse` puts the first child on the
baseline. A 2px `box-shadow` in the surface colour separates stacked segments,
per the dataviz mark spec.

**Lanes** (`.act-lane`) — `overflow: hidden`, containing a `.act-track` whose
width is `calc(100% * span / actWin)`. Marks sit at `left: actPct(day)%` of
the track, so widening the track re-lays them out with no JS. Marks keep their
2px width because they are absolutely sized.

### 3.3 The per-frame cost is two style writes

Every track shares the same pan and reveal. Rather than looping rows, the
renderer writes two custom properties on the lanes container:

```css
.act-lanes { --act-pan: 0px; --act-rev: 100%; }
.act-track {
  transform: translateX(var(--act-pan));
  clip-path: inset(0 var(--act-rev) 0 0);
  will-change: transform;
}
```

```js
lanes.style.setProperty('--act-pan', pan + 'px');
lanes.style.setProperty('--act-rev', rev + '%');
```

Two writes per frame regardless of whether 21 lanes or 112 are on screen. This
is a deliberate improvement on the prototype, which looped every visible track.

Per-row work that remains — play counts, the owned-cover flip, the quiet fade —
is guarded by change detection and touches an element only when its value
actually changes.

### 3.4 Reveal

`--act-rev` is `100 - actPct(pos)`, a percentage of each track's own box, so it
is correct at every zoom without recomputation. Everything to the right of the
playhead is clipped, which is what makes the chart draw itself as it plays.

The lane's baseline hairline (`.act-lane::before`) sits outside the track and
is **not** clipped — the empty track ahead of the playhead still reads as a
lane.

## 4. Controls

### 4.1 Transport

Play/pause, a range scrubber, 0.5×/1×/2×, and a replay button that appears at
the end — the same control vocabulary and the same Tabler icons as
`.race-controls`, so the two charts do not look like they came from different
apps.

**Playback is a continuous day clock driven by `requestAnimationFrame`,** not
the race chart's `setTimeout` frame chain. The race chart has one frame per
purchase day and nothing between them; this chart's axis is continuous calendar
time and its weekly columns must grow smoothly. A frame-per-event-day clock
would hop unevenly and stutter the band.

Rate is tied to zoom so the visible window always takes roughly two and a half
seconds to cross:

```js
function actRate() { return Math.min(150, Math.max(25, actWin / 2.5)); }  // days/sec
```

At full span that is 150 days/sec — about 5.4 seconds end to end.

### 4.2 The band is the scrubber

`pointerdown` on the band pauses playback and seeks; `pointermove` while
captured keeps seeking. The range input stays for keyboard and assistive
access, and both write through the same `actSeek()`.

### 4.3 Zoom — `all · 1 yr · 90 d · 30 d`

At full span, 813 days across ~700px is 1.2 days per pixel and a run of plays
is an unreadable smear. Narrowing the window rescales the lanes while the band
keeps the full arc, with the visible range drawn on the band as a highlighted
rectangle.

While playing zoomed, the window follows the playhead, holding it at 62% of the
lane viewport so what is coming is visible, clamped at both ends:

```js
actWinStart = clamp(pos - actWin * 0.62, 0, ACT_LAST() - actWin);
```

### 4.4 Show — `top 21 · top 50 · all 112`

Every record gets a lane element up front; the control decides how many are
displayed. Whatever is not shown is folded into a single density band below,
labelled with its count, carrying every one of its events as faint marks — so
nothing is ever hidden, only compressed.

Above 30 visible lanes the list becomes a scroll pane capped at 430px. The
playhead line sits outside the scroll pane so it spans the whole plot.

This control exists because of the finding in §"The data this runs on": the
fade-when-quiet only ever fires in the tail. A view that cannot open the tail
cannot show the thing the chart is for.

### 4.5 Order — `most played · in rotation · bought`

- **most played** — play count descending (default)
- **in rotation** — most recently played first
- **bought** — purchase date ascending

All three are computed from the whole timeline, not from the playhead, so
**rows never re-rank during playback**. The race chart directly above already
owns rank animation; a second racing chart competes with it, and a row that
moves cannot be followed. Order changes only when the user clicks.

Re-sorting re-applies the current "show" cut, so the folded band always holds
exactly the records not on screen.

### 4.6 Hover a lane to solo it

Pointing at a lane dims the band to 22% and overlays that record's own events
across the full span, coloured by type. The caption becomes
`artist — album · N plays · last DD Mon YYYY`.

This is the payoff for stacking the two panels: it answers where a single album
sits inside the overall habit, which neither panel can answer alone.

Clicking a lane calls `openDetail(id)`, matching the race chart's covers.

### 4.7 The quiet fade

A lane whose last play is more than **60 days** before the playhead gets
`.act-row.gone` — name, cover and count drop to 34% opacity together — and
lights back up the moment it is played again.

60 days, not the 120 the prototype started with: at 120 the class never fired
once on the default 21 rows. At 60 it fires on 6 of them at the end of the
timeline and stays rare in the middle, which is an honest reading of a
collection whose top records are played every few weeks.

A dotted hairline runs from a lane's last play to the end of the axis whenever
that gap exceeds 60 days, so silence is visible as well as implied.

### 4.8 The note card

A strip under the band holds **the most recent note as of the playhead** —
record, date and text — updated by crossfade as the playhead passes each one.
It holds rather than flashes: with 28 notes over a 5-second run, anything
timer-driven is a flicker. Fixed minimum height so the layout does not jump
before the first note.

## 5. Colour

Four new tokens per theme in `templates/index.html`, beside the existing
palette:

```css
[data-theme="dark"]  { --ev-bought:#ac9008; --ev-cleaned:#0b9d9d;
                       --ev-played:#2171cc; --ev-note:#a5397e; }
[data-theme="light"] { --ev-bought:#b39609; --ev-cleaned:#07a4a4;
                       --ev-played:#2171cc; --ev-note:#a5397e; }
```

Validated with the dataviz skill's `validate_palette.js` against both chart
surfaces, `--pairs all`: lightness band, chroma floor, CVD separation
— worst separation across deutan, protan and tritan is **8.2 (dark)** and
**10.2 (light)**, against a target of ≥8 — normal-vision floor and contrast all
pass. These are event-type colours and are **separate from `GENRE_PALETTE`** —
this chart never colours by genre.

Colour is never the only signal: the legend carries the app's existing event
icons from `DM_HIST_ICON` — `ti-shopping-bag`, `ti-headphones`, `ti-droplet`
and a note marker — the same icons the detail-view timeline already uses, and
mark shape differs per type (bought is a dot, the rest are ticks of differing
height).

Every colour in the chart resolves from a CSS variable, so the theme toggle
needs no JS in this chart at all.

## 6. Wiring

`renderActivity()` is called from the **top** of `renderHistory()`, before the
race chart's early return for an empty timeline — so the activity chart renders
its own empty state rather than being skipped. `renderHistory()` stays the
History tab's single entry point; it is already called from `switchTab()` and
from the theme toggle.

`switchTab()` gains `actPause()` alongside the existing `racePause()` when
leaving the tab, so no `requestAnimationFrame` loop runs behind the collection
view.

**Known, accepted behaviour:** toggling the theme while on the History tab
re-renders and restarts both charts from the beginning. This is already true of
the race chart; making only the new chart preserve its position would be the
inconsistency.

## 7. Empty and reduced-motion states

- **Nothing in scope** — the box shows the same kind of message as
  `.race-empty`: "nothing to replay yet — records need a bought date to appear
  here." Controls disabled.
- **Nothing but purchases** — a collection with no plays, cleanings or notes
  still has a valid axis and renders: the band shows only bought columns and
  every lane is a gold dot with a dotted tail. No special case.
- **`prefers-reduced-motion`** — opens on the finished chart at the last day
  instead of autoplaying, exactly as the race chart does. Every control still
  works; the user starts it themselves. Segment-height and row-opacity
  transitions are disabled.

## 8. Tests

`tests/test_activity.js` under `node:test`, wrapped by `tests/test_activity.py`
so `pytest` stays the one command — the pattern of `test_history.py` and
`test_spend.py`, skipped when node is absent. `TZ` is pinned to
`America/Sao_Paulo` before any `Date` is constructed, as in `test_history.js`.

Covering:

- an empty collection, and one where nothing is in scope, return `null`
- wishlist records are excluded even when they carry events
- owned records with no bought date are excluded
- an unparseable bought date drops the record; an unparseable play date drops
  only that play
- a note with no text is not an event
- `d0` is the earliest event day, including when a play predates every purchase
- `span` covers the last event day inclusive
- week bucketing: day 0 and day 6 land in week 0, day 7 in week 1
- `cum` is monotonic, and its last value equals `totals` for each type
- lane day indices are ascending and relative to `d0`
- `lastPlay` falls back to `bought` when a record was never played
- `playedOn` indexes every play and nothing else
- default lane order is play count desc, ties by bought asc
- a single-day collection returns `span === 1` without throwing

The animation is not unit-testable. `docs/history-tab-manual-verification.md`
gains an activity-chart section with the live collection's expected shape (112
lanes, 399 plays, totals reconciling to 214 + 185, the cleaned series appearing
in March 2026, 6 rows dimmed at the end at the default cut).

## 9. Files

| File | Change |
|---|---|
| `static/activity.js` | **create** — `buildActivity()` |
| `tests/test_activity.js` | **create** — `node:test` unit tests |
| `tests/test_activity.py` | **create** — pytest wrapper |
| `templates/index.html` | event-colour tokens; activity chart CSS; the second `.chart-box` markup; `renderActivity()` and its controller; `actPause()` in `switchTab()`; `renderActivity()` call in `renderHistory()`; `<script src="/static/activity.js">` after `history.js` |
| `docs/history-tab-manual-verification.md` | **append** — activity chart checks |

No Python, no schema change, no new dependency. Covers are already resident
from `loadRecords()`, so the chart adds no network cost.

## Out of scope

- Re-ranking lanes during playback (§4.5).
- Sharing one transport with the race chart (§2).
- Wishlist records as empty lanes — they have no events.
- Any change to the race chart itself.
