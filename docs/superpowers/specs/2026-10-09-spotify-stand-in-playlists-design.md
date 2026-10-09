# Spotify stand-in playlists — design

Date: 2026-10-09

## Goal

Some records are not on Spotify as an album, so they have no Spotify link and
never reach the filtered playlists. A new admin section builds a **stand-in**:
a playlist on the owner's Spotify holding that record's songs, found one by
one by title and artist. Its cover is the record's cover and its description
carries the record's facts. Once the owner is happy with one, **match** links
it to the record, and from then on every filtered playlist on the Spotify tab
takes its songs from it, exactly as it does from an album.

## Decisions (from brainstorming)

- Songs come from the record's own tracklist. A record without one gets a
  tracklist suggested by Claude (Haiku, cost written to the spend ledger as
  source `tracklist`); the owner reviews it, and confirming saves it onto the
  record through the ordinary record PUT, so hearts work on it afterwards.
- Build is **preview first**: every song is searched and shown with its hit
  (or "not found"); the owner unticks wrong hits, then creates.
- Match writes the playlist's link into `record.spotify_url` (approach A).
  `spotify_sync.album_tracks` already reads a playlist link as an ordered
  tracklist, so the sync and `match_track` (liked songs) need no change.

## What stays as it is

- `spotify_sync.sync`, `desired_tracks`, `album_tracks`, `match_track`.
- The OAuth scopes: `playlist-modify-private` and `ugc-image-upload` already
  cover creating, filling and setting the cover.
- The record PUT and `_clean_tracks` validation.

## 1. A stand-in counts as an album, not a compilation

`playlist_filters` sorts records by link kind: a playlist link is a
"compilation", and the tab's default `source` is `albums`. A matched record
must count as an album — the record *is* one — or the default playlists would
drop it.

- New column `Record.spotify_standin` (Boolean, default False), added by the
  boot-time column migration like `spotify_missing`, sent in `to_dict` as
  `spotify_standin`.
- `link_kind` in `playlist_filters.py` and `linkKind` in
  `static/playlist_filters.js` stay as they are; `_matches` / `matches` treat
  `record.spotify_standin` as kind `album`. New cases in
  `tests/fixtures/playlist_filter_cases.json` hold both sides to it.
- `_playlist_records` passes `spotify_standin` through.
- Any record PUT that changes `spotify_url` clears `spotify_standin` (unless
  the same PUT sets it), so pasting a real album link later turns the flag off.

## 2. Data

New table `StandInPlaylist`:

| column | |
|---|---|
| `id` | PK |
| `record_id` | the record it stands in for (no FK cascade; a deleted record leaves an orphan row, shown as "record deleted") |
| `spotify_id` | the playlist on Spotify; stored before tracks are added |
| `name` | "Artist — Album" |
| `track_count` | songs put on it |
| `song_count` | songs on the record's tracklist |
| `cover_url` | read back from Spotify after the upload |
| `created_at` | stamp |
| `matched_at` | stamp, null until matched |

## 3. Routes (all `@require_auth`, under `/api/spotify/stand-ins`)

- `GET /api/spotify/stand-ins` → `{stand_ins: [...], candidates: [...]}`.
  Candidates are records (owned and wishlist) whose `spotify_url` is empty:
  `{id, artist, album_name, year, cover_url, has_tracks, spotify_missing}`,
  sorted by artist then album. Each stand-in carries its record's
  artist/album/cover and `matched`.
- `POST /api/spotify/stand-ins/tracklist {record_id}` → `{tracks: [{side,
  title}], disc_count}`. Claude Haiku with a JSON schema; refuses (400) a
  record that already has a tracklist. Nothing is saved here.
- `POST /api/spotify/stand-ins/preview {record_id}` → `{songs: [{side, title,
  hit: {uri, name, album, year, image_url} | null}]}`. One Spotify search per
  song, through the owner's client: `track:"title" artist:"artist"`, limit 10.
  A hit must credit the artist (same rule as `scan.find_spotify_album`) and
  match the title by `spotify_sync._norm` (exact, then extras stripped).
  Among hits: the record's own album name first, then a title without
  live/demo/remix wording, then the earliest release date.
- `POST /api/spotify/stand-ins {record_id, uris}` → creates the private
  playlist, name "Artist — Album", description from the record (see 4), adds
  the uris in order, uploads the cover. Returns the stand-in and a `cover`
  status ("uploaded" | "needs_reconnect" | "failed" | "none"). Refuses a
  record that already has a Spotify link, and an empty `uris`.
- `POST /api/spotify/stand-ins/<id>/match` → sets the record's
  `spotify_url` to the playlist link, `spotify_standin=True`,
  `spotify_missing=False`, and the row's `matched_at`. Refuses (409) if the
  record has some other link by now.
- `POST /api/spotify/stand-ins/<id>/unmatch` → clears the link and flag if
  they are still this playlist's.
- `DELETE /api/spotify/stand-ins/<id>` → unfollows on Spotify (gone is fine),
  unmatches if matched, deletes the row.

Errors use the existing helpers: `_not_connected`, `_login_expired`, 502 with
the Spotify message.

## 4. Description and cover

- Description: `"{Artist} — {Album} ({year}) · {genre} · {Country} · vinyl
  stand-in, {n} of {m} songs found · Zucoloto vinyl collection"`, empty parts
  left out (where the record was bought is never shown), capped at 300 characters (Spotify's
  limit). No newlines (Spotify rejects them).
- Cover: the record's `cover_data` decoded, converted to RGB, resized to
  640×640 (centre-cropped square) and saved as JPEG with falling quality
  until the base64 fits 256 KB — the same loop as `cover_art.render`, moved
  into a shared `cover_art.to_spotify_jpeg(img)`. A record without a cover
  gets Spotify's mosaic ("none").

## 5. Admin UI — "spotify stand-ins"

A fourth admin section, last on the page, spanning both columns
(`grid-template-areas: "places spotify" "data spotify" "standin standin"`;
the phone layout appends it). It wears the Spotify tab's palette (the
`--sp-*` variables) and reuses its row classes (`.playlist-row`,
`.playlist-art`, `.playlist-main`, `.playlist-actions`, `.pl-tag`), so it
reads like the tab.

- **Your stand-ins** header in the tab's "Your Library" style, with pills
  **All · Matched · Not matched**.
- One row per stand-in: the cover, the name (link to Spotify), "Playlist •
  n of m songs", a chip **matched** (green) or **not matched**, and actions:
  match / unmatch, delete, open in Spotify.
- Below, **new stand-in**: a search box over the candidates (artist/album
  text filter), a list of them (cover, album, artist, "no tracklist" tag).
  Picking one shows the step it needs:
  1. no tracklist → "suggest tracklist with Claude" button → editable list
     of side + title (rows can be deleted) → "save tracklist" (record PUT
     with `tracks` and `disc_count`) → step 2.
  2. "find songs on Spotify" → preview list: checkbox, side, title, the hit
     (track name · album · year) or "not found" (unticked, disabled).
  3. "create playlist (n songs)" → the new row appears at the top of the
     list, not matched.
- The pure bits (the candidate text filter, the pill filter, hit labels,
  the side letters a disc count allows) live in `static/standins.js`, tested
  with node like `static/admin.js`.

## 6. Testing

- `tests/test_standins.py`: FakeSpotify extended with `/search` and the
  playlist-details PUT; covers search ranking, preview, create (id stored
  before items, cover uploaded, description content), match/unmatch/delete,
  refusals, the tracklist route with a mocked Claude, and that a matched
  record lands in a default (`source: albums`) playlist sync.
- Filter fixture cases for `spotify_standin` (py + js).
- `tests/test_standins.js` for `static/standins.js`.
- Manual verification doc: `docs/stand-in-playlists-manual-verification.md`.
