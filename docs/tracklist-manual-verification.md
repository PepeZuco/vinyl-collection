# Tracklists — what to check by hand

The automated tests cover the rules (`tests/test_tracks.js`), the endpoints
(`tests/test_tracks_endpoint.py`), the events (`tests/test_timeline.js`) and
the search field (`tests/test_filters.js`). What follows is what only an eye
can settle. No part of this UI has been seen running; every implementer worked
without a browser and said so.

---

## The grid

1. Set one record to `disc_count: 2` and another to `3`.
2. Both grow sleeves behind the cover and a segmented gold bar down the left
   edge — one segment per disc. **Check this in both themes, not just
   whichever one happens to be open.** Dark is the default theme and the one
   actually at risk: the sleeve sits on `.vcard-cover`'s near-black `#111`
   ground, and dark's sleeve colour must read as a visibly lighter sliver
   against it, not blend into it. (Light's high-contrast card-hover colour
   made this easy to miss — it was never the theme in danger.)
3. **Every other card is unchanged, with no bar at all.** A mark on all 250
   cards is the failure this design exists to avoid.
4. At phone width the stack does not push a card into its neighbour.

---

## The drawer

5. A record with no tracklist opens on **Info**, not on an empty Tracks tab.
6. **Click the Tracks tab button itself** on that same no-tracklist record.
   It must actually switch and show *no tracklist yet* plus, unlocked, a
   **+ add the songs** button that opens the form at step 4 — the tab has to
   be reachable by clicking it, not just skipped past on open.
7. A record with songs opens on **Tracks**.
8. Paging with the arrows keeps you on the tab you chose, except where rule 5
   sends you back to Info.
9. A single LP shows sides A and B with **no** "Disc 1" heading; a double shows
   the disc headings.
10. The **Format** cell reads `—`, `12"` and `2 × 12"` in the three cases.

---

## Liking

11. Tapping an outline heart fills it and shows today's date. Reload: it is
    still there.
12. Tapping it again clears both.
13. Clicking the date accepts `2026-08-02` and rejects both `hello` and
    `2026-02-30` (a date that is the right shape but does not exist —
    accepting it used to desync the drawer, which stayed liked, from the
    Calendar, where the like silently vanished).
14. Locked (not in edit mode), hearts render but do not respond.
15. Stop the server, tap a heart: it fills, reverts, and says it could not save.

---

## The timeline

16. A like appears on its day in the **Calendar**, in the **History** tab and in
    the record's own **Timeline** tab, reading *Liked <song>*.
17. The calendar's heart button switches likes off and on.
18. On a day with a play, a like and a note, they read in that order.
19. Backdate a like to well before the collection's earliest
    bought/played/cleaned/note date (e.g. 1976 on a collection that starts in
    2019). Scroll/navigate the Calendar back to that year: the date is
    reachable and the like shows there. (`calUpdateDateRange` now folds
    `liked_at` into the range alongside the other date fields — a backdated
    like used to be permanently out of the calendar's navigable range.)

---

## Search

20. The **Song** checkbox is unticked on load.
21. A song title finds nothing until it is ticked, then finds its record.

---

## The form

22. Discs 2 grows sides C and D.
23. Discs back to 1 with a song on side C refuses, naming side C.
24. Pasting `1. Mother` / `02 - Hey You (4:40)` yields `Mother` and `Hey You`.
25. The up-arrow swaps within a side and never moves a song across sides.
26. A half-typed tracklist survives closing and reopening the tab.
27. The four glyphs this step and the drawer introduced actually render —
    each should show a real icon, not an empty box: the filled heart
    (`ti-heart-filled`), the Size picker's ruler (`ti-ruler-measure`), the
    Discs picker / drawer Format cell's stacked discs (`ti-stack-2`), and the
    paste box's clipboard (`ti-clipboard-text`).
28. **Known annoyance:** pasting a tracklist into a side's paste box, then
    clicking any *other* control in this step before it registers, re-renders
    the step and discards what was just pasted. Paste, then click somewhere
    other than a live control to let it settle, or use the resulting rows
    directly.

---

## The backup

27. `/api/export` then `/api/import` of that file preserves tracks, likes,
    disc count and size.
