# Admin page — design

Date: 2026-10-04

## Goal

One edit-mode **admin** page, opened from the header's ⋯ menu, that holds the
owner's housekeeping tools in one place:

1. **Places** — the bought-at places editor.
2. **Data** — export, import, backups.
3. **Spotify → wishlist** — pick one of the owner's Spotify playlists; Claude
   names each song's original studio album, MusicBrainz checks it was pressed
   on vinyl, and the owner ticks which albums go on the wishlist.

## What stays as it is

- Every existing endpoint: `/api/places*`, `/api/export`, `/api/import`,
  `/api/backups*`, `/api/spotify/connect|callback|disconnect|account`.
- `places.js` and the backups rendering — moved into the page, not rewritten.
- Spotify OAuth, `SpotifyAccount`, the `_spotify_client(acct)` helper and its
  retry/429 handling. The existing scope `playlist-read-private` already
  covers reading the owner's playlists; no re-consent.
- The wishlist model: a `Record` with `have_it=False`.
- The vinyl check: `scan.flag_vinyl` (MusicBrainz + `confirm_vinyl`).
- Visitors: nothing changes for them. Export is already edit-mode only.

## 1. Page and menu

- The ⋯ menu (`#moreMenu`) loses its **places**, **export**, **backups** and
  **import** items and gains one **admin** item (`ti-settings`), shown only in
  edit mode (same toggle in the edit-mode setter that shows those items today).
- Admin is a tab like stats/playlists: `#adminPage` (`.admin-page`), shown via
  `switchTab('admin')`. It has no desktop tab button or mobile tab-bar slot —
  the ⋯ menu (and the mobile "More" sheet) is the only door. The filter bar
  is hidden on it, as on playlists.
- Leaving edit mode while on admin switches back to `collection`.
- Three sections, stacked, each with a small heading:
  - **Places** — `places.js` renders into `#adminPlacesBody` instead of the
    `#placesOverlay` modal body.
  - **Data** — export button, import file picker, and the backups list
    rendered inline (`#adminBackupsBody`) with the existing `renderBackups`.
  - **Spotify → wishlist** — see section 2.
- `#placesOverlay`, `#backupsOverlay`, `openPlaces/closePlaces`,
  `openBackups/closeBackups` and the old menu items are removed (the menu
  items are their only callers).

## 2. Spotify → wishlist

### Owner flow

1. Not connected → the section shows the existing connect button and nothing
   else.
2. Connected → a list of the owner's playlists (owned and followed): cover,
   name, song count. Picking one shows a **scan** button.
3. Scan → one live progress line: `reading songs… N` → `identifying albums
   N / M` → `checking vinyl N / K`.
4. Result → a **review list, one row per album**:
   - cover, artist, album, year, vinyl badge (confirmed / likely / none),
     and the playlist songs that led to it ("3 songs: Hey Jude, Let It Be, …").
   - **confirmed** — ticked by default.
   - **likely** — shown, unticked by default.
   - **none** — greyed, cannot be ticked.
   - **already have** — matches a record in the collection or wishlist;
     greyed, cannot be ticked, labelled "in collection" / "on wishlist".
   - **unverified** — the album came from the Spotify fallback (see errors);
     unticked by default.
   - If the playlist was cut at the cap, a note says so.
5. **add N to wishlist** → the same path search's wishlist add uses today,
   then a toast `N added to the wishlist` and the added rows flip to
   "on wishlist".

### Server

**`GET /api/spotify/me/playlists`** — `@require_auth`. Reads
`client.pages("/me/playlists")` and returns
`{playlists: [{id, name, image_url, track_count, owner}]}`. 409 with
`{error: "not_connected"}` when there is no `SpotifyAccount`.

**Why two routes, not one stream.** Production runs gunicorn with
`--timeout 120` and MusicBrainz is throttled to one call a second, so a
500-song playlist (a few hundred albums) cannot be resolved inside one
request. The work is split the way the playlist sync already splits its
long reads: the server does the fast part in one call, and the browser feeds
the slow part back in chunks, showing progress between them.

**`POST /api/spotify/wishlist-scan`** `{playlist_id}` — `@require_auth`.
The fast part, one JSON response:

1. **Read tracks** — `spotify_sync.playlist_tracks(client, playlist_id)`
   (new): `[{title, artists, album, release_year, image_url}]`, skipping
   local files, episodes and null tracks. Capped at **500** songs
   (`PLAYLIST_SCAN_CAP`); `truncated: true` in the result when cut.
2. **Identify albums** — `scan.identify_albums(tracks, usage_out)` (new):
   Claude Haiku (`IDENTIFY_MODEL = "claude-haiku-4-5"`), batches of 50
   songs run in parallel (4 workers), structured JSON output. Per song:
   `{artist, album, year}` = the song's **original studio album** by that
   artist (not a compilation, single, deluxe or remaster edition), or
   `album: null` when Claude cannot place it — those are dropped and counted
   (`unplaced`). A batch whose call fails falls back to each song's Spotify
   album, marked `unverified: true`.
3. **Group** — songs collapse by `(scan._normalise(artist),
   scan._normalise(album))`; each album keeps its song titles and the first
   Spotify image as `spotify_image`.
4. **Skip what's owned** — `_search_duplicate` against the collection; a
   match carries `duplicate_of: {id, artist, album_name}` and `have_it`.

Result: `{albums: [{key, artist, album_name, year, songs, spotify_image,
unverified, duplicate_of, have_it}], truncated, unplaced, song_count}`.
Claude spend banked with `_record_scan_spend("playlist", spent)` in a
`finally`.

**`POST /api/spotify/wishlist-scan/resolve`** `{albums: [...]}` —
`@require_auth`. The slow part, at most **24** albums per call
(`RESOLVE_CHUNK`, = `scan.COVER_FETCH_LIMIT` so every row gets artwork);
more is a 400. For each album:

1. `scan.resolve_album(artist, album)` (new) — one MusicBrainz release-group
   query ranked with `_rank_candidates`; returns `{mbid, year, artist,
   album_name}` or `None`. No country lookup: that would be three more
   throttled calls per album for a field the wishlist does not need.
2. `scan.search_covers(rows)`, then the Spotify image for any row still
   without one.
3. `scan.flag_vinyl(rows, usage_out=spent)` → `vinyl`.

Returns `{albums: [... the same rows plus mbid, year, cover_data, vinyl]}`
in input order, keyed by `key`. An album MusicBrainz does not know keeps
Claude's name and year and goes through `flag_vinyl` with no mbid (Claude's
verdict alone decides likely / none). `MusicBrainzUnavailable` → 502
`{error}`; the client stops and shows it, keeping the chunks already
resolved. Spend banked as `"playlist"`.

### Client

- `static/admin.js` (new): pure helpers exported for tests —
  `canTick(album)`, `defaultTicked(album)`, `chunk(list, size)`,
  `songsLabel(songs)`, `progressText(stage, done, total)`.
- `index.html`: the admin page markup, and the scan loop — POST the scan,
  render the albums as "checking…", then POST `/resolve` one chunk at a time
  and re-render after each (`checking vinyl 48 / 140`).
- `addToWishlist(releases)` (new shared helper, extracted from
  `addPickedToWishlist` in `index.html`): `/api/search/genres` then one
  `POST /api/records` per release with `have_it: false`; returns the added
  records. `addPickedToWishlist` keeps its UI handling and calls the helper.

## Errors

| situation                          | behaviour                                                       |
|------------------------------------|-----------------------------------------------------------------|
| not in edit mode                   | 401 (`require_auth`); admin item is hidden anyway               |
| Spotify not connected              | section shows the connect button                                |
| Spotify error / long rate limit    | 502 `{error}`; the message is shown above the scan button       |
| a Claude batch fails               | those songs use their Spotify album, rows marked `unverified`   |
| MusicBrainz unreachable            | resolve 502; scan stops, chunks already resolved stay shown     |
| empty playlist / nothing placeable | result with no albums; "nothing to add from this playlist"     |
| one `POST /api/records` fails      | the rest still go in; toast counts only what was added         |

## Testing

- `tests/test_admin_page.py` — routes with Spotify and Anthropic mocked as
  `conftest.py` does: playlists list, not-connected 409, auth 401, scan
  grouping, owned-album skip, 500 cap, Claude-batch fallback to
  `unverified`, resolve chunk limit, MusicBrainz-down 502, usage banked with
  `source='playlist'`.
- `tests/test_identify_albums.py` — batching (120 songs → 3 calls), parsing,
  `album: null` handling.
- `tests/test_admin.js` + `tests/test_admin.py` runner — `defaultTicked`,
  `canTick`, review-list rendering, following the existing JS/py test pairs.
- Existing places / backups / import / export tests updated for the moved
  DOM (`test_backups_dom.*` in particular).
- `docs/admin-page-manual-verification.md` — menu entry, each section, a
  real playlist scan, adding to the wishlist.

## Out of scope

- Re-scanning automatically when a playlist changes.
- Picking a non-studio pressing (live, compilation) for a song.
- Adding wishlist rows anywhere other than through the review list.
