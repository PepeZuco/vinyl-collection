# History Tab — One Clock For Both Charts

## Problem

The History tab holds two replays and each drives itself.

The race chart ("how the collection grew") runs a `setTimeout` frame chain: 31
frames, one per purchase day, one second each, ~31s end to end. Every purchase
day gets the same slice of screen time regardless of how far apart the
purchases actually were.

The activity chart ("how the collection is used") runs a `requestAnimationFrame`
day clock across 813 consecutive calendar days at 150 days/sec, ~5.4s end to
end.

So the tab shows two playheads, moving at unrelated speeds, under two separate
transports. Watching one tells you nothing about where the other is. This
replaces both with **one clock, one playhead, one transport**, pinned to the
bottom of the tab.

`2026-08-25-history-activity-chart-design.md` §2 argued the opposite —
"they are different clocks and a single scrubber cannot address both". That
call is superseded here. The reasoning behind it was not wrong, and §2 of this
document is how it gets answered.

## The problem the old §2 was pointing at

Measured against the live collection, not assumed:

| | |
|---|---|
| Shared axis | `2024-05-31` → `2026-08-21`, **813 days** |
| Both charts' day 0 | `2024-05-31` — identical, so no offset is needed |
| Purchase days (race frames) | **31**, `2024-05-31` → `2026-08-01` |
| Other event days | 177 |
| Empty days | 605 |
| Gap between purchase day 1 and 2 | **352 days** — 43% of the whole axis |
| Records bought on day 0 | 3 |
| Plays in that 352-day gap | 10 of 399 (3%); zero cleanings |
| Race chart's tail | ends 20 days before the axis does |

The two charts run on different *kinds* of time. The race chart's is ordinal —
frame 1, frame 2 — which is why it feels evenly paced. Calendar time is not
evenly paced: three records were bought, then nothing happened for almost a
year, then everything happened at once.

Put both on a naive calendar clock and each gets worse. The race chart freezes
on 3 bars for 43% of the run. Then, at a 31-second total, five of the thirty
purchase transitions land less than 120ms apart — fast enough to read as a
flicker rather than a move.

## The fix: warp the rate, never the axis

The playhead's **position** stays linear in calendar time. Every mark, tick,
lane and week column stays exactly where it is, and the x-axis keeps meaning
what it says. What varies is the **rate of travel**: the clock sprints through
stretches where nothing happens and slows where events cluster.

This is the "skip silence" idea from video editors, and it is the only option
that fixes the dead stretch without either lying about the axis or dropping
data from the replay.

Each day gets a weight. Wall-clock time is handed out in proportion to weight:

| Day | Weight | Why |
|---|---|---|
| A purchase day (a race frame) | **6** | It must be on screen long enough for bars to visibly move |
| Any other day carrying an event | **1** | Plays, cleanings, notes — worth seeing, cheaper than a purchase |
| An empty day | **0.04** | Passes almost for free |

At **30 seconds** total for 1× — chosen to sit beside the race chart's current
~31s, which is the pacing this tab already has — those weights give, measured
against the live collection:

- every purchase transition **465ms** on screen, comfortably above flicker
- the 352-day gap collapsed from ~13s to **1.8s**
- **94%** of the runtime spent on days where something happens

The three constants and the total are tunable in one place and are the only
numbers worth revisiting if the collection's shape changes.

## 1. The clock — `static/activity.js`

The module already knows every event day and, through `lanes[].bought`, every
purchase day. It gains one builder and two lookups, all pure and node-testable
alongside the existing 26 tests.

```js
buildClock(act) -> {
  cum:   [Number],   // length span + 1; cum[d] is the weight before day d
  total: Number,     // cum[span] — the whole run in weight units
}
```

`cum` is monotonically non-decreasing and starts at 0, which is what makes both
lookups a binary search:

```js
dayAtProgress(clock, p)  -> Number   // weight units -> fractional day
progressAtDay(clock, day) -> Number  // fractional day -> weight units
```

The two are inverses at day boundaries. `dayAtProgress` interpolates inside a
day so the playhead moves smoothly rather than stepping, and both clamp to the
axis rather than throwing.

**Weights live as module constants**, not magic numbers at the call site:

```js
const CLOCK_W_BUY   = 6;
const CLOCK_W_EVENT = 1;
const CLOCK_W_EMPTY = 0.04;
```

A collection with no events at all still produces a valid clock — every day
weighs `CLOCK_W_EMPTY`, `total` is positive, and playback degenerates to a
linear sweep. That is the correct behaviour, not a special case.

## 2. The transport — one owner, renamed

Playback today is split across `race*` and `act*` functions. Merging them while
leaving the survivor named `act*` would be actively misleading once it drives
the race chart, and the previous build's reviews found three separate bugs in
exactly this area when transport logic was split across owners.

So the shared transport is `hist*`, and it owns the clock:

| New | Replaces |
|---|---|
| `histPlay()` | `racePlay()`, `actPlay()` |
| `histPause()` | `racePause()`, `actPause()` |
| `histSeek(day)` | `raceSeek(i)`, `actSeek(day)` |
| `histReplay()` | `raceReplay()`, `actReplay()` |
| `histSyncControls()` | `raceSyncControls()`, `actSyncControls()` |
| `histTick(t)` | `raceSchedule()`, `actTick()` |
| `histSetSpeed(s)` | `raceSetSpeed()`, the `[data-act-speed]` handler |

`histTick` advances `histProgress` in weight units at `clock.total / 30` per
second, scaled by speed, then derives the day through `dayAtProgress()` and
paints both charts. `histSeek(day)` goes the other way through
`progressAtDay()`, so the scrubber and the band drag stay in calendar days.

**Deleted outright:** `RACE_BASE_MS`, `raceFrameMs()`, `raceSchedule()`,
`racePlaying`, `raceSpeed`, `raceTimer`, `actPlaying`, `actRaf`, `actLastT`,
`actSpeed`, `actRate()`.

**Redefined, not deleted:** `raceApplyDuration()`. It has three callers
(`raceSnapTo`, and the old play/speed paths) and `raceSnapTo`'s
zero-then-restore dance is still needed to stop a replay running every bar
backwards. It keeps its name and its job — write `--race-dur` — but takes the
duration from the gap arithmetic below instead of from a fixed frame interval.

## 3. The race chart follows the clock

`racePaint(i, animate)` keeps its signature. What changes is who calls it and
with what.

The renderer derives the frame from the day:

```js
raceFrameForDay(day)   // index of the last purchase day at or before `day`, or -1
```

`raceFrames` already carries each frame's `day` as `'YYYY-MM-DD'`;
`buildActivity`'s `d0` and `VinylActivity.dayAt()` convert between that and a
day index, so no new date parsing enters the renderer. The mapping is computed
once per render into an array indexed by day, not searched per frame.

`histPaint` calls `racePaint` only when the derived frame index **changes** —
the same change-detection discipline the activity chart's per-row writes
already use, so 60fps costs nothing while the race chart is between purchases.

**Bar-growth duration.** Today `--race-dur` equals the frame interval, which is
what makes the race read as continuous rather than as a slideshow. Under the
shared clock the interval varies, so on each frame change the renderer sets
`--race-dur` to the wall-clock time until the *next* purchase day:

```js
const msPerUnit = HIST_TOTAL_MS / clock.total / histSpeed;   // HIST_TOTAL_MS = 30000
clamp((progressAtDay(clock, nextBuyDay) - progressAtDay(clock, thisBuyDay)) * msPerUnit,
      120, 900)
```

`msPerUnit` divides by `histSpeed`, so at 2× the bars animate twice as fast and
still finish exactly as the next purchase lands — the property that makes the
race read as one continuous move rather than a slideshow.

Clamped because the gaps are uneven: without a floor a same-week purchase pair
would animate in 40ms, and without a ceiling the 352-day gap would leave bars
crawling for two seconds.

**The tail.** The race chart's last purchase is `2026-08-01`, 20 days before
the axis ends. It holds its final frame for the last ~0.5s of the run. That is
correct — nothing was bought in that window — and `histSyncControls` keys "at
the end" off the **day**, not off `raceIndex`, so the replay button appears when
the whole timeline finishes rather than when the race chart runs out.

## 4. One control bar, pinned

The race chart's transport survives and becomes the tab's. The activity chart's
entire `.race-controls` row (`#actPlayBtn`, `#actScrub`, `.act-speed-btn` ×3,
`#actReplayBtn`) is deleted.

The surviving bar moves out of the race chart's `.chart-box` and becomes the
last child of `#historyPage`, so it spans the tab rather than one chart:

```html
<div class="history-transport" id="histTransport">
  <button class="race-btn" id="racePlayBtn" …>
  <input type="range" id="raceScrub" min="0" max="812" step="1" aria-label="day">
  <div class="race-speeds">… .race-speed-btn ×3 …</div>
  <button class="race-btn hidden" id="raceReplayBtn" …>
</div>
```

`#raceScrub`'s `max` changes from `raceFrames.length - 1` to the last day
index, and its `aria-label` from "purchase day" to "day". The band drag and the
scrubber then operate on the same scale — both calendar days — so the two
gestures agree.

```css
.history-transport{
  position:sticky; bottom:0; z-index:4;
  display:flex; align-items:center; gap:12px;
  padding:12px 0 14px;
  background:var(--bg);            /* the page ground, not the card */
  border-top:1px solid var(--border);
}
@media(max-width:760px){
  /* clear .mobile-tabbar, which is position:fixed, 58px tall, and adds the
     safe-area inset on notched phones */
  .history-transport{ bottom:calc(58px + env(safe-area-inset-bottom, 0px)); }
}
```

The bar is inside `#historyPage`, which is `display:none` on every other tab,
so nothing sticks anywhere else. `background` is `--bg` rather than `--surface`
because the bar sits on the page ground between chart boxes, not inside one.
`z-index:4` keeps it above the charts and below `.mobile-tabbar`'s `80`.

No extra bottom padding is needed: a sticky element stays in flow and occupies
its own space at the end of the container, so the last lane is never trapped
underneath it. Mid-scroll the bar floats over the lanes, which is the point.

The existing `.race-controls` rule stays — the class is gone from the markup
but the rule is harmless, and the widened `#raceScrub, #actScrub` and
`.race-speed-btn, .act-speed-btn` selectors from the previous build get their
now-dead halves dropped in the same pass.

## 5. What the two charts keep

Everything except playback. The activity chart keeps its zoom, show, order,
band-drag, hover-solo, click-through, note card and quiet fade. The race chart
keeps its bars, covers, tooltip and day readout. Neither chart's *rendering*
changes — only what tells it which moment to render.

Both `#raceDay` and `#actDay` currently print a date, and under one clock they
would always agree — so `#actDay` is removed and the activity chart's readout
row keeps only its caption. One playhead, one date on screen.

`#raceDay` becomes that date, and its meaning changes. Today `racePaint` sets
it to `frame.day` — the purchase day being shown. Under the shared clock it
must show **the playhead's day**, which between purchases is not the frame's
day at all. `histPaint` owns that write now, from
`VinylActivity.dayAt(act.d0, day)`; `racePaint`'s own assignment to it is
removed. Without this the readout would freeze on the last purchase date and
sit there for up to 56 days of travel.

## 6. Reduced motion

Unchanged in spirit: the tab opens on the finished state rather than
autoplaying, and every control still works. `histSyncControls` and the opening
seek move to `actLast()` for both charts at once, so the race chart shows its
final frame and the activity chart its final day — which is what each already
did separately.

## 7. Tests

`tests/test_activity.js` grows a `── the clock ──` section covering
`buildClock`, `dayAtProgress` and `progressAtDay`:

- `cum` has length `span + 1`, starts at 0, and is monotonically non-decreasing
- `total` equals the sum of every day's weight
- a purchase day weighs `CLOCK_W_BUY`; an event-only day `CLOCK_W_EVENT`; an
  empty day `CLOCK_W_EMPTY`
- a day that is both a purchase and a play day weighs `CLOCK_W_BUY`, not the sum
- `dayAtProgress(0)` is day 0 and `dayAtProgress(total)` is the last day
- `progressAtDay` and `dayAtProgress` round-trip at day boundaries
- both clamp out-of-range input instead of throwing or returning `NaN`
- a collection with purchases but no other events still yields a positive
  `total` and a usable clock
- a one-day collection produces `cum.length === 2` and does not divide by zero

The pacing arithmetic is a property worth pinning too, because it is the whole
point of the design: on a synthetic collection with a known shape, assert that
the empty run's share of `total` is under a stated bound while the event days'
share is over one. That test fails loudly if a weight is ever changed
carelessly.

The animation stays untestable and stays in
`docs/history-tab-manual-verification.md`, which gains: one playhead moving in
both charts at once; the scrubber and band drag agreeing; the sticky bar
staying put while the lanes scroll and clearing the mobile tab bar; and the
race chart holding its last frame for the final 20 days.

## 8. Files

| File | Change |
|---|---|
| `static/activity.js` | **modify** — `buildClock`, `dayAtProgress`, `progressAtDay`, three weight constants |
| `tests/test_activity.js` | **modify** — the clock section |
| `templates/index.html` | **modify** — delete the activity transport; move and pin the race transport; `hist*` transport replacing both; `raceFrameForDay`; `--race-dur` from the real gap; drop `#actDay`; CSS for the sticky bar |
| `docs/history-tab-manual-verification.md` | **modify** — shared-clock checks |

No Python, no schema change, no new dependency.

## Out of scope

- Changing either chart's rendering, controls or data model beyond playback.
- Making the sticky bar appear on any other tab.
- Per-record-count weighting of purchase days — a nine-record day gets the same
  465ms as a one-record day, because the bars animate in parallel and nine
  records do not need nine times the screen time.
- Preserving the ability to play the two charts independently. That is the
  point of the change.
