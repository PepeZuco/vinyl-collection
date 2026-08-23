# Group view — manual verification

The bucket rules are covered by `tests/test_grouping.js` (21 tests, run through
`pytest` via `tests/test_grouping.py`), and the render path was driven headlessly
against the real page. What follows is what neither can reach: how it *looks*,
and how it behaves on a real phone.

Tick the ones that pass; anything that fails, tell me what you saw.

---

## 1. Desktop

1. Top-right corner shows **two** buttons: grid and group. The old list button
   is gone.
2. Click **group**. The collection divides into crates, headed by the field in
   **Sort by** — with the default sort, calendar months like *August 2026*.
3. Each header shows a record count on the right, and the counts add up to the
   record count in the page header.
4. Cards inside crates look exactly like grid cards: hover lift, quick-edit
   pencil (when logged in), play-count +/−, rating squares, country flag.
5. Scroll a long crate. Its header **sticks** to the top of the window and is
   replaced by the next crate's header as you pass into it.
6. Click a header. The crate collapses, the chevron rotates, the header stays.
7. Reload the page. The crate you collapsed is **still** collapsed.
8. Change **Sort by** to *Artist*. Crates become one per artist, and nothing is
   collapsed — the collapse from step 6 belongs to *Date added* only.
9. Go back to *Date added*. Your collapsed crate is still there.
10. Hit **collapse all**, then reload. Everything is still shut and the button
    reads *expand all*.
11. Flip the sort direction arrow. Crates reverse along with the cards in them.
12. Sort by *Year* → decades. *Total rating* → star bands. *Plays* → play bands
    ending in *Never played*.
13. Type something in search that matches nothing. You get the normal empty
    state, not an empty crate.
14. Search something that matches a little. Crates that lost all their records
    disappear rather than showing "0 records".
15. Open a record from inside a crate, then use the **←/→** arrows in the detail
    drawer. It walks records in the order they appear on screen, crossing from
    one crate into the next.
16. Switch back to **grid**. Ordinary grid, no headers. Reload — still grid.
17. Both themes: crate headers and the count read cleanly in light and dark.

## 2. Phone (this is the part with no coverage at all)

1. The top-right grid/group toggle is **not** visible — it's desktop-only.
2. Tap the **filters** button. The sheet now has a **Crates** section directly
   under *Sort by*.
3. The switch reads **Group by date added** — naming whatever the sort field
   currently is.
4. Change *Sort by* to *Year* without leaving the sheet. The switch relabels
   itself to **Group by year** immediately.
5. Turn the switch on. Tap **Show records**. The collection is in crates.
6. Headers are a filled rounded row, tall enough to tap comfortably, with the
   count in a pill on the right.
7. Cards sit **two per row** inside each crate.
8. Scroll. Headers stick to the top and don't collide with anything.
9. Tap a header to collapse. Tap it again to expand.
10. Reopen the sheet — the switch is still on and still names the sort field.
11. Turn the switch off. Back to a plain two-column grid.
12. Rotate to landscape, or try a tablet width: crates still read correctly at
    three and four columns.

## 3. Upgrading from the old list view

Already checked headlessly — a browser holding the retired `'list'` in
`localStorage['vinyl-view']` opens in grid, with no errors. Worth one glance on
your own machine if you had list view selected, but nothing is expected here.
