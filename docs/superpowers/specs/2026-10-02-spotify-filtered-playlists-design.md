# Spotify filtered playlists — design

Date: 2026-10-02

## Goal

Replace the two fixed Spotify playlists ("Zucoloto Vinyl Collection" and
"— Liked") with playlists the owner defines from filters. The playlists popup
lists every playlist this app created; creating one with a filter combination
that already exists resyncs that playlist instead of making a duplicate.

## What stays as it is

- OAuth connect / disconnect, `SpotifyAccount`, `SpotifyAlbumCache`.
- The chunked sync: `desired_tracks` reads albums under a deadline, raises
  `Incomplete`, the client re-POSTs and shows "reading albums… N / M".
- `mirror()`: the playlist always holds exactly what the filters select —
  adds what is missing, removes what no longer belongs.
- The skipped report: `unmatched` (grouped per record, with `songs`) and
  `bad_links`, each entry carrying `label` and `cover_url`, shown as two
  groups with covers.
- The record pool: owned (`have_it`) records with a Spotify link, oldest
  purchase first.

## Data

New table `SpotifyPlaylist`:

| column           | type          | notes                                              |
|------------------|---------------|----------------------------------------------------|
| `id`             | int PK        |                                                    |
| `spotify_id`     | str(64)       | null until the first sync creates it on Spotify    |
| `name`           | str(100)      | Spotify's name limit                               |
| `filters`        | text (JSON)   | normalized filters, see below                      |
| `filter_key`     | str, unique   | canonical JSON of the normalized filters           |
| `created_at`     | str(50)       | local stamp, same convention as Record stamps      |
| `last_synced_at` | str(50)       | null until a sync completes                        |
| `last_total`     | int           | track count after the last sync                    |
| `last_records`   | int           | records contributing after the last sync           |

The skipped lists are not stored; they appear only right after a sync.

## Filters

One JSON object. Every key is optional; an absent/empty key does not filter.
Filters combine with AND.

| key                         | type                 | rule |
|-----------------------------|----------------------|------|
| `liked`                     | bool, default `true` | true: only hearted songs, matched per song with `match_track` (unmatched ones reported). false: every track of the album |
| `year_from`, `year_to`      | int                  | record year = first 4-digit run in `Record.year`. Inclusive. With either bound set, a record without a readable year is excluded |
| `genres`                    | list[str]            | record's `genre` equals any of them, case-insensitive, trimmed |
| `pepe_min`, `jenni_min`     | number 0.5–5         | `my_rating` ≥ `pepe_min`, `wife_rating` ≥ `jenni_min`. An unrated record (0/null) never passes a set minimum |
| `rating_mode`               | `"and"` \| `"or"`, default `"and"` | with both minimums set: and = both pass, or = either passes. Ignored when fewer than two minimums are set |
| `places`                    | list[str]            | record's `bought_where` equals any of them, case-insensitive, trimmed |
| `bought_from`, `bought_to`  | `YYYY-MM-DD`         | compared on the first 10 chars of `bought_date`. Inclusive; same day both sides = exact date. With either bound set, a record without a purchase date is excluded |

### Normalization and the filter key

`spotify_sync.normalize_filters(raw)`:

- drops unknown keys, empty strings, empty lists, null;
- coerces years to int, minimums to float, dates validated as `YYYY-MM-DD`
  (invalid values are a 400, not silently dropped);
- `liked` always present (default true); `rating_mode` kept only when both
  minimums are set, defaulting to `"and"`;
- lists: trimmed, de-duplicated case-insensitively, sorted, lowercased for the
  key (the display form keeps the first spelling seen);
- swaps a reversed range (from > to).

`filter_key` = `json.dumps(normalized_for_key, sort_keys=True, separators=(",", ":"))`.

### Suggested name

`suggest_name(filters)` (mirrored in the page JS so it updates live):
`"Zucoloto Vinyl"` + `" — Liked"` when liked, then `" · "`-joined parts for
the set filters: genres (comma-joined), year range (`1970–1979`, `≥1990`,
`≤1965`), ratings (`Pepe ≥4`, `Pepe ≥4 or Jenni ≥4`), places, bought range.
Truncated to 100 characters with an ellipsis. Editable before creating; once
the user types in the name field, it stops following the filters.

## Server

`spotify_sync.py`

- `normalize_filters(raw) -> dict`, `filter_key(filters) -> str`,
  `suggest_name(filters) -> str`.
- `select(records, filters) -> records` — the record-level filters (year,
  genre, rating, places, bought range). Records now also carry `year`,
  `genre`, `my_rating`, `wife_rating`, `bought_where`, `bought_date`.
- `desired_tracks(client, records, liked, cache, deadline)` — the `kind`
  argument becomes the `liked` bool; behaviour otherwise unchanged.
- `sync(client, records, playlist, cache, deadline)` — takes the saved
  playlist's `spotify_id`/`name`; if `spotify_id` is missing or Spotify
  answers 404 for it, creates a new private playlist and returns its id.
  Replaces `find_or_create_playlist` by name.
- `delete_playlist(client, spotify_id)` — `DELETE /playlists/{id}/followers`
  (Spotify's way of deleting your own playlist). A 404 counts as done.
- `PLAYLISTS` constant is removed (kept only as migration data).

`app.py`

- `_playlist_records()` returns the extra fields above.
- `GET /api/spotify/playlists` → `{playlists: [{id, name, filters, summary,
  url, last_synced_at, last_total, last_records}], genres: [...],
  places: [...]}`. `genres`/`places` are the distinct non-empty values in the
  collection, for the pickers.
- `POST /api/spotify/playlists` `{filters, name?}` → normalizes; if the key
  exists, returns `{playlist, existed: true}`; otherwise inserts and returns
  `{playlist, existed: false}`. Creating on Spotify happens on the first sync.
- `POST /api/spotify/playlists/<id>/sync` → the existing chunked sync
  (`202 {incomplete, done, total}` until finished, then the result). On
  success stores `spotify_id`, `last_synced_at`, `last_total`, `last_records`.
- `DELETE /api/spotify/playlists/<id>` → unfollows on Spotify (if it has a
  `spotify_id`), then deletes the row. Spotify errors other than 404 abort
  with 502 and keep the row.
- `GET /api/spotify/account` drops its `playlists` field.
- All behind `require_auth`; 409 `{connect: true}` when not connected or the
  login expired, as today.

### Migration

On startup, if `SpotifyPlaylist` is empty, insert the two former fixed
playlists: `{liked: false}` named "Zucoloto Vinyl Collection" and
`{liked: true}` named "Zucoloto Vinyl Collection — Liked", with
`spotify_id` null. On their first sync, before creating, `sync` looks up the
owner's playlists by that exact name once (the old `find_or_create` lookup)
and adopts the id if found — so the playlist already on Spotify is kept, not
duplicated. The lookup by name only happens while `spotify_id` is null.

## Popup UI

Connected state, top to bottom:

1. Account line (unchanged).
2. **Your playlists** — one row per saved playlist: name, `[sync]`,
   `[delete]`, a one-line filter summary, and the last result
   ("312 tracks · synced 2 days ago · open ↗", or "never synced"). Sync
   progress, the result, and the not-found / bad-link groups render under the
   row as today.
3. **New playlist** (collapsible, collapsed when playlists exist):
   - Songs: radio liked (default) / every track.
   - Year: from / to number inputs.
   - Genre, Bought at: chip pickers fed from `genres` / `places`.
   - Rating: Pepe ≥ and Jenni ≥ selects (–, 1…5 in halves); the and/or
     switch appears only when both are set.
   - Bought: from / to date inputs.
   - Live "N records match" count, computed client-side from the loaded
     collection with the same rules (owned + Spotify link + filters). The
     `liked` choice also requires at least one hearted song. A 0 shows as a
     warning but does not block creating.
   - Name field, auto-filled from `suggestName` until edited.
   - `[create & sync]`: POST, then sync that row. If `existed`, the existing
     row is highlighted, scrolled to, and synced, with "already exists —
     resynced".
4. Footer note (unchanged wording about mirroring).

Delete asks `confirm("Delete '<name>' from Spotify too?")`.

## Errors

- Playlist deleted on Spotify by hand → next sync gets 404 on it, creates a
  new one, stores the new id.
- Login expired → 409 `{connect: true}`, panel returns to the connect state.
- Invalid filter values → 400 with the field name; the form shows it.
- Delete fails on Spotify (not 404) → row kept, error on the row.

## Testing

Python (`tests/test_spotify_playlists.py`, `tests/test_spotify_filters.py`):

- each filter rule incl. edge cases: unreadable/empty year, unrated record,
  missing purchase date, genre/place case and whitespace, and/or ratings,
  reversed ranges, exact-date range;
- normalization and key equality across ordering/casing; invalid values → 400;
- create returns the existing row for an equal key;
- migration seeds two rows; first sync adopts an existing same-named
  playlist; a 404 on a stored id recreates;
- delete calls the followers endpoint; 404 is treated as gone.

JSDOM (`tests/test_playlists_dom.js`):

- the saved list renders with summaries and last results;
- the live match count and the auto-name follow the form;
- a typed name stops following;
- a duplicate create highlights and syncs the existing row;
- delete confirms, calls DELETE, and removes the row.

## Out of scope

- Editing a saved playlist's filters (delete and create instead).
- Ordering options other than oldest purchase first.
- Scheduled / automatic syncs.
