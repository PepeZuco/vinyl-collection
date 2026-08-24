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
