# Search by Name Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third way to fill the add-record form — type an artist or album name, get that artist's real releases, tick several, and fill the form for each in turn.

**Architecture:** One cheap Claude call parses the loose query into `{artist, album?}`. MusicBrainz then answers the whole question in two throttled calls — artist search for the MBID, then a release-group search by `arid:` — so year, country, type and MBID arrive for every row at once and ticking a card needs no second lookup. Cover art is the only fan-out, fetched in a thread pool. The picked releases become a queue that walks the existing add form, one record at a time.

**Tech Stack:** Flask + SQLAlchemy, `anthropic` SDK, `requests`, vanilla JS in one Jinja template plus small pure ES5 modules under `static/`, pytest + `node --test` + jsdom.

**Spec:** `docs/superpowers/specs/2026-09-07-search-by-name-design.md`

## Global Constraints

- **Never let Claude recall a year, country or release list.** Claude parses the query; MusicBrainz supplies every fact. This mirrors `_SLEEVE_SYSTEM` (`scan.py:506`).
- **No `effort` in `output_config`.** It 400s on Haiku 4.5 — see the comment at `scan.py:645`. Structured outputs (`output_config.format`) are fine.
- **`SEARCH_MODEL = "claude-haiku-4-5"`**, which is already priced in `pricing.py`.
- **`MB_SEARCH_LIMIT = 40`**, **`COVER_WORKERS = 8`**, **`COVER_FETCH_LIMIT = 24`**.
- **Every external call is mocked in tests.** `tests/conftest.py` installs an autouse `no_real_network` fixture that raises on any real socket. A test that forgets a patch fails loudly rather than billing the API.
- **MusicBrainz tests must neutralise the throttle.** Copy the `no_real_sleeping` fixture from `tests/test_scan_musicbrainz.py:9-16`, or every lookup blocks a real second.
- **Spend is banked in a `finally`.** The Claude call was billed the moment it returned, whatever failed afterwards.
- **JS tests are `node --test`, wrapped by a pytest shim** so `pytest` stays the single command. Copy the shim from `tests/test_spend.py`.
- **Line references are against `main` at `ddfd7d7`.** This repo's `templates/index.html` moves a lot; treat every reference as a symbol name first and a number second.

---

## A correction to the spec, before Task 1

The spec says per-row `duplicate_of` comes from the existing `find_duplicate` "no new code". **That is wrong, and it would ship a feature that silently never works.**

`find_duplicate` (`scan.py:108`) requires an exact match after `_normalise` on *both* artist and album. MusicBrainz canonicalises this artist to **"Jorge Ben Jor"**, while all three records in the collection say **"Jorge Ben"**:

```
_normalise("Jorge Ben Jor") == "jorge ben jor"
_normalise("Jorge Ben")     == "jorge ben"        # never equal
```

So not one of the three duplicate badges the mockup promises would fire.

The release-group payload carries both names:

```json
"artist-credit": [{"name": "Jorge Ben",
                   "artist": {"id": "19499124-…", "name": "Jorge Ben Jor"}}]
```

`artist-credit[0].name` is the name **credited on that release** — "Jorge Ben" — and it is the one that matches the collection. `lookup_musicbrainz` uses the canonical `artist.name`; this plan deliberately does **not** change that (it would alter photo-scan behaviour nobody asked to change).

Two consequences, both handled in Task 2 and Task 4:

1. `lookup_discography` returns the **credited** name as `artist`, falling back to the canonical one. This is also what should fill the form — adding three records as "Jorge Ben Jor" beside three existing "Jorge Ben" would split the artist in the shelf's crates and in `setupBlocks`.
2. Duplicate detection tries the credited name **and** the canonical name, so a collection filed either way is still matched.

---

## File Structure

| File | Responsibility |
|---|---|
| `scan.py` (modify) | `parse_search_query`, `lookup_artist`, `lookup_discography`, `search_covers`. Record identification is already this module's job. |
| `app.py` (modify) | `POST /api/search`, `POST /api/search/genres`, two ledger touch-ups. |
| `static/queue.js` (create) | Pure queue model — position, counter, labels, chip states, advance/skip. New file because the four DOM collisions in Task 9 are only reviewable if the state machine underneath them is pure and unit-tested, exactly as `draft.js` and `spend.js` already are. |
| `templates/index.html` (modify) | The third button, `#searchOverlay`, the results multi-select mode, the queue wiring. |
| `tests/fixtures/mb_artist_jorge_ben.json` (create) | Trimmed real artist-search response. |
| `tests/fixtures/mb_discography_jorge_ben.json` (create) | Trimmed real release-group response. |
| `tests/test_search_query.py` (create) | `parse_search_query` against a stubbed client. |
| `tests/test_search_musicbrainz.py` (create) | `lookup_artist`, `lookup_discography`, query-string shape. |
| `tests/test_search_covers.py` (create) | The thread pool: order, cap, never-raises. |
| `tests/test_search_endpoint.py` (create) | `/api/search`: the three error rows, per-row duplicates, spend banking. |
| `tests/test_search_genres.py` (create) | `/api/search/genres`: pairing, `None`, one `scan_id`, the cap. |
| `tests/test_queue.js` + `tests/test_queue.py` (create) | The pure queue model. |
| `tests/test_boot.js` (modify) | DOM wiring for the button, the popup, the results mode and the queue. |
| `docs/search-by-name-manual-verification.md` (create) | What only a real API can show. |

---

## Task 1: Parse the loose query

**Files:**
- Modify: `scan.py` (add near `classify_genre`, `scan.py:630`)
- Test: `tests/test_search_query.py`

**Interfaces:**
- Consumes: `scan._anthropic_client`, `scan._record_usage` (both exist).
- Produces: `SEARCH_MODEL = "claude-haiku-4-5"`; `parse_search_query(query: str, usage_out: list | None = None) -> dict` returning `{"artist": str, "album": str | None}`. Raises `ValueError` on an empty query and `RuntimeError` when `ANTHROPIC_API_KEY` is unset.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_search_query.py
import json
from unittest.mock import patch, Mock

import pytest

import scan


def _claude_response(payload: dict):
    block = Mock()
    block.type = "text"
    block.text = json.dumps(payload)
    message = Mock()
    message.content = [block]
    return message


def test_an_artist_only_query_returns_no_album():
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"artist": "Jorge Ben", "album": None})

    with patch.object(scan, "_anthropic_client", return_value=client):
        assert scan.parse_search_query("jorge ben") == {
            "artist": "Jorge Ben", "album": None}


def test_a_query_naming_both_returns_both():
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"artist": "Milton Nascimento", "album": "Clube da Esquina"})

    with patch.object(scan, "_anthropic_client", return_value=client):
        assert scan.parse_search_query("clube da esquina") == {
            "artist": "Milton Nascimento", "album": "Clube da Esquina"}


def test_uses_haiku_and_sends_no_effort():
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"artist": "Rita Lee", "album": None})

    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.parse_search_query("rita lee")

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5"
    # output_config.effort 400s on Haiku 4.5 — see the comment at scan.py:645.
    assert "effort" not in kwargs["output_config"]


def test_records_usage_for_the_ledger():
    client = Mock()
    response = _claude_response({"artist": "Criolo", "album": None})
    response.usage = Mock(input_tokens=180, output_tokens=40)
    client.messages.create.return_value = response

    spent = []
    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.parse_search_query("criolo", usage_out=spent)

    assert spent == [{"model": "claude-haiku-4-5",
                      "input_tokens": 180, "output_tokens": 40}]


def test_an_empty_query_is_rejected_without_calling_the_api():
    client = Mock()
    with patch.object(scan, "_anthropic_client", return_value=client):
        with pytest.raises(ValueError):
            scan.parse_search_query("   ")
    client.messages.create.assert_not_called()


def test_an_artistless_answer_is_rejected():
    """Nothing downstream can act on a parse with no artist in it."""
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"artist": None, "album": None})

    with patch.object(scan, "_anthropic_client", return_value=client):
        with pytest.raises(ValueError):
            scan.parse_search_query("asdfghjkl")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_search_query.py -v`
Expected: FAIL — `AttributeError: module 'scan' has no attribute 'parse_search_query'`

- [ ] **Step 3: Implement**

Add to `scan.py`, immediately after `classify_genre`:

```python
SEARCH_MODEL = "claude-haiku-4-5"

_SEARCH_SYSTEM = (
    "You turn a record collector's loose search into a lookup key.\n"
    "Rules:\n"
    "1. Correct obvious misspellings to the artist's usual spelling.\n"
    "2. If the query names only an album, name the artist who recorded it.\n"
    "3. If the query names only an artist, return null for the album.\n"
    "4. Never invent a year, a country, or a list of releases. Those are "
    "looked up from a music database afterwards."
)

_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "artist": {"type": ["string", "null"]},
        "album": {"type": ["string", "null"]},
    },
    "required": ["artist", "album"],
    "additionalProperties": False,
}


def parse_search_query(query: str, usage_out: list | None = None) -> dict:
    """A loose query to {"artist": str, "album": str | None}.

    Unlike classify_genre this DOES raise: an unparsed query has no useful
    degraded form — there is nothing to search MusicBrainz for.
    """
    query = (query or "").strip()
    if not query:
        raise ValueError("Type an artist or album name")

    client = _anthropic_client()
    response = client.messages.create(
        model=SEARCH_MODEL,
        max_tokens=256,
        system=_SEARCH_SYSTEM,
        output_config={
            "format": {"type": "json_schema", "schema": _SEARCH_SCHEMA},
        },
        messages=[{"role": "user", "content": query}],
    )
    _record_usage(usage_out, SEARCH_MODEL, response)
    try:
        text = next(b.text for b in response.content if b.type == "text")
        parsed = json.loads(text)
    except (StopIteration, ValueError) as e:
        raise RuntimeError(f"Could not parse the search response: {e}") from e

    artist = (parsed.get("artist") or "").strip()
    if not artist:
        raise ValueError(f"Couldn't tell what artist {query!r} means")
    album = (parsed.get("album") or "").strip() or None
    return {"artist": artist, "album": album}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_search_query.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add scan.py tests/test_search_query.py
git commit -m "feat: parse a loose search query into an artist and album"
```

---

## Task 2: Resolve the artist and list the discography

**Files:**
- Modify: `scan.py` (add after `lookup_musicbrainz`, `scan.py:402`)
- Create: `tests/fixtures/mb_artist_jorge_ben.json`, `tests/fixtures/mb_discography_jorge_ben.json`
- Test: `tests/test_search_musicbrainz.py`

**Interfaces:**
- Consumes: `scan._mb_get`, `scan._lucene_escape`, `scan._artist_country`, `scan.MusicBrainzUnavailable`, `scan.MB_MIN_SCORE`.
- Produces:
  - `MB_SEARCH_LIMIT = 40`
  - `lookup_artist(name: str) -> dict | None` → `{"mbid": str, "name": str, "country": str | None}`
  - `lookup_discography(mbid: str, album: str | None = None) -> list[dict]` → rows shaped exactly like `lookup_musicbrainz`'s: `{"mbid", "year", "country", "artist", "album_name", "type"}`, plus `"credited"` and `"canonical"` carrying the two artist spellings for Task 4's duplicate check. Chronological, undated last.

- [ ] **Step 1: Create the fixtures**

`tests/fixtures/mb_artist_jorge_ben.json` — trimmed from the live response; scores and MBIDs are real:

```json
{
  "created": "2026-09-07T18:00:00.000Z",
  "count": 3,
  "offset": 0,
  "artists": [
    {"id": "19499124-36d4-4ccc-b28d-04dde3d2076f", "type": "Person",
     "score": 100, "name": "Jorge Ben Jor", "sort-name": "Ben Jor, Jorge",
     "country": "BR"},
    {"id": "e28c0b26-3bdb-45dc-b4f5-f309c7c35ec4", "type": "Person",
     "score": 91, "name": "Ben Webster", "sort-name": "Webster, Ben",
     "country": "US"},
    {"id": "837555ba-012e-45f1-9a9c-9628da13ee54", "type": "Person",
     "score": 86, "name": "Ben E. King", "sort-name": "King, Ben E.",
     "country": "US"}
  ]
}
```

`tests/fixtures/mb_discography_jorge_ben.json` — four release groups, deliberately **out of chronological order** so the sort is actually exercised, and one with no `first-release-date`:

```json
{
  "created": "2026-09-07T18:00:00.000Z",
  "count": 4,
  "offset": 0,
  "release-groups": [
    {"id": "9c1f0f1e-0a1b-4c2d-8e3f-1a2b3c4d5e6f", "score": 100,
     "title": "África Brasil", "first-release-date": "1976",
     "primary-type": "Album",
     "artist-credit": [{"name": "Jorge Ben",
       "artist": {"id": "19499124-36d4-4ccc-b28d-04dde3d2076f",
                  "name": "Jorge Ben Jor", "sort-name": "Ben Jor, Jorge"}}]},
    {"id": "01ecd040-de09-3fec-85cd-13c240b12dba", "score": 100,
     "title": "Ben é samba bom", "first-release-date": "1964",
     "primary-type": "Album",
     "artist-credit": [{"name": "Jorge Ben",
       "artist": {"id": "19499124-36d4-4ccc-b28d-04dde3d2076f",
                  "name": "Jorge Ben Jor", "sort-name": "Ben Jor, Jorge"}}]},
    {"id": "2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819", "score": 100,
     "title": "Força bruta", "first-release-date": "1970",
     "primary-type": "Album",
     "artist-credit": [{"name": "Jorge Ben",
       "artist": {"id": "19499124-36d4-4ccc-b28d-04dde3d2076f",
                  "name": "Jorge Ben Jor", "sort-name": "Ben Jor, Jorge"}}]},
    {"id": "3c4d5e6f-7081-492a-b3c4-d5e6f708192a", "score": 100,
     "title": "Grandes nomes", "primary-type": "Album",
     "artist-credit": [{"name": "Jorge Ben Jor",
       "artist": {"id": "19499124-36d4-4ccc-b28d-04dde3d2076f",
                  "name": "Jorge Ben Jor", "sort-name": "Ben Jor, Jorge"}}]}
  ]
}
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_search_musicbrainz.py
from unittest.mock import patch, Mock

import pytest

import scan
from conftest import load_fixture


@pytest.fixture(autouse=True)
def no_real_sleeping(monkeypatch):
    """Neutralise the 1 req/sec throttle so the suite doesn't crawl."""
    monkeypatch.setattr(scan.time, "sleep", lambda _s: None)
    monkeypatch.setattr(scan, "_mb_last_call", 0.0)


def _response(payload, status=200):
    mock = Mock()
    mock.status_code = status
    mock.json.return_value = payload
    mock.raise_for_status = Mock()
    return mock


# ── lookup_artist ───────────────────────────────────────────────────────────

def test_resolves_the_top_scoring_artist():
    with patch.object(scan.requests, "get",
                      return_value=_response(load_fixture("mb_artist_jorge_ben"))):
        found = scan.lookup_artist("jorge ben")

    assert found == {"mbid": "19499124-36d4-4ccc-b28d-04dde3d2076f",
                     "name": "Jorge Ben Jor", "country": "BR"}


def test_no_artists_returns_none():
    with patch.object(scan.requests, "get",
                      return_value=_response({"count": 0, "artists": []})):
        assert scan.lookup_artist("zzzzzzzz") is None


def test_a_weak_top_score_returns_none():
    """Below MB_MIN_SCORE the top hit is noise, and offering it makes the
    search look like it guessed — the same reason the scan applies this."""
    weak = {"count": 1, "artists": [
        {"id": "aaaa", "name": "Something Else", "score": 12, "country": "US"}]}
    with patch.object(scan.requests, "get", return_value=_response(weak)):
        assert scan.lookup_artist("jorge ben") is None


def test_an_unreachable_musicbrainz_propagates():
    with patch.object(scan, "_mb_get",
                      side_effect=scan.MusicBrainzUnavailable("down")):
        with pytest.raises(scan.MusicBrainzUnavailable):
            scan.lookup_artist("jorge ben")


# ── lookup_discography ──────────────────────────────────────────────────────

def test_lists_the_discography_chronologically():
    responses = [
        _response(load_fixture("mb_discography_jorge_ben")),
        _response(load_fixture("mb_artist_jorge_ben")),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        rows = scan.lookup_discography("19499124-36d4-4ccc-b28d-04dde3d2076f")

    assert [r["album_name"] for r in rows] == [
        "Ben é samba bom", "Força bruta", "África Brasil", "Grandes nomes"]
    assert [r["year"] for r in rows] == ["1964", "1970", "1976", None]


def test_rows_use_the_credited_artist_name_not_the_canonical_one():
    """MusicBrainz canonicalises to "Jorge Ben Jor"; the collection says
    "Jorge Ben". Filling the form with the canonical name would split the
    artist in the shelf's crates, and duplicate detection would never match."""
    responses = [
        _response(load_fixture("mb_discography_jorge_ben")),
        _response(load_fixture("mb_artist_jorge_ben")),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        rows = scan.lookup_discography("19499124-36d4-4ccc-b28d-04dde3d2076f")

    assert rows[0]["artist"] == "Jorge Ben"
    assert rows[0]["credited"] == "Jorge Ben"
    assert rows[0]["canonical"] == "Jorge Ben Jor"
    # The row with no separate credit falls back to the canonical spelling.
    assert rows[3]["artist"] == "Jorge Ben Jor"


def test_the_query_asks_for_albums_by_mbid_and_excludes_comps():
    responses = [
        _response(load_fixture("mb_discography_jorge_ben")),
        _response(load_fixture("mb_artist_jorge_ben")),
    ]
    with patch.object(scan.requests, "get", side_effect=responses) as get:
        scan.lookup_discography("19499124-36d4-4ccc-b28d-04dde3d2076f")

    query = get.call_args_list[0].kwargs["params"]["query"]
    # arid:, not artist:(name) — the fuzzy artist match returns 3655 rows
    # scoring 100 apiece and is worthless on its own.
    assert "arid:19499124-36d4-4ccc-b28d-04dde3d2076f" in query
    assert "primarytype:Album" in query
    assert "-secondarytype:Compilation" in query
    assert "-secondarytype:Live" in query
    assert get.call_args_list[0].kwargs["params"]["limit"] == scan.MB_SEARCH_LIMIT


def test_an_album_narrows_the_query():
    responses = [
        _response(load_fixture("mb_discography_jorge_ben")),
        _response(load_fixture("mb_artist_jorge_ben")),
    ]
    with patch.object(scan.requests, "get", side_effect=responses) as get:
        scan.lookup_discography("19499124-36d4-4ccc-b28d-04dde3d2076f",
                                album="Africa Brasil")

    query = get.call_args_list[0].kwargs["params"]["query"]
    assert "releasegroup:(Africa Brasil)" in query


def test_the_artist_country_is_fetched_once_for_the_whole_discography():
    responses = [
        _response(load_fixture("mb_discography_jorge_ben")),
        _response(load_fixture("mb_artist_jorge_ben")),
    ]
    with patch.object(scan.requests, "get", side_effect=responses) as get:
        rows = scan.lookup_discography("19499124-36d4-4ccc-b28d-04dde3d2076f")

    assert {r["country"] for r in rows} == {"BR"}
    assert get.call_count == 2   # the search, then one artist lookup — not one per row
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_search_musicbrainz.py -v`
Expected: FAIL — `AttributeError: module 'scan' has no attribute 'lookup_artist'`

- [ ] **Step 4: Implement**

Add to `scan.py`, after `lookup_musicbrainz`:

```python
# A full discography for a prolific artist is about thirty release groups;
# forty leaves headroom without turning the results grid into a scroll marathon.
MB_SEARCH_LIMIT = 40


def lookup_artist(name: str) -> dict | None:
    """Top artist match as {"mbid", "name", "country"}, or None.

    Raises MusicBrainzUnavailable, like every other _mb_get caller.
    """
    if not name:
        return None
    payload = _mb_get("/artist/", {"query": f"artist:({_lucene_escape(name)})",
                                   "limit": 3})
    artists = (payload or {}).get("artists") or []
    if not artists:
        return None
    best = artists[0]
    if (best.get("score") or 0) < MB_MIN_SCORE:
        return None
    return {"mbid": best.get("id"), "name": best.get("name") or name,
            "country": best.get("country")}


def lookup_discography(mbid: str, album: str | None = None) -> list[dict]:
    """Release groups for one artist, chronological, undated last.

    Rows match lookup_musicbrainz's shape so the client renders them with the
    same card, plus `credited`/`canonical` for duplicate matching.

    The search is by arid rather than by artist name: `artist:(Jorge Ben)`
    returns thousands of groups all scoring 100, because the parenthesised
    fuzzy match only discriminates when it is paired with a release title.
    """
    if not mbid:
        return []

    query = (f"arid:{mbid} AND primarytype:Album"
             " AND -secondarytype:Compilation AND -secondarytype:Live")
    if album:
        query += f" AND releasegroup:({_lucene_escape(album)})"

    payload = _mb_get("/release-group/", {"query": query,
                                          "limit": MB_SEARCH_LIMIT})
    groups = (payload or {}).get("release-groups") or []

    rows = []
    country_cache: dict = {}
    for group in groups:
        credit = (group.get("artist-credit") or [{}])[0]
        artist = credit.get("artist") or {}
        canonical = artist.get("name") or ""
        # The name printed on THIS release. MusicBrainz canonicalises the
        # artist ("Jorge Ben Jor") but the sleeve — and the collection — say
        # "Jorge Ben". Using the canonical name here would split the artist
        # across two crates on the shelf and defeat find_duplicate.
        credited = credit.get("name") or canonical
        released = group.get("first-release-date") or ""
        rows.append({
            "mbid": group.get("id"),
            "year": released[:4] if len(released) >= 4 else None,
            "country": _artist_country(artist.get("id"), country_cache)
                       if artist.get("id") else None,
            "label": None,
            "artist": credited,
            "credited": credited,
            "canonical": canonical,
            "album_name": group.get("title") or "",
            "type": group.get("primary-type"),
        })

    # Chronological, with undated groups last rather than first: "" sorts
    # before every real year, and a compilation MusicBrainz never dated is not
    # what the collector is looking for at the top of the grid.
    rows.sort(key=lambda r: (r["year"] is None, r["year"] or ""))
    return rows
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_search_musicbrainz.py -v`
Expected: 9 passed

- [ ] **Step 6: Commit**

```bash
git add scan.py tests/test_search_musicbrainz.py \
        tests/fixtures/mb_artist_jorge_ben.json \
        tests/fixtures/mb_discography_jorge_ben.json
git commit -m "feat: resolve an artist to its MusicBrainz discography"
```

---

## Task 3: Fetch cover art in parallel

**Files:**
- Modify: `scan.py` (add after `fetch_cover`, `scan.py:480`; add `import concurrent.futures` at the top)
- Test: `tests/test_search_covers.py`

**Interfaces:**
- Consumes: `scan.fetch_cover`.
- Produces: `COVER_WORKERS = 8`, `COVER_FETCH_LIMIT = 24`, `search_covers(rows: list[dict]) -> None` — mutates each row in place, setting `cover_data` to a data URI or `None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_search_covers.py
from unittest.mock import patch

import scan


def _rows(n):
    return [{"mbid": f"m{i}", "artist": "Jorge Ben", "album_name": f"A{i}"}
            for i in range(n)]


def test_every_row_gets_its_own_cover_in_input_order():
    """A pool completes out of order; the grid must not."""
    rows = _rows(5)
    with patch.object(scan, "fetch_cover",
                      side_effect=lambda c, *_a: "art:" + c["album_name"]):
        scan.search_covers(rows)

    assert [r["cover_data"] for r in rows] == [
        "art:A0", "art:A1", "art:A2", "art:A3", "art:A4"]


def test_rows_past_the_cap_are_left_without_artwork():
    rows = _rows(scan.COVER_FETCH_LIMIT + 3)
    with patch.object(scan, "fetch_cover", return_value="art") as fetch:
        scan.search_covers(rows)

    assert fetch.call_count == scan.COVER_FETCH_LIMIT
    assert rows[scan.COVER_FETCH_LIMIT]["cover_data"] is None
    assert rows[-1]["cover_data"] is None


def test_one_row_blowing_up_does_not_lose_the_others():
    """fetch_cover is documented never to raise, but the pool must not trust
    that absolutely — a single bad row cannot cost the whole grid."""
    rows = _rows(3)

    def boom(candidate, *_args):
        if candidate["album_name"] == "A1":
            raise RuntimeError("cover art archive said no")
        return "art:" + candidate["album_name"]

    with patch.object(scan, "fetch_cover", side_effect=boom):
        scan.search_covers(rows)

    assert [r["cover_data"] for r in rows] == ["art:A0", None, "art:A2"]


def test_an_empty_list_is_fine():
    scan.search_covers([])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_search_covers.py -v`
Expected: FAIL — `AttributeError: module 'scan' has no attribute 'search_covers'`

- [ ] **Step 3: Implement**

Add `import concurrent.futures` to the imports at the top of `scan.py`, then add after `fetch_cover`:

```python
# Cover art is the only part of a search that fans out. The pool touches no
# MusicBrainz endpoint — Cover Art Archive is a different host and
# _download_image does not throttle — so it never contends with _mb_lock.
COVER_WORKERS = 8

# fetch_cover's iTunes fallback is one HTTP call per miss, and forty of those
# inside a few seconds is what gets an IP throttled. A row nobody scrolls to
# also does not need its bytes paid for.
COVER_FETCH_LIMIT = 24


def search_covers(rows: list[dict]) -> None:
    """Fill `cover_data` on each row, in parallel, in place.

    Never raises: a search that found the releases is still worth showing
    when the artwork does not arrive.
    """
    for row in rows:
        row["cover_data"] = None
    wanted = rows[:COVER_FETCH_LIMIT]
    if not wanted:
        return

    def one(row):
        try:
            return fetch_cover(row)
        except Exception:
            logger.warning("Cover fetch failed for %r", row.get("album_name"),
                           exc_info=True)
            return None

    with concurrent.futures.ThreadPoolExecutor(
            max_workers=COVER_WORKERS) as pool:
        # Map preserves input order regardless of completion order.
        for row, cover in zip(wanted, pool.map(one, wanted)):
            row["cover_data"] = cover
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_search_covers.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add scan.py tests/test_search_covers.py
git commit -m "feat: fetch search cover art in a pool, capped and ordered"
```

---

## Task 4: The `/api/search` endpoint

**Files:**
- Modify: `app.py` (add after `scan_record`'s spend helpers; touch `SEED_ESTIMATE_USD` at `app.py:614` and the `estimate` block at `app.py:688`)
- Test: `tests/test_search_endpoint.py`

**Interfaces:**
- Consumes: `scan.parse_search_query`, `scan.lookup_artist`, `scan.lookup_discography`, `scan.search_covers`, `scan.find_duplicate`, `app._record_scan_spend`, `app._scan_estimate`.
- Produces: `POST /api/search` taking `{"query": str}` and returning `{"query", "artist", "album", "results": [...]}`; ledger source `"search"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_search_endpoint.py
from unittest.mock import patch

import pytest

import app as app_module
import scan


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        with c.session_transaction() as session:
            session["authed"] = True
        yield c


@pytest.fixture(autouse=True)
def _clean_records():
    with app_module.app.app_context():
        app_module.Record.query.delete()
        app_module.db.session.commit()
    yield


def _seed(artist, album):
    with app_module.app.app_context():
        app_module.db.session.add(
            app_module.Record(artist=artist, album_name=album, genre="MPB & Samba"))
        app_module.db.session.commit()


DISCOGRAPHY = [
    {"mbid": "m1", "year": "1970", "country": "BR", "artist": "Jorge Ben",
     "credited": "Jorge Ben", "canonical": "Jorge Ben Jor",
     "album_name": "Força bruta", "type": "Album", "label": None},
    {"mbid": "m2", "year": "1976", "country": "BR", "artist": "Jorge Ben",
     "credited": "Jorge Ben", "canonical": "Jorge Ben Jor",
     "album_name": "África Brasil", "type": "Album", "label": None},
]


def test_returns_the_discography(client):
    with patch.object(scan, "parse_search_query",
                      return_value={"artist": "Jorge Ben", "album": None}), \
         patch.object(scan, "lookup_artist",
                      return_value={"mbid": "19499124", "name": "Jorge Ben Jor",
                                    "country": "BR"}), \
         patch.object(scan, "lookup_discography",
                      return_value=[dict(r) for r in DISCOGRAPHY]), \
         patch.object(scan, "search_covers"):
        res = client.post("/api/search", json={"query": "jorge ben"})

    assert res.status_code == 200
    body = res.get_json()
    assert body["artist"] == "Jorge Ben Jor"
    assert [r["album_name"] for r in body["results"]] == [
        "Força bruta", "África Brasil"]


def test_a_record_you_already_own_is_flagged_per_row(client):
    """The collection files this artist as "Jorge Ben"; MusicBrainz
    canonicalises to "Jorge Ben Jor". Matching only the canonical spelling
    would badge nothing."""
    _seed("Jorge Ben", "África Brasil")

    with patch.object(scan, "parse_search_query",
                      return_value={"artist": "Jorge Ben", "album": None}), \
         patch.object(scan, "lookup_artist",
                      return_value={"mbid": "19499124", "name": "Jorge Ben Jor",
                                    "country": "BR"}), \
         patch.object(scan, "lookup_discography",
                      return_value=[dict(r) for r in DISCOGRAPHY]), \
         patch.object(scan, "search_covers"):
        body = client.post("/api/search", json={"query": "jorge ben"}).get_json()

    assert body["results"][0]["duplicate_of"] is None
    assert body["results"][1]["duplicate_of"]["album_name"] == "África Brasil"


def test_a_collection_filed_under_the_canonical_name_is_also_matched(client):
    _seed("Jorge Ben Jor", "Força bruta")

    with patch.object(scan, "parse_search_query",
                      return_value={"artist": "Jorge Ben", "album": None}), \
         patch.object(scan, "lookup_artist",
                      return_value={"mbid": "19499124", "name": "Jorge Ben Jor",
                                    "country": "BR"}), \
         patch.object(scan, "lookup_discography",
                      return_value=[dict(r) for r in DISCOGRAPHY]), \
         patch.object(scan, "search_covers"):
        body = client.post("/api/search", json={"query": "jorge ben"}).get_json()

    assert body["results"][0]["duplicate_of"]["album_name"] == "Força bruta"


def test_no_such_artist_is_an_empty_list_not_an_error(client):
    with patch.object(scan, "parse_search_query",
                      return_value={"artist": "Zzz", "album": None}), \
         patch.object(scan, "lookup_artist", return_value=None):
        res = client.post("/api/search", json={"query": "zzzzz"})

    assert res.status_code == 200
    assert res.get_json()["results"] == []


def test_an_unreachable_musicbrainz_is_502_not_an_empty_result(client):
    """"Nothing matched" and "the database was down" call for different words
    and different next steps — that is why MusicBrainzUnavailable exists."""
    with patch.object(scan, "parse_search_query",
                      return_value={"artist": "Jorge Ben", "album": None}), \
         patch.object(scan, "lookup_artist",
                      side_effect=scan.MusicBrainzUnavailable("busy")):
        res = client.post("/api/search", json={"query": "jorge ben"})

    assert res.status_code == 502
    assert "musicbrainz" in res.get_json()["error"].lower()


def test_a_missing_api_key_is_503(client):
    with patch.object(scan, "parse_search_query",
                      side_effect=RuntimeError("ANTHROPIC_API_KEY is not set")):
        res = client.post("/api/search", json={"query": "jorge ben"})

    assert res.status_code == 503


def test_an_unparseable_query_is_400(client):
    with patch.object(scan, "parse_search_query",
                      side_effect=ValueError("Type an artist or album name")):
        res = client.post("/api/search", json={"query": "   "})

    assert res.status_code == 400


def test_spend_is_banked_even_when_musicbrainz_dies_afterwards(client):
    """The Claude call was billed the moment it returned."""
    def spend(query, usage_out=None):
        usage_out.append({"model": "claude-haiku-4-5",
                          "input_tokens": 100, "output_tokens": 20})
        return {"artist": "Jorge Ben", "album": None}

    with patch.object(scan, "parse_search_query", side_effect=spend), \
         patch.object(scan, "lookup_artist",
                      side_effect=scan.MusicBrainzUnavailable("busy")):
        client.post("/api/search", json={"query": "jorge ben"})

    with app_module.app.app_context():
        rows = app_module.ScanSpend.query.filter_by(source="search").all()
    assert len(rows) == 1


def test_the_usage_endpoint_quotes_a_search_estimate(client):
    body = client.get("/api/scan/usage").get_json()
    assert "search" in body["estimate"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_search_endpoint.py -v`
Expected: FAIL — 404 on `/api/search`

- [ ] **Step 3: Implement**

In `app.py`, extend the seed estimates (`app.py:614`):

```python
SEED_ESTIMATE_USD = {"photo": 0.006, "spotify": 0.0004, "search": 0.0005}
```

Extend the `estimate` block in `scan_usage` (`app.py:688`):

```python
        "estimate": {"photo": _scan_estimate("photo"),
                     "spotify": _scan_estimate("spotify"),
                     "search": _scan_estimate("search")},
```

Add the route after `scan_usage`:

```python
# ── search by name ────────────────────────────────────────────────────────────

@app.route("/api/search", methods=["POST"])
@require_auth
def search_records():
    """Releases matching a loose artist/album query.

    Unlike /api/scan this returns a LIST of releases rather than one record's
    fields, which is why it is its own route.
    """
    d = request.get_json(silent=True) or {}
    query = (d.get("query") or "").strip()

    rows = db.session.query(
        Record.id, Record.artist, Record.album_name, Record.genre
    ).all()

    spent = []
    try:
        parsed = scan.parse_search_query(query, usage_out=spent)
        artist = scan.lookup_artist(parsed["artist"])
        if artist is None:
            results = []
        else:
            results = scan.lookup_discography(artist["mbid"], parsed["album"])
            scan.search_covers(results)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except scan.MusicBrainzUnavailable:
        app.logger.warning("MusicBrainz unavailable for search %r", query)
        return jsonify({"error": "Couldn't reach MusicBrainz — try again in "
                                 "a moment"}), 502
    except RuntimeError as e:
        message = str(e)
        return jsonify({"error": message}), 503 if "not set" in message else 502
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    finally:
        _record_scan_spend("search", spent)

    existing = [{"id": r.id, "artist": r.artist or "",
                 "album_name": r.album_name or ""} for r in rows]
    for row in results:
        row["duplicate_of"] = _search_duplicate(row, existing)

    return jsonify({
        "query": query,
        "artist": artist["name"] if artist else None,
        "album": parsed["album"],
        "results": results,
    })


def _search_duplicate(row, existing):
    """The collection row this release is already in, under either spelling.

    MusicBrainz canonicalises the artist ("Jorge Ben Jor") while the sleeve and
    the collection use the credited name ("Jorge Ben"). find_duplicate needs an
    exact normalised match, so both are tried or nothing is ever flagged.
    """
    for name in (row.get("credited"), row.get("canonical")):
        if not name:
            continue
        found = scan.find_duplicate(name, row.get("album_name", ""), existing)
        if found:
            return {"id": found["id"], "artist": found["artist"],
                    "album_name": found["album_name"]}
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_search_endpoint.py -v`
Expected: 9 passed

- [ ] **Step 5: Run the whole server suite for regressions**

Run: `python -m pytest tests/ -v --ignore=tests/test_boot.py -x`
Expected: all pass. (`test_boot.py` is excluded here because it hangs on some machines after passing; Task 7 onward runs its JS directly.)

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_search_endpoint.py
git commit -m "feat: add POST /api/search with per-row duplicate flags"
```

---

## Task 5: The `/api/search/genres` endpoint

**Files:**
- Modify: `app.py` (add after `search_records`)
- Test: `tests/test_search_genres.py`

**Interfaces:**
- Consumes: `scan.classify_genre`, `app._record_scan_spend`, `scan.MB_SEARCH_LIMIT`.
- Produces: `POST /api/search/genres` taking `{"releases": [{"artist", "album_name"}, ...]}` and returning `{"genres": [str | None, ...]}` positionally aligned with the input.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_search_genres.py
from unittest.mock import patch

import pytest

import app as app_module
import scan


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        with c.session_transaction() as session:
            session["authed"] = True
        yield c


def test_genres_line_up_with_the_releases_sent(client):
    with patch.object(scan, "classify_genre",
                      side_effect=["MPB & Samba", "Soul & Funk"]):
        body = client.post("/api/search/genres", json={"releases": [
            {"artist": "Jorge Ben", "album_name": "Força bruta"},
            {"artist": "Tim Maia", "album_name": "Racional"},
        ]}).get_json()

    assert body["genres"] == ["MPB & Samba", "Soul & Funk"]


def test_an_unclassifiable_record_comes_back_as_null(client):
    with patch.object(scan, "classify_genre", side_effect=["Rock", None]):
        body = client.post("/api/search/genres", json={"releases": [
            {"artist": "Pink Floyd", "album_name": "Animals"},
            {"artist": "Unknown", "album_name": "Unknown"},
        ]}).get_json()

    assert body["genres"] == ["Rock", None]


def test_the_whole_batch_is_one_scan_id(client):
    """A queue's genre work is one act, so _scan_estimate prices it as one."""
    def spend(artist, album, genres, usage_out=None):
        usage_out.append({"model": "claude-haiku-4-5",
                          "input_tokens": 50, "output_tokens": 10})
        return "Rock"

    with patch.object(scan, "classify_genre", side_effect=spend):
        client.post("/api/search/genres", json={"releases": [
            {"artist": "A", "album_name": "1"},
            {"artist": "B", "album_name": "2"},
            {"artist": "C", "album_name": "3"},
        ]})

    with app_module.app.app_context():
        rows = app_module.ScanSpend.query.filter_by(source="search").all()
    assert len(rows) == 3                       # one ledger row per call
    assert len({r.scan_id for r in rows}) == 1  # all under one scan


def test_an_oversized_list_is_refused(client):
    """One request must not become an unbounded fan-out of billed calls."""
    releases = [{"artist": "A", "album_name": str(i)}
                for i in range(scan.MB_SEARCH_LIMIT + 1)]
    with patch.object(scan, "classify_genre") as classify:
        res = client.post("/api/search/genres", json={"releases": releases})

    assert res.status_code == 400
    classify.assert_not_called()


def test_an_empty_list_costs_nothing(client):
    with patch.object(scan, "classify_genre") as classify:
        body = client.post("/api/search/genres", json={"releases": []}).get_json()

    assert body["genres"] == []
    classify.assert_not_called()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_search_genres.py -v`
Expected: FAIL — 404 on `/api/search/genres`

- [ ] **Step 3: Implement**

Add to `app.py` after `search_records`:

```python
@app.route("/api/search/genres", methods=["POST"])
@require_auth
def search_genres():
    """Classify the releases picked from a search, in one round trip.

    One request rather than one per record, so the genre work for a whole
    queue lands under a single scan_id and is priced as the single act it is.
    """
    d = request.get_json(silent=True) or {}
    releases = d.get("releases") or []
    if not isinstance(releases, list):
        return jsonify({"error": "releases must be a list"}), 400
    if len(releases) > scan.MB_SEARCH_LIMIT:
        return jsonify({"error": f"At most {scan.MB_SEARCH_LIMIT} at a time"}), 400
    if not releases:
        return jsonify({"genres": []})

    vocabulary = sorted({g for (g,) in db.session.query(Record.genre).distinct()
                         if g})

    spent = []
    try:
        genres = [
            scan.classify_genre((r or {}).get("artist") or "",
                                (r or {}).get("album_name") or "",
                                vocabulary, usage_out=spent)
            for r in releases
        ]
    finally:
        _record_scan_spend("search", spent)

    return jsonify({"genres": genres})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_search_genres.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_search_genres.py
git commit -m "feat: classify a queue's genres in one request"
```

---

## Task 6: The pure queue model

**Files:**
- Create: `static/queue.js`, `tests/test_queue.js`, `tests/test_queue.py`
- Modify: `templates/index.html` (add the `<script src>` beside the other static modules)

**Interfaces:**
- Consumes: nothing.
- Produces: global `VinylQueue` with `create(releases)`, `current(q)`, `position(q)`, `total(q)`, `remaining(q)`, `isLast(q)`, `advance(q)`, `skip(q)`, `counter(q)`, `saveLabel(q)`, `chips(q)`. Every function is pure — `advance` and `skip` return a **new** queue and never mutate the one passed in.

- [ ] **Step 1: Write the failing tests**

```javascript
// tests/test_queue.js
// Tests for the pure add-queue model behind "record 2 of 3".
// Run by tests/test_queue.py so `pytest` stays the single command.

const test = require('node:test');
const assert = require('node:assert');

const VinylQueue = require('../static/queue.js');

const THREE = [
  { album_name: 'Força bruta', year: '1970' },
  { album_name: 'Negro é lindo', year: '1971' },
  { album_name: 'Ben', year: '1972' },
];

test('a fresh queue starts on the first record', () => {
  const q = VinylQueue.create(THREE);
  assert.strictEqual(VinylQueue.position(q), 1);
  assert.strictEqual(VinylQueue.total(q), 3);
  assert.strictEqual(VinylQueue.current(q).album_name, 'Força bruta');
});

test('the counter reads the way the header shows it', () => {
  let q = VinylQueue.create(THREE);
  assert.strictEqual(VinylQueue.counter(q), '1 of 3');
  q = VinylQueue.advance(q);
  assert.strictEqual(VinylQueue.counter(q), '2 of 3');
});

test('advancing does not mutate the queue it was given', () => {
  const q = VinylQueue.create(THREE);
  VinylQueue.advance(q);
  assert.strictEqual(VinylQueue.position(q), 1);
});

test('the last record says save rather than save and next', () => {
  let q = VinylQueue.create(THREE);
  assert.strictEqual(VinylQueue.saveLabel(q), 'save & next');
  q = VinylQueue.advance(VinylQueue.advance(q));
  assert.ok(VinylQueue.isLast(q));
  assert.strictEqual(VinylQueue.saveLabel(q), 'save');
});

test('advancing past the last record empties the queue', () => {
  let q = VinylQueue.create(THREE);
  for (let i = 0; i < 3; i++) q = VinylQueue.advance(q);
  assert.strictEqual(VinylQueue.current(q), null);
  assert.strictEqual(VinylQueue.remaining(q), 0);
});

test('skipping drops the record without counting it as done', () => {
  let q = VinylQueue.create(THREE);
  q = VinylQueue.skip(q);
  assert.strictEqual(VinylQueue.current(q).album_name, 'Negro é lindo');
  assert.strictEqual(VinylQueue.total(q), 2);
  assert.strictEqual(VinylQueue.counter(q), '1 of 2');
});

test('chips report which record is done, current and still waiting', () => {
  const q = VinylQueue.advance(VinylQueue.create(THREE));
  assert.deepStrictEqual(VinylQueue.chips(q).map(c => c.status),
    ['done', 'current', 'pending']);
  assert.strictEqual(VinylQueue.chips(q)[1].release.album_name, 'Negro é lindo');
});

test('a single record is immediately the last one', () => {
  const q = VinylQueue.create([THREE[0]]);
  assert.ok(VinylQueue.isLast(q));
  assert.strictEqual(VinylQueue.counter(q), '1 of 1');
  assert.strictEqual(VinylQueue.saveLabel(q), 'save');
});

test('an empty queue is finished and has nothing current', () => {
  const q = VinylQueue.create([]);
  assert.strictEqual(VinylQueue.current(q), null);
  assert.strictEqual(VinylQueue.remaining(q), 0);
  assert.ok(!VinylQueue.isLast(q));
});
```

```python
# tests/test_queue.py
"""Run the JavaScript add-queue tests under pytest.

Same arrangement as tests/test_spend.py: the model is pure, so it lives in
static/queue.js where a JS runtime can reach it, and pytest shells out.
"""

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_queue_js():
    result = subprocess.run(
        ["node", "--test", "tests/test_queue.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test tests/test_queue.js`
Expected: FAIL — `Cannot find module '../static/queue.js'`

- [ ] **Step 3: Implement**

```javascript
// static/queue.js
/* The add-queue: the records picked from a search, walked one at a time
 * through the add form.
 *
 * Pure and immutable so the DOM wiring in index.html has nothing to get wrong
 * about counting — advance() and skip() return a new queue, and every label
 * the form shows is derived here rather than assembled at the call site.
 * See tests/test_queue.js. */
const VinylQueue = (function () {

  function create(releases) {
    return { releases: (releases || []).slice(), index: 0 };
  }

  function total(q) { return q.releases.length; }

  function current(q) {
    return q.index < q.releases.length ? q.releases[q.index] : null;
  }

  /* 1-based, for "2 of 3". Clamped so a finished queue does not read "4 of 3"
   * in the moment between the last save and the form closing. */
  function position(q) {
    return Math.min(q.index + 1, q.releases.length) || 0;
  }

  function remaining(q) { return Math.max(0, q.releases.length - q.index); }

  function isLast(q) {
    return q.releases.length > 0 && q.index === q.releases.length - 1;
  }

  function advance(q) {
    return { releases: q.releases.slice(), index: q.index + 1 };
  }

  /* Dropping a record is not the same as finishing it: it leaves the queue
   * shorter rather than moving further through it, so "1 of 3" becomes
   * "1 of 2" instead of "2 of 3". */
  function skip(q) {
    const releases = q.releases.slice();
    releases.splice(q.index, 1);
    return { releases: releases, index: q.index };
  }

  function counter(q) { return position(q) + ' of ' + total(q); }

  function saveLabel(q) { return isLast(q) ? 'save' : 'save & next'; }

  function chips(q) {
    return q.releases.map(function (release, i) {
      return {
        release: release,
        status: i < q.index ? 'done' : (i === q.index ? 'current' : 'pending'),
      };
    });
  }

  return { create, current, position, total, remaining, isLast,
           advance, skip, counter, saveLabel, chips };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylQueue;
```

Add the script tag in `templates/index.html` beside the other static modules (search for `<script src="/static/spend.js">`):

```html
<script src="/static/queue.js"></script>
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test tests/test_queue.js`
Expected: 9 passing

Then: `python -m pytest tests/test_queue.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add static/queue.js tests/test_queue.js tests/test_queue.py templates/index.html
git commit -m "feat: add the pure add-queue model"
```

---

## Task 7: The entry button and the query popup

**Files:**
- Modify: `templates/index.html` — CSS beside `.scan-actions` (`templates/index.html:2074` area), markup in the `.scan-actions` row, a new `#searchOverlay` modelled on `#spotifyOverlay` (`templates/index.html:2288`), and the JS
- Test: `tests/test_boot.js`

**Interfaces:**
- Consumes: `VinylSpend.scanHintText`, the `scanUsage` variable, `refreshScanUsage`.
- Produces: `openSearchOverlay()`, `closeSearchOverlay()`, `submitSearch()`, `runSearch(query)`, `searchInFlight`, `searchResults` (the array of rows from `/api/search`).

- [ ] **Step 1: Write the failing boot tests**

Add to `tests/test_boot.js`:

```javascript
test('the form offers a third way in, and it needs nothing handed over', async () => {
  const { win } = await boot();
  win.openAdd();

  const btn = win.document.getElementById('searchNameBtn');
  assert.ok(btn, 'the search button is in the form');
  // Analyse is dead until a cover or a link is handed in; search never is,
  // because needing nothing is the whole point of it.
  assert.ok(win.document.getElementById('analyseBtn').disabled);
  assert.ok(!btn.disabled);
  assert.ok(btn.closest('.scan-actions'), 'it sits in the scan-actions row');
});

test('the search popup opens with the price on it and closes again', async () => {
  const { win } = await boot();
  win.openAdd();
  win.openSearchOverlay();

  const overlay = win.document.getElementById('searchOverlay');
  assert.ok(!overlay.classList.contains('hidden'));
  assert.match(win.document.getElementById('searchHint').textContent,
               /nothing is sent/);

  win.closeSearchOverlay();
  assert.ok(overlay.classList.contains('hidden'));
});

test('a search fills the results screen from what the server sent', async () => {
  const { win } = await boot();
  win.openAdd();
  win.fetch = async () => ({
    ok: true,
    json: async () => ({
      query: 'jorge ben', artist: 'Jorge Ben Jor', album: null,
      results: [
        { mbid: 'm1', artist: 'Jorge Ben', album_name: 'Força bruta',
          year: '1970', country: 'BR', type: 'Album',
          cover_data: null, duplicate_of: null },
        { mbid: 'm2', artist: 'Jorge Ben', album_name: 'África Brasil',
          year: '1976', country: 'BR', type: 'Album',
          cover_data: null,
          duplicate_of: { id: 7, artist: 'Jorge Ben',
                          album_name: 'África Brasil' } },
      ],
    }),
  });

  await win.runSearch('jorge ben');

  assert.ok(!win.document.getElementById('scanOverlay').classList.contains('hidden'));
  assert.strictEqual(win.document.querySelectorAll('#scanBody .scan-card').length, 2);
  // The one already in the collection wears the same red bar the scan uses.
  assert.strictEqual(win.document.querySelectorAll('#scanBody .scan-badge-dup').length, 1);
});
```

- [ ] **Step 2: Run the boot tests to verify they fail**

Run: `python -m pytest tests/test_boot.py -v`
Expected: FAIL — `searchNameBtn` is null.

If `test_boot.py` hangs on this machine after reporting results, run the JS directly instead — export the two env vars the shim sets (`VINYL_PAGE_HTML`, `VINYL_RECORDS_JSON`, `VINYL_JSDOM_PATH`) and run `node --test tests/test_boot.js`.

- [ ] **Step 3: Implement the markup and CSS**

In the `.scan-actions` row (`templates/index.html:2074`), after the Spotify button:

```html
            <button type="button" class="scan-find" id="searchNameBtn" onclick="openSearchOverlay()">
              <i class="ti ti-list-search"></i> Search
            </button>
```

No new CSS rule is needed — `.scan-find` deliberately inherits the neutral
`.scan-actions button` styling. Analyse keeps the accent and Spotify the green;
a third coloured button would make the row a stripe.

Add the overlay next to `#spotifyOverlay`:

```html
<!-- Search by name — the way in when there is no sleeve to photograph and no
     link to paste. Same chrome as the Spotify popup because it does the same
     job: one field, hand it in, the results screen takes over. -->
<div class="overlay hidden" id="searchOverlay">
  <div class="modal" style="max-width:460px">
    <div class="modal-head">
      <span class="modal-title">search by name</span>
      <button class="btn btn-ghost btn-sm" onclick="closeSearchOverlay()"><i class="ti ti-x"></i></button>
    </div>
    <div class="modal-body">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px">
        <i class="ti ti-list-search" style="font-size:22px;color:var(--accent)"></i>
        <span style="font-size:13px;color:var(--label)">artist, album, or both</span>
      </div>
      <input type="text" id="searchQueryInput" placeholder="jorge ben"
             style="width:100%" onkeydown="if(event.key==='Enter'){event.preventDefault();submitSearch()}">
      <span id="searchErr" style="font-size:12px;color:var(--danger);display:none;margin-top:6px"></span>
      <div class="scan-hint" id="searchHint"></div>
    </div>
    <div class="modal-foot">
      <button class="btn" onclick="closeSearchOverlay()">cancel</button>
      <button class="btn btn-primary" id="searchSubmitBtn" onclick="submitSearch()">
        <i class="ti ti-arrow-right"></i> search
      </button>
    </div>
  </div>
</div>
```

- [ ] **Step 4: Implement the JS**

Add near `runScan`:

```javascript
// ── search by name ──────────────────────────────────────────────────────────

let searchInFlight = false;
let searchResults = [];
let searchQuery = '';

function openSearchOverlay(){
  document.getElementById('searchErr').style.display = 'none';
  document.getElementById('searchHint').textContent =
    VinylSpend.scanHintText({armed: true, source: 'search', usage: scanUsage});
  document.getElementById('searchOverlay').classList.remove('hidden');
  document.getElementById('searchQueryInput').focus();
}

function closeSearchOverlay(){
  document.getElementById('searchOverlay').classList.add('hidden');
}

function submitSearch(){
  const query = document.getElementById('searchQueryInput').value.trim();
  if(!query){ showSearchError('type an artist or album name'); return; }
  runSearch(query);
}

function showSearchError(message){
  const el = document.getElementById('searchErr');
  el.textContent = message || '';
  el.style.display = message ? '' : 'none';
}

function setSearchBusy(busy){
  searchInFlight = busy;
  document.getElementById('searchSubmitBtn').disabled = busy;
  document.getElementById('searchQueryInput').disabled = busy;
}

async function runSearch(query){
  // Same guard, same reason, as runScan's: every call costs real credits and
  // Enter-then-click is two of them.
  if(searchInFlight) return;
  setSearchBusy(true);
  showSearchError('');
  try{
    let res, data;
    try{
      res = await fetch('/api/search', {method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({query})});
      data = await res.json();
    }catch(e){
      showSearchError('search failed — try again');
      return;
    }
    if(!res.ok){
      showSearchError((data && data.error) || 'search failed');
      return;
    }
    searchQuery = query;
    searchResults = data.results || [];
    closeSearchOverlay();
    openSearchResults(data);
  } finally {
    setSearchBusy(false);
    refreshScanUsage();
  }
}
```

- [ ] **Step 5: Run the boot tests to verify they pass**

Run: `python -m pytest tests/test_boot.py -v`
Expected: the three new tests pass along with the existing ones.

(`openSearchResults` and the multi-select grid arrive in Task 8; until then the
third test fails on that call. Implement Task 8 before re-running it, or stub
`openSearchResults` to open `#scanOverlay` and call `renderSearchResults`.)

- [ ] **Step 6: Commit**

```bash
git add templates/index.html tests/test_boot.js
git commit -m "feat: add the search-by-name button and query popup"
```

---

## Task 8: The results screen, with checkboxes

**Files:**
- Modify: `templates/index.html` — `.scan-grid.wide` CSS beside `.scan-grid` (`templates/index.html:773`), refactor `renderScanCandidates` (`templates/index.html:5177`), add the search-mode renderer and footer
- Test: `tests/test_boot.js`

**Interfaces:**
- Consumes: `searchResults`, `esc`, `countryLabelFromCode`, `sameAlbumTitle`.
- Produces: `openSearchResults(data)`, `renderSearchResults()`, `toggleSearchPick(i)`, `searchPicked` (a `Set` of indices), `addPickedRecords()`, and `scanCardHtml(candidate, opts)` — the card renderer now shared with `renderScanCandidates`.

- [ ] **Step 1: Write the failing boot tests**

Add to `tests/test_boot.js`:

```javascript
async function searched(win) {
  win.openAdd();
  win.fetch = async () => ({
    ok: true,
    json: async () => ({
      query: 'jorge ben', artist: 'Jorge Ben Jor', album: null,
      results: [
        { mbid: 'm1', artist: 'Jorge Ben', album_name: 'Força bruta',
          year: '1970', country: 'BR', type: 'Album', cover_data: null,
          duplicate_of: null },
        { mbid: 'm2', artist: 'Jorge Ben', album_name: 'Negro é lindo',
          year: '1971', country: 'BR', type: 'Album', cover_data: null,
          duplicate_of: null },
        { mbid: 'm3', artist: 'Jorge Ben', album_name: 'África Brasil',
          year: '1976', country: 'BR', type: 'Album', cover_data: null,
          duplicate_of: { id: 7, artist: 'Jorge Ben', album_name: 'África Brasil' } },
      ],
    }),
  });
  await win.runSearch('jorge ben');
  return win;
}

test('nothing is selected until you tick something', async () => {
  const { win } = await boot();
  await searched(win);

  assert.strictEqual(win.searchPicked.size, 0);
  assert.ok(win.document.getElementById('searchAddBtn').disabled);
});

test('ticking cards moves the count and the button label', async () => {
  const { win } = await boot();
  await searched(win);

  win.toggleSearchPick(0);
  assert.match(win.document.getElementById('searchAddBtn').textContent,
               /add 1 record\b/);

  win.toggleSearchPick(1);
  assert.strictEqual(win.searchPicked.size, 2);
  assert.match(win.document.getElementById('searchAddBtn').textContent,
               /add 2 records/);

  win.toggleSearchPick(0);   // untick
  assert.strictEqual(win.searchPicked.size, 1);
});

test('a record already in the collection is badged, not hidden', async () => {
  const { win } = await boot();
  await searched(win);

  assert.strictEqual(win.document.querySelectorAll('#scanBody .scan-card').length, 3);
  assert.strictEqual(win.document.querySelectorAll('#scanBody .scan-badge-dup').length, 1);
});

test('the search grid is wider than the scan grid', async () => {
  const { win } = await boot();
  await searched(win);
  // Three columns suit a scan's four alternates; a discography is twelve to
  // thirty and wants four.
  assert.ok(win.document.querySelector('#scanBody .scan-grid.wide'));
});

test('a search that matched no artist explains itself', async () => {
  const { win } = await boot();
  win.openAdd();
  win.fetch = async () => ({
    ok: true,
    json: async () => ({ query: 'zzz', artist: null, album: null, results: [] }),
  });
  await win.runSearch('zzz');

  assert.match(win.document.getElementById('scanBody').textContent, /no artist/i);
});
```

- [ ] **Step 2: Run the boot tests to verify they fail**

Run: `python -m pytest tests/test_boot.py -v`
Expected: FAIL — `win.searchPicked` is undefined.

- [ ] **Step 3: Add the wide-grid CSS**

Beside `.scan-grid` (`templates/index.html:773`):

```css
/* A scan returns four or five alternates and three columns suit them. A
   discography is twelve to thirty, where 242px is still a legible sleeve. */
.scan-grid.wide{grid-template-columns:repeat(4,1fr)}
@media(max-width:760px){.scan-grid.wide{grid-template-columns:repeat(2,1fr)}}
```

- [ ] **Step 4: Extract the shared card renderer**

Replace the card-building block inside `renderScanCandidates` (`templates/index.html:5177`) so both callers share it:

```javascript
/* One release as a card. Shared by the scan's alternates and the search's
 * results: the two screens differ in how a card is chosen, not in what a
 * release looks like. `opts.selectable` adds the checkbox, `opts.selected`
 * marks it, and `opts.onclick` is the handler name to bind. */
function scanCardHtml(c, opts){
  opts = opts || {};
  const art = c.cover_data
    ? `<img src="${esc(c.cover_data)}" alt="${esc(c.album_name||'')}">`
    : `<i class="ti ti-disc"></i><span class="no-art">no artwork found</span>`;
  const dup = opts.duplicate
    ? '<span class="scan-badge-dup"><i class="ti ti-alert-triangle"></i> already in your collection</span>'
    : '';
  const best = opts.best ? '<span class="scan-badge-best">best match</span>' : '';
  const box = opts.selectable
    ? `<span class="scan-pick${opts.selected ? ' on' : ''}"><i class="ti ti-check"></i></span>`
    : '';
  const meta = [c.year || '?', c.country ? countryLabelFromCode(c.country) : null,
                (c.type && c.type !== 'Album') ? c.type.toLowerCase() : null]
    .filter(Boolean).join(' · ');
  return `<button type="button" class="scan-card${opts.selected ? ' picked' : ''}"
     onclick="${opts.onclick}">
     <div class="scan-card-cover">${art}${best}${box}${dup}</div>
     <div class="scan-card-body">
       <div class="scan-card-album">${esc(c.album_name||'')}</div>
       <div class="scan-card-meta">${esc(c.artist||'')}</div>
       <div class="scan-card-meta">${esc(meta)}</div>
     </div>
   </button>`;
}
```

And rewrite `renderScanCandidates`'s card loop to call it:

```javascript
  const cards = scanCandidates.map((c,i) => scanCardHtml(c, {
    best: i === 0,
    duplicate: scanDuplicateOf && sameAlbumTitle(c.album_name, scanDuplicateOf.album_name),
    onclick: `pickCandidate(${i})`,
  })).join('');
```

Add the checkbox and selected-card CSS beside `.scan-badge-best`:

```css
/* The tick sits on the artwork, so it needs its own ground to stay legible
   over a light sleeve. */
.scan-pick{position:absolute;top:9px;left:9px;width:26px;height:26px;border-radius:6px;
  display:flex;align-items:center;justify-content:center;font-size:15px;
  background:rgba(0,0,0,.55);border:1px solid rgba(232,232,224,.45);color:transparent}
.scan-pick.on{background:var(--accent);border-color:var(--accent);color:#0c0c0c}
.scan-card.picked{border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 12%,transparent)}
```

- [ ] **Step 5: Implement the search results mode**

```javascript
let searchPicked = new Set();

function openSearchResults(data){
  searchPicked = new Set();
  document.getElementById('scanReadoutLabel').textContent = 'you searched for';
  document.getElementById('scanReadoutTitle').textContent = data.query || '';
  const thumb = document.getElementById('scanReadoutThumb');
  document.getElementById('scanReadoutImg').removeAttribute('src');
  thumb.style.display = 'none';
  const genre = document.getElementById('scanReadoutGenre');
  genre.textContent = data.artist || '';
  genre.style.display = data.artist ? '' : 'none';
  document.getElementById('scanGoogleLink').style.display = 'none';

  renderSearchResults();
  document.getElementById('scanOverlay').classList.remove('hidden');
}

function renderSearchResults(){
  const body = document.getElementById('scanBody');
  if(!searchResults.length){
    body.innerHTML =
      `<div class="scan-empty">
         <i class="ti ti-user-question"></i>
         <div class="scan-empty-title">no artist matched</div>
         <div class="scan-empty-text">MusicBrainz has nobody by that name. Check the
           spelling, or type the album title instead — the search can work back to
           the artist from it.</div>
       </div>`;
    renderSearchFoot();
    return;
  }
  const owned = searchResults.filter(r => r.duplicate_of).length;
  const cards = searchResults.map((c,i) => scanCardHtml(c, {
    selectable: true,
    selected: searchPicked.has(i),
    duplicate: !!c.duplicate_of,
    onclick: `toggleSearchPick(${i})`,
  })).join('');
  const count = `${searchResults.length} release${searchResults.length===1?'':'s'}`
    + (owned ? ` · ${owned} already yours` : '')
    + ' · tick the ones you have';
  body.innerHTML = `<div class="scan-count">${esc(count)}</div>
     <div class="scan-grid wide">${cards}</div>`;
  renderSearchFoot();
}

function toggleSearchPick(i){
  if(searchPicked.has(i)) searchPicked.delete(i); else searchPicked.add(i);
  renderSearchResults();
}

function renderSearchFoot(){
  const n = searchPicked.size;
  const btn = document.getElementById('searchAddBtn');
  btn.disabled = n === 0;
  btn.textContent = n === 1 ? 'add 1 record' : `add ${n} records`;
  document.getElementById('searchSelected').textContent =
    n ? `${n} selected` : 'nothing selected yet';
}
```

Add the footer controls to `#scanOverlay`'s `.scan-foot`, hidden in scan mode:

```html
      <span class="spacer"></span>
      <span id="searchSelected" style="font-size:12px;color:var(--label)"></span>
      <button class="btn btn-primary" id="searchAddBtn" onclick="addPickedRecords()" disabled>add records</button>
```

The two modes share the footer, so each one owns what it shows. Add to
`openScanOverlay`, before `renderScanCandidates()`:

```javascript
  // Scan mode: the Google fallback, no picking.
  document.getElementById('searchSelected').style.display = 'none';
  document.getElementById('searchAddBtn').style.display = 'none';
```

and to `openSearchResults`, before `renderSearchResults()`:

```javascript
  // Search mode: pick several, no Google fallback — the releases came from
  // MusicBrainz, so "none of these fit" means the query was wrong, not the art.
  document.getElementById('searchSelected').style.display = '';
  document.getElementById('searchAddBtn').style.display = '';
```

`addPickedRecords` is bound by the footer button here but implemented in
Task 9. Between the two tasks the button is inert rather than broken — an
`onclick` naming an undefined function throws only when clicked, and no test
in this task clicks it.

- [ ] **Step 6: Run the boot tests to verify they pass**

Run: `python -m pytest tests/test_boot.py -v`
Expected: the five new tests pass, and the three from Task 7 now pass too.

- [ ] **Step 7: Commit**

```bash
git add templates/index.html tests/test_boot.js
git commit -m "feat: pick several releases from the search results"
```

---

## Task 9: Walk the queue through the add form

**Files:**
- Modify: `templates/index.html` — `addPickedRecords`, `advanceQueue`, the queue strip markup, and the four collision points: `openAdd` (`templates/index.html:4320`), `offerDraft`'s call site (`templates/index.html:4369`), `applyOwnershipMode`'s save label (`templates/index.html:3906`), `closeForm` (`templates/index.html:4500`), `submitForm` (`templates/index.html:4585`)
- Test: `tests/test_boot.js`

**Interfaces:**
- Consumes: `VinylQueue`, `searchResults`, `searchPicked`, `applyCandidate`, `openAdd`, `submitForm`, `closeForm`, `VinylDraft`, `draftStore`.
- Produces: `addQueue` (a `VinylQueue` or `null`), `addPickedRecords()`, `advanceQueue()`, `skipQueued()`, `renderQueueStrip()`.

**The four collisions.** Each is a real behaviour in the current code that breaks the queue if unhandled; each has its own test below.

1. `openAdd` ends with `offerDraft()` — advancing would offer the *previous* record's draft. Clear the draft before calling `openAdd`, not after.
2. `applyOwnershipMode` owns `formSaveBtn.textContent` and resets it to `save` / `add to wishlist` on every ownership toggle. It is reached from `setHaveIt` → `renderOwnSwitch` → `applyOwnershipMode`, so the queue's label has to be applied in the innermost one.
3. `closeForm` is the cancel path and must drop the whole queue; its confirm should say how many records go with it.
4. `openAdd` clears `scanCandidates`, which kills the reopen-results button. The queue keeps `searchResults` separately and rebinds it — reopening costs nothing, because the search was paid for once and covers every record in it.

- [ ] **Step 1: Write the failing boot tests**

```javascript
async function queued(win) {
  await searched(win);
  win.toggleSearchPick(0);
  win.toggleSearchPick(1);
  win.fetch = async () => ({ ok: true, json: async () => ({ genres: ['MPB & Samba', 'MPB & Samba'] }) });
  await win.addPickedRecords();
  return win;
}

test('picking two records opens the form on the first, counting', async () => {
  const { win } = await boot();
  await queued(win);

  assert.strictEqual(win.document.getElementById('formOverlay').classList.contains('hidden'), false);
  assert.strictEqual(win.document.getElementById('queueCounter').textContent, '1 of 2');
  assert.strictEqual(win.document.getElementById('fAlbum').value, 'Força bruta');
  assert.strictEqual(win.document.getElementById('fArtist').value, 'Jorge Ben');
  assert.strictEqual(win.document.getElementById('fYear').value, '1970');
});

test('the save button says save and next until the last record', async () => {
  const { win } = await boot();
  await queued(win);
  assert.strictEqual(win.document.getElementById('formSaveBtn').textContent, 'save & next');
});

test('the ownership switch does not clobber the queue save label', async () => {
  // setHaveIt -> renderOwnSwitch -> applyOwnershipMode resets formSaveBtn
  // .textContent on every toggle.
  const { win } = await boot();
  await queued(win);
  win.setHaveIt(false);
  assert.strictEqual(win.document.getElementById('formSaveBtn').textContent, 'save & next');
  win.setHaveIt(true);
  assert.strictEqual(win.document.getElementById('formSaveBtn').textContent, 'save & next');
});

test('saving advances to the next record without offering the last one back', async () => {
  const { win } = await boot();
  await queued(win);
  win.fetch = async () => ({ ok: true, json: async () => ({ id: 99, artist: 'Jorge Ben', album_name: 'Força bruta' }) });

  await win.submitForm();

  assert.strictEqual(win.document.getElementById('queueCounter').textContent, '2 of 2');
  assert.strictEqual(win.document.getElementById('fAlbum').value, 'Negro é lindo');
  // The draft banner must not be showing the record that was just saved.
  assert.ok(win.document.getElementById('draftFlag').hidden);
  assert.strictEqual(win.document.getElementById('formSaveBtn').textContent, 'save');
});

test('saving the last record closes the form and empties the queue', async () => {
  const { win } = await boot();
  await queued(win);
  win.fetch = async () => ({ ok: true, json: async () => ({ id: 99, artist: 'a', album_name: 'b' }) });

  await win.submitForm();
  await win.submitForm();

  assert.ok(win.document.getElementById('formOverlay').classList.contains('hidden'));
  assert.strictEqual(win.addQueue, null);
});

test('skipping drops one record and shortens the count', async () => {
  const { win } = await boot();
  await queued(win);

  win.skipQueued();

  assert.strictEqual(win.document.getElementById('queueCounter').textContent, '1 of 1');
  assert.strictEqual(win.document.getElementById('fAlbum').value, 'Negro é lindo');
});

test('cancelling the form drops the rest of the queue', async () => {
  const { win } = await boot();
  await queued(win);

  win.confirm = () => true;
  win.closeForm();

  assert.strictEqual(win.addQueue, null);
  assert.ok(win.document.getElementById('formOverlay').classList.contains('hidden'));
});

test('the reopen-results button survives advancing', async () => {
  // openAdd clears scanCandidates, which is what used to kill this button.
  const { win } = await boot();
  await queued(win);
  win.fetch = async () => ({ ok: true, json: async () => ({ id: 99, artist: 'a', album_name: 'b' }) });

  await win.submitForm();

  assert.ok(win.document.getElementById('scanRepickBtn').classList.contains('on'));
});

test('the queue strip marks what is done, current and waiting', async () => {
  const { win } = await boot();
  await queued(win);
  const chips = win.document.querySelectorAll('#queueStrip .qchip');
  assert.strictEqual(chips.length, 2);
  assert.ok(chips[0].classList.contains('current'));
  assert.ok(chips[1].classList.contains('pending'));
});
```

- [ ] **Step 2: Run the boot tests to verify they fail**

Run: `python -m pytest tests/test_boot.py -v`
Expected: FAIL — `win.addPickedRecords` is not a function.

- [ ] **Step 3: Add the queue strip markup**

Immediately after `#formOverlay`'s `.modal-head`:

```html
      <div class="queue-strip" id="queueStrip" hidden>
        <span class="queue-label">from your search</span>
        <div class="queue-chips" id="queueChips"></div>
        <span class="queue-counter" id="queueCounter"></span>
        <button type="button" class="btn btn-sm" onclick="skipQueued()">skip this one</button>
      </div>
```

```css
.queue-strip{display:flex;align-items:center;gap:12px;padding:12px 18px;background:var(--bg);
  border-bottom:1px solid var(--border);flex-wrap:wrap}
.queue-label{font-size:10.5px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;white-space:nowrap}
.queue-chips{display:flex;gap:8px;flex:1;min-width:0;flex-wrap:wrap}
.qchip{display:flex;align-items:center;gap:8px;padding:5px 10px;border-radius:7px;
  border:1px solid var(--border);background:var(--card);font-size:12px;color:var(--label);white-space:nowrap}
.qchip.done{opacity:.55}
.qchip.current{border-color:var(--accent);color:var(--accent);font-weight:600;
  background:color-mix(in srgb,var(--accent) 10%,transparent)}
.queue-counter{font-family:var(--font-mono);font-size:11px;color:var(--accent);
  border:1px solid color-mix(in srgb,var(--accent) 45%,transparent);border-radius:4px;padding:4px 9px}
```

- [ ] **Step 4: Implement the queue**

```javascript
// ── the add queue ───────────────────────────────────────────────────────────
// Lives outside everything openAdd resets, because it has to survive the
// openAdd that starts the next record.
let addQueue = null;

async function addPickedRecords(){
  const picked = [...searchPicked].sort((a,b) => a-b).map(i => searchResults[i]);
  if(!picked.length) return;

  // One request for the whole queue: the genre work is a single act and is
  // priced as one in the ledger.
  let genres = [];
  try{
    const res = await fetch('/api/search/genres', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({releases: picked.map(r => (
        {artist: r.artist, album_name: r.album_name}))})});
    if(res.ok) genres = (await res.json()).genres || [];
  }catch(e){ /* a record with no genre is a record you set the genre on */ }
  picked.forEach((r,i) => { r.genre = genres[i] || ''; });

  addQueue = VinylQueue.create(picked);
  closeScanOverlay();
  startQueuedRecord();
  refreshScanUsage();
}

/* Open the form on the queue's current record. Also the advance path, so the
 * draft is cleared BEFORE openAdd runs — openAdd ends in offerDraft(), which
 * would otherwise offer back the record that was just saved. */
function startQueuedRecord(){
  const release = VinylQueue.current(addQueue);
  if(!release){ addQueue = null; closeForm(true); return; }

  VinylDraft.clear(draftStore());
  openAdd();

  setScanField('fArtist', release.artist);
  setScanField('fAlbum', release.album_name);
  setScanField('fGenre', release.genre);
  applyCandidate(release);

  // openAdd cleared scanCandidates, which is what drives the reopen button.
  // Rebind it: reopening costs nothing, because the search was paid for once
  // and covers every record in the queue.
  scanCandidates = searchResults;
  updateScanControls();

  renderQueueStrip();
  formBaseline = formValues();
  formChanged();
}

function advanceQueue(){
  addQueue = VinylQueue.advance(addQueue);
  startQueuedRecord();
}

function skipQueued(){
  if(!addQueue) return;
  addQueue = VinylQueue.skip(addQueue);
  startQueuedRecord();
}

function renderQueueStrip(){
  const strip = document.getElementById('queueStrip');
  if(!addQueue || !VinylQueue.total(addQueue)){ strip.hidden = true; return; }
  strip.hidden = false;
  document.getElementById('queueCounter').textContent = VinylQueue.counter(addQueue);
  document.getElementById('queueChips').innerHTML =
    VinylQueue.chips(addQueue).map(c =>
      `<span class="qchip ${c.status}">${esc(c.release.album_name || '')}</span>`).join('');
  syncSaveLabel();
}

/* The queue's label, applied wherever applyOwnershipMode would otherwise win. */
function syncSaveLabel(){
  if(!addQueue) return false;
  document.getElementById('formSaveBtn').textContent = VinylQueue.saveLabel(addQueue);
  return true;
}
```

- [ ] **Step 5: Wire the four collisions**

In `applyOwnershipMode` (`templates/index.html:3894`, the label at `:3906`), let the queue win:

```javascript
  // The queue's "save & next" outranks this, or the first ownership toggle
  // would silently put the label back to "save" mid-queue. renderOwnSwitch
  // calls this on every toggle, which is why the guard lives here and not there.
  if(!syncSaveLabel()){
    document.getElementById('formSaveBtn').textContent =
      (!editingId && !owned) ? 'add to wishlist' : 'save';
  }
```

In `submitForm` (`templates/index.html:4585`), replace the success tail:

```javascript
  if(editingId){records=records.map(x=>x.id===editingId?rec:x);toast('changes saved');}
  else{records.push(rec);toast('record added');}
  render();
  // A queue with more in it re-opens the form instead of closing it.
  if(addQueue && !VinylQueue.isLast(addQueue)){ advanceQueue(); return; }
  addQueue = null;
  closeForm(true);
```

In `closeForm` (`templates/index.html:4500`), drop the queue and say what it costs:

```javascript
function closeForm(force){
  const queued = addQueue ? VinylQueue.remaining(addQueue) - 1 : 0;
  if (force !== true && formIsDirty()) {
    const scanned = coverDirty || scanWrote && Object.keys(scanWrote).length;
    let message = scanned
      ? 'Discard this record? The scan that filled it would have to be paid for again.'
      : 'Discard this record? What you typed will be lost.';
    if (queued > 0) {
      message += `\n\n${queued} more record${queued===1?'':'s'} from your search `
               + `${queued===1?'is':'are'} still waiting, and will be dropped too.`;
    }
    if (!confirm(message)) return;
  }
  addQueue = null;
  document.getElementById('queueStrip').hidden = true;
  VinylDraft.clear(draftStore());
  ...
```

- [ ] **Step 6: Run the boot tests to verify they pass**

Run: `python -m pytest tests/test_boot.py -v`
Expected: the nine new tests pass alongside every existing one.

- [ ] **Step 7: Run the whole suite**

Run: `python -m pytest tests/ -v`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add templates/index.html tests/test_boot.js
git commit -m "feat: walk the picked releases through the add form"
```

---

## Task 10: Manual verification notes

**Files:**
- Create: `docs/search-by-name-manual-verification.md`

Only a real API shows these; the suite mocks every one of them.

- [ ] **Step 1: Write the document**

```markdown
# Search by name — what to check by hand

The suite mocks Claude, MusicBrainz, Cover Art Archive and iTunes. These are
the things only the real ones can tell you. Needs `ANTHROPIC_API_KEY` and
`MUSICBRAINZ_CONTACT` set.

## The price is what the hint claimed

1. Note the month total under the Analyse button.
2. Search `jorge ben`. The hint said roughly 0.05¢.
3. Reopen the form. The month total should have moved by about that much —
   an order of magnitude under a photo scan, which is the point of using
   Haiku for a query parse.

## Thirty covers arrive in a tolerable time

Search an artist with a long discography (`jorge ben`, `rita lee`,
`pink floyd`). Expect the grid within about ten seconds: two throttled
MusicBrainz calls at a second each, then the cover pool. Rows past the
24th are expected to show "no artwork found" — that is the cap, not a bug.

## A search of an artist you own badges the right rows

Search `jorge ben` with *Ben é Samba Bom*, *A Tábua de Esmeralda* and
*África Brasil* in the collection. All three should wear the red bar.

If none do, the credited-versus-canonical artist name has regressed:
MusicBrainz canonicalises to "Jorge Ben Jor" and the collection says
"Jorge Ben". See `_search_duplicate` in `app.py`.

## An unreachable MusicBrainz says so

MusicBrainz sheds load with a 503 often enough to hit by trying a few
searches in a row. When it does, the message must be "couldn't reach
MusicBrainz", never "no artist matched" — they call for different next
steps from you.

## The form is filled with the credited name

After adding a Jorge Ben record from a search, the shelf must show it in the
same crate as the ones already there — not a second "Jorge Ben Jor" crate
beside it.

## A queue survives a wrong turn

Pick three. On record two, hit *skip this one*: the counter goes to "2 of 2"
and record three is on screen. Start again, and on record two hit *cancel*:
it should warn that one more record is waiting and will be dropped.
```

- [ ] **Step 2: Commit**

```bash
git add docs/search-by-name-manual-verification.md
git commit -m "docs: what to check by hand for search by name"
```

---

## Self-Review

**Spec coverage.** Every section maps to a task: *What produces the results* → Tasks 1–3; *Cover art* → Task 3; *POST /api/search* → Task 4; *POST /api/search/genres* → Task 5; *Errors* → Task 4 (three tests, one per row of the spec's table); *Spend ledger* → Task 4 steps 3 and Task 5; *Entry point* → Task 7; *The query popup* → Task 7; *The results screen* → Task 8; *The queue* → Tasks 6 and 9; *Testing* → every task; *Manual verification* → Task 10.

One spec statement is contradicted on purpose and called out at the top: per-row `duplicate_of` is **not** "no new code". `_search_duplicate` exists because MusicBrainz's canonical artist name never matches the collection's credited one.

**Type consistency.** `lookup_discography` rows carry `credited` and `canonical` (Task 2), consumed by `_search_duplicate` (Task 4) and never used client-side. `search_covers` mutates rows in place and returns `None` (Task 3), so Task 4 calls it as a statement. `VinylQueue` names are identical in `static/queue.js`, `tests/test_queue.js` and Task 9. `scanCardHtml(c, opts)` is defined once in Task 8 and called by both `renderScanCandidates` and `renderSearchResults`.

**Known ordering constraint.** Task 7's third boot test calls `openSearchResults`, which Task 8 implements. Run Tasks 7 and 8 back to back, or stub as the step notes.
