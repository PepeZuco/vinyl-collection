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
   edge — one segment per disc.
3. **Every other card is unchanged, with no bar at all.** A mark on all 250
   cards is the failure this design exists to avoid.
4. At phone width the stack does not push a card into its neighbour.

---

## The drawer

5. A record with no tracklist opens on **Info**, not on an empty Tracks tab.
6. Its Tracks tab reads *no tracklist yet* and, unlocked, offers **add the
   songs** — which opens the form at step 4.
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
13. Clicking the date accepts `2026-08-02` and rejects `hello`.
14. Locked (not in edit mode), hearts render but do not respond.
15. Stop the server, tap a heart: it fills, reverts, and says it could not save.

---

## The timeline

16. A like appears on its day in the **Calendar**, in the **History** tab and in
    the record's own **Timeline** tab, reading *Liked <song>*.
17. The calendar's heart button switches likes off and on.
18. On a day with a play, a like and a note, they read in that order.
19. **Known limitation:** A like backdated to before the collection's earliest
    bought/played/cleaned/note date will not be reachable by scrolling the
    calendar's date range. The History tab still lists it correctly. This is
    expected behaviour; the calendar range is computed from event dates other
    than likes.

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

---

## The backup

27. `/api/export` then `/api/import` of that file preserves tracks, likes,
    disc count and size.
