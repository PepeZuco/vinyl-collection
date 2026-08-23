# Group view — manual verification

The bucket rules are covered by `tests/test_grouping.js` (28 tests, run through
`pytest` via `tests/test_grouping.py`), and the render path was driven headlessly
against the real page. What follows is what neither can reach: how it *looks*,
and how it behaves on a real phone.

Crates are no longer a mode you switch into — they are the collection. There is
no grid/group toggle on either desktop or phone.

Tick the ones that pass; anything that fails, tell me what you saw.

---

## 1. Desktop

1. The top-right corner has **no** grid/group buttons. Nothing sits to the right
   of the dice — the toolbar just ends there, and the row still lines up.
2. The collection opens **in crates**, headed by the field in **Sort by** — with
   the default sort, calendar months like *August 2026*. No reload, no click.
3. Each header shows a record count on the right, and the counts add up to the
   record count in the page header.
4. Cards inside crates look exactly like the old grid cards: hover lift,
   quick-edit pencil (when logged in), play-count +/−, rating squares, flag.
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
16. Both themes: crate headers and the count read cleanly in light and dark.

## 2. Last played (new sort field)

1. **Sort by** now offers **Last played**, at the bottom of the list.
2. Pick it. Crates are calendar months again — the month of each record's *most
   recent* play, newest month first.
3. A record played three times sits in the month of the **latest** play, not the
   first one.
4. The **Never played** crate is last, and holds every record with no plays.
   Its count plus the month counts equals the header count.
5. Flip the sort direction. The months reverse and *Never played* leads.
6. Play a record from the detail drawer (the **+**). It jumps to the current
   month's crate on the next render.
7. Collapse a crate here, then switch to *Date added* and back — the collapse
   belongs to *Last played* on its own, like every other field.

## 3. "Artist country" label

1. Open any record. The bottom-right meta cell now reads **Artist country**, not
   *Country* — so it no longer looks like the country you bought it in.
2. The label fits on **one line** in the cell, and the four meta cells stay a
   tidy 2×2 (check a narrow window too).
3. The edit form's field, under *The record*, carries the same name.

## 4. Phone

1. Tap the **filters** button. The sheet has *Sort by*, *Genres* and *Buyer* —
   the old **Crates** switch is gone.
2. The collection is in crates without you asking for it.
3. Headers are a filled rounded row, tall enough to tap comfortably, with the
   count in a pill on the right.
4. Cards sit **two per row** inside each crate.
5. Scroll. Headers stick to the top and don't collide with anything.
6. Tap a header to collapse. Tap it again to expand.
7. Choose *Last played* in the sheet and tap **Show records** — months again,
   *Never played* at the end.
8. Rotate to landscape, or try a tablet width: crates still read correctly at
   three and four columns.

## 5. Upgrading from the old toggle

A browser that still holds `localStorage['vinyl-view']` from before (`'grid'`,
`'group'`, or the long-retired `'list'`) now ignores it entirely and opens in
crates. Checked headlessly; worth one glance on your own machine if you had grid
selected, but nothing is expected here.
