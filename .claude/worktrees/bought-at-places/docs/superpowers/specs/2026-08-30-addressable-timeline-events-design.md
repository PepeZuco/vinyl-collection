# Addressable Timeline Events

## Problem

Two complaints with one cause.

Clicking a cover in the Timeline opens the record but says nothing about why you
clicked it. You saw a purple border, so you knew there was a note; the drawer
that opens shows the record's whole history with the note somewhere inside it,
and you go looking for the thing you had already found.

And a record you bought, cleaned, played twice and wrote a note about on one
Sunday draws as five identical covers in one 150-pixel column. Four kinds of
fact wearing four border colours, decoded one at a time.

The cause is that an event has no name. `eventsByDay` (`static/timeline.js:31`)
produces `{type, r, time}` tuples that only ever get drawn, and every chip's
click handler throws all of it away except `r.id`:

```js
onclick="event.stopPropagation();openDetailFromCal(${r.id})"
```

So a chip cannot say which event it came from, and several events about one
record cannot merge into one chip without losing what they were. Give an event
a name and both halves fall out of it.

This is not only a Week problem. Month draws one `cal-pill` per event and hides
the rest behind `+N more`; the Day agenda draws a full `cal-event` row per
event. All three zooms collapse to **one entry per record, per day**.

## The event key

A new pure function in `static/timeline.js`:

```js
keyOf(ev)  // 'played:2026-03-08T21:47:02:1'
```

| Type | Key | Why |
|---|---|---|
| bought | `bought:<bought_date>` | `bought_date` is one column, so a record has at most one, ever |
| cleaned | `cleaned:<at>:<i>` | `i` is the position in `parseCleanedDates(r.cleaned_dates)` |
| played | `played:<at>:<i>` | `i` is the position in `parsePlayDates(r.play_dates)` |
| note | `note:<date>:<i>` | `i` is the position in `parseNotes(r.notes, r.bought_date)` |

The index is not redundant. `nowStamp()` keeps seconds, so anything logged
through the app is already unique — but rows written before times were kept
carry a bare `YYYY-MM-DD`, and two clockless cleanings on one day would collide
on the stamp alone. Indexing every list-backed type is uniform and costs
nothing. Bought needs no index because its column cannot hold two.

The key is computed once, in `eventsByDay`, and rides on the event alongside
`type` and `r`. Every renderer reads it rather than deriving it.

Keys are stable for the life of a page load, which is all the click needs. They
are not durable identifiers: inserting a note ahead of another shifts the second
one's index, and `records` is re-fetched after any edit anyway.

## Record-days

A second pure function, beside `eventsByDay` rather than inside it — the
existing model and its tests stand unchanged:

```js
recordDays(dayEvents)  // one day's events -> one entry per record
```

Given the list `eventsByDay` files under a day, it returns:

```js
[{ r, day, acts: [{ type, evs: [ev, ...] }, ...], evs: [ev, ...] }]
```

- `acts` is sorted by the existing `TYPE_ORDER` — bought, cleaned, played, note.
  A record is bought before it is cleaned, cleaned before it is played, and a
  note comes after the thing it describes.
- Entries are ordered by each record's **earliest** event that day, falling back
  to album name, which is the tiebreak `eventsByDay` already uses. A record's
  place in the column is where its day started.
- `evs` keeps the day's flat, chronological list for the whole-day focus.

## Week

`calWeekChip` becomes `calRecordDayChip`. The cover gets a neutral
`var(--border)` — it stops spending its only channel on activity type — and the
day's actions line up beneath it as coloured icons.

**The count rule, entire:** the icon is always drawn; a numeral joins it only
when that action happened more than once that day. A lone icon means once.
Nothing in the grid ever prints a `1`.

Bought needs no exception in the code. Its count cannot reach two, so the
`> 1` test never fires for it.

The icons are already decided: the Timeline's own type filter bar
(`templates/index.html:1736`) draws `ti-shopping-bag`, `ti-droplet`,
`ti-headphones` and `ti-note`. The rail uses that set, so the icon on a chip and
the icon on the switch that hides it are the same glyph. Tabler is loaded as a
full webfont, so the same four hold at 15px, 11px and 10px with no second asset.

The record drawer draws three of them already (`DM_HIST_ICON`) and has no icon
for notes; it gains `ti-note` here, which is what makes a note's history entry
and its chip icon match.

At 390px the week column is about 46 pixels, leaving roughly 40 for the rail.
Four icons in 40 pixels is 10 pixels each: readable, and far below a tappable
target. **So the rail changes job by width.** At `≤760px` (the breakpoint the
week grid already uses, `templates/index.html:1585`) the rail takes
`pointer-events:none`, its icons drop to 10px, its numerals drop entirely, and
the whole chip taps through to `openCalDay(day)` — where every action is a full
row. One extra tap, on the device where you are browsing rather than aiming.

## Month

A `cal-pill` becomes one record-day rather than one event: the act icons at
11px, then the album text. `+N more` counts record-days, so fewer cells reach
the three-entry ceiling than do today.

Month pills carry **icons only, no numerals**. A pill is a line of text in a
cell about 120 pixels wide, and the numerals are the first thing that stops
fitting. The count is one zoom away in Week and Day.

`cal-cell-dots` keeps its one dot per distinct type, unchanged.

## Day and the day modal

`calEventRow` becomes `calRecordDayRow`, one row per record-day, used by both
the Day view and the modal a month cell opens.

The `.cal-badge` at the end of the row — which today names one type — becomes
the same rail, each icon a click target. Where the day includes notes, every
note's text renders in full inside the row, as it does today, each carrying its
own key.

## Focus: three widths

`openDetail(id, focus)`, narrowest first:

| Clicked | Focus | Lights |
|---|---|---|
| an icon that happened once | `note:2026-03-08:0` | that entry, and its date |
| an icon carrying a numeral | `2026-03-08~played` | that day's plays, and its date |
| the cover | `2026-03-08` | the whole day |

The middle width earns its place. Two plays cannot resolve to one play, but
routing them to the whole day drags the cleaning and the purchase in with them,
which is not what you clicked.

`focus` is optional. Every existing caller of `openDetail(id)` keeps working and
opens with no highlight.

`dmHistoryEntryHTML` stamps `data-ev="<key>"` on each entry and `data-day` on
both the entry and its group header, so all three widths resolve through one
`querySelectorAll`.

## The highlight

**Tint and rail.** The matched entry takes a 20% wash of its own activity colour
and a 3px rail down its left edge; the date header takes the same wash. For a
whole-day focus each entry keeps its own colour and the header takes the app's
gold, since there is no single colour a four-kind day could wear.

Five seconds: 4.2s held, then 800ms fading out. `prefers-reduced-motion` keeps
the tint and drops the transition.

The drawer shows the record's **complete** history throughout — every day group,
every event, oldest to newest. The highlight is additive and never filters. The
surrounding history is usually why the click was worth making.

## Surviving the re-render

This is the part that will bite.

`openDetail` calls `dmCenterSlide` / `ddCenterSlide`; the carousel's scroll
handler calls `dmSetCurrent`, which rewrites `#dmInfo` and `#ddInfo` wholesale
(`templates/index.html:3350`). Any class the highlighter added after render is
gone on the next scroll frame.

So the focus lives in a module variable that `dmInfoHTML` **reads while
building the HTML**, not in a class applied afterwards:

```js
let detailFocus = null;   // {focus, until} or null
```

- `openDetail(id, focus)` sets it before `renderDetailContent`.
- `dmInfoHTML` stamps `hit` on the matching entries as it renders, so every
  re-render reproduces the highlight rather than losing it.
- One `setTimeout` at 4.2s clears `detailFocus`, applies `fading` directly to
  the live nodes, and removes it 800ms later.
- The timer is cleared by `closeDetail` and by `goToDetailRecord`, so navigating
  to another record never carries a stale highlight or fires a timer against a
  detached node.

**Open scrolled, do not scroll after.** On mobile the History sits below the
cover carousel, the crate strip and the metadata grid. `.overlay.hidden` is
`display:none`, so there is no layout to scroll while hidden — the scroll has to
follow `classList.remove('hidden')` in the same task, before paint, exactly as
`openDetail` already does for `dmCenterSlide`. Otherwise the first of the five
seconds is spent watching the page move.

## Colours

The Timeline paints its four types as literals — `#F5C518`, `#4AA3C4`,
`#5FBF7A`, `#9B7FD4` — in `cal-dot`, `cal-badge` and `cal-week-chip`. The
Insights activity strip paints the same four facts from `--ev-bought`,
`--ev-cleaned`, `--ev-played`, `--ev-note`, which hold entirely different values
(`#ac9008`, `#0b9d9d`, `#2171cc`, `#a5397e`).

Two palettes for one set of four facts, and this change makes activity colour
the primary carrier of meaning in three views. The Timeline's literals move into
the existing `--ev-*` tokens, adopting the Timeline's values.

**This changes the Insights activity strip's colours**, which is the visible
consequence of having one palette instead of two. See *Decide at review*.

`bought` also stops being `var(--accent)`. It is the only one of the four that
changes between themes, and in light mode the accent is `#7A5A00` — a dark
olive, which is not what "gold means bought" is trying to say. It takes a
theme-aware pair of its own: `#F5C518` dark, `#b39609` light (the value
`--ev-bought` already carries there), so it stays gold in both without being
coupled to the accent.

## Testing

`keyOf` and `recordDays` are pure functions in `static/timeline.js`, so they
join `tests/test_timeline.js`, run by `tests/test_timeline.py` under `node
--test`. Cases:

- a key is stable across two calls for the same event
- two clockless cleanings on one day get different keys
- bought's key carries no index
- a record with four kinds on one day collapses to one entry with four `acts`
- `acts` come back in bought-cleaned-played-note order regardless of input order
- two plays on one day land in one `act` with two `evs`
- record-days are ordered by each record's earliest event, album name breaking ties
- a day with two records returns two entries

The click-through is DOM-shaped, so it goes in `tests/test_boot.js`, which
already boots the real template in jsdom:

- each of the three focus widths marks exactly the intended entries and no others
- a whole-day focus marks every entry of that day and the header
- a re-render (`dmSetCurrent`) preserves the highlight
- `closeDetail` during the five seconds leaves no timer firing against a
  detached node
- `openDetail(id)` with no focus highlights nothing

## Decide at review

1. **The palette.** Unifying on `--ev-*` changes the Insights activity strip's
   colours to the Timeline's. The alternative is leaving both palettes and
   fixing only `bought` — smaller, but it keeps two answers to one question.
2. **Month numerals.** Dropped at pill size above. If a month cell should carry
   counts, the pill needs to lose something else to fit them.

## Interactions with work in flight

`2026-08-30-note-pictures-design.md` touches two of the same places and neither
collides:

- It adds an optional `images` key to each note object. Note keys index into the
  `parseNotes` array, whose shape and order are unchanged, so keys are unaffected.
- It appends a thumbnail strip inside the note branch of `dmHistoryEntryHTML`;
  this adds `data-ev` / `data-day` to the entry wrapper and a `hit` class. Same
  function, different parts. Whichever lands second rebases trivially.
- Its Calendar section reads "Unchanged", so it makes no claim on the week,
  month or day renderers this spec rewrites.

## Out of scope

- The Replay scale. It answers "how did we get here" over the whole collection
  and has no per-day entries to collapse.
- Making event keys durable across edits. They live for one page load.
- The shelf, the filter bar, and every other caller of `openDetail`, which keeps
  its one-argument form.
