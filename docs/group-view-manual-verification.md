# Crates — manual verification

Grouping is now its own control, independent of sorting. `Group by` decides what
the crates are; `Sort by` decides how records run inside them.

The bucket and ordering rules are covered by `tests/test_grouping.js` (47 tests,
run through `pytest` via `tests/test_grouping.py`), and the whole pipeline was
driven over the real 259-record collection — every crate set totals 259, and
flattening the crates reproduces the sorted list in all of them. The
`localStorage` migration was exercised against the real `loadGroupBy` source.

What follows is what none of that reaches: how it *looks*, and how it behaves on
a real phone.

Tick the ones that pass; anything that fails, tell me what you saw.

---

## 1. Desktop

1. The toolbar has **two** dropdowns side by side: **Crates** on the left,
   **Sort by** (with its direction arrow) on the right. The old grid/group
   toggle in the top-right corner is **gone**.
2. The Crates dropdown opens to nine entries: *No crates*, then Month added,
   Genre, Country, Decade, Album initial, Rating, Plays, Last played. There is
   a divider under *No crates*.
3. Pick **No crates**. Plain grid, no headers — this is what the old grid button
   used to do.
4. Pick **Genre**. Twelve crates, running *Blues → Classical → … → Rock →
   Soul & Funk*, with **Unknown genre** last.
5. Each header shows a record count on the right, and the counts add up to the
   record count in the page header.
6. Cards inside crates look exactly like grid cards: hover lift, quick-edit
   pencil (when logged in), play-count +/−, rating squares, country flag.
7. Now change **Sort by** to *Year* without touching Crates. The crates stay put
   as genres; only the order of the cards inside them changes.
8. Pick **Country**. Headers show a **flag** followed by the country name —
   *Brazil*, *United States*, *United Kingdom* — with **Unknown country** (137
   records) last.
9. Flip the sort direction arrow. The crates reverse *and* the cards in them do,
   but **Unknown country stays at the bottom** rather than jumping to the top.
   This is the one ordering rule worth staring at.
10. Scroll a long crate. Its header **sticks** to the top of the window and is
    replaced by the next crate's header as you pass into it.
11. Click a header. The crate collapses, the chevron rotates, the header stays.
12. Reload the page. The crate you collapsed is **still** collapsed, and you are
    **still grouped by country** — the choice persists.
13. Switch to **Genre**. Nothing is collapsed — the collapse from step 11 belongs
    to *Country* only. Switch back to Country; it is still there.
14. Hit **collapse all**, then reload. Everything is still shut and the button
    reads *expand all*.
15. **Decade** → 2020s…1950s, *Year unknown* last. **Rating** → star bands,
    *Unrated* last. **Plays** → play bands; note *Never played* is a real band
    here and **does** flip with the arrow. **Last played** → calendar months,
    *Never played* (149 records) last.
16. **Album initial** → 25 crates, `#` first (digits and symbols share it).
17. Type something in search that matches nothing. You get the normal empty
    state, not an empty crate.
18. Search something that matches a little. Crates that lost all their records
    disappear rather than showing "0 records".
19. Open a record from inside a crate, then use the **←/→** arrows in the detail
    drawer. It walks records in the order they appear on screen, crossing from
    one crate into the next.
20. Both themes: crate headers, the count, and the country flags read cleanly in
    light and dark.
21. Narrow the window until the toolbar wraps. Two dropdowns plus the genre
    filter and buyer toggle should wrap tidily, not overflow.

## 2. Phone (this is the part with no coverage at all)

1. Tap the **filters** button. The sheet's first section is **Crates**, above
   *Sort by*. The old on/off switch and its "Change the sort above and this
   follows it" hint are gone.
2. It is a full-width dropdown reading whatever you are grouped by.
3. Pick **Genre**, tap **Show records**. The collection is in genre crates.
4. Headers are a filled rounded row, tall enough to tap comfortably, with the
   count in a pill on the right.
5. Cards sit **two per row** inside each crate.
6. Scroll. Headers stick to the top and don't collide with anything.
7. Tap a header to collapse. Tap it again to expand.
8. Reopen the sheet — it still reads *Genre*.
9. Pick **Country**. Flags render at the right size in the header at phone
   widths, and the name isn't clipped.
10. Pick **No crates**. Back to a plain two-column grid.
11. Rotate to landscape, or try a tablet width: crates still read correctly at
    three and four columns.

## 3. Upgrading from the old toggle

Checked against the real `loadGroupBy` source, all paths passing:

| what the browser was holding | opens as |
|---|---|
| nothing (fresh visit) | grouped by **Month added** |
| `vinyl-view: 'group'` | grouped by **Month added**, old key cleared |
| `vinyl-view: 'grid'` | **No crates** |
| `vinyl-view: 'list'` (retired) | **No crates** |
| `vinyl-group: 'genre'` | grouped by **Genre** |
| `vinyl-group:` garbage | grouped by **Month added** |

Nothing expected here, but worth one glance on your own machine if you had the
old group view selected.
