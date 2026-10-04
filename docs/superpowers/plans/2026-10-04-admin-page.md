# Admin Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One edit-mode admin page, opened from the header's ⋯ menu, holding places, data (export / import / backups) and a new Spotify-playlist → wishlist tool.

**Architecture:** The admin page is a new tab (`switchTab('admin')`) with three sections. Places and backups keep their render functions and element ids and just move into the page. The Spotify tool has a fast server call (read the playlist, Claude names each song's studio album, group, mark owned) and a chunked slow call (MusicBrainz resolve + covers + vinyl check, at most 24 albums per request), which the browser loops over so no request goes near gunicorn's 120 s timeout.

**Tech Stack:** Flask + SQLAlchemy (`app.py`), `scan.py` (MusicBrainz, Anthropic SDK `anthropic==1.0.0`), `spotify_sync.py` (Spotify Web API client), one big `templates/index.html` with small `static/*.js` modules, pytest + `node --test` (jsdom for DOM tests, run through pytest wrappers).

**Spec:** `docs/superpowers/specs/2026-10-04-admin-page-design.md`

## Global Constraints

- All commands run from `vinyl-collection/`. Full suite: `python -m pytest -q`.
- Every new route is `@require_auth`. Visitors see no change.
- No real network in tests — `tests/conftest.py` turns any socket connect into an `AssertionError`; patch `spotify_sync.requests.request`, `scan._mb_get`, `scan._anthropic_client`, etc.
- Claude model for identification: `IDENTIFY_MODEL = "claude-haiku-4-5"`, structured output via `output_config={"format": {"type": "json_schema", "schema": ...}}` (same call shape as `scan.confirm_vinyl`).
- Claude spend banked with `_record_scan_spend("playlist", spent)` inside a `finally`.
- `PLAYLIST_SCAN_CAP = 500` songs; identify batch = 50 songs, 4 parallel workers; `RESOLVE_CHUNK = 24` (= `scan.COVER_FETCH_LIMIT`).
- Spotify playlist items come from `/playlists/{id}/items?...&additional_types=track` (the February 2026 path; `/tracks` is gone). An entry's track is under `item` (new) or `track` (old) — read both.
- Wishlist rows are added exactly as search adds them: `/api/search/genres` then `POST /api/records` with `have_it: false`.
- Code style: match the file you are in — long explanatory comments on *why*, compact JS in `index.html`, `esc()` around every interpolated string in HTML.
- Commit after each task with a `feat:`/`test:`/`refactor:`/`docs:` message ending in `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A playlist with the same album many times, spelled differently** ("Abbey Road" vs "Abbey Road (Remastered 2009)" from Claude's fallback path) — expect one row per album after `_normalise`, not duplicates. Pinned in Task 4 (`test_scan_groups_songs_by_normalised_album`).
2. **A playlist whose songs are all already owned or wishlisted** — expect every row greyed "in collection"/"on wishlist", the add button disabled, and no resolve calls for them. Pinned in Task 4 (`test_owned_albums_are_marked_and_not_resolved`) and Task 6 (`canTick` tests).
3. **MusicBrainz goes down halfway through the chunks** — expect the scan to stop with the error shown and the already-resolved rows still tickable. Pinned in Task 5 (`test_resolve_maps_musicbrainz_down_to_502`) and Task 8 (DOM test `a failed chunk keeps what was resolved`).
4. **A Spotify login that expired** (refresh token revoked) — expect the "connect again" path (409 `connect: true`), not a 502. Pinned in Task 4 (`test_scan_login_expired_is_409_connect`).
5. **Locking edit mode while on the admin page** — expect a return to the collection tab, with no admin content left visible. Pinned in Task 7 (DOM test `locking while on admin goes back to the collection`).

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `spotify_sync.py` | modify | `user_playlists(client)`, `playlist_tracks(client, pid, cap)` — read-only Spotify listings |
| `scan.py` | modify | `identify_albums(tracks, usage_out)` (Claude), `resolve_album(artist, album)` (one MB query) |
| `app.py` | modify | 3 routes: `GET /api/spotify/me/playlists`, `POST /api/spotify/wishlist-scan`, `POST /api/spotify/wishlist-scan/resolve` |
| `static/admin.js` | create | pure review-list rules: `canTick`, `defaultTicked`, `chunk`, `songsLabel`, `progressText` |
| `templates/index.html` | modify | admin page markup + CSS, ⋯ menu, `switchTab`, `setAuthed`, places/backups moved, Spotify tool UI, `addToWishlist` helper |
| `tests/test_playlist_tracks.py` | create | Task 1 |
| `tests/test_identify_albums.py` | create | Task 2 |
| `tests/test_resolve_album.py` | create | Task 3 |
| `tests/test_wishlist_scan.py` | create | Tasks 4–5 |
| `tests/test_admin.js` + `tests/test_admin_js.py` | create | Task 6 |
| `tests/test_admin_dom.js` + `tests/test_admin_dom.py` | create | Tasks 7–8 (replaces `test_backups_dom.*`) |
| `tests/test_backups_dom.js` + `.py` | delete | folded into `test_admin_dom.*` |
| `tests/test_boot.js` | modify | export-visibility test now checks `#adminBtn` |
| `docs/admin-page-manual-verification.md` | create | Task 9 |

---

### Task 1: Spotify listings — `user_playlists` and `playlist_tracks`

**Files:**
- Modify: `spotify_sync.py` (add after `playlist_uris`, ~line 382)
- Test: `tests/test_playlist_tracks.py`

**Interfaces:**
- Consumes: `spotify_sync.Client.pages(path)` (existing; yields every item across pages).
- Produces:
  - `user_playlists(client) -> list[dict]` — `[{"id": str, "name": str, "image_url": str, "track_count": int, "owner": str}]`
  - `playlist_tracks(client, playlist_id: str, cap: int) -> tuple[list[dict], bool]` — `([{"title", "artists": [str], "album", "release_year", "image_url"}], truncated)`

- [ ] **Step 1: Write the failing tests**

```python
"""Reading the owner's playlists and a playlist's songs, for the wishlist tool.

The Client is replaced by a stub whose pages() answers from a dict: these
functions only shape Spotify's paging objects, so the HTTP layer (already
covered by test_spotify_playlists.py) is not what is under test here.
"""

import spotify_sync


class StubClient:
    def __init__(self, pages):
        self._pages = pages
        self.asked = []

    def pages(self, path):
        self.asked.append(path)
        for prefix, items in self._pages.items():
            if path.startswith(prefix):
                yield from items
                return


def _track(title, artist, album, date="1969-09-26", image="https://i/x.jpg"):
    return {"type": "track", "name": title, "is_local": False,
            "artists": [{"name": artist}],
            "album": {"name": album, "release_date": date,
                      "images": [{"url": image}]}}


def test_user_playlists_shapes_each_playlist():
    c = StubClient({"/me/playlists": [
        {"id": "P1", "name": "Road trip", "owner": {"display_name": "Me"},
         "images": [{"url": "https://i/p1.jpg"}], "items": {"total": 42}},
        # Pre-2026 shape: the count is under "tracks", there are no images.
        {"id": "P2", "name": "Old", "owner": {"id": "someone"},
         "images": None, "tracks": {"total": 7}},
    ]})
    assert spotify_sync.user_playlists(c) == [
        {"id": "P1", "name": "Road trip", "image_url": "https://i/p1.jpg",
         "track_count": 42, "owner": "Me"},
        {"id": "P2", "name": "Old", "image_url": "", "track_count": 7,
         "owner": "someone"},
    ]


def test_user_playlists_skips_null_entries():
    c = StubClient({"/me/playlists": [None, {"id": "P1", "name": "A"}]})
    assert [p["id"] for p in spotify_sync.user_playlists(c)] == ["P1"]


def test_playlist_tracks_reads_the_items_path_and_both_entry_shapes():
    c = StubClient({"/playlists/PL/items": [
        {"item": _track("Come Together", "The Beatles", "Abbey Road")},
        {"track": _track("Something", "The Beatles", "Abbey Road")},
    ]})
    tracks, truncated = spotify_sync.playlist_tracks(c, "PL", cap=500)
    assert c.asked[0].startswith("/playlists/PL/items")
    assert "additional_types=track" in c.asked[0]
    assert truncated is False
    assert tracks == [
        {"title": "Come Together", "artists": ["The Beatles"], "album": "Abbey Road",
         "release_year": "1969", "image_url": "https://i/x.jpg"},
        {"title": "Something", "artists": ["The Beatles"], "album": "Abbey Road",
         "release_year": "1969", "image_url": "https://i/x.jpg"},
    ]


def test_playlist_tracks_skips_episodes_local_files_and_removed_tracks():
    local = _track("Demo", "Me", "Tape")
    local["is_local"] = True
    c = StubClient({"/playlists/PL/items": [
        {"item": {"type": "episode", "name": "A podcast"}},
        {"item": local},
        {"item": None},
        None,
        {"item": _track("Lovely Day", "Bill Withers", "Menagerie", date="1977")},
    ]})
    tracks, _ = spotify_sync.playlist_tracks(c, "PL", cap=500)
    assert [t["title"] for t in tracks] == ["Lovely Day"]
    assert tracks[0]["release_year"] == "1977"


def test_playlist_tracks_stops_at_the_cap_and_says_so():
    c = StubClient({"/playlists/PL/items": [
        {"item": _track(f"Song {i}", "A", "B")} for i in range(5)]})
    tracks, truncated = spotify_sync.playlist_tracks(c, "PL", cap=3)
    assert [t["title"] for t in tracks] == ["Song 0", "Song 1", "Song 2"]
    assert truncated is True


def test_playlist_tracks_exactly_at_the_cap_is_not_truncated():
    c = StubClient({"/playlists/PL/items": [
        {"item": _track(f"Song {i}", "A", "B")} for i in range(3)]})
    _, truncated = spotify_sync.playlist_tracks(c, "PL", cap=3)
    assert truncated is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_playlist_tracks.py -q`
Expected: FAIL — `AttributeError: module 'spotify_sync' has no attribute 'user_playlists'`

- [ ] **Step 3: Implement**

Add to `spotify_sync.py` after `playlist_uris`:

```python
# ── reading the owner's playlists, for the wishlist tool ─────────────────────

def _first_image(images):
    return ((images or [{}])[0] or {}).get("url") or ""


def user_playlists(client):
    """Every playlist on the owner's account, owned or followed, in Spotify's order.

    The count moved from `tracks.total` to `items.total` in the February 2026
    API change; both are read so a cached old-shape page does not show zero.
    """
    out = []
    for p in client.pages("/me/playlists?limit=50"):
        if not p or not p.get("id"):
            continue
        owner = p.get("owner") or {}
        count = (p.get("items") or p.get("tracks") or {}).get("total") or 0
        out.append({"id": p["id"], "name": p.get("name") or "",
                    "image_url": _first_image(p.get("images")),
                    "track_count": int(count),
                    "owner": owner.get("display_name") or owner.get("id") or ""})
    return out


def playlist_tracks(client, playlist_id, cap):
    """The songs on a playlist, as the wishlist scan needs them, and whether `cap` cut it.

    Local files and podcast episodes are skipped: neither names an album that
    could be on a record. One entry past the cap is read so "exactly cap" and
    "more than cap" can be told apart.
    """
    out = []
    for entry in client.pages(f"/playlists/{playlist_id}/items?limit=50&additional_types=track"):
        item = (entry or {}).get("item") or (entry or {}).get("track")
        if not item or item.get("type") != "track" or item.get("is_local"):
            continue
        if len(out) == cap:
            return out, True
        album = item.get("album") or {}
        out.append({"title": item.get("name") or "",
                    "artists": [a.get("name") or "" for a in item.get("artists") or []],
                    "album": album.get("name") or "",
                    "release_year": (album.get("release_date") or "")[:4],
                    "image_url": _first_image(album.get("images"))})
    return out, False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_playlist_tracks.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add spotify_sync.py tests/test_playlist_tracks.py
git commit -m "feat: read the owner's Spotify playlists and a playlist's songs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `scan.identify_albums` — Claude names each song's studio album

**Files:**
- Modify: `scan.py` (add after `_vinyl_status`, ~line 1094)
- Test: `tests/test_identify_albums.py`

**Interfaces:**
- Consumes: `scan._anthropic_client()`, `scan._record_usage(usage_out, model, response)` (existing).
- Produces: `identify_albums(tracks: list[dict], usage_out: list | None = None) -> list[dict]` — one dict per input track, same order: `{"artist": str, "album": str | None, "year": str | None, "unverified": bool}`. `album is None` means Claude could not place it. `unverified=True` means the batch's call failed and the Spotify album was used instead. Constants `IDENTIFY_MODEL`, `IDENTIFY_BATCH = 50`, `IDENTIFY_WORKERS = 4`.

- [ ] **Step 1: Write the failing tests**

```python
"""identify_albums: one Claude verdict per playlist song, batched, never raising."""

import json
import threading
from types import SimpleNamespace

import scan


def _song(i, artist="The Beatles", album="1 (Remastered)"):
    return {"title": f"Song {i}", "artists": [artist], "album": album,
            "release_year": "2000", "image_url": ""}


class FakeClaude:
    """Answers each batch from `answer(lines)`; records every call."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []
        self.lock = threading.Lock()
        self.messages = self

    def create(self, **kw):
        with self.lock:
            self.calls.append(kw)
        lines = kw["messages"][0]["content"].split("\n")
        body = self.answer(lines)
        if isinstance(body, Exception):
            raise body
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(body))],
            usage=SimpleNamespace(input_tokens=100, output_tokens=20))


def _patch(monkeypatch, fake):
    monkeypatch.setattr(scan, "_anthropic_client", lambda: fake)


def _studio(lines):
    return {"albums": [{"artist": "The Beatles", "album": "Abbey Road", "year": "1969"}
                       for _ in lines]}


def test_returns_one_answer_per_song_in_order(monkeypatch):
    _patch(monkeypatch, FakeClaude(_studio))
    out = scan.identify_albums([_song(1), _song(2)])
    assert out == [{"artist": "The Beatles", "album": "Abbey Road", "year": "1969",
                    "unverified": False}] * 2


def test_the_prompt_numbers_songs_with_artist_title_and_spotify_album(monkeypatch):
    fake = FakeClaude(_studio)
    _patch(monkeypatch, fake)
    scan.identify_albums([_song(1)])
    call = fake.calls[0]
    assert call["model"] == scan.IDENTIFY_MODEL == "claude-haiku-4-5"
    assert call["messages"][0]["content"] == "1. The Beatles — Song 1 — on Spotify: 1 (Remastered)"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "studio album" in call["system"]


def test_120_songs_are_three_calls_and_three_usage_rows(monkeypatch):
    fake = FakeClaude(_studio)
    _patch(monkeypatch, fake)
    usage = []
    out = scan.identify_albums([_song(i) for i in range(120)], usage_out=usage)
    assert len(fake.calls) == 3
    assert sorted(len(c["messages"][0]["content"].split("\n")) for c in fake.calls) == [20, 50, 50]
    assert len(out) == 120
    assert len(usage) == 3 and all(u["model"] == "claude-haiku-4-5" for u in usage)


def test_a_null_album_is_kept_as_unplaced(monkeypatch):
    _patch(monkeypatch, FakeClaude(lambda lines: {"albums": [
        {"artist": "Unknown", "album": None, "year": None}]}))
    assert scan.identify_albums([_song(1)]) == [
        {"artist": "Unknown", "album": None, "year": None, "unverified": False}]


def test_a_failed_batch_falls_back_to_the_spotify_album(monkeypatch):
    _patch(monkeypatch, FakeClaude(lambda lines: RuntimeError("overloaded")))
    assert scan.identify_albums([_song(1, album="Menagerie")]) == [
        {"artist": "The Beatles", "album": "Menagerie", "year": "2000", "unverified": True}]


def test_a_short_answer_falls_back_only_for_the_missing_songs(monkeypatch):
    _patch(monkeypatch, FakeClaude(lambda lines: {"albums": [
        {"artist": "The Beatles", "album": "Abbey Road", "year": "1969"}]}))
    out = scan.identify_albums([_song(1), _song(2, album="Help!")])
    assert out[0]["album"] == "Abbey Road" and out[0]["unverified"] is False
    assert out[1] == {"artist": "The Beatles", "album": "Help!", "year": "2000",
                      "unverified": True}


def test_no_api_key_falls_back_for_every_song(monkeypatch):
    def boom():
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    monkeypatch.setattr(scan, "_anthropic_client", boom)
    out = scan.identify_albums([_song(1)])
    assert out[0]["unverified"] is True


def test_no_songs_asks_nothing(monkeypatch):
    fake = FakeClaude(_studio)
    _patch(monkeypatch, fake)
    assert scan.identify_albums([]) == []
    assert fake.calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_identify_albums.py -q`
Expected: FAIL — `AttributeError: module 'scan' has no attribute 'identify_albums'`

- [ ] **Step 3: Implement**

Add to `scan.py` after `_vinyl_status`:

```python
# ── which album a playlist song is from ──────────────────────────────────────

IDENTIFY_MODEL = "claude-haiku-4-5"

# Fifty numbered lines is a short prompt and a short answer; a 500-song
# playlist is ten of them, run IDENTIFY_WORKERS at a time so the whole pass
# fits comfortably inside one request.
IDENTIFY_BATCH = 50
IDENTIFY_WORKERS = 4

_IDENTIFY_SYSTEM = (
    "You name the album a song comes from, so the owner can look for it on vinyl.\n"
    "Rules:\n"
    "1. Answer with the ORIGINAL STUDIO ALBUM by that artist that first "
    "included the song — never a compilation, greatest-hits, single, live "
    "album, soundtrack reissue, deluxe edition or remaster. Drop edition "
    "suffixes such as \"(Remastered 2009)\" or \"(Deluxe)\".\n"
    "2. The Spotify album is a hint, not the answer: playlists are full of "
    "compilations and remasters.\n"
    "3. A song that was only ever a single, or that you do not know, gets "
    "album null. Never guess.\n"
    "4. artist is the album's credited artist as usually written.\n"
    "5. One answer per numbered song, in the order given."
)

_IDENTIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "albums": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "artist": {"type": "string"},
                    "album": {"type": ["string", "null"]},
                    "year": {"type": ["string", "null"]},
                },
                "required": ["artist", "album", "year"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["albums"],
    "additionalProperties": False,
}


def _spotify_fallback(track: dict) -> dict:
    return {"artist": (track.get("artists") or [""])[0],
            "album": track.get("album") or None,
            "year": track.get("release_year") or None,
            "unverified": True}


def _identify_batch(batch: list, usage_out: list | None) -> list:
    """One Claude call for up to IDENTIFY_BATCH songs. Never raises."""
    lines = [f"{i}. {', '.join(t.get('artists') or ['?'])} — {t.get('title') or '?'}"
             f" — on Spotify: {t.get('album') or '?'}"
             for i, t in enumerate(batch, 1)]
    answers: list = []
    try:
        client = _anthropic_client()
        response = client.messages.create(
            model=IDENTIFY_MODEL,
            # About thirty tokens per answer, plus the JSON scaffolding.
            max_tokens=40 * len(batch) + 64,
            system=_IDENTIFY_SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": _IDENTIFY_SCHEMA}},
            messages=[{"role": "user", "content": "\n".join(lines)}],
        )
        _record_usage(usage_out, IDENTIFY_MODEL, response)
        text = next(b.text for b in response.content if b.type == "text")
        parsed = json.loads(text)
        answers = parsed.get("albums") if isinstance(parsed, dict) else []
        if not isinstance(answers, list):
            answers = []
    except Exception:
        logger.warning("Album identification failed for a batch", exc_info=True)
        answers = []

    # Same discipline as confirm_vinyl: a short answer is never zipped as-is,
    # or every song after the gap would be credited to its neighbour's album.
    out = []
    for i, track in enumerate(batch):
        a = answers[i] if i < len(answers) and isinstance(answers[i], dict) else None
        if a is None or not isinstance(a.get("artist"), str):
            out.append(_spotify_fallback(track))
            continue
        out.append({"artist": a["artist"].strip(),
                    "album": (a.get("album") or "").strip() or None,
                    "year": (a.get("year") or "").strip()[:4] or None,
                    "unverified": False})
    return out


def identify_albums(tracks: list, usage_out: list | None = None) -> list:
    """The original studio album of each song, in order. Never raises.

    A batch whose call fails falls back to each song's own Spotify album,
    marked unverified — the owner still gets a list to review, and the badge
    says which rows Claude did not check.
    """
    if not tracks:
        return []
    batches = [tracks[i:i + IDENTIFY_BATCH] for i in range(0, len(tracks), IDENTIFY_BATCH)]
    # usage_out is appended from worker threads; list.append is atomic in
    # CPython, and the order of ledger rows does not matter.
    with concurrent.futures.ThreadPoolExecutor(max_workers=IDENTIFY_WORKERS) as pool:
        results = list(pool.map(lambda b: _identify_batch(b, usage_out), batches))
    return [row for batch in results for row in batch]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_identify_albums.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add scan.py tests/test_identify_albums.py
git commit -m "feat: identify each playlist song's original studio album with Claude

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `scan.resolve_album` — one MusicBrainz query per album

**Files:**
- Modify: `scan.py` (add after `lookup_musicbrainz`, ~line 455)
- Test: `tests/test_resolve_album.py`

**Interfaces:**
- Consumes: `scan._mb_get`, `scan._mb_query`, `scan._rank_candidates` (existing).
- Produces: `resolve_album(artist: str, album: str) -> dict | None` — `{"mbid", "year", "artist", "album_name"}` or `None` when MusicBrainz has no match. Raises `MusicBrainzUnavailable` when MusicBrainz can't be reached (callers map it to 502).

- [ ] **Step 1: Write the failing tests**

```python
"""resolve_album: the cheap MusicBrainz lookup the wishlist scan uses.

One throttled call per album and no country lookup — lookup_musicbrainz's
three extra artist calls per album would make a playlist of a hundred
albums take five minutes.
"""

import pytest

import scan


def _group(mbid, title, artist="The Beatles", date="1969-09-26", kind="Album"):
    return {"id": mbid, "title": title, "first-release-date": date,
            "primary-type": kind, "score": 100,
            "artist-credit": [{"artist": {"id": "a1", "name": artist}}]}


def test_returns_the_best_ranked_group(monkeypatch):
    calls = []

    def fake_get(path, params, attempts=scan.MB_MAX_ATTEMPTS):
        calls.append((path, params))
        return {"release-groups": [_group("rg-abbey", "Abbey Road")]}

    monkeypatch.setattr(scan, "_mb_get", fake_get)
    assert scan.resolve_album("The Beatles", "Abbey Road") == {
        "mbid": "rg-abbey", "year": "1969", "artist": "The Beatles",
        "album_name": "Abbey Road"}
    assert len(calls) == 1 and calls[0][0] == "/release-group/"


def test_no_groups_is_none(monkeypatch):
    monkeypatch.setattr(scan, "_mb_get", lambda *a, **k: {"release-groups": []})
    assert scan.resolve_album("Nobody", "Nothing") is None


def test_no_artist_or_album_asks_nothing(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("asked MusicBrainz")
    monkeypatch.setattr(scan, "_mb_get", boom)
    assert scan.resolve_album("", "Abbey Road") is None
    assert scan.resolve_album("The Beatles", "") is None


def test_an_unreachable_musicbrainz_raises(monkeypatch):
    def down(*a, **k):
        raise scan.MusicBrainzUnavailable("down")
    monkeypatch.setattr(scan, "_mb_get", down)
    with pytest.raises(scan.MusicBrainzUnavailable):
        scan.resolve_album("The Beatles", "Abbey Road")


def test_a_group_with_no_date_has_no_year(monkeypatch):
    monkeypatch.setattr(scan, "_mb_get", lambda *a, **k: {
        "release-groups": [_group("rg", "Abbey Road", date="")]})
    assert scan.resolve_album("The Beatles", "Abbey Road")["year"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_resolve_album.py -q`
Expected: FAIL — `AttributeError: module 'scan' has no attribute 'resolve_album'`

- [ ] **Step 3: Implement**

Add to `scan.py` right after `lookup_musicbrainz`:

```python
def resolve_album(artist: str, album: str) -> dict | None:
    """The release group an artist + album names, or None. One MusicBrainz call.

    The wishlist scan's lookup: same query and ranking as lookup_musicbrainz,
    but only the top hit and no artist-country call, because a playlist can
    name a hundred albums and every call here waits a second on the throttle.
    Raises MusicBrainzUnavailable like lookup_musicbrainz does.
    """
    if not artist or not album:
        return None
    payload = _mb_get("/release-group/", {"query": _mb_query(artist, album), "limit": 5})
    groups = (payload or {}).get("release-groups") or []
    ranked = _rank_candidates(groups, album, artist)[:1]
    if not ranked:
        return None
    group = ranked[0]
    credit = (group.get("artist-credit") or [{}])[0].get("artist") or {}
    released = group.get("first-release-date") or ""
    return {"mbid": group.get("id"),
            "year": released[:4] if len(released) >= 4 else None,
            "artist": credit.get("name") or artist,
            "album_name": group.get("title") or album}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_resolve_album.py -q`
Expected: 5 passed. If `_rank_candidates` drops the single fixture group (it can demote non-matching titles), check its rules at `scan.py:343` and make the fixture title match exactly, which it already does here.

- [ ] **Step 5: Commit**

```bash
git add scan.py tests/test_resolve_album.py
git commit -m "feat: resolve an album to its MusicBrainz release group in one call

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Routes — list playlists and scan a playlist

**Files:**
- Modify: `app.py` (new section after the Spotify playlist routes, before `# ── backups` / `@app.route("/api/backups")`, ~line 2326)
- Test: `tests/test_wishlist_scan.py`

**Interfaces:**
- Consumes: `spotify_sync.user_playlists`, `spotify_sync.playlist_tracks` (Task 1); `scan.identify_albums` (Task 2); existing `_spotify_account()`, `_spotify_client(acct)`, `_not_connected()`, `_login_expired(acct)`, `_search_duplicate(row, existing)`, `_record_scan_spend(source, spent)`, `scan._normalise`.
- Produces:
  - `GET /api/spotify/me/playlists` → `200 {"playlists": [...user_playlists rows]}` | `409 {"error", "connect": true}` | `502 {"error"}`
  - `POST /api/spotify/wishlist-scan {playlist_id}` → `200 {"albums": [Album], "truncated": bool, "unplaced": int, "song_count": int}` where
    `Album = {"key": str, "artist": str, "album_name": str, "year": str|None, "songs": [str], "spotify_image": str, "unverified": bool, "duplicate_of": {id, artist, album_name}|None, "have_it": bool|None}`.
    `key` = `"<normalised artist>|<normalised album>"`. Order: first appearance in the playlist.
  - `PLAYLIST_SCAN_CAP = 500` module constant in `app.py`.

- [ ] **Step 1: Write the failing tests**

```python
"""The wishlist scan routes: reading a playlist, naming its albums, and
resolving them in chunks. Spotify, Claude and MusicBrainz are all stubbed at
the module boundary (spotify_sync / scan functions), never at the socket."""

from unittest.mock import patch

import pytest

import app as app_module
import scan
import spotify_sync


@pytest.fixture
def client():
    with app_module.app.app_context():
        app_module.SpotifyAccount.query.delete()
        app_module.Record.query.delete()
        app_module.ScanSpend.query.delete()
        app_module.db.session.commit()
    c = app_module.app.test_client()
    with c.session_transaction() as s:
        s["authed"] = True
    return c


def _connect():
    with app_module.app.app_context():
        app_module.db.session.add(app_module.SpotifyAccount(
            id=1, refresh_token="RT", display_name="Me"))
        app_module.db.session.commit()


def _record(artist, album, have_it=True):
    with app_module.app.app_context():
        r = app_module.Record(artist=artist, album_name=album, have_it=have_it)
        app_module.db.session.add(r)
        app_module.db.session.commit()
        return r.id


def _track(title, artist, album):
    return {"title": title, "artists": [artist], "album": album,
            "release_year": "1969", "image_url": f"https://i/{album}.jpg"}


def _identified(artist, album, unverified=False, year="1969"):
    return {"artist": artist, "album": album, "year": year, "unverified": unverified}


# ── GET /api/spotify/me/playlists ───────────────────────────────────────────

def test_playlists_need_edit_mode():
    c = app_module.app.test_client()
    assert c.get("/api/spotify/me/playlists").status_code == 401


def test_playlists_not_connected_is_409(client):
    r = client.get("/api/spotify/me/playlists")
    assert r.status_code == 409 and r.get_json()["connect"] is True


def test_playlists_lists_the_account(client):
    _connect()
    rows = [{"id": "P1", "name": "Road trip", "image_url": "", "track_count": 3, "owner": "Me"}]
    with patch.object(spotify_sync, "user_playlists", return_value=rows):
        r = client.get("/api/spotify/me/playlists")
    assert r.status_code == 200 and r.get_json() == {"playlists": rows}


def test_playlists_spotify_error_is_502(client):
    _connect()
    with patch.object(spotify_sync, "user_playlists",
                      side_effect=spotify_sync.SpotifyError("Spotify returned 500")):
        r = client.get("/api/spotify/me/playlists")
    assert r.status_code == 502


# ── POST /api/spotify/wishlist-scan ─────────────────────────────────────────

def _scan(client, tracks, identified, truncated=False):
    with patch.object(spotify_sync, "playlist_tracks", return_value=(tracks, truncated)) as pt, \
         patch.object(scan, "identify_albums", return_value=identified) as ia:
        r = client.post("/api/spotify/wishlist-scan", json={"playlist_id": "PL"})
    return r, pt, ia


def test_scan_needs_edit_mode():
    c = app_module.app.test_client()
    assert c.post("/api/spotify/wishlist-scan", json={"playlist_id": "PL"}).status_code == 401


def test_scan_needs_a_playlist_id(client):
    _connect()
    assert client.post("/api/spotify/wishlist-scan", json={}).status_code == 400


def test_scan_not_connected_is_409(client):
    r = client.post("/api/spotify/wishlist-scan", json={"playlist_id": "PL"})
    assert r.status_code == 409


def test_scan_login_expired_is_409_connect(client):
    _connect()
    with patch.object(spotify_sync, "playlist_tracks",
                      side_effect=spotify_sync.NotConnected("revoked")):
        r = client.post("/api/spotify/wishlist-scan", json={"playlist_id": "PL"})
    assert r.status_code == 409 and r.get_json()["connect"] is True


def test_scan_reads_with_the_cap(client):
    _connect()
    _, pt, _ = _scan(client, [], [])
    assert pt.call_args.args[1] == "PL"
    assert pt.call_args.kwargs["cap"] == app_module.PLAYLIST_SCAN_CAP == 500


def test_scan_groups_songs_by_normalised_album(client):
    _connect()
    tracks = [_track("Come Together", "The Beatles", "Abbey Road (Remastered 2009)"),
              _track("Something", "The Beatles", "1"),
              _track("Lovely Day", "Bill Withers", "Menagerie")]
    identified = [_identified("The Beatles", "Abbey Road"),
                  _identified("the beatles", "Abbey  Road"),
                  _identified("Bill Withers", "Menagerie", year="1977")]
    r, _, _ = _scan(client, tracks, identified)
    d = r.get_json()
    assert r.status_code == 200
    assert d["song_count"] == 3 and d["unplaced"] == 0 and d["truncated"] is False
    assert [a["album_name"] for a in d["albums"]] == ["Abbey Road", "Menagerie"]
    abbey = d["albums"][0]
    assert abbey["songs"] == ["Come Together", "Something"]
    assert abbey["artist"] == "The Beatles" and abbey["year"] == "1969"
    assert abbey["spotify_image"] == "https://i/Abbey Road (Remastered 2009).jpg"
    assert abbey["key"] == "beatles|abbey road"
    assert abbey["duplicate_of"] is None and abbey["have_it"] is None


def test_scan_counts_unplaced_songs_and_drops_them(client):
    _connect()
    r, _, _ = _scan(client, [_track("Single", "X", "Single")],
                    [{"artist": "X", "album": None, "year": None, "unverified": False}])
    d = r.get_json()
    assert d["albums"] == [] and d["unplaced"] == 1


def test_scan_keeps_the_unverified_flag(client):
    _connect()
    r, _, _ = _scan(client, [_track("A", "X", "Y")], [_identified("X", "Y", unverified=True)])
    assert r.get_json()["albums"][0]["unverified"] is True


def test_owned_albums_are_marked_and_not_resolved(client):
    _connect()
    owned = _record("The Beatles", "Abbey Road", have_it=True)
    wished = _record("Bill Withers", "Menagerie", have_it=False)
    r, _, _ = _scan(client,
                    [_track("Come Together", "The Beatles", "Abbey Road"),
                     _track("Lovely Day", "Bill Withers", "Menagerie")],
                    [_identified("The Beatles", "Abbey Road"),
                     _identified("Bill Withers", "Menagerie")])
    a, b = r.get_json()["albums"]
    assert a["duplicate_of"]["id"] == owned and a["have_it"] is True
    assert b["duplicate_of"]["id"] == wished and b["have_it"] is False


def test_scan_reports_truncation(client):
    _connect()
    r, _, _ = _scan(client, [], [], truncated=True)
    assert r.get_json()["truncated"] is True


def test_scan_banks_claude_spend_as_playlist(client):
    _connect()

    def identify(tracks, usage_out=None):
        usage_out.append({"model": "claude-haiku-4-5", "input_tokens": 10, "output_tokens": 5})
        return [_identified("X", "Y")]

    with patch.object(spotify_sync, "playlist_tracks", return_value=([_track("A", "X", "Y")], False)), \
         patch.object(scan, "identify_albums", side_effect=identify):
        client.post("/api/spotify/wishlist-scan", json={"playlist_id": "PL"})
    with app_module.app.app_context():
        rows = app_module.ScanSpend.query.all()
        assert [r.source for r in rows] == ["playlist"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_wishlist_scan.py -q`
Expected: FAIL — 404s / `AttributeError: module 'app' has no attribute 'PLAYLIST_SCAN_CAP'`

- [ ] **Step 3: Implement**

Add to `app.py` before `@app.route("/api/backups")`:

```python
# ── spotify playlist → wishlist ───────────────────────────────────────────────
# The admin page's tool: read one of the owner's playlists, name each song's
# studio album, and offer the albums for the wishlist. Split in two routes
# because the MusicBrainz half is throttled to a call a second — a big
# playlist cannot be resolved inside gunicorn's 120 s, so the browser feeds
# the albums back to /resolve in chunks (see RESOLVE_CHUNK).

PLAYLIST_SCAN_CAP = 500


def _album_key(artist, album):
    return f"{scan._normalise(artist)}|{scan._normalise(album)}"


@app.route("/api/spotify/me/playlists")
@require_auth
def spotify_my_playlists():
    acct = _spotify_account()
    if not acct or not acct.refresh_token:
        return _not_connected()
    try:
        return jsonify({"playlists": spotify_sync.user_playlists(_spotify_client(acct))})
    except spotify_sync.NotConnected:
        return _login_expired(acct)
    except (spotify_sync.SpotifyError, requests.RequestException) as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/spotify/wishlist-scan", methods=["POST"])
@require_auth
def spotify_wishlist_scan():
    d = request.get_json(silent=True) or {}
    playlist_id = str(d.get("playlist_id") or "").strip()
    if not playlist_id:
        return jsonify({"error": "pick a playlist first"}), 400
    acct = _spotify_account()
    if not acct or not acct.refresh_token:
        return _not_connected()

    spent = []
    try:
        try:
            tracks, truncated = spotify_sync.playlist_tracks(
                _spotify_client(acct), playlist_id, cap=PLAYLIST_SCAN_CAP)
        except spotify_sync.NotConnected:
            return _login_expired(acct)
        except (spotify_sync.SpotifyError, requests.RequestException) as e:
            return jsonify({"error": str(e)}), 502

        identified = scan.identify_albums(tracks, usage_out=spent)

        albums, by_key, unplaced = [], {}, 0
        for track, found in zip(tracks, identified):
            if not found.get("album"):
                unplaced += 1
                continue
            key = _album_key(found["artist"], found["album"])
            row = by_key.get(key)
            if row is None:
                row = by_key[key] = {
                    "key": key, "artist": found["artist"], "album_name": found["album"],
                    "year": found.get("year"), "songs": [],
                    "spotify_image": track.get("image_url") or "",
                    "unverified": bool(found.get("unverified")),
                    "duplicate_of": None, "have_it": None}
                albums.append(row)
            row["songs"].append(track["title"])

        owned = {r.id: r.have_it for r in Record.query.with_entities(Record.id, Record.have_it)}
        existing = [{"id": r.id, "artist": r.artist or "", "album_name": r.album_name or ""}
                    for r in Record.query.with_entities(Record.id, Record.artist, Record.album_name)]
        for row in albums:
            dup = _search_duplicate({"credited": row["artist"], "album_name": row["album_name"]},
                                    existing)
            if dup:
                row["duplicate_of"] = dup
                row["have_it"] = bool(owned.get(dup["id"]))

        return jsonify({"albums": albums, "truncated": truncated,
                        "unplaced": unplaced, "song_count": len(tracks)})
    finally:
        _record_scan_spend("playlist", spent)
```

Check `requests` is already imported in `app.py` (`grep -n "^import requests" app.py`); it is used by the existing sync route's `except`, so it should be.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_wishlist_scan.py -q`
Expected: 15 passed

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_wishlist_scan.py
git commit -m "feat: list Spotify playlists and scan one into wishlist candidates

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Route — resolve a chunk of albums (MusicBrainz, covers, vinyl)

**Files:**
- Modify: `app.py` (append to the section from Task 4)
- Test: `tests/test_wishlist_scan.py` (append)

**Interfaces:**
- Consumes: `scan.resolve_album` (Task 3); existing `scan.search_covers(rows)`, `scan.flag_vinyl(rows, usage_out=)`, `scan._download_image(url)`, `scan.COVER_FETCH_LIMIT`.
- Produces: `POST /api/spotify/wishlist-scan/resolve {albums: [Album]}` → `200 {"albums": [Album + {"mbid": str|None, "year": str|None, "cover_data": str|None, "vinyl": "confirmed"|"likely"|"none"}]}` in input order; `400` for an empty list or more than `RESOLVE_CHUNK`; `502 {"error"}` when MusicBrainz is down. `RESOLVE_CHUNK = 24` in `app.py`. Rows with `duplicate_of` set are returned unchanged (no lookups).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_wishlist_scan.py`)

```python
# ── POST /api/spotify/wishlist-scan/resolve ─────────────────────────────────

def _album(artist, album, **extra):
    row = {"key": f"{artist}|{album}".lower(), "artist": artist, "album_name": album,
           "year": "1969", "songs": ["x"], "spotify_image": "https://i/s.jpg",
           "unverified": False, "duplicate_of": None, "have_it": None}
    row.update(extra)
    return row


@pytest.fixture
def offline_resolve():
    """resolve / covers / vinyl stubbed; tests override what they care about."""
    with patch.object(scan, "resolve_album",
                      side_effect=lambda a, b: {"mbid": f"rg-{b}", "year": "1970",
                                                "artist": a, "album_name": b}) as ra, \
         patch.object(scan, "search_covers",
                      side_effect=lambda rows: [r.__setitem__("cover_data", "data:c") for r in rows]), \
         patch.object(scan, "flag_vinyl",
                      side_effect=lambda rows, **kw: [r.__setitem__("vinyl", "confirmed") for r in rows]) as fv, \
         patch.object(scan, "_download_image", return_value="data:spotify"):
        yield ra, fv


def test_resolve_needs_edit_mode():
    c = app_module.app.test_client()
    r = c.post("/api/spotify/wishlist-scan/resolve", json={"albums": [_album("A", "B")]})
    assert r.status_code == 401


def test_resolve_refuses_empty_and_oversized_chunks(client):
    assert client.post("/api/spotify/wishlist-scan/resolve", json={"albums": []}).status_code == 400
    too_many = [_album("A", f"B{i}") for i in range(app_module.RESOLVE_CHUNK + 1)]
    assert app_module.RESOLVE_CHUNK == 24
    assert client.post("/api/spotify/wishlist-scan/resolve",
                       json={"albums": too_many}).status_code == 400


def test_resolve_fills_mbid_year_cover_and_vinyl_in_order(client, offline_resolve):
    r = client.post("/api/spotify/wishlist-scan/resolve",
                    json={"albums": [_album("The Beatles", "Abbey Road"),
                                     _album("Bill Withers", "Menagerie")]})
    assert r.status_code == 200
    a, b = r.get_json()["albums"]
    assert (a["album_name"], a["mbid"], a["year"], a["cover_data"], a["vinyl"]) == \
           ("Abbey Road", "rg-Abbey Road", "1970", "data:c", "confirmed")
    assert b["album_name"] == "Menagerie" and b["songs"] == ["x"]


def test_resolve_keeps_claudes_name_when_musicbrainz_has_none(client, offline_resolve):
    ra, _ = offline_resolve
    ra.side_effect = lambda a, b: None
    a = client.post("/api/spotify/wishlist-scan/resolve",
                    json={"albums": [_album("X", "Obscure")]}).get_json()["albums"][0]
    assert a["mbid"] is None and a["album_name"] == "Obscure" and a["year"] == "1969"


def test_resolve_falls_back_to_the_spotify_image(client, offline_resolve):
    with patch.object(scan, "search_covers",
                      side_effect=lambda rows: [r.__setitem__("cover_data", None) for r in rows]):
        a = client.post("/api/spotify/wishlist-scan/resolve",
                        json={"albums": [_album("X", "Y")]}).get_json()["albums"][0]
    assert a["cover_data"] == "data:spotify"


def test_resolve_skips_rows_already_owned(client, offline_resolve):
    ra, fv = offline_resolve
    owned = _album("X", "Y", duplicate_of={"id": 1, "artist": "X", "album_name": "Y"}, have_it=True)
    a = client.post("/api/spotify/wishlist-scan/resolve",
                    json={"albums": [owned]}).get_json()["albums"][0]
    assert ra.call_count == 0 and a["duplicate_of"]["id"] == 1


def test_resolve_maps_musicbrainz_down_to_502(client, offline_resolve):
    ra, _ = offline_resolve
    ra.side_effect = scan.MusicBrainzUnavailable("down")
    r = client.post("/api/spotify/wishlist-scan/resolve", json={"albums": [_album("X", "Y")]})
    assert r.status_code == 502 and "MusicBrainz" in r.get_json()["error"]


def test_resolve_banks_vinyl_spend_as_playlist(client, offline_resolve):
    _, fv = offline_resolve

    def flag(rows, usage_out=None, **kw):
        usage_out.append({"model": "claude-haiku-4-5", "input_tokens": 1, "output_tokens": 1})
        for r in rows:
            r["vinyl"] = "likely"

    fv.side_effect = flag
    client.post("/api/spotify/wishlist-scan/resolve", json={"albums": [_album("X", "Y")]})
    with app_module.app.app_context():
        assert [r.source for r in app_module.ScanSpend.query.all()] == ["playlist"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_wishlist_scan.py -q -k resolve`
Expected: FAIL — 404 / `AttributeError: ... 'RESOLVE_CHUNK'`

- [ ] **Step 3: Implement** (append to the Task 4 section in `app.py`)

```python
# One chunk is at most what search_covers will fetch artwork for, so no row
# in a chunk comes back without a cover for want of budget — and 24 throttled
# MusicBrainz calls is about 25 s, far inside the worker timeout.
RESOLVE_CHUNK = scan.COVER_FETCH_LIMIT


@app.route("/api/spotify/wishlist-scan/resolve", methods=["POST"])
@require_auth
def spotify_wishlist_resolve():
    d = request.get_json(silent=True) or {}
    albums = d.get("albums")
    if not isinstance(albums, list) or not albums:
        return jsonify({"error": "no albums to check"}), 400
    if len(albums) > RESOLVE_CHUNK:
        return jsonify({"error": f"at most {RESOLVE_CHUNK} albums per call"}), 400

    rows = [dict(a) for a in albums if isinstance(a, dict)]
    todo = [r for r in rows if not r.get("duplicate_of")]
    spent = []
    try:
        try:
            for row in todo:
                found = scan.resolve_album(row.get("artist") or "", row.get("album_name") or "")
                row["mbid"] = found["mbid"] if found else None
                if found and found.get("year"):
                    row["year"] = found["year"]
        except scan.MusicBrainzUnavailable:
            app.logger.warning("MusicBrainz unavailable for the wishlist scan")
            return jsonify({"error": "Couldn't reach MusicBrainz — try again in a moment"}), 502

        # search_covers and flag_vinyl both read artist / album_name / mbid,
        # which is exactly what these rows carry.
        scan.search_covers(todo)
        for row in todo:
            if not row.get("cover_data") and row.get("spotify_image"):
                row["cover_data"] = scan._download_image(row["spotify_image"])
        scan.flag_vinyl(todo, usage_out=spent)
        return jsonify({"albums": rows})
    finally:
        _record_scan_spend("playlist", spent)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_wishlist_scan.py -q`
Expected: 23 passed

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_wishlist_scan.py
git commit -m "feat: resolve wishlist-scan albums in chunks — MusicBrainz, covers, vinyl

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `static/admin.js` — review-list rules

**Files:**
- Create: `static/admin.js`
- Create: `tests/test_admin.js`, `tests/test_admin_js.py`

**Interfaces:**
- Consumes: the `Album` shape from Tasks 4–5. `vinyl` is absent until the album's chunk has been resolved.
- Produces (global `VinylAdmin` in the browser, `module.exports` in node):
  - `canTick(album) -> bool` — false if `duplicate_of`, if `vinyl === 'none'`, or if not resolved yet (`!album.vinyl`)
  - `defaultTicked(album) -> bool` — `canTick(album) && album.vinyl === 'confirmed' && !album.unverified`
  - `chunk(list, size) -> list[list]`
  - `songsLabel(songs) -> string` — `"1 song: A"`, `"3 songs: A, B, C"`, `"5 songs: A, B, C, …"`
  - `progressText(stage, done, total) -> string` — `'reading'` → `"reading songs and naming albums…"`; `'resolving'` → `"checking vinyl 24 / 140"`

- [ ] **Step 1: Write the failing tests**

`tests/test_admin.js`:

```js
// The review list's rules — which album rows can be ticked, and which start
// ticked. Pure, so they are pinned here rather than through the DOM.

const test = require('node:test');
const assert = require('node:assert');

const { canTick, defaultTicked, chunk, songsLabel, progressText } =
  require('../static/admin.js');

const album = extra => Object.assign({ key: 'k', artist: 'A', album_name: 'B',
  songs: ['x'], unverified: false, duplicate_of: null, have_it: null,
  vinyl: 'confirmed' }, extra);

test('a confirmed, verified album can be ticked and starts ticked', () => {
  assert.strictEqual(canTick(album()), true);
  assert.strictEqual(defaultTicked(album()), true);
});

test('a likely album can be ticked but starts unticked', () => {
  assert.strictEqual(canTick(album({ vinyl: 'likely' })), true);
  assert.strictEqual(defaultTicked(album({ vinyl: 'likely' })), false);
});

test('an album never pressed on vinyl cannot be ticked', () => {
  assert.strictEqual(canTick(album({ vinyl: 'none' })), false);
  assert.strictEqual(defaultTicked(album({ vinyl: 'none' })), false);
});

test('an album already owned or wishlisted cannot be ticked', () => {
  const owned = album({ duplicate_of: { id: 1 }, have_it: true, vinyl: undefined });
  assert.strictEqual(canTick(owned), false);
  assert.strictEqual(defaultTicked(owned), false);
  assert.strictEqual(canTick(album({ duplicate_of: { id: 2 }, have_it: false })), false);
});

test('an album still being checked cannot be ticked yet', () => {
  assert.strictEqual(canTick(album({ vinyl: undefined })), false);
});

test('an unverified confirmed album can be ticked but starts unticked', () => {
  const a = album({ unverified: true });
  assert.strictEqual(canTick(a), true);
  assert.strictEqual(defaultTicked(a), false);
});

test('chunk splits into fixed-size pieces, last one short', () => {
  assert.deepStrictEqual(chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]);
  assert.deepStrictEqual(chunk([], 24), []);
});

test('songsLabel names up to three songs', () => {
  assert.strictEqual(songsLabel(['A']), '1 song: A');
  assert.strictEqual(songsLabel(['A', 'B', 'C']), '3 songs: A, B, C');
  assert.strictEqual(songsLabel(['A', 'B', 'C', 'D', 'E']), '5 songs: A, B, C, …');
});

test('progressText words each stage', () => {
  assert.strictEqual(progressText('reading'), 'reading songs and naming albums…');
  assert.strictEqual(progressText('resolving', 24, 140), 'checking vinyl 24 / 140');
});
```

`tests/test_admin_js.py`:

```python
"""Run the admin review-list rules (tests/test_admin.js) under pytest.

Same shape as tests/test_places_js.py: pure functions in static/admin.js,
node's test runner, and a skip when node is not installed.
"""

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_admin_js():
    result = subprocess.run(["node", "--test", "tests/test_admin.js"],
                            cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_admin_js.py -q`
Expected: FAIL — `Cannot find module '../static/admin.js'`

- [ ] **Step 3: Implement** `static/admin.js`

```js
/* The admin page's Spotify → wishlist review list: which album rows can be
 * ticked, which start ticked, and the words for the progress line.
 *
 * Loaded as a plain script in the browser, where `const VinylAdmin` lands in
 * the global lexical scope for the inline script below it; required as a
 * module by tests/test_admin.js. */

const VinylAdmin = (function () {

  /* Never an album already on the shelf or the wishlist, never one MusicBrainz
   * and Claude agree was not pressed, and not until its chunk has come back —
   * an unchecked row has no badge to justify the tick. */
  function canTick(album) {
    if (!album || album.duplicate_of) return false;
    if (!album.vinyl) return false;
    return album.vinyl !== 'none';
  }

  /* Only what is both on a known pressing and named by Claude starts ticked:
   * "likely" and the Spotify-fallback rows are offered, not assumed. */
  function defaultTicked(album) {
    return canTick(album) && album.vinyl === 'confirmed' && !album.unverified;
  }

  function chunk(list, size) {
    const out = [];
    for (let i = 0; i < (list || []).length; i += size) out.push(list.slice(i, i + size));
    return out;
  }

  function songsLabel(songs) {
    const s = songs || [];
    const shown = s.slice(0, 3).join(', ') + (s.length > 3 ? ', …' : '');
    return `${s.length} ${s.length === 1 ? 'song' : 'songs'}: ${shown}`;
  }

  function progressText(stage, done, total) {
    if (stage === 'reading') return 'reading songs and naming albums…';
    return `checking vinyl ${done} / ${total}`;
  }

  return { canTick, defaultTicked, chunk, songsLabel, progressText };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylAdmin;
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_admin_js.py -q`
Expected: 1 passed (9 node subtests)

- [ ] **Step 5: Commit**

```bash
git add static/admin.js tests/test_admin.js tests/test_admin_js.py
git commit -m "feat: review-list rules for the Spotify → wishlist tool

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The admin page — menu, tab, places and data moved in

**Files:**
- Modify: `templates/index.html`
  - CSS near `.playlists-page` (~line 1543)
  - ⋯ menu markup (~lines 3202–3215)
  - page markup after `#playlistsPage` (~line 3451)
  - delete `#placesOverlay` and `#backupsOverlay` (~lines 4207–4232)
  - `<script src="/static/admin.js">` after `spend.js` (~line 4349)
  - `setAuthed` (~lines 4500–4521)
  - `openPlaces`/`closePlaces` (~line 9991), `openBackups`/`closeBackups` (~line 10184)
  - `switchTab` (~line 11576)
- Create: `tests/test_admin_dom.js`, `tests/test_admin_dom.py`
- Delete: `tests/test_backups_dom.js`, `tests/test_backups_dom.py`
- Modify: `tests/test_boot.js` (~line 2658, the export test)

**Interfaces:**
- Consumes: existing `renderPlaces()`, `loadPlaces()`, `renderBackups(list, keepDays)`, `loadBackups()`, `#placesBody`, `#backupsBody`, `#exportBtn`, `#importInput` (ids kept so their existing listeners keep working).
- Produces: `#adminBtn` (menu item), `#adminPage` (`.admin-page`, `.visible` when shown), `openAdmin()`, `loadAdmin()`, `#adminSpotifyBody` (empty container filled in Task 8), and `switchTab('admin')` calling `loadAdmin()`.

- [ ] **Step 1: Write the failing DOM tests**

`tests/test_admin_dom.py`: copy `tests/test_backups_dom.py` exactly, changing only the docstring's first line to `"""Run tests/test_admin_dom.js under pytest.`, the test name to `test_admin_dom_js`, and the node file to `tests/test_admin_dom.js`.

`tests/test_admin_dom.js`: copy the header of `tests/test_backups_dom.js` from the `require`s through the `press()` helper (lines 14–113: `boot`, `settle`, `press`). Then extend `boot()`'s `fetch` stub, before the final `return json({ ok: true })`, with:

```js
    if (u.endsWith('/api/spotify/account')) return json(opts && opts.account || { configured: true, connected: false });
    if (u.endsWith('/api/spotify/me/playlists')) return json({ playlists: (opts && opts.playlists) || [] });
    if (u.endsWith('/api/spotify/playlists')) return json({ playlists: [], genres: [], places: [] });
```

Then replace the tests with:

```js
test('a visitor is offered no admin item', async () => {
  const { win, doc } = await boot({ authed: false });
  try {
    assert.strictEqual(doc.getElementById('adminBtn').style.display, 'none');
  } finally { win.close(); }
});

test('the old places, export, backups and import items are gone from the menu', async () => {
  const { win, doc } = await boot({ authed: true });
  try {
    const menu = doc.getElementById('morePanel');
    for (const id of ['placesBtn', 'backupsBtn', 'exportBtn', 'importLabel'])
      assert.strictEqual(menu.querySelector('#' + id), null, id + ' is still in the menu');
    assert.strictEqual(doc.getElementById('placesOverlay'), null);
    assert.strictEqual(doc.getElementById('backupsOverlay'), null);
  } finally { win.close(); }
});

test('edit mode opens the admin page from the menu with all three sections', async () => {
  const { win, doc } = await boot({ authed: true });
  try {
    assert.notStrictEqual(doc.getElementById('adminBtn').style.display, 'none');
    press(win, doc.getElementById('adminBtn'));
    await settle();
    assert.ok(doc.getElementById('adminPage').classList.contains('visible'));
    assert.ok(doc.getElementById('collectionPage').classList.contains('hidden'));
    assert.ok(doc.getElementById('morePanel').classList.contains('hidden'), 'menu stayed open');
    for (const id of ['placesBody', 'exportBtn', 'importInput', 'backupsBody', 'adminSpotifyBody'])
      assert.ok(doc.querySelector('#adminPage #' + id), id + ' is not on the admin page');
    assert.strictEqual(doc.getElementById('filterBar').style.display, 'none');
  } finally { win.close(); }
});

test('the admin page lists a download link per snapshot, newest first', async () => {
  const { win, doc } = await boot({ authed: true });
  try {
    press(win, doc.getElementById('adminBtn'));
    await settle();
    const links = [...doc.querySelectorAll('#backupsBody a')];
    assert.deepStrictEqual(links.map(a => a.getAttribute('href')),
      ['/api/backups/vinyl-2026-09-19.db', '/api/backups/vinyl-2026-09-18.db']);
  } finally { win.close(); }
});

test('an unanswered backups request says so instead of looking empty', async () => {
  const { win, doc } = await boot({ authed: true, failBackups: true });
  try {
    press(win, doc.getElementById('adminBtn'));
    await settle();
    assert.match(doc.getElementById('backupsBody').textContent, /could not read the backups/);
  } finally { win.close(); }
});

test('the places editor renders on the admin page', async () => {
  const { win, doc } = await boot({ authed: true });
  try {
    press(win, doc.getElementById('adminBtn'));
    await settle();
    assert.match(doc.getElementById('placesBody').textContent, /No places yet|add a new place/);
  } finally { win.close(); }
});

test('locking while on admin goes back to the collection', async () => {
  const { win, doc } = await boot({ authed: true });
  try {
    press(win, doc.getElementById('adminBtn'));
    await settle();
    win.setAuthed(false);
    await settle();
    assert.ok(!doc.getElementById('adminPage').classList.contains('visible'));
    assert.ok(!doc.getElementById('collectionPage').classList.contains('hidden'));
  } finally { win.close(); }
});
```

`tests/test_boot.js` ~line 2658 — replace the export test with:

```js
/* Export, import, backups and places live on the admin page now, and the only
 * door to it is the ⋯ menu's admin item — so that item is what must hide from
 * a visitor (export navigates, and would land them on a bare 401 page). */
test('the admin item is offered only in edit mode', async () => {
  const { win, doc } = await boot();
  win.setAuthed(false);
  assert.strictEqual($(doc, '#adminBtn').style.display, 'none',
    'a visitor is offered an admin page that will refuse them');
  win.setAuthed(true);
  assert.notStrictEqual($(doc, '#adminBtn').style.display, 'none');
});
```

Delete the old files: `git rm tests/test_backups_dom.js tests/test_backups_dom.py`

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_admin_dom.py tests/test_boot.py -q`
Expected: FAIL — `Cannot read properties of null (reading 'style')` for `#adminBtn`

- [ ] **Step 3: Implement**

3a. ⋯ menu (`#morePanel`): delete the `placesBtn`, `exportBtn`, `backupsBtn` buttons and the `importLabel` label. Add right after `loginBtn`:

```html
          <button class="menu-item" id="adminBtn" style="display:none" onclick="openAdmin()"><i class="ti ti-settings"></i><span>admin</span></button>
```

Update the comment at `/* more menu — groups export / import / edit-mode behind the header */` (~line 2159) to `/* more menu — edit mode, admin, playlists, screensaver */`, and the JS banner `// ── header "more actions" menu — export / import / edit mode` to `// ── header "more actions" menu`.

3b. Page markup, right after the `#playlistsPage` div:

```html
  <!-- admin page: the owner's housekeeping in one place — places, the data
       (export / import / snapshots) and the Spotify playlist → wishlist tool.
       Edit mode only; the ⋯ menu's admin item is the only door. The ids
       inside are the ones the old modals used, so their code moved unchanged. -->
  <div class="admin-page" id="adminPage">
    <section class="admin-section">
      <h2 class="admin-h"><i class="ti ti-map-pin"></i> places</h2>
      <div id="placesBody"></div>
    </section>
    <section class="admin-section">
      <h2 class="admin-h"><i class="ti ti-database"></i> data</h2>
      <div class="admin-data-row">
        <button class="btn" id="exportBtn"><i class="ti ti-download"></i> export CSV</button>
        <label class="btn admin-import" id="importLabel">
          <i class="ti ti-upload"></i> import CSV
          <input type="file" accept=".csv" id="importInput">
        </label>
      </div>
      <div class="admin-sub">backups</div>
      <div id="backupsBody"></div>
    </section>
    <section class="admin-section">
      <h2 class="admin-h"><i class="ti ti-brand-spotify"></i> spotify → wishlist</h2>
      <div id="adminSpotifyBody"></div>
    </section>
  </div>
```

3c. CSS, after `.playlists-page.visible{display:block}`:

```css
.admin-page{display:none;max-width:640px}
.admin-page.visible{display:block}
.admin-section{margin:0 0 28px}
.admin-h{font-size:13px;font-weight:600;text-transform:lowercase;letter-spacing:.02em;
  display:flex;align-items:center;gap:6px;margin:0 0 10px;color:var(--text)}
.admin-sub{font-size:12px;color:var(--muted);margin:14px 0 6px}
.admin-data-row{display:flex;gap:8px;flex-wrap:wrap}
.admin-import{position:relative;overflow:hidden;cursor:pointer}
.admin-import input{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;height:100%}
```

Before writing, check the variable names: `grep -n "^\s*--muted\|^\s*--text" templates/index.html | head`. Use whatever the `.playlists-page` rules use for the body and secondary text colours.

3d. Delete the `#placesOverlay` and `#backupsOverlay` blocks, with their comments. Move the backups comment ("Download only: there is deliberately no restore button…") above `renderBackups` in the script.

3e. Script tag: add `<script src="/static/admin.js"></script>` after `<script src="/static/spend.js"></script>`.

3f. `setAuthed`: delete the `importLabel`, `placesBtn`, `exportBtn` and `backupsBtn` display lines and their comments. In their place:

```js
  // The admin page holds export (the private notes), the snapshots (the whole
  // database) and places (a rename rewrites every record) — all behind auth,
  // and this item is the only way in.
  document.getElementById('adminBtn').style.display = val ? '' : 'none';
  if (!val && currentTab === 'admin') switchTab('collection');
```

3g. Replace `openPlaces`/`closePlaces` with nothing (the state reset moves into `loadAdmin`). Replace `openBackups`/`closeBackups` with the admin openers:

```js
// ── admin page ─────────────────────────────────────────────────────────────
function openAdmin(){
  document.getElementById('morePanel').classList.add('hidden');
  switchTab('admin');
}

function loadAdmin(){
  placeEditingId = null;
  placeFormOpen = false;
  renderPlaces();
  loadPlaces().then(renderPlaces);
  renderBackups(null);
  loadBackups();
  loadAdminSpotify();
}

// Filled in by the Spotify → wishlist tool; a placeholder until then.
function loadAdminSpotify(){}
```

`renderPlaces` focuses `#placeName` when the form is open. Since `loadAdmin` closes the form first, opening the page steals no focus.

3h. `switchTab`: after the `playlistsPage` toggle line add

```js
  document.getElementById('adminPage').classList.toggle('visible', tab === 'admin');
```

change the filter-bar condition to

```js
  document.getElementById('filterBar').style.display =
    tab === 'features' || tab === 'playlists' || tab === 'admin' ? 'none' : '';
```

and next to `if (tab === 'playlists') loadPlaylists();` add `if (tab === 'admin') loadAdmin();`.

`urlstate.js`'s `TABS` stays as it is: a reload of `?tab=admin` decodes to the collection, so the admin page cannot be deep-linked, which is what we want for a visitor.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_admin_dom.py tests/test_boot.py tests/test_places.py tests/test_places_js.py tests/test_import.py -q`
Expected: all pass. Then run the whole suite, `python -m pytest -q`, to catch any other test that referenced the removed ids:

```bash
grep -rn "placesOverlay\|backupsOverlay\|openPlaces\|openBackups\|placesBtn\|backupsBtn" tests/ templates/ static/
```
Expected: no matches.

- [ ] **Step 5: Commit**

```bash
git add -A templates/index.html tests/test_admin_dom.js tests/test_admin_dom.py tests/test_boot.js
git commit -m "feat: admin page in the ⋯ menu — places, export, import and backups move in

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Spotify → wishlist UI and the shared `addToWishlist` helper

**Files:**
- Modify: `templates/index.html`
  - `addPickedToWishlist` (~line 9511)
  - `loadAdminSpotify` placeholder from Task 7
  - CSS after the `.admin-*` rules
- Modify: `tests/test_admin_dom.js` (append tests, extend the fetch stub)

**Interfaces:**
- Consumes: `GET /api/spotify/account`, `GET /api/spotify/me/playlists`, `POST /api/spotify/wishlist-scan`, `POST /api/spotify/wishlist-scan/resolve` (Tasks 4–5); `VinylAdmin.*` (Task 6); existing `esc`, `toast`, `records`, `render`, `refreshScanUsage`.
- Produces: `addToWishlist(releases) -> Promise<Record[]>`, used by both search and admin. Admin state is `adminSp = {account, playlists, picked, scan, ticked:Set<key>, busy, error, progress}`.

- [ ] **Step 1: Write the failing DOM tests**

Extend `boot()`'s fetch stub in `tests/test_admin_dom.js` to accept POST bodies and the scan routes. Change the stub's signature to `win.fetch = async (url, init) => {` and add the block below **right after the `json` helper, before the existing `if (u.endsWith('/api/records')) return json([]);` line**. Otherwise that line answers the record POSTs with `[]` and `posted` stays empty:

```js
    const body = init && init.body && typeof init.body === 'string' ? JSON.parse(init.body) : null;
    if (u.endsWith('/api/spotify/wishlist-scan')) return json(opts.scanResult);
    if (u.endsWith('/api/spotify/wishlist-scan/resolve')) {
      if (opts.failResolveAfter !== undefined && ++resolveCalls > opts.failResolveAfter)
        return { ok: false, status: 502, json: async () => ({ error: "Couldn't reach MusicBrainz" }) };
      return json({ albums: body.albums.map(a => Object.assign({}, a,
        a.duplicate_of ? {} : { vinyl: opts.vinyl ? opts.vinyl(a) : 'confirmed', cover_data: '' })) });
    }
    if (u.endsWith('/api/search/genres')) return json({ genres: body.releases.map(() => 'Rock') });
    if (u.endsWith('/api/records') && init && init.method === 'POST') {
      posted.push(body);
      return json(Object.assign({ id: 100 + posted.length }, body));
    }
```

Declare `let resolveCalls = 0; const posted = [];` at the top of `boot()`, and add `posted` to its return object. Make `opts` default to `{}` (`opts = opts || {};` as the first line of `boot`).

Append these tests:

```js
const CONNECTED = { configured: true, connected: true, display_name: 'Me' };
const PLAYLISTS = [{ id: 'PL', name: 'Road trip', image_url: '', track_count: 3, owner: 'Me' }];
const album = (name, extra) => Object.assign({ key: 'a|' + name.toLowerCase(), artist: 'A',
  album_name: name, year: '1970', songs: ['s1'], spotify_image: '', unverified: false,
  duplicate_of: null, have_it: null }, extra);

async function openSpotifyTool(opts) {
  const ctx = await boot(Object.assign({ authed: true, account: CONNECTED, playlists: PLAYLISTS }, opts));
  press(ctx.win, ctx.doc.getElementById('adminBtn'));
  await settle();
  return ctx;
}

async function runScan(ctx) {
  press(ctx.win, ctx.doc.querySelector('#adminSpotifyBody [data-playlist="PL"]'));
  await settle();
  press(ctx.win, ctx.doc.getElementById('adminScanBtn'));
  for (let i = 0; i < 5; i++) await settle();
}

test('not connected shows the connect button and no playlists', async () => {
  const { win, doc } = await openSpotifyTool({ account: { configured: true, connected: false } });
  try {
    const body = doc.getElementById('adminSpotifyBody');
    assert.ok(body.querySelector('[onclick*="/api/spotify/connect"]'), 'no connect button');
    assert.strictEqual(body.querySelectorAll('[data-playlist]').length, 0);
  } finally { win.close(); }
});

test('connected lists the playlists with their song counts', async () => {
  const { win, doc } = await openSpotifyTool();
  try {
    const row = doc.querySelector('#adminSpotifyBody [data-playlist="PL"]');
    assert.ok(row, 'playlist row missing');
    assert.match(row.textContent, /Road trip/);
    assert.match(row.textContent, /3 songs/);
  } finally { win.close(); }
});

test('a scan shows one row per album with the review rules applied', async () => {
  const scanResult = { song_count: 4, unplaced: 1, truncated: false, albums: [
    album('Confirmed'), album('Likely'), album('Never'),
    album('Owned', { duplicate_of: { id: 7, artist: 'A', album_name: 'Owned' }, have_it: true })] };
  const vinyl = a => ({ Confirmed: 'confirmed', Likely: 'likely', Never: 'none' })[a.album_name];
  const { win, doc } = await openSpotifyTool({ scanResult, vinyl });
  try {
    await runScan({ win, doc });
    const box = name => doc.querySelector(`#adminSpotifyBody [data-album="a|${name.toLowerCase()}"] input[type=checkbox]`);
    assert.strictEqual(box('Confirmed').checked, true);
    assert.strictEqual(box('Confirmed').disabled, false);
    assert.strictEqual(box('Likely').checked, false);
    assert.strictEqual(box('Likely').disabled, false);
    assert.strictEqual(box('Never').disabled, true);
    assert.strictEqual(box('Owned').disabled, true);
    assert.match(doc.querySelector('#adminSpotifyBody [data-album="a|owned"]').textContent, /in collection/);
    assert.match(doc.getElementById('adminSpotifyBody').textContent, /1 song.*could not be placed/);
    assert.match(doc.getElementById('adminAddBtn').textContent, /add 1 to wishlist/);
  } finally { win.close(); }
});

test('adding posts the ticked albums as wishlist records', async () => {
  const scanResult = { song_count: 1, unplaced: 0, truncated: false, albums: [album('Confirmed')] };
  const ctx = await openSpotifyTool({ scanResult });
  try {
    await runScan(ctx);
    press(ctx.win, ctx.doc.getElementById('adminAddBtn'));
    for (let i = 0; i < 5; i++) await settle();
    assert.strictEqual(ctx.posted.length, 1);
    assert.deepStrictEqual(
      { artist: ctx.posted[0].artist, album_name: ctx.posted[0].album_name,
        have_it: ctx.posted[0].have_it, genre: ctx.posted[0].genre },
      { artist: 'A', album_name: 'Confirmed', have_it: false, genre: 'Rock' });
    assert.match(ctx.doc.querySelector('[data-album="a|confirmed"]').textContent, /on wishlist/);
  } finally { ctx.win.close(); }
});

test('a failed chunk keeps what was resolved and shows the error', async () => {
  const albums = Array.from({ length: 30 }, (_, i) => album('Album ' + i));
  const scanResult = { song_count: 30, unplaced: 0, truncated: false, albums };
  const ctx = await openSpotifyTool({ scanResult, failResolveAfter: 1 });
  try {
    await runScan(ctx);
    const body = ctx.doc.getElementById('adminSpotifyBody');
    assert.match(body.textContent, /Couldn't reach MusicBrainz/);
    assert.strictEqual(ctx.doc.querySelector('[data-album="a|album 0"] input').disabled, false);
    assert.strictEqual(ctx.doc.querySelector('[data-album="a|album 29"] input').disabled, true);
  } finally { ctx.win.close(); }
});

test('a cut playlist says how many songs were read', async () => {
  const scanResult = { song_count: 500, unplaced: 0, truncated: true, albums: [album('X')] };
  const ctx = await openSpotifyTool({ scanResult });
  try {
    await runScan(ctx);
    assert.match(ctx.doc.getElementById('adminSpotifyBody').textContent, /first 500 songs/);
  } finally { ctx.win.close(); }
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_admin_dom.py -q`
Expected: the six new tests FAIL (no connect button, no `[data-playlist]` rows); the Task 7 tests still pass.

- [ ] **Step 3: Implement**

3a. Pull `addToWishlist` out of `addPickedToWishlist`. Replace the body between `try {` and the toast with a call to a new helper defined just above it:

```js
/* The wishlist's whole act is naming the record — no purchase, no condition,
 * nothing else to fill (see setHaveIt) — so each release goes straight to
 * /api/records with what was already collected about it. Shared by search's
 * bulk add and the admin page's playlist tool. One failed POST does not stop
 * the rest; the caller gets only what was actually added. */
async function addToWishlist(releases){
  let genres = [];
  try{
    const res = await fetch('/api/search/genres', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({releases: releases.map(r => (
        {artist: r.artist, album_name: r.album_name}))})});
    if(res.ok) genres = (await res.json()).genres || [];
  }catch(e){ /* a record with no genre is a record you set the genre on */ }

  const added = [];
  for (let i = 0; i < releases.length; i++) {
    const r = releases[i];
    const body = {
      artist: r.artist || '', album_name: r.album_name || '',
      year: r.year || '', genre: genres[i] || '',
      country: r.country || '', cover_data: r.cover_data || '',
      have_it: false,
    };
    try{
      const res = await fetch('/api/records', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
      if(res.ok) added.push(await res.json());
    }catch(e){ /* one failed add should not stop the rest of the batch */ }
  }
  added.forEach(rec => records.push(rec));
  if(added.length) render();
  refreshScanUsage();
  return added;
}
```

and in `addPickedToWishlist` keep the guard and status lines. Replace the genres fetch and the POST loop with:

```js
    document.getElementById('searchAddStatusText').textContent = 'adding…';
    const added = await addToWishlist(picked);
```

Leave its own `added.forEach(...)`, `render()` and `refreshScanUsage()` calls out, since the helper now does them. Keep `closeForm(true)` and the toast. Run `python -m pytest tests/test_search_endpoint.py tests/test_boot.py -q` now to make sure search's wishlist add didn't change.

3b. Replace the `loadAdminSpotify(){}` placeholder with the tool:

```js
// ── admin: spotify playlist → wishlist ─────────────────────────────────────
// The server names each song's studio album in one call, then the albums
// come back to /resolve in chunks of RESOLVE_CHUNK — MusicBrainz is throttled
// to a call a second, and one request for a whole playlist would outlive the
// worker timeout. Each chunk re-renders the list, so the rows fill in as the
// badges arrive; a failed chunk stops the loop but keeps what came back.
const ADMIN_RESOLVE_CHUNK = 24;
let adminSp = {account: null, playlists: [], picked: null, scan: null,
               ticked: new Set(), busy: false, error: '', progress: ''};

async function loadAdminSpotify(){
  adminSp.error = '';
  try{
    const r = await fetch('/api/spotify/account');
    adminSp.account = r.ok ? await r.json() : null;
    if(adminSp.account && adminSp.account.connected){
      const p = await fetch('/api/spotify/me/playlists');
      const d = await p.json().catch(() => ({}));
      if(p.ok) adminSp.playlists = d.playlists || [];
      else { adminSp.error = d.error || 'could not read your playlists';
             if(d.connect) adminSp.account.connected = false; }
    }
  }catch(e){ adminSp.error = 'could not reach the server'; }
  renderAdminSpotify();
}

function pickAdminPlaylist(id){
  if(adminSp.busy) return;
  adminSp.picked = id; adminSp.scan = null; adminSp.ticked = new Set(); adminSp.error = '';
  renderAdminSpotify();
}

async function scanAdminPlaylist(){
  if(adminSp.busy || !adminSp.picked) return;
  adminSp.busy = true; adminSp.error = ''; adminSp.scan = null; adminSp.ticked = new Set();
  adminSp.progress = VinylAdmin.progressText('reading');
  renderAdminSpotify();
  try{
    const r = await fetch('/api/spotify/wishlist-scan', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({playlist_id: adminSp.picked})});
    const d = await r.json().catch(() => ({}));
    if(!r.ok){
      adminSp.error = d.error || 'the scan failed';
      if(d.connect && adminSp.account) adminSp.account.connected = false;
      return;
    }
    adminSp.scan = d;
    const pending = d.albums.filter(a => !a.duplicate_of);
    const chunks = VinylAdmin.chunk(pending, ADMIN_RESOLVE_CHUNK);
    let done = 0;
    for(const part of chunks){
      adminSp.progress = VinylAdmin.progressText('resolving', done, pending.length);
      renderAdminSpotify();
      const rr = await fetch('/api/spotify/wishlist-scan/resolve', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify({albums: part})});
      const dd = await rr.json().catch(() => ({}));
      if(!rr.ok){ adminSp.error = dd.error || 'checking vinyl failed'; break; }
      const byKey = new Map(dd.albums.map(a => [a.key, a]));
      adminSp.scan.albums = adminSp.scan.albums.map(a => byKey.get(a.key) || a);
      dd.albums.forEach(a => { if(VinylAdmin.defaultTicked(a)) adminSp.ticked.add(a.key); });
      done += part.length;
    }
  }catch(e){
    adminSp.error = 'could not reach the server';
  }finally{
    adminSp.busy = false; adminSp.progress = '';
    renderAdminSpotify();
    refreshScanUsage();
  }
}

function toggleAdminAlbum(key, on){
  if(on) adminSp.ticked.add(key); else adminSp.ticked.delete(key);
  renderAdminSpotify();
}

async function addAdminAlbums(){
  if(adminSp.busy || !adminSp.scan) return;
  const picked = adminSp.scan.albums.filter(a => adminSp.ticked.has(a.key) && VinylAdmin.canTick(a));
  if(!picked.length) return;
  adminSp.busy = true; adminSp.progress = 'adding…'; renderAdminSpotify();
  try{
    const added = await addToWishlist(picked);
    // Matched back by name, not position: a failed POST leaves a gap.
    const keyOf = r => (r.artist || '').toLowerCase() + '|' + (r.album_name || '').toLowerCase();
    const addedBy = new Map(added.map(r => [keyOf(r), r]));
    adminSp.scan.albums = adminSp.scan.albums.map(a => {
      const rec = addedBy.get(keyOf(a));
      if(!rec) return a;
      adminSp.ticked.delete(a.key);
      return Object.assign({}, a, {duplicate_of: {id: rec.id, artist: rec.artist,
        album_name: rec.album_name}, have_it: false});
    });
    toast(added.length ? `${added.length} added to the wishlist` : 'nothing was added — try again');
  }finally{
    adminSp.busy = false; adminSp.progress = '';
    renderAdminSpotify();
  }
}

function adminAlbumRowHTML(a){
  const can = VinylAdmin.canTick(a);
  const checked = can && adminSp.ticked.has(a.key);
  const badge = a.duplicate_of ? (a.have_it ? 'in collection' : 'on wishlist')
    : !a.vinyl ? 'checking…'
    : a.vinyl === 'confirmed' ? 'on vinyl' : a.vinyl === 'likely' ? 'likely on vinyl' : 'no vinyl';
  const cover = a.cover_data || a.spotify_image;
  return `<label class="asw-row${can ? '' : ' off'}" data-album="${esc(a.key)}">
    <input type="checkbox" ${checked ? 'checked' : ''} ${can && !adminSp.busy ? '' : 'disabled'}
      onchange="toggleAdminAlbum(this.closest('[data-album]').dataset.album, this.checked)">
    ${cover ? `<img class="asw-cover" src="${esc(cover)}" alt="">` : '<span class="asw-cover"></span>'}
    <span class="asw-text">
      <span class="asw-title">${esc(a.album_name)}${a.year ? ` <span class="asw-year">${esc(a.year)}</span>` : ''}</span>
      <span class="asw-artist">${esc(a.artist)}</span>
      <span class="asw-songs">${esc(VinylAdmin.songsLabel(a.songs))}</span>
    </span>
    <span class="asw-badge v-${esc(a.duplicate_of ? 'owned' : (a.vinyl || 'pending'))}">${esc(badge)}${a.unverified ? ' · unverified' : ''}</span>
  </label>`;
}

function renderAdminSpotify(){
  const body = document.getElementById('adminSpotifyBody');
  if(!body) return;
  const acct = adminSp.account;
  if(!acct){ body.innerHTML = `<div class="backup-note">${esc(adminSp.error || 'loading…')}</div>`; return; }
  if(!acct.connected){
    body.innerHTML = `${adminSp.error ? `<div class="place-err">${esc(adminSp.error)}</div>` : ''}
      <button class="btn" onclick="window.location.href='/api/spotify/connect'">
      <i class="ti ti-brand-spotify"></i> connect Spotify</button>`;
    return;
  }
  const lists = adminSp.playlists.map(p => `<button class="asw-pl${p.id === adminSp.picked ? ' on' : ''}"
      data-playlist="${esc(p.id)}" onclick="pickAdminPlaylist(this.dataset.playlist)" ${adminSp.busy ? 'disabled' : ''}>
      ${p.image_url ? `<img src="${esc(p.image_url)}" alt="">` : '<span class="asw-pl-img"></span>'}
      <span class="asw-pl-name">${esc(p.name)}</span>
      <span class="asw-pl-count">${p.track_count} ${p.track_count === 1 ? 'song' : 'songs'}</span>
    </button>`).join('') || '<div class="backup-note">no playlists on this account</div>';

  let html = `<div class="asw-pls">${lists}</div>`;
  if(adminSp.picked) html += `<button class="btn btn-primary" id="adminScanBtn"
      onclick="scanAdminPlaylist()" ${adminSp.busy ? 'disabled' : ''}><i class="ti ti-search"></i> scan</button>`;
  if(adminSp.progress) html += `<div class="backup-note">${esc(adminSp.progress)}</div>`;
  if(adminSp.error) html += `<div class="place-err">${esc(adminSp.error)}</div>`;

  const s = adminSp.scan;
  if(s){
    const notes = [];
    if(s.truncated) notes.push(`only the first ${s.song_count} songs were read`);
    if(s.unplaced) notes.push(`${s.unplaced} ${s.unplaced === 1 ? 'song' : 'songs'} could not be placed on an album`);
    if(notes.length) html += `<div class="backup-note">${esc(notes.join(' · '))}</div>`;
    if(!s.albums.length) html += '<div class="backup-note">nothing to add from this playlist</div>';
    html += `<div class="asw-list">${s.albums.map(adminAlbumRowHTML).join('')}</div>`;
    const n = s.albums.filter(a => adminSp.ticked.has(a.key) && VinylAdmin.canTick(a)).length;
    if(s.albums.length) html += `<button class="btn btn-primary" id="adminAddBtn" onclick="addAdminAlbums()"
      ${n && !adminSp.busy ? '' : 'disabled'}><i class="ti ti-shopping-cart"></i> add ${n} to wishlist</button>`;
  }
  body.innerHTML = html;
}
```

3c. CSS, after the `.admin-*` rules (purple `#9B7FD4` is the app's wishlist colour, green its owned colour; check the owned green with `grep -n "own-opt" templates/index.html`):

```css
.asw-pls{display:flex;flex-direction:column;gap:4px;margin:0 0 10px;max-height:260px;overflow:auto}
.asw-pl{display:flex;align-items:center;gap:10px;padding:6px 8px;border-radius:8px;border:1px solid transparent;
  background:none;color:inherit;text-align:left;cursor:pointer;font:inherit}
.asw-pl:hover{background:var(--surface2,rgba(127,127,127,.08))}
.asw-pl.on{border-color:var(--accent)}
.asw-pl img,.asw-pl-img{width:32px;height:32px;border-radius:4px;object-fit:cover;background:rgba(127,127,127,.15);flex-shrink:0}
.asw-pl-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.asw-pl-count{font-size:12px;opacity:.6}
.asw-list{display:flex;flex-direction:column;gap:6px;margin:12px 0}
.asw-row{display:flex;align-items:center;gap:10px;padding:6px 8px;border-radius:8px;cursor:pointer}
.asw-row.off{opacity:.5;cursor:default}
.asw-cover{width:44px;height:44px;border-radius:4px;object-fit:cover;background:rgba(127,127,127,.15);flex-shrink:0}
.asw-text{flex:1;min-width:0;display:flex;flex-direction:column}
.asw-title{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.asw-year,.asw-artist,.asw-songs{font-size:12px;opacity:.7}
.asw-songs{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.asw-badge{font-size:11px;padding:2px 8px;border-radius:999px;white-space:nowrap;background:rgba(127,127,127,.15)}
.asw-badge.v-confirmed{color:#4CAF7D;background:rgba(76,175,125,.16)}
.asw-badge.v-likely{color:#9B7FD4;background:rgba(155,127,212,.16)}
```

Keep the page within 16px side padding at phone width. The rows wrap their text with ellipsis, so no row scrolls horizontally.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_admin_dom.py tests/test_boot.py tests/test_search_endpoint.py -q`
Expected: all pass. Then run the full suite: `python -m pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html tests/test_admin_dom.js
git commit -m "feat: Spotify playlist → wishlist tool on the admin page

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Manual verification doc and README

**Files:**
- Create: `docs/admin-page-manual-verification.md`
- Modify: `README.md` (the features list; check its headings with `grep -n "^#" README.md`)

- [ ] **Step 1: Write the manual verification doc**

Follow the shape of `docs/bought-at-places-manual-verification.md` (`head -40` it first):

```markdown
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
```

- [ ] **Step 2: Add a README line**

In the features list, add one bullet next to the Spotify playlists entry:

```markdown
- **Admin page** (⋯ → admin, edit mode): places, CSV export/import, backups, and a Spotify playlist → wishlist tool that names each song's studio album with Claude and checks MusicBrainz for a vinyl pressing.
```

- [ ] **Step 3: Run the full suite one last time**

Run: `python -m pytest -q`
Expected: all pass (node-backed tests skip only if node is absent).

- [ ] **Step 4: Commit**

```bash
git add docs/admin-page-manual-verification.md README.md
git commit -m "docs: admin page manual verification and README entry

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
