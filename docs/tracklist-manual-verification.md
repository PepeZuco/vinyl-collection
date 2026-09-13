# Tracklists — what to check by hand

The automated tests cover the rules (`tests/test_tracks.js`), the endpoints
(`tests/test_tracks_endpoint.py`), the events (`tests/test_timeline.js`) and
the search field (`tests/test_filters.js`). What follows is what only an eye
can settle. No part of this UI has been seen running; every implementer worked
without a browser and said so.

---

## The grid

1. Set one record to `disc_count: 2`, another to `3`, and another to `4` — the
   highest the form's Discs picker offers.
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

29. `/api/export` then `/api/import` of that file preserves tracks, likes,
    disc count and size.

---

## Who plays each song (multi-artist records)

The picker and the credit under the title are the only two things this feature
draws. Neither has been seen in a browser.

30. On a record with **one** artist, step 4 shows no picker at all — the song
    row is exactly what rule 25 already describes.
31. On a record whose artist field holds `Edu Lobo; Gal Costa`, every song row
    grows a small select offering *— who plays it —*, `Edu Lobo` and
    `Gal Costa`, and nothing else.
32. **At phone width the select must not squeeze the title input to nothing.**
    It is `flex:0 1 118px`, so it is allowed to shrink; check that the title is
    still the widest thing on the row and that the row does not wrap oddly or
    push the heart and × buttons off the edge.
33. Type the two artists into the **single** artist field as `A; B` on step 1,
    without ticking *multiple artists*, then walk to step 4: the pickers offer
    both. (The tick box is a way of editing the same semicolon-separated field,
    not a separate mode.)
34. Tick *multiple artists*, add a third artist row, then go to step 4 — the
    pickers offer all three. Coming back to step 1 and renaming one updates the
    pickers without losing what was already chosen.
35. Credit a song, then rename that artist's row: the song follows the new
    name. Check the select actually shows the new name, not a blank.
36. Credit a song, then press the trash on that artist's row: it is **refused**
    with a toast naming how many songs still credit them. The row stays.
37. Same again, but clear the artist's name to empty instead of pressing the
    trash: also refused, and the name comes back in the input.
38. An artist nobody is credited to is removed with no fuss.
39. In the drawer's **Tracks** tab, a credited song shows the name in small
    muted type under the title; an uncredited one shows nothing at all and does
    not borrow the record's artists. **Check both themes** — the credit uses
    `--muted` on the row's hover ground.
40. A long artist name under a long title must wrap rather than push the like
    date and heart out of the row.
41. Search with only the default fields ticked (**Song** still unticked) finds
    the compilation by a name that appears *only* on a song — a guest who is
    not in the artist field. Ticking **Song** off and on changes nothing about
    that; unticking **Artist** hides it.
42. `/api/export` then `/api/import` preserves the credits along with the rest.
