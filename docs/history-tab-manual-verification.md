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

- [ ] Toggling the theme mid-race re-renders the tab in the new palette — this
      restarts the race from frame 0 and autoplays; that is expected, not a bug.
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
