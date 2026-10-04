# Admin page — manual verification

Run locally with `ANTHROPIC_API_KEY`, `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`
set, logged into edit mode.

## Menu

1. As a visitor, open ⋯ — there is no **admin** item, and no places / export / backups / import.
2. Enter edit mode, open ⋯ — **admin** is there; the four old items are not.
3. Pick **admin** — the page opens, the filter bar hides, the menu closes.
4. Lock edit mode from ⋯ while on admin — you land on the collection.
5. Reload with `?tab=admin` in the URL — you land on the collection.

## Places and data

6. Places: add, rename, merge (rename onto an existing name), delete — same as the old modal.
7. Export CSV downloads; import CSV of that file adds records and toasts the count.
8. Backups lists snapshots newest first and each downloads.

## Spotify → wishlist

9. With Spotify disconnected the section shows only **connect Spotify**; connecting returns to the app.
10. Connected: your playlists list with counts. Pick a ~30-song playlist, press **scan**.
11. The progress line reads "reading songs and naming albums…", then "checking vinyl N / M".
12. Rows: one per album; songs listed under each; owned albums say "in collection" and cannot be ticked;
    confirmed rows start ticked, likely unticked, no-vinyl greyed.
13. Press **add N to wishlist** — the toast counts them, the rows flip to "on wishlist",
    and the records appear under the wishlist filter with covers.
14. Stats → spend: the month total went up (source "playlist" rows in the ledger).
15. A 500+ song playlist: the note says only the first 500 songs were read, and the scan finishes.
16. Phone width (≤ 400px): no horizontal scroll on the admin page; rows ellipsize.
