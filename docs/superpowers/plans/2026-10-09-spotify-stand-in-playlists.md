# Spotify Stand-in Playlists Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin section that builds a Spotify playlist standing in for a record that is not on Spotify, and links it to the record so the filtered playlists use it.

**Architecture:** A new `standins.py` holds the pure Spotify work (search ranking, description, create). `app.py` gains a `StandInPlaylist` table, a `Record.spotify_standin` flag and the `/api/spotify/stand-ins` routes. The filters treat a stand-in link as an album. The admin page gets a fourth section rendered by inline JS plus a pure helper `static/standins.js`.

**Tech Stack:** Flask, SQLAlchemy, requests, Pillow, Anthropic SDK; vanilla JS; pytest + node:test.

**Spec:** `docs/superpowers/specs/2026-10-09-spotify-stand-in-playlists-design.md`

## Global Constraints

- Spotify description ≤ 300 characters, no newlines.
- Spotify cover: JPEG, base64 ≤ 256 KB.
- Playlist is private (`public: False`).
- Claude model for the tracklist: `claude-haiku-4-5`, no `effort` parameter; spend source `tracklist`.
- Endpoints use the February 2026 API paths (`/me/playlists`, `/playlists/{id}/items`).
- Tests never touch the network (conftest guard).

## Review Focus

- A record matched, then its link edited by hand to an album link → `spotify_standin` must turn off (Task 1 test).
- Song titles with "(Live)" / "- Remastered" / accents → title matching uses `_norm` both strict and stripped (Task 2 test).
- A record whose cover is PNG with alpha, or huge → converted to RGB and squeezed under 256 KB (Task 2 test).
- Matching after the record gained some other link meanwhile → 409, the link is not overwritten (Task 3 test).
- Deleting a matched stand-in → the record's link is cleared, not left dead (Task 3 test).

---

### Task 1: `spotify_standin` flag and the filters

**Files:** Modify `app.py` (Record column, `to_dict`, column migration, `update_record`, `_playlist_records`), `playlist_filters.py` (`_matches`), `static/playlist_filters.js` (`matches`), `tests/fixtures/playlist_filter_cases.json`. Test: `tests/test_standins.py`.

**Produces:** `Record.spotify_standin: bool`; record dicts carry `spotify_standin`; filters count a flagged record as `album`.

- [ ] Add fixture cases: stand-in playlist link with `source` default → match; with `compilations` → no match; unflagged playlist link with default → no match (already covered).
- [ ] Run `pytest tests/test_playlist_filters.py tests/test_playlist_filters_js.py` → new cases fail.
- [ ] In both filter modules: `kind = "album" if r.get("spotify_standin") else link_kind(...)`.
- [ ] Column + migration entry `"spotify_standin": "BOOLEAN"`, `to_dict`, `_playlist_records` passes it; `update_record`: if `spotify_url` changes and the PUT does not send `spotify_standin`, clear it.
- [ ] Test in `test_standins.py`: PUT a new spotify_url on a flagged record clears the flag.
- [ ] Run the filter tests and `test_standins.py` → pass.

### Task 2: `standins.py` — search, description, cover, create

**Files:** Create `standins.py`; modify `cover_art.py` (extract `to_spotify_jpeg(img)`); test `tests/test_standins.py`.

**Interfaces (produces):**
- `pick_hit(title, artist, album, items) -> dict | None` — items are Spotify search track objects; returns `{uri, name, album, year, image_url}`.
- `find_song(client, title, artist, album) -> dict | None` — one `/search` call.
- `preview(client, record) -> list[{side, title, hit}]` — record dict with `artist, album_name, tracks`.
- `description(record, found, total) -> str` (≤ 300, no newlines).
- `cover_jpeg(data_uri) -> bytes | None`.
- `create(client, name, description, uris, on_created) -> spotify_id` — POST `/me/playlists`, `on_created(id)`, then POST items in 100s.
- `cover_art.to_spotify_jpeg(img: PIL.Image) -> bytes`.

- [ ] Tests: ranking prefers own album, then non-live, then earliest; rejects other artists and other titles; description drops empty parts and caps; cover from RGBA PNG yields JPEG under the cap; create stores id before items (FakeSpotify call order).
- [ ] Run → fail; implement; run → pass. `pytest tests/test_cover_art.py` still passes.

### Task 3: table and routes

**Files:** Modify `app.py`; extend `scan.py` with `suggest_tracklist(artist, album, year, usage_out) -> {tracks, disc_count} | None`; test `tests/test_standins.py`.

**Consumes:** Task 2 functions; `_spotify_client`, `_not_connected`, `_login_expired`, `_record_scan_spend`, `spotify_sync.upload_cover/playlist_cover/delete_playlist`.

- [ ] Tests (FakeSpotify with `/search`): list shows candidates without a link; preview returns hits; create makes the playlist (private, name, description, uris, cover uploaded) and the row; create refuses a record with a link and empty uris; match sets link/flag/clears missing; match 409 when the record has another link; unmatch; delete unfollows and unmatches; tracklist route with mocked Claude writes spend and refuses a record that has tracks; not connected → 409 connect; a matched record is picked up by a default-filter sync.
- [ ] Run → fail; implement; run → pass.

### Task 4: admin UI

**Files:** Create `static/standins.js`, `tests/test_standins.js`, `tests/test_standins_js.py`; modify `templates/index.html` (CSS vars scope, grid area, section markup, script tag, render/load functions, `loadAdmin`).

**Interfaces (produces, `VinylStandins`):** `filterCandidates(list, query)`, `pillKeeps(standIn, pill)`, `hitLabel(hit)`, `sidesFor(discCount)`, `discCountFor(tracks)`.

- [ ] node tests for the helpers → fail → implement → pass.
- [ ] Section markup + render/load + actions (suggest, save tracklist, preview, tick, create, match, unmatch, delete).
- [ ] Screenshot the admin page with Flask running (see memory: chromium libs in scratchpad).

### Task 5: docs and full run

- [ ] `docs/stand-in-playlists-manual-verification.md`; README Spotify section line.
- [ ] Run the whole pytest suite minus boot tests; compare against the baseline failures.
