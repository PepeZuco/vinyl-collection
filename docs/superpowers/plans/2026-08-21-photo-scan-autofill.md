# Photo Scan Autofill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill the add-record form automatically from either a photo of a
record sleeve or a shared Spotify link.

**Architecture:** Two input paths resolve a record to artist + album — Claude
vision for photos, the Spotify Web API for links. Both then feed one shared
enrichment pipeline: MusicBrainz supplies the original release year and the
artist's country, a cover-art chain supplies the image, and a duplicate check
compares against existing records. All logic lives in a new `scan.py` of pure
data-in/data-out functions; `app.py` only wires one new route.

**Tech Stack:** Python 3 / Flask / SQLAlchemy (existing), `anthropic` SDK,
`requests`, `pytest`. Frontend is vanilla JS in a single template — no build
step, no framework.

**Spec:** `docs/superpowers/specs/2026-08-21-photo-scan-autofill-design.md`

## Global Constraints

- **Model for vision:** `claude-sonnet-5`. Model for genre classification:
  `claude-haiku-4-5`. Use these exact model ID strings — no date suffixes.
- **Effort:** `output_config: {"effort": "low"}` on both Claude calls. These
  are extraction tasks, not reasoning tasks.
- **Never derive `year` from Spotify's `release_date`.** Each Spotify album
  entry is a specific release, so a remaster reports the remaster date. Year
  comes from MusicBrainz on both input paths, always.
- **Never let the vision model infer year or country.** Its prompt forbids
  it; those come from MusicBrainz.
- **MusicBrainz requires** a `User-Agent` of the form
  `VinylCollection/1.0 ( <MUSICBRAINZ_CONTACT> )` and a maximum of 1
  request/second.
- **Genre enum is built at request time** from the database's distinct
  genres, never hardcoded.
- **`/api/scan` is `@require_auth`**, like every other write route.
- **Scanning is purely additive.** Every failure path must leave the existing
  manual form fully usable. No new code may block it.
- **Spotify logo:** `static/spotify-logo.png` rendered at exactly 24×24 px,
  native aspect ratio, no CSS filters, no `border-radius`, no background
  plate, ≥12px clear space on all sides.
- Existing code style: 4-space Python indent, no type annotations in
  `app.py`. New `scan.py` may use annotations (it is a fresh module).

---

## File Structure

| File | Responsibility |
|---|---|
| `scan.py` *(new)* | All extraction/lookup logic. Seven pure functions, no Flask objects, no DB session. |
| `tests/conftest.py` *(new)* | Shared pytest fixtures and the fixture-loading helper. |
| `tests/fixtures/*.json` *(new)* | Recorded MusicBrainz and Spotify responses. |
| `tests/test_scan_*.py` *(new)* | One test module per `scan.py` unit. |
| `app.py` *(modify)* | Adds `POST /api/scan` only — route wiring, no logic. |
| `templates/index.html` *(modify)* | Action sheet, camera modal, Spotify paste field, autofill wiring. |
| `requirements.txt` *(modify)* | `anthropic`, `requests`, `pytest`. |
| `README.md` *(modify)* | Documents the four new environment variables. |

**`scan.py` public interface** (locked — later tasks depend on these exact
names and types):

```python
def parse_spotify_url(url: str) -> tuple[str, str]
def find_duplicate(artist: str, album: str, existing: list[dict]) -> dict | None
def lookup_musicbrainz(artist: str, album: str) -> list[dict]
def fetch_cover(candidate: dict, spotify_image_url: str | None = None) -> str | None
def extract_from_image(image_data_uri: str, genres: list[str]) -> dict
def classify_genre(artist: str, album: str, genres: list[str]) -> str | None
def extract_from_spotify(url: str) -> dict
```

A **candidate** dict, produced by `lookup_musicbrainz` and consumed by
`fetch_cover` and the endpoint:

```python
{"mbid": str, "year": str | None, "country": str | None,
 "label": str | None, "artist": str, "album_name": str}
```

---

### Task 1: Test scaffolding and `parse_spotify_url()`

Starts the project: adds dependencies, creates the test tree, and delivers
the first pure function. `parse_spotify_url` has no I/O, so it needs no
mocking — the right place to prove the test setup works.

**Files:**
- Create: `scan.py`
- Create: `pytest.ini`
- Create: `tests/test_scan_spotify_url.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: nothing
- Produces: `parse_spotify_url(url: str) -> tuple[str, str]` returning
  `(kind, spotify_id)` where `kind` is `"album"` or `"track"`. Raises
  `ValueError` for anything else.

- [ ] **Step 0: Confirm the Python environment**

**Already done by the controller — verify, don't redo.** `.venv/` exists at
the repo root with every dependency installed. Confirm with:

```bash
.venv/bin/python -c "import flask, anthropic, requests, pytest; print('ok')"
```

Use `.venv/bin/python -m pytest` (or activate the venv) for every test
command in this plan.

For reproducibility, this is how that venv was created. Ubuntu 26.04 ships
Python 3.14 with no `pip`, no `ensurepip`, and no `venv` module, and PEP 668
blocks `--user` installs. This needs no `sudo`:

```bash
curl -sSo /tmp/pip.pyz https://bootstrap.pypa.io/pip/pip.pyz
python3 /tmp/pip.pyz install --target /tmp/bootstrap virtualenv
PYTHONPATH=/tmp/bootstrap python3 -m virtualenv .venv
.venv/bin/pip install -r requirements.txt
```

- [ ] **Step 1: Add dependencies and pytest configuration**

Append to `requirements.txt` (keep the existing three lines):

```
anthropic==1.0.0
requests==2.34.2
pytest==9.1.1
jsonschema==4.26.0
```

These are the versions actually installed and verified in `.venv`. `jsonschema`
is test-only: it validates that the structured-output schemas this feature
builds actually behave as intended (see Task 5), which plain unit tests with a
mocked client cannot check.

**On `anthropic` 1.x:** 1.0.0 is the current major version, and its
`messages.create` surface is unchanged from 0.x for everything this plan
uses. `output_config` was verified present in the installed SDK's signature.
The 1.x breaking changes (httpx2, awaited async `.with_raw_response`,
removed Text Completions) touch nothing here.

Create `pytest.ini` at the repo root:

```ini
[pytest]
pythonpath = .
testpaths = tests
```

`pythonpath = .` is **required**, not cosmetic — verified empirically on
this machine. Under pytest's default `prepend` import mode, a test file with
no `__init__.py` gets its own directory (`tests/`) inserted into `sys.path`,
not the repo root, so a bare `pytest` fails every `import scan` with
`ModuleNotFoundError`. (`python -m pytest` happens to mask this by adding
CWD to `sys.path` — don't rely on that.)

- [ ] **Step 2: Write the failing test**

Create `tests/test_scan_spotify_url.py`:

```python
import pytest
from scan import parse_spotify_url

ALBUM_ID = "4LH4d3cOWNNsVw41Gqt2kv"
TRACK_ID = "0eGsygTp906u18L0Oimnem"


@pytest.mark.parametrize("url", [
    f"https://open.spotify.com/album/{ALBUM_ID}",
    f"https://open.spotify.com/album/{ALBUM_ID}?si=abc123def456",
    f"https://open.spotify.com/intl-pt/album/{ALBUM_ID}",
    f"https://open.spotify.com/intl-de/album/{ALBUM_ID}?si=x",
    f"spotify:album:{ALBUM_ID}",
    f"  https://open.spotify.com/album/{ALBUM_ID}  ",
])
def test_album_urls_resolve(url):
    assert parse_spotify_url(url) == ("album", ALBUM_ID)


@pytest.mark.parametrize("url", [
    f"https://open.spotify.com/track/{TRACK_ID}",
    f"https://open.spotify.com/intl-pt/track/{TRACK_ID}?si=q",
    f"spotify:track:{TRACK_ID}",
])
def test_track_urls_resolve(url):
    assert parse_spotify_url(url) == ("track", TRACK_ID)


@pytest.mark.parametrize("url", [
    "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
    "https://open.spotify.com/artist/3fMbdgg4jU18AjLCKBhRSm",
    "https://example.com/album/123",
    "not a url at all",
    "",
])
def test_unsupported_urls_raise(url):
    with pytest.raises(ValueError):
        parse_spotify_url(url)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python -m pytest tests/test_scan_spotify_url.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scan'`

- [ ] **Step 4: Write the minimal implementation**

Create `scan.py`:

```python
"""Record identification: sleeve photos and Spotify links to record fields."""
import re

_SPOTIFY_URL_RE = re.compile(
    r"^https?://open\.spotify\.com/(?:intl-[a-z]{2}/)?(album|track)/([A-Za-z0-9]+)",
    re.IGNORECASE,
)
_SPOTIFY_URI_RE = re.compile(r"^spotify:(album|track):([A-Za-z0-9]+)$", re.IGNORECASE)


def parse_spotify_url(url: str) -> tuple[str, str]:
    """Resolve a Spotify album or track link to (kind, spotify_id).

    Accepts web URLs (with or without an ``intl-xx`` segment or ``?si=``
    query) and ``spotify:`` URIs. Raises ValueError for playlists, artists,
    and anything unrecognised.
    """
    candidate = (url or "").strip()
    for pattern in (_SPOTIFY_URL_RE, _SPOTIFY_URI_RE):
        match = pattern.match(candidate)
        if match:
            return match.group(1).lower(), match.group(2)
    raise ValueError(f"Not a Spotify album or track link: {url!r}")
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/test_scan_spotify_url.py -v`
Expected: PASS — 14 passed

- [ ] **Step 6: Commit**

```bash
git add requirements.txt pytest.ini scan.py tests/test_scan_spotify_url.py
git commit -m "Add scan module with Spotify URL parsing"
```

---

### Task 2: `find_duplicate()`

Detects that a scanned record is already in the collection. Pure function
over a list of record dicts — no DB session, so it is trivially testable.

Normalisation must strip accents: the collection is ~20% Brazilian, where
`Sérgio` and `Sergio` are the same artist.

**Files:**
- Modify: `scan.py`
- Create: `tests/test_scan_duplicates.py`

**Interfaces:**
- Consumes: nothing
- Produces: `find_duplicate(artist, album, existing) -> dict | None`, where
  `existing` is a list of dicts each having at least `id`, `artist`, and
  `album_name` (exactly what `Record.to_dict()` returns). Returns the
  matching dict, or `None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scan_duplicates.py`:

```python
from scan import find_duplicate

EXISTING = [
    {"id": 1, "artist": "Bill Withers", "album_name": "Live at Carnegie Hall"},
    {"id": 2, "artist": "Sérgio Mendes", "album_name": "Brasil '66"},
    {"id": 3, "artist": "The Beatles", "album_name": "Abbey Road"},
    {"id": 4, "artist": "Bill Withers", "album_name": "Bill Withers’ Greatest Hits"},
]


def test_exact_match():
    assert find_duplicate("Bill Withers", "Live at Carnegie Hall", EXISTING)["id"] == 1


def test_case_insensitive():
    assert find_duplicate("BILL WITHERS", "live at carnegie hall", EXISTING)["id"] == 1


def test_accents_ignored():
    assert find_duplicate("Sergio Mendes", "Brasil '66", EXISTING)["id"] == 2


def test_leading_article_ignored():
    assert find_duplicate("Beatles", "Abbey Road", EXISTING)["id"] == 3


def test_punctuation_ignored():
    assert find_duplicate(
        "Bill Withers", "Bill Withers Greatest Hits", EXISTING
    )["id"] == 4


def test_no_match_returns_none():
    assert find_duplicate("Adele", "30", EXISTING) is None


def test_album_must_also_match():
    assert find_duplicate("Bill Withers", "Menagerie", EXISTING) is None


def test_empty_inputs_return_none():
    assert find_duplicate("", "", EXISTING) is None
    assert find_duplicate("Adele", "30", []) is None


def test_junk_normalising_to_empty_key_returns_none():
    """Punctuation-only input reduces to an empty key; it must never match."""
    junk = [{"id": 99, "artist": "---", "album_name": "***"}]
    assert find_duplicate("???", "!!!", junk) is None
    assert find_duplicate("   ", "   ", junk) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_scan_duplicates.py -v`
Expected: FAIL — `ImportError: cannot import name 'find_duplicate'`

- [ ] **Step 3: Write the minimal implementation**

Add to `scan.py` (imports go at the top with the existing `import re`):

```python
import unicodedata

_LEADING_ARTICLES = ("the ", "an ", "a ", "os ", "as ", "o ", "um ", "uma ")


def _normalise(value: str) -> str:
    """Casefold, strip accents and punctuation, drop a leading article."""
    text = unicodedata.normalize("NFKD", (value or "").casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for article in _LEADING_ARTICLES:
        if text.startswith(article):
            return text[len(article):]
    return text


def find_duplicate(artist: str, album: str, existing: list[dict]) -> dict | None:
    """Return the first existing record matching artist + album, else None."""
    # Guard the NORMALISED key, not the raw strings: punctuation-only input
    # ("???") is truthy but reduces to "", and two empty keys compare equal.
    key = (_normalise(artist), _normalise(album))
    if not key[0] or not key[1]:
        return None
    for record in existing:
        if (_normalise(record.get("artist", "")),
                _normalise(record.get("album_name", ""))) == key:
            return record
    return None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_scan_duplicates.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: Commit**

```bash
git add scan.py tests/test_scan_duplicates.py
git commit -m "Add duplicate detection with accent and article normalisation"
```

---

### Task 3: `lookup_musicbrainz()`

Supplies the two fields that are not on a sleeve: original release year and
artist country. Two HTTP calls per lookup, throttled to MusicBrainz's
1 req/sec limit.

**Files:**
- Modify: `scan.py`
- Create: `tests/conftest.py`
- Create: `tests/fixtures/mb_release_group_withers.json`
- Create: `tests/fixtures/mb_artist_withers.json`
- Create: `tests/test_scan_musicbrainz.py`

**Interfaces:**
- Consumes: nothing
- Produces: `lookup_musicbrainz(artist, album) -> list[dict]` of up to 3
  candidate dicts (shape defined in File Structure above), highest-scoring
  first. Returns `[]` on no match, network error, or timeout.

- [ ] **Step 1: Create the recorded fixtures**

These are trimmed from real API responses. Create
`tests/fixtures/mb_release_group_withers.json`:

```json
{
  "release-groups": [
    {
      "id": "8f1318d9-8a6f-3c4c-a6de-bcdabc7123e4",
      "score": 100,
      "title": "Live at Carnegie Hall",
      "first-release-date": "1973",
      "artist-credit": [
        {"artist": {"id": "fd1a2d9d-9bb6-44de-83a3-41560658aba9",
                    "name": "Bill Withers"}}
      ]
    },
    {
      "id": "aaaaaaaa-0000-0000-0000-000000000001",
      "score": 72,
      "title": "Para Sempre",
      "artist-credit": [
        {"artist": {"id": "fd1a2d9d-9bb6-44de-83a3-41560658aba9",
                    "name": "Bill Withers"}}
      ]
    }
  ]
}
```

Note the second entry deliberately has **no** `first-release-date` — the
real-world case observed on Altamiro Carrilho.

Create `tests/fixtures/mb_artist_withers.json`:

```json
{
  "id": "fd1a2d9d-9bb6-44de-83a3-41560658aba9",
  "name": "Bill Withers",
  "country": "US",
  "area": {"name": "United States", "iso-3166-1-codes": ["US"]}
}
```

This fixture exercises only the `payload.get("country")` branch. Add a
second one, `tests/fixtures/mb_artist_country_fallback.json`, so the
`area.iso-3166-1-codes` fallback is covered too — country is one of the two
fields this task exists to supply, and a silent regression there corrupts
records:

```json
{
  "id": "bbbbbbbb-0000-0000-0000-000000000002",
  "name": "Fallback Artist",
  "country": null,
  "area": {"name": "United Kingdom", "iso-3166-1-codes": ["GB"]}
}
```

- [ ] **Step 2: Create the fixture loader**

Create `tests/conftest.py`:

```python
import json
import pathlib

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    """Load a recorded API response by filename stem."""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
```

- [ ] **Step 3: Write the failing test**

Create `tests/test_scan_musicbrainz.py`:

```python
from unittest.mock import patch, Mock

import pytest

import scan
from conftest import load_fixture


@pytest.fixture(autouse=True)
def no_real_sleeping(monkeypatch):
    """Neutralise the 1 req/sec throttle so the suite doesn't crawl.

    Without this, every lookup in this module blocks for a real second.
    """
    monkeypatch.setattr(scan.time, "sleep", lambda _s: None)
    monkeypatch.setattr(scan, "_mb_last_call", 0.0)


def _response(payload, status=200):
    mock = Mock()
    mock.status_code = status
    mock.json.return_value = payload
    mock.raise_for_status = Mock()
    return mock


def test_returns_year_and_country():
    responses = [
        _response(load_fixture("mb_release_group_withers")),
        _response(load_fixture("mb_artist_withers")),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("Bill Withers", "Live at Carnegie Hall")

    assert candidates[0]["year"] == "1973"
    assert candidates[0]["country"] == "US"
    assert candidates[0]["mbid"] == "8f1318d9-8a6f-3c4c-a6de-bcdabc7123e4"
    assert candidates[0]["album_name"] == "Live at Carnegie Hall"


def test_missing_release_date_yields_no_year():
    responses = [
        _response(load_fixture("mb_release_group_withers")),
        _response(load_fixture("mb_artist_withers")),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("Bill Withers", "Para Sempre")

    assert candidates[1]["year"] is None
    assert candidates[1]["country"] == "US"


def test_no_match_returns_empty_list():
    with patch.object(scan.requests, "get", return_value=_response({"release-groups": []})):
        assert scan.lookup_musicbrainz("Nobody", "Nothing") == []


def test_network_error_returns_empty_list():
    with patch.object(scan.requests, "get", side_effect=scan.requests.RequestException):
        assert scan.lookup_musicbrainz("Bill Withers", "Menagerie") == []


def test_country_falls_back_to_area_iso_code():
    """country is null -> the ISO code must come from area.iso-3166-1-codes."""
    responses = [
        _response(load_fixture("mb_release_group_withers")),
        _response(load_fixture("mb_artist_country_fallback")),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("Fallback Artist", "Live at Carnegie Hall")

    assert candidates[0]["country"] == "GB"


def test_country_is_none_when_both_sources_absent():
    responses = [
        _response(load_fixture("mb_release_group_withers")),
        _response({"id": "x", "name": "Nowhere Artist"}),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("Nowhere Artist", "Live at Carnegie Hall")

    assert candidates[0]["country"] is None


def test_sends_identifying_user_agent():
    with patch.object(scan.requests, "get", return_value=_response({"release-groups": []})) as get:
        scan.lookup_musicbrainz("Bill Withers", "Menagerie")

    headers = get.call_args.kwargs["headers"]
    assert "VinylCollection" in headers["User-Agent"]


def test_throttle_enforces_one_second_gap():
    sleeps = []
    with patch.object(scan.time, "sleep", side_effect=sleeps.append):
        with patch.object(scan.time, "monotonic", side_effect=[0.0, 0.0, 0.2, 0.2]):
            scan._throttle_musicbrainz()
            scan._throttle_musicbrainz()

    assert sleeps and sleeps[0] > 0
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `python -m pytest tests/test_scan_musicbrainz.py -v`
Expected: FAIL — `AttributeError: module 'scan' has no attribute 'requests'`

- [ ] **Step 5: Write the minimal implementation**

Add to `scan.py`:

```python
import os
import threading
import time

import requests

MB_BASE = "https://musicbrainz.org/ws/2"
MB_TIMEOUT = 2.0

_mb_lock = threading.Lock()
_mb_last_call = 0.0


def _musicbrainz_headers() -> dict:
    contact = os.environ.get("MUSICBRAINZ_CONTACT", "unknown@example.com")
    return {"User-Agent": f"VinylCollection/1.0 ( {contact} )"}


def _throttle_musicbrainz() -> None:
    """Block until at least 1s has passed since the previous MusicBrainz call."""
    global _mb_last_call
    with _mb_lock:
        wait = 1.0 - (time.monotonic() - _mb_last_call)
        if wait > 0:
            time.sleep(wait)
        _mb_last_call = time.monotonic()


def _mb_get(path: str, params: dict) -> dict | None:
    _throttle_musicbrainz()
    try:
        response = requests.get(
            f"{MB_BASE}{path}",
            params={**params, "fmt": "json"},
            headers=_musicbrainz_headers(),
            timeout=MB_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None


def _artist_country(artist_mbid: str, cache: dict) -> str | None:
    if artist_mbid in cache:
        return cache[artist_mbid]
    payload = _mb_get(f"/artist/{artist_mbid}", {}) or {}
    country = payload.get("country")
    if not country:
        codes = (payload.get("area") or {}).get("iso-3166-1-codes") or []
        country = codes[0] if codes else None
    cache[artist_mbid] = country
    return country


def lookup_musicbrainz(artist: str, album: str) -> list[dict]:
    """Return up to 3 release-group candidates with year and artist country."""
    if not artist:
        return []
    query = f'artist:"{artist}"'
    if album:
        query += f' AND releasegroup:"{album}"'

    payload = _mb_get("/release-group/", {"query": query, "limit": 5})
    if not payload:
        return []

    candidates = []
    country_cache: dict = {}
    for group in payload.get("release-groups", [])[:3]:
        credit = (group.get("artist-credit") or [{}])[0].get("artist") or {}
        released = group.get("first-release-date") or ""
        candidates.append({
            "mbid": group.get("id"),
            "year": released[:4] if len(released) >= 4 else None,
            "country": _artist_country(credit.get("id"), country_cache)
                       if credit.get("id") else None,
            "label": None,
            "artist": credit.get("name") or artist,
            "album_name": group.get("title") or album,
        })
    return candidates
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `python -m pytest tests/test_scan_musicbrainz.py -v`
Expected: PASS — 8 passed

- [ ] **Step 7: Verify against the live API**

Run this once to confirm the real service still matches the fixtures:

```bash
MUSICBRAINZ_CONTACT=you@example.com python -c "
import scan
print(scan.lookup_musicbrainz('Bill Withers', 'Live at Carnegie Hall')[0])
"
```

Expected: a dict with `'year': '1973'` and `'country': 'US'`.

- [ ] **Step 8: Commit**

```bash
git add scan.py tests/conftest.py tests/fixtures tests/test_scan_musicbrainz.py
git commit -m "Add MusicBrainz lookup for release year and artist country"
```

---

### Task 4: `fetch_cover()`

Walks the cover-art chain and returns a base64 data URI ready to store in
`Record.cover_data`, matching how covers are already persisted.

Order is Cover Art Archive → iTunes → Spotify. Spotify is deliberately last
despite being highest quality on the link path — see the spec's rationale
about permanent storage.

**Files:**
- Modify: `scan.py`
- Create: `tests/test_scan_cover.py`

**Interfaces:**
- Consumes: a candidate dict from `lookup_musicbrainz`
- Produces: `fetch_cover(candidate, spotify_image_url=None) -> str | None`
  returning a `data:image/...;base64,...` URI or `None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scan_cover.py`:

```python
from unittest.mock import patch, Mock

import scan

CANDIDATE = {
    "mbid": "8f1318d9-8a6f-3c4c-a6de-bcdabc7123e4",
    "artist": "Bill Withers",
    "album_name": "Live at Carnegie Hall",
    "year": "1973", "country": "US", "label": None,
}


def _image(status=200, content=b"\xff\xd8\xffbytes", ctype="image/jpeg"):
    mock = Mock()
    mock.status_code = status
    mock.content = content
    mock.headers = {"Content-Type": ctype}
    return mock


def test_prefers_cover_art_archive():
    with patch.object(scan.requests, "get", return_value=_image()) as get:
        result = scan.fetch_cover(CANDIDATE)

    assert result.startswith("data:image/jpeg;base64,")
    assert "coverartarchive.org" in get.call_args_list[0].args[0]


def test_falls_back_to_itunes_when_archive_404s():
    itunes_json = Mock(status_code=200)
    itunes_json.json.return_value = {
        "results": [{"artworkUrl100": "https://is1.example.com/a/100x100bb.jpg"}]
    }
    responses = [_image(status=404), itunes_json, _image()]
    with patch.object(scan.requests, "get", side_effect=responses) as get:
        result = scan.fetch_cover(CANDIDATE)

    assert result.startswith("data:image/jpeg;base64,")
    assert "600x600bb" in get.call_args_list[2].args[0]


def test_falls_back_to_spotify_image_last():
    responses = [_image(status=404), Mock(status_code=200, **{"json.return_value": {"results": []}}), _image()]
    with patch.object(scan.requests, "get", side_effect=responses) as get:
        result = scan.fetch_cover(CANDIDATE, spotify_image_url="https://i.scdn.co/image/x")

    assert result.startswith("data:image/jpeg;base64,")
    assert get.call_args_list[2].args[0] == "https://i.scdn.co/image/x"


def test_returns_none_when_everything_misses():
    responses = [_image(status=404), Mock(status_code=200, **{"json.return_value": {"results": []}})]
    with patch.object(scan.requests, "get", side_effect=responses):
        assert scan.fetch_cover(CANDIDATE) is None


def test_returns_none_on_timeout():
    with patch.object(scan.requests, "get", side_effect=scan.requests.Timeout):
        assert scan.fetch_cover(CANDIDATE) is None


def test_no_mbid_skips_archive():
    itunes_json = Mock(status_code=200)
    itunes_json.json.return_value = {"results": []}
    with patch.object(scan.requests, "get", side_effect=[itunes_json]) as get:
        assert scan.fetch_cover({**CANDIDATE, "mbid": None}) is None

    assert "itunes" in get.call_args_list[0].args[0]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_scan_cover.py -v`
Expected: FAIL — `AttributeError: module 'scan' has no attribute 'fetch_cover'`

- [ ] **Step 3: Write the minimal implementation**

Add to `scan.py` (add `import base64` to the top imports):

```python
COVER_TIMEOUT = 4.0


def _download_image(url: str) -> str | None:
    """Download an image URL and return it as a base64 data URI."""
    try:
        response = requests.get(url, timeout=COVER_TIMEOUT)
    except requests.RequestException:
        return None
    if response.status_code != 200 or not response.content:
        return None
    media_type = response.headers.get("Content-Type", "image/jpeg").split(";")[0]
    encoded = base64.b64encode(response.content).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def _itunes_artwork_url(artist: str, album: str) -> str | None:
    try:
        response = requests.get(
            "https://itunes.apple.com/search",
            params={"term": f"{artist} {album}", "entity": "album", "limit": 1},
            timeout=COVER_TIMEOUT,
        )
        results = response.json().get("results") or []
    except (requests.RequestException, ValueError):
        return None
    if not results:
        return None
    art = results[0].get("artworkUrl100")
    return art.replace("100x100bb", "600x600bb") if art else None


def fetch_cover(candidate: dict, spotify_image_url: str | None = None) -> str | None:
    """Return cover art as a base64 data URI, or None if every source misses."""
    mbid = candidate.get("mbid")
    if mbid:
        cover = _download_image(
            f"https://coverartarchive.org/release-group/{mbid}/front-500"
        )
        if cover:
            return cover

    itunes_url = _itunes_artwork_url(
        candidate.get("artist", ""), candidate.get("album_name", "")
    )
    if itunes_url:
        cover = _download_image(itunes_url)
        if cover:
            return cover

    if spotify_image_url:
        return _download_image(spotify_image_url)
    return None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_scan_cover.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Commit**

```bash
git add scan.py tests/test_scan_cover.py
git commit -m "Add cover art chain: Cover Art Archive, iTunes, Spotify"
```

---

### Task 5: `extract_from_image()`

The vision call. Structured output with a **dynamic** genre enum built from
the caller's genre list, so the model cannot invent a genre outside the
collection's vocabulary.

**Files:**
- Modify: `scan.py`
- Create: `tests/test_scan_image.py`

**Interfaces:**
- Consumes: nothing
- Produces: `extract_from_image(image_data_uri, genres) -> dict` with keys
  `artist`, `album_name`, `genre`, `label`, `catalog_number` — every value a
  `str` or `None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scan_image.py`:

```python
import json
from unittest.mock import patch, Mock

import pytest

import scan

GENRES = ["Rock", "MPB & Samba", "Jazz", "Soul & Funk"]
DATA_URI = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="


def _claude_response(payload: dict):
    block = Mock()
    block.type = "text"
    block.text = json.dumps(payload)
    message = Mock()
    message.content = [block]
    return message


def test_returns_extracted_fields():
    payload = {"artist": "Bill Withers", "album_name": "Live at Carnegie Hall",
               "genre": "Soul & Funk", "label": "Sussex", "catalog_number": "SXBS 7025"}
    client = Mock()
    client.messages.create.return_value = _claude_response(payload)

    with patch.object(scan, "_anthropic_client", return_value=client):
        result = scan.extract_from_image(DATA_URI, GENRES)

    assert result["artist"] == "Bill Withers"
    assert result["genre"] == "Soul & Funk"
    assert result["catalog_number"] == "SXBS 7025"


def test_genre_enum_is_built_from_supplied_genres():
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"artist": "X", "album_name": "Y", "genre": None,
         "label": None, "catalog_number": None}
    )

    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.extract_from_image(DATA_URI, GENRES)

    schema = client.messages.create.call_args.kwargs["output_config"]["format"]["schema"]
    assert schema["properties"]["genre"]["enum"] == GENRES


def test_uses_sonnet_5_at_low_effort():
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"artist": "X", "album_name": "Y", "genre": None,
         "label": None, "catalog_number": None}
    )

    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.extract_from_image(DATA_URI, GENRES)

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-5"
    assert kwargs["output_config"]["effort"] == "low"


def test_prompt_forbids_inferring_year_and_country():
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"artist": "X", "album_name": "Y", "genre": None,
         "label": None, "catalog_number": None}
    )

    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.extract_from_image(DATA_URI, GENRES)

    system = client.messages.create.call_args.kwargs["system"].lower()
    assert "year" in system and "country" in system


def test_illegible_fields_stay_none():
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"artist": "Bill Withers", "album_name": None, "genre": None,
         "label": None, "catalog_number": None}
    )

    with patch.object(scan, "_anthropic_client", return_value=client):
        result = scan.extract_from_image(DATA_URI, GENRES)

    assert result["album_name"] is None
    assert result["genre"] is None


def test_missing_api_key_raises_runtime_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        scan.extract_from_image(DATA_URI, GENRES)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_scan_image.py -v`
Expected: FAIL — `AttributeError: module 'scan' has no attribute '_anthropic_client'`

- [ ] **Step 3: Write the minimal implementation**

Add to `scan.py` (add `import json` to the top imports):

```python
import anthropic

VISION_MODEL = "claude-sonnet-5"
GENRE_MODEL = "claude-haiku-4-5"

_SLEEVE_SYSTEM = (
    "You read record sleeves. Report only what is printed on the image.\n"
    "Rules:\n"
    "1. If a field is not legible, return null. Never guess.\n"
    "2. Never infer or recall the release year or the country. Those are "
    "looked up from a music database afterwards. Reporting a year printed "
    "on the sleeve would give a pressing date, which is wrong here."
)


def _anthropic_client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=key)


def _sleeve_schema(genres: list[str]) -> dict:
    nullable_string = {"type": ["string", "null"]}
    return {
        "type": "object",
        "properties": {
            "artist": nullable_string,
            "album_name": nullable_string,
            # anyOf, NOT {"type": ["string","null"], "enum": genres} — `type` and
            # `enum` are ANDed, so null fails the enum and becomes unreachable,
            # forcing the model to invent a genre it was told to omit.
            "genre": {"anyOf": [{"type": "string", "enum": genres},
                                {"type": "null"}]},
            "label": nullable_string,
            "catalog_number": nullable_string,
        },
        "required": ["artist", "album_name", "genre", "label", "catalog_number"],
        "additionalProperties": False,
    }


def _media_type_and_data(data_uri: str) -> tuple[str, str]:
    header, _, payload = data_uri.partition(",")
    media_type = header.split(":")[1].split(";")[0] if ":" in header else "image/jpeg"
    return media_type, payload


def extract_from_image(image_data_uri: str, genres: list[str]) -> dict:
    """Read artist, album, genre, label and catalog number off a sleeve photo."""
    client = _anthropic_client()
    media_type, data = _media_type_and_data(image_data_uri)

    response = client.messages.create(
        model=VISION_MODEL,
        max_tokens=1024,
        system=_SLEEVE_SYSTEM,
        output_config={"effort": "low",
                       "format": {"type": "json_schema",
                                  "schema": _sleeve_schema(genres)}},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": media_type, "data": data}},
                {"type": "text", "text": "Read this record sleeve."},
            ],
        }],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_scan_image.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: Commit**

```bash
git add scan.py tests/test_scan_image.py
git commit -m "Add sleeve extraction via Claude vision with dynamic genre enum"
```

---

### Task 6: `classify_genre()`

The Spotify path has no genre available — Spotify's album `genres` field is
deprecated and always empty. A cheap text-only Haiku call fills it from
artist and album name, constrained to the same enum.

**Files:**
- Modify: `scan.py`
- Create: `tests/test_scan_genre.py`

**Interfaces:**
- Consumes: nothing
- Produces: `classify_genre(artist, album, genres) -> str | None`. The return
  value is always a member of `genres`, or `None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scan_genre.py`:

```python
import json
from unittest.mock import patch, Mock

import scan

GENRES = ["Rock", "MPB & Samba", "Jazz", "Soul & Funk"]


def _claude_response(payload: dict):
    block = Mock()
    block.type = "text"
    block.text = json.dumps(payload)
    message = Mock()
    message.content = [block]
    return message


def test_returns_a_genre_from_the_enum():
    client = Mock()
    client.messages.create.return_value = _claude_response({"genre": "Soul & Funk"})

    with patch.object(scan, "_anthropic_client", return_value=client):
        assert scan.classify_genre("Bill Withers", "Menagerie", GENRES) == "Soul & Funk"


def test_uses_haiku():
    client = Mock()
    client.messages.create.return_value = _claude_response({"genre": "Jazz"})

    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.classify_genre("Bill Evans", "Waltz for Debby", GENRES)

    assert client.messages.create.call_args.kwargs["model"] == "claude-haiku-4-5"


def test_null_genre_returns_none():
    client = Mock()
    client.messages.create.return_value = _claude_response({"genre": None})

    with patch.object(scan, "_anthropic_client", return_value=client):
        assert scan.classify_genre("Unknown", "Unknown", GENRES) is None


def test_value_outside_enum_is_rejected():
    client = Mock()
    client.messages.create.return_value = _claude_response({"genre": "Polka"})

    with patch.object(scan, "_anthropic_client", return_value=client):
        assert scan.classify_genre("X", "Y", GENRES) is None


def test_api_failure_returns_none():
    client = Mock()
    client.messages.create.side_effect = RuntimeError("boom")

    with patch.object(scan, "_anthropic_client", return_value=client):
        assert scan.classify_genre("X", "Y", GENRES) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_scan_genre.py -v`
Expected: FAIL — `AttributeError: module 'scan' has no attribute 'classify_genre'`

- [ ] **Step 3: Write the minimal implementation**

Add to `scan.py`:

```python
def classify_genre(artist: str, album: str, genres: list[str]) -> str | None:
    """Pick the best-fitting genre from the collection's own vocabulary."""
    if not genres:
        return None
    try:
        client = _anthropic_client()
        response = client.messages.create(
            model=GENRE_MODEL,
            max_tokens=256,
            system="Classify the record into exactly one of the supplied "
                   "genres. Return null if none fit.",
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": {
                    "type": "object",
                    "properties": {"genre": {"anyOf": [{"type": "string", "enum": genres},
                                                       {"type": "null"}]}},
                    "required": ["genre"],
                    "additionalProperties": False,
                }},
            },
            messages=[{"role": "user", "content": f"Artist: {artist}\nAlbum: {album}"}],
        )
        text = next(b.text for b in response.content if b.type == "text")
        genre = json.loads(text).get("genre")
    except Exception:
        return None
    return genre if genre in genres else None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_scan_genre.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Commit**

```bash
git add scan.py tests/test_scan_genre.py
git commit -m "Add genre classification for the Spotify path"
```

---

### Task 7: `extract_from_spotify()`

Resolves a Spotify link to artist, album, and cover image URL using the
client credentials flow. The token is cached in-process and refreshed once on
a 401.

The regression test guarding `release_date` is the most important test in
this task — it protects the collection's original-release convention.

**Files:**
- Modify: `scan.py`
- Create: `tests/fixtures/spotify_album.json`
- Create: `tests/test_scan_spotify.py`

**Interfaces:**
- Consumes: `parse_spotify_url` from Task 1
- Produces: `extract_from_spotify(url) -> dict` with keys `artist`,
  `album_name`, `image_url`. Raises `ValueError` for unusable URLs and
  `RuntimeError` when credentials are missing or the album is not found.

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/spotify_album.json` — note `release_date` is a
remaster year, deliberately different from the true original:

```json
{
  "name": "Live at Carnegie Hall",
  "release_date": "2015-06-01",
  "release_date_precision": "day",
  "genres": [],
  "label": "Sussex",
  "artists": [{"name": "Bill Withers", "id": "3XHO7cRUPCLOr6jwp8vsx5"}],
  "images": [
    {"url": "https://i.scdn.co/image/big", "height": 640, "width": 640},
    {"url": "https://i.scdn.co/image/small", "height": 64, "width": 64}
  ]
}
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_scan_spotify.py`:

```python
from unittest.mock import patch, Mock

import pytest

import scan
from conftest import load_fixture


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "secret")
    scan._spotify_token = None
    scan._spotify_token_expiry = 0.0


def _json_response(payload, status=200):
    mock = Mock()
    mock.status_code = status
    mock.json.return_value = payload
    return mock


def _token_response():
    return _json_response({"access_token": "tok", "expires_in": 3600})


def test_album_link_returns_fields():
    album = _json_response(load_fixture("spotify_album"))
    with patch.object(scan.requests, "post", return_value=_token_response()):
        with patch.object(scan.requests, "get", return_value=album):
            result = scan.extract_from_spotify(
                "https://open.spotify.com/album/4LH4d3cOWNNsVw41Gqt2kv"
            )

    assert result["artist"] == "Bill Withers"
    assert result["album_name"] == "Live at Carnegie Hall"
    assert result["image_url"] == "https://i.scdn.co/image/big"


def test_release_date_is_never_returned_as_year():
    """Guards the original-release convention: Spotify dates are reissue dates."""
    album = _json_response(load_fixture("spotify_album"))
    with patch.object(scan.requests, "post", return_value=_token_response()):
        with patch.object(scan.requests, "get", return_value=album):
            result = scan.extract_from_spotify(
                "https://open.spotify.com/album/4LH4d3cOWNNsVw41Gqt2kv"
            )

    assert "year" not in result
    assert "2015" not in str(result)


def test_track_link_resolves_via_its_album():
    track = _json_response({"album": load_fixture("spotify_album")})
    with patch.object(scan.requests, "post", return_value=_token_response()):
        with patch.object(scan.requests, "get", return_value=track) as get:
            result = scan.extract_from_spotify(
                "https://open.spotify.com/track/0eGsygTp906u18L0Oimnem"
            )

    assert "/tracks/" in get.call_args.args[0]
    assert result["album_name"] == "Live at Carnegie Hall"


def test_multiple_artists_are_joined():
    payload = load_fixture("spotify_album")
    payload["artists"] = [{"name": "Jorge Ben"}, {"name": "Gilberto Gil"}]
    with patch.object(scan.requests, "post", return_value=_token_response()):
        with patch.object(scan.requests, "get", return_value=_json_response(payload)):
            result = scan.extract_from_spotify("spotify:album:4LH4d3cOWNNsVw41Gqt2kv")

    assert result["artist"] == "Jorge Ben, Gilberto Gil"


def test_token_is_cached_across_calls():
    album = _json_response(load_fixture("spotify_album"))
    with patch.object(scan.requests, "post", return_value=_token_response()) as post:
        with patch.object(scan.requests, "get", return_value=album):
            scan.extract_from_spotify("spotify:album:4LH4d3cOWNNsVw41Gqt2kv")
            scan.extract_from_spotify("spotify:album:4LH4d3cOWNNsVw41Gqt2kv")

    assert post.call_count == 1


def test_401_triggers_exactly_one_refresh():
    album = _json_response(load_fixture("spotify_album"))
    responses = [_json_response({}, status=401), album]
    with patch.object(scan.requests, "post", return_value=_token_response()) as post:
        with patch.object(scan.requests, "get", side_effect=responses):
            result = scan.extract_from_spotify("spotify:album:4LH4d3cOWNNsVw41Gqt2kv")

    assert post.call_count == 2
    assert result["album_name"] == "Live at Carnegie Hall"


def test_missing_credentials_raise(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    with pytest.raises(RuntimeError):
        scan.extract_from_spotify("spotify:album:4LH4d3cOWNNsVw41Gqt2kv")


def test_unknown_album_raises():
    with patch.object(scan.requests, "post", return_value=_token_response()):
        with patch.object(scan.requests, "get", return_value=_json_response({}, status=404)):
            with pytest.raises(RuntimeError):
                scan.extract_from_spotify("spotify:album:4LH4d3cOWNNsVw41Gqt2kv")


def test_playlist_link_raises_value_error():
    with pytest.raises(ValueError):
        scan.extract_from_spotify("https://open.spotify.com/playlist/37i9dQZF1DX")
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python -m pytest tests/test_scan_spotify.py -v`
Expected: FAIL — `AttributeError: module 'scan' has no attribute '_spotify_token'`

- [ ] **Step 4: Write the minimal implementation**

Add to `scan.py`:

```python
SPOTIFY_API = "https://api.spotify.com/v1"
SPOTIFY_TIMEOUT = 5.0

_spotify_token: str | None = None
_spotify_token_expiry: float = 0.0


def _spotify_access_token(force_refresh: bool = False) -> str:
    """Fetch (and cache) a client-credentials bearer token."""
    global _spotify_token, _spotify_token_expiry
    if not force_refresh and _spotify_token and time.time() < _spotify_token_expiry:
        return _spotify_token

    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET are not set")

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")
    response = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        headers={"Authorization": f"Basic {basic}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        timeout=SPOTIFY_TIMEOUT,
    )
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("Spotify rejected the client credentials")
    _spotify_token = token
    _spotify_token_expiry = time.time() + payload.get("expires_in", 3600) - 60
    return token


def _spotify_get(path: str) -> dict:
    """GET a Spotify endpoint, refreshing the token once on a 401."""
    for attempt in range(2):
        token = _spotify_access_token(force_refresh=attempt == 1)
        response = requests.get(
            f"{SPOTIFY_API}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=SPOTIFY_TIMEOUT,
        )
        if response.status_code == 401 and attempt == 0:
            continue
        if response.status_code != 200:
            raise RuntimeError(f"Spotify returned {response.status_code} for {path}")
        return response.json()
    raise RuntimeError("Spotify authentication failed")


def extract_from_spotify(url: str) -> dict:
    """Resolve a Spotify album or track link to artist, album and cover URL.

    Deliberately does NOT return a year: Spotify's ``release_date`` belongs to
    that specific album entry, so a remaster reports the remaster date. The
    year always comes from MusicBrainz.
    """
    kind, spotify_id = parse_spotify_url(url)
    payload = _spotify_get(f"/{kind}s/{spotify_id}")
    album = payload.get("album") if kind == "track" else payload
    if not album:
        raise RuntimeError("Spotify returned no album for that link")

    images = album.get("images") or []
    return {
        "artist": ", ".join(a["name"] for a in album.get("artists", []) if a.get("name")),
        "album_name": album.get("name") or "",
        "image_url": images[0]["url"] if images else None,
    }
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/test_scan_spotify.py -v`
Expected: PASS — 9 passed

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest tests/ -v`
Expected: PASS — 61 passed (14 + 9 + 8 + 6 + 9 + 6 + 9)

- [ ] **Step 7: Commit**

```bash
git add scan.py tests/fixtures/spotify_album.json tests/test_scan_spotify.py
git commit -m "Add Spotify link resolution via client credentials flow"
```

---

### Task 8: `POST /api/scan` endpoint

Wires the pieces together. Contains no extraction logic of its own — it
selects an input path, runs the shared pipeline, and shapes the response.

**Files:**
- Modify: `app.py` (add route after the existing `delete_record`, before the
  `── CSV import / export ──` section comment)
- Create: `tests/test_scan_endpoint.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: every `scan.py` function from Tasks 1–7
- Produces: `POST /api/scan` returning the JSON contract below. The frontend
  in Tasks 9–11 depends on these exact key names.

```json
{"source": "photo|spotify", "artist": "", "album_name": "", "genre": "",
 "candidates": [{"mbid": "", "year": "", "country": "", "label": "",
                 "artist": "", "album_name": "", "cover_data": ""}],
 "duplicate_of": {"id": 0, "artist": "", "album_name": ""},
 "search_string": ""}
```

- [ ] **Step 1: Write the failing test**

Create `tests/test_scan_endpoint.py`:

```python
from unittest.mock import patch

import pytest

import app as app_module


@pytest.fixture
def client(monkeypatch, tmp_path):
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        with test_client.session_transaction() as session:
            session["authed"] = True
        yield test_client


def test_requires_auth():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as anon:
        assert anon.post("/api/scan", json={"image": "data:image/jpeg;base64,x"}).status_code == 401


def test_rejects_both_inputs(client):
    response = client.post("/api/scan", json={"image": "x", "spotify_url": "y"})
    assert response.status_code == 400


def test_rejects_neither_input(client):
    assert client.post("/api/scan", json={}).status_code == 400


def test_photo_path_returns_merged_fields(client):
    extracted = {"artist": "Bill Withers", "album_name": "Live at Carnegie Hall",
                 "genre": "Soul & Funk", "label": "Sussex", "catalog_number": None}
    candidate = {"mbid": "abc", "year": "1973", "country": "US", "label": None,
                 "artist": "Bill Withers", "album_name": "Live at Carnegie Hall"}

    with patch.object(app_module.scan, "extract_from_image", return_value=extracted), \
         patch.object(app_module.scan, "lookup_musicbrainz", return_value=[candidate]), \
         patch.object(app_module.scan, "fetch_cover", return_value="data:image/jpeg;base64,zz"):
        response = client.post("/api/scan", json={"image": "data:image/jpeg;base64,x"})

    body = response.get_json()
    assert response.status_code == 200
    assert body["source"] == "photo"
    assert body["artist"] == "Bill Withers"
    assert body["genre"] == "Soul & Funk"
    assert body["candidates"][0]["year"] == "1973"
    assert body["candidates"][0]["cover_data"] == "data:image/jpeg;base64,zz"
    assert "Bill Withers Live at Carnegie Hall 1973 vinyl cover" == body["search_string"]


def test_spotify_path_classifies_genre(client):
    resolved = {"artist": "Bill Withers", "album_name": "Live at Carnegie Hall",
                "image_url": "https://i.scdn.co/image/big"}
    candidate = {"mbid": "abc", "year": "1973", "country": "US", "label": None,
                 "artist": "Bill Withers", "album_name": "Live at Carnegie Hall"}

    with patch.object(app_module.scan, "extract_from_spotify", return_value=resolved), \
         patch.object(app_module.scan, "classify_genre", return_value="Soul & Funk"), \
         patch.object(app_module.scan, "lookup_musicbrainz", return_value=[candidate]), \
         patch.object(app_module.scan, "fetch_cover", return_value=None):
        response = client.post("/api/scan",
                               json={"spotify_url": "spotify:album:4LH4d3cOWNNsVw41Gqt2kv"})

    body = response.get_json()
    assert body["source"] == "spotify"
    assert body["genre"] == "Soul & Funk"


def test_musicbrainz_miss_still_returns_vision_fields(client):
    extracted = {"artist": "Obscure", "album_name": "Unknown", "genre": "Jazz",
                 "label": None, "catalog_number": None}

    with patch.object(app_module.scan, "extract_from_image", return_value=extracted), \
         patch.object(app_module.scan, "lookup_musicbrainz", return_value=[]):
        response = client.post("/api/scan", json={"image": "data:image/jpeg;base64,x"})

    body = response.get_json()
    assert response.status_code == 200
    assert body["artist"] == "Obscure"
    assert body["candidates"] == []


def test_missing_api_key_returns_503(client):
    with patch.object(app_module.scan, "extract_from_image",
                      side_effect=RuntimeError("ANTHROPIC_API_KEY is not set")):
        response = client.post("/api/scan", json={"image": "data:image/jpeg;base64,x"})

    assert response.status_code == 503


def test_bad_spotify_url_returns_400(client):
    with patch.object(app_module.scan, "extract_from_spotify",
                      side_effect=ValueError("nope")):
        response = client.post("/api/scan", json={"spotify_url": "https://example.com"})

    assert response.status_code == 400
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_scan_endpoint.py -v`
Expected: FAIL — 404 responses, because the route does not exist yet

- [ ] **Step 3: Write the minimal implementation**

Add `import scan` to the top of `app.py`, then add this route directly after
`delete_record`:

```python
# ── scan (photo / Spotify autofill) ───────────────────────────────────────────

@app.route("/api/scan", methods=["POST"])
@require_auth
def scan_record():
    d = request.get_json(silent=True) or {}
    image = d.get("image")
    spotify_url = d.get("spotify_url")
    if bool(image) == bool(spotify_url):
        return jsonify({"error": "Provide exactly one of image or spotify_url"}), 400

    # Load only the four columns needed. Record.query.all() would pull every
    # cover_data blob — ~31MB across the collection — on every scan.
    rows = db.session.query(
        Record.id, Record.artist, Record.album_name, Record.genre
    ).all()
    genres = sorted({r.genre for r in rows if r.genre})

    try:
        if image:
            source = "photo"
            fields = scan.extract_from_image(image, genres)
            spotify_image = None
        else:
            source = "spotify"
            resolved = scan.extract_from_spotify(spotify_url)
            spotify_image = resolved.get("image_url")
            fields = {
                "artist": resolved["artist"],
                "album_name": resolved["album_name"],
                "genre": scan.classify_genre(
                    resolved["artist"], resolved["album_name"], genres),
                "label": None,
                "catalog_number": None,
            }
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        message = str(e)
        status = 503 if "not set" in message else 502
        return jsonify({"error": message}), status
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    artist = fields.get("artist") or ""
    album = fields.get("album_name") or ""

    candidates = scan.lookup_musicbrainz(artist, album)
    for candidate in candidates:
        candidate["cover_data"] = scan.fetch_cover(candidate, spotify_image)

    year = candidates[0]["year"] if candidates else ""
    existing = [{"id": r.id, "artist": r.artist or "",
                 "album_name": r.album_name or ""} for r in rows]
    duplicate = scan.find_duplicate(artist, album, existing)

    return jsonify({
        "source": source,
        "artist": artist,
        "album_name": album,
        "genre": fields.get("genre") or "",
        "candidates": candidates,
        "duplicate_of": {"id": duplicate["id"], "artist": duplicate["artist"],
                         "album_name": duplicate["album_name"]} if duplicate else None,
        "search_string": " ".join(p for p in [artist, album, year, "vinyl cover"] if p),
    })
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_scan_endpoint.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Document the environment variables**

Add to `README.md` in the Railway **Variables** list (after `DATA_DIR`):

```markdown
   - `ANTHROPIC_API_KEY` — chave da API da Anthropic (console.anthropic.com).
     Não é a assinatura do Claude.ai; é cobrança separada por uso. Sem ela, o
     scan por foto fica desabilitado.
   - `MUSICBRAINZ_CONTACT` — e-mail de contato enviado no `User-Agent` para a
     MusicBrainz (obrigatório pela API deles).
   - `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` — de um app registrado em
     developer.spotify.com. Sem eles, apenas o colar link do Spotify fica
     desabilitado.
```

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest tests/ -v`
Expected: PASS — 69 passed

- [ ] **Step 7: Commit**

```bash
git add app.py README.md tests/test_scan_endpoint.py
git commit -m "Add POST /api/scan endpoint wiring the scan pipeline"
```

---

### Task 9: Cover action sheet, camera capture, and client-side resize

Replaces the direct file-picker click on the cover drop zone with a
three-option action sheet, and adds the in-page camera.

No JS test framework exists in this project, so this task is verified
manually. The verification steps are exact — do not skip them.

**Files:**
- Modify: `templates/index.html` — the `.cover-drop` block at ~line 1138, and
  the cover upload handler at ~line 2298

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: `resizeImage(file, maxEdge)` returning a `Promise<string>` data
  URI, and `applyCover(dataUri)` setting `coverDataUri` plus the preview.
  Task 10 and Task 11 both call these.

- [ ] **Step 1: Replace the cover drop markup**

Replace the `<div class="cover-drop">…</div>` block with:

```html
<div class="cover-drop" id="coverDrop" onclick="openCoverSheet()">
  <div id="coverDropInner">
    <i class="ti ti-photo" style="font-size:24px;opacity:.2;display:block;margin-bottom:4px"></i>
    <span style="font-size:12px;color:var(--muted)">click to add album cover</span>
  </div>
  <img id="coverPreview" class="cover-preview" style="display:none">
</div>
<input type="file" accept="image/*" id="coverInput" style="display:none">
<input type="file" accept="image/*" capture="environment" id="coverCaptureInput" style="display:none">

<div class="cover-sheet hidden" id="coverSheet">
  <button type="button" class="cover-sheet-row" onclick="pickCoverFile()">
    <i class="ti ti-folder"></i> Choose file
  </button>
  <button type="button" class="cover-sheet-row" id="coverSheetCamera" onclick="openCamera()">
    <i class="ti ti-camera"></i> Take photo
  </button>
</div>

<div class="overlay hidden" id="cameraOverlay">
  <div class="modal" style="max-width:420px">
    <div class="modal-head">
      <span class="modal-title">take photo</span>
      <button class="btn btn-ghost btn-sm" onclick="closeCamera()"><i class="ti ti-x"></i></button>
    </div>
    <div class="modal-body" style="text-align:center">
      <video id="camVideo" playsinline autoplay muted
             style="width:100%;border-radius:var(--radius);background:#000"></video>
    </div>
    <div class="modal-foot">
      <button class="btn" onclick="closeCamera()">cancel</button>
      <button class="btn btn-primary" onclick="captureFrame()">capture</button>
    </div>
  </div>
</div>
```

`playsinline`, `autoplay`, and `muted` are all three required — without
`playsinline`, iOS Safari hijacks the video into fullscreen.

- [ ] **Step 2: Add the stylesheet rules**

Add near the other modal rules in the `<style>` block:

```css
.cover-sheet{margin-top:8px;border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;background:var(--surface)}
.cover-sheet.hidden{display:none}
.cover-sheet-row{display:flex;align-items:center;gap:10px;width:100%;padding:12px;background:none;border:none;border-bottom:1px solid var(--border);color:var(--text);font-family:var(--font);font-size:13px;cursor:pointer;text-align:left}
.cover-sheet-row:last-child{border-bottom:none}
.cover-sheet-row:hover{background:var(--card)}
```

- [ ] **Step 3: Replace the cover upload handler**

Replace the existing `coverInput` change listener with:

```js
// ── cover: action sheet, camera, resize ────────────────────────────────────
let camStream = null;

function openCoverSheet(){
  const sheet = document.getElementById('coverSheet');
  sheet.classList.toggle('hidden');
  // Hide the camera row when no camera path can work at all.
  const hasCamera = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)
    || 'capture' in document.createElement('input');
  document.getElementById('coverSheetCamera').style.display = hasCamera ? '' : 'none';
}
function closeCoverSheet(){ document.getElementById('coverSheet').classList.add('hidden'); }

function pickCoverFile(){ closeCoverSheet(); document.getElementById('coverInput').click(); }
function fallbackCapture(){ closeCoverSheet(); document.getElementById('coverCaptureInput').click(); }

async function openCamera(){
  closeCoverSheet();
  // navigator.mediaDevices is undefined (not an error) outside a secure context.
  if(!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia){ fallbackCapture(); return; }
  try{
    // `ideal`, never `exact` — `exact` throws on desktops with no rear camera.
    camStream = await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'}}});
  }catch(err){ fallbackCapture(); return; }
  const video = document.getElementById('camVideo');
  video.srcObject = camStream;
  document.getElementById('cameraOverlay').classList.remove('hidden');
  try{ await video.play(); }catch(e){}
}

function closeCamera(){
  if(camStream){ camStream.getTracks().forEach(t=>t.stop()); camStream = null; }
  const video = document.getElementById('camVideo');
  video.srcObject = null;
  document.getElementById('cameraOverlay').classList.add('hidden');
}

function captureFrame(){
  const video = document.getElementById('camVideo');
  const scale = Math.min(1, 1000/Math.max(video.videoWidth, video.videoHeight));
  const cv = document.createElement('canvas');
  cv.width = Math.round(video.videoWidth*scale);
  cv.height = Math.round(video.videoHeight*scale);
  cv.getContext('2d').drawImage(video, 0, 0, cv.width, cv.height);
  const dataUri = cv.toDataURL('image/jpeg', .85);
  closeCamera();
  applyCover(dataUri);
  scanFromImage(dataUri);
}

async function resizeImage(file, maxEdge=1000){
  let bmp;
  try{
    // imageOrientation:'from-image' applies the EXIF rotation flag; without it
    // portrait phone photos land sideways.
    bmp = await createImageBitmap(file, {imageOrientation:'from-image'});
  }catch(e){
    bmp = await new Promise((res, rej)=>{
      const img = new Image();
      img.onload = ()=>res(img); img.onerror = rej;
      img.src = URL.createObjectURL(file);
    });
  }
  const w0 = bmp.width || bmp.naturalWidth, h0 = bmp.height || bmp.naturalHeight;
  const scale = Math.min(1, maxEdge/Math.max(w0, h0));
  const cv = document.createElement('canvas');
  cv.width = Math.round(w0*scale); cv.height = Math.round(h0*scale);
  cv.getContext('2d').drawImage(bmp, 0, 0, cv.width, cv.height);
  return cv.toDataURL('image/jpeg', .85);
}

function applyCover(dataUri){
  coverDataUri = dataUri;
  const preview = document.getElementById('coverPreview');
  preview.src = dataUri;
  preview.style.display = 'block';
  document.getElementById('coverDropInner').style.display = 'none';
}

async function handleCoverFile(e){
  const file = e.target.files[0];
  if(!file) return;
  e.target.value = '';
  const dataUri = await resizeImage(file);
  applyCover(dataUri);
  scanFromImage(dataUri);
}
document.getElementById('coverInput').addEventListener('change', handleCoverFile);
document.getElementById('coverCaptureInput').addEventListener('change', handleCoverFile);

// Defined in Task 11; stubbed here so this task runs standalone.
function scanFromImage(dataUri){}
```

- [ ] **Step 4: Verify on desktop**

Run `python app.py`, open `http://localhost:5000`, unlock edit mode, click
**add record**, then click the cover box. Confirm:
- The sheet opens with both rows.
- **Choose file** opens a file picker; picking a large photo shows a preview.
- **Take photo** prompts for camera permission and shows a live preview.
- **Capture** closes the modal, shows the frame as the preview, **and the
  webcam indicator light goes out**.
- **Cancel** also turns the indicator light out.

- [ ] **Step 5: Verify EXIF orientation**

Take a **portrait** photo on a phone, transfer it to the desktop, and import
it via **Choose file**. The preview must be upright, not rotated 90°. If it
is sideways, `createImageBitmap` is not applying orientation in that browser
— fix before continuing, since a sideways sleeve degrades OCR too.

- [ ] **Step 6: Commit**

```bash
git add templates/index.html
git commit -m "Add cover action sheet with camera capture and EXIF-safe resize"
```

---

### Task 10: Spotify paste field and logo

Adds the third row to the action sheet.

**Files:**
- Modify: `templates/index.html` — the `#coverSheet` block from Task 9
- Uses: `static/spotify-logo.png` (already committed)

**Interfaces:**
- Consumes: `applyCover` from Task 9
- Produces: `scanFromSpotify(url)` — called by Task 11's shared handler.

- [ ] **Step 1: Add the Spotify row to the sheet**

Append inside `#coverSheet`, after the camera row:

```html
<!-- The 12px gaps are Spotify's required exclusion zone (half the 24px
     mark's height), not arbitrary spacing. Do not harmonise them to 8px. -->
<div class="cover-sheet-row" style="flex-direction:column;align-items:stretch;gap:12px;cursor:default">
  <span style="display:flex;align-items:center;gap:12px">
    <img src="/static/spotify-logo.png" alt="Spotify" class="spotify-mark">
    Paste Spotify link
  </span>
  <span style="display:flex;gap:6px">
    <input type="text" id="spotifyUrlInput" placeholder="https://open.spotify.com/album/…"
           style="flex:1;min-width:0" onkeydown="if(event.key==='Enter'){event.preventDefault();submitSpotifyUrl()}">
    <button type="button" class="btn btn-sm" onclick="submitSpotifyUrl()">
      <i class="ti ti-arrow-right"></i>
    </button>
  </span>
  <span id="spotifyUrlErr" style="font-size:12px;color:var(--danger);display:none"></span>
</div>
```

- [ ] **Step 2: Add the logo style**

Spotify's guidelines require ≥21px for the icon alone, native aspect ratio,
no recolouring, and clear space of half the icon height. 24px with 12px of
row padding satisfies all of it. The green mark is permitted on black or
white only — this app's two themes are `#141414` and `#ffffff`, so no
monochrome variant is needed.

```css
.spotify-mark{width:24px;height:24px;flex-shrink:0;display:block}
```

Do not add `border-radius`, `filter`, a background plate, or any transform to
this element.

- [ ] **Step 3: Add the submit handler**

```js
function submitSpotifyUrl(){
  const input = document.getElementById('spotifyUrlInput');
  const url = input.value.trim();
  if(!url) return;
  scanFromSpotify(url);
}

// Pasting a share link is the whole gesture — submit without a second tap.
document.getElementById('spotifyUrlInput').addEventListener('paste', e=>{
  const text = (e.clipboardData || window.clipboardData).getData('text') || '';
  if(/open\.spotify\.com|^spotify:/.test(text.trim())){
    setTimeout(()=>scanFromSpotify(text.trim()), 0);
  }
});

function showSpotifyError(message){
  const el = document.getElementById('spotifyUrlErr');
  el.textContent = message;
  el.style.display = message ? 'block' : 'none';
}

// Defined in Task 11; stubbed here so this task runs standalone.
function scanFromSpotify(url){}
```

- [ ] **Step 4: Verify the row renders correctly**

Reload the add-record form and open the cover sheet. Confirm:
- The Spotify mark renders at 24×24, circular green with white bars, not
  stretched or clipped.
- It looks correct in **both** themes — toggle the theme and re-check.
- The input and arrow button sit on one row and do not overflow on a narrow
  window (resize to ~360px wide).

- [ ] **Step 5: Commit**

```bash
git add templates/index.html
git commit -m "Add Spotify link paste row with brand-compliant logo"
```

---

### Task 11: Autofill, candidate picker, and duplicate warning

Connects both input paths to the form. Replaces the two stubs from Tasks 9
and 10 with real implementations.

**Files:**
- Modify: `templates/index.html`

**Interfaces:**
- Consumes: `applyCover` (Task 9), `showSpotifyError` (Task 10), and the
  `/api/scan` contract (Task 8)
- Produces: nothing downstream — this is the final task.

- [ ] **Step 1: Add the candidate and duplicate markup**

Insert directly after the album-name form group:

```html
<div id="scanAlternates" style="display:none;margin-top:4px">
  <a href="#" style="font-size:12px;color:var(--accent)" onclick="event.preventDefault();toggleAlternates()">
    not this one? (<span id="scanAltCount">0</span>)
  </a>
  <div id="scanAltList" class="cover-sheet hidden" style="margin-top:6px"></div>
</div>
```

And directly inside the top of the form's `modal-body`:

```html
<div id="scanDupWarning" style="display:none;margin-bottom:12px;padding:10px;
     border:1px solid var(--danger);border-radius:var(--radius);font-size:13px">
</div>
```

- [ ] **Step 2: Replace both stubs with the real implementation**

Delete the two stub functions (`function scanFromImage(dataUri){}` and
`function scanFromSpotify(url){}`) and add:

```js
// ── scan: autofill from photo or Spotify link ──────────────────────────────
let scanCandidates = [];

async function runScan(body){
  showSpotifyError('');
  toast('scanning…');
  let res, data;
  try{
    res = await fetch('/api/scan', {method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    data = await res.json();
  }catch(e){
    toast('scan failed — fill the form manually');
    return;
  }
  if(!res.ok){
    const message = (data && data.error) || 'scan failed';
    if(body.spotify_url) showSpotifyError(message); else toast(message);
    return;
  }
  applyScanResult(data);
}

function scanFromImage(dataUri){ runScan({image:dataUri}); }
function scanFromSpotify(url){ runScan({spotify_url:url}); }

function applyScanResult(data){
  if(data.artist) document.getElementById('fArtist').value = data.artist;
  if(data.album_name) document.getElementById('fAlbum').value = data.album_name;
  if(data.genre){ populateGenreSelect(data.genre); document.getElementById('fGenre').value = data.genre; }

  scanCandidates = data.candidates || [];
  if(scanCandidates.length) applyCandidate(scanCandidates[0]);

  const alternates = document.getElementById('scanAlternates');
  if(scanCandidates.length > 1){
    document.getElementById('scanAltCount').textContent = scanCandidates.length;
    alternates.style.display = 'block';
    document.getElementById('scanAltList').innerHTML = scanCandidates.map((c,i)=>
      `<button type="button" class="cover-sheet-row" onclick="pickCandidate(${i})">
         ${esc(c.album_name||'')} — ${esc(c.year||'?')} · ${esc(c.country||'?')}
       </button>`).join('');
  } else {
    alternates.style.display = 'none';
  }

  const warning = document.getElementById('scanDupWarning');
  if(data.duplicate_of){
    warning.innerHTML = `⚠ You already have <strong>${esc(data.duplicate_of.artist)} —
      ${esc(data.duplicate_of.album_name)}</strong> in the collection.`;
    warning.style.display = 'block';
  } else {
    warning.style.display = 'none';
  }

  closeCoverSheet();
  toast('fields filled — check before saving');
}

function applyCandidate(c){
  if(c.year) document.getElementById('fYear').value = c.year;
  if(c.country) document.getElementById('fCountry').value = countryLabelFromCode(c.country);
  if(c.cover_data) applyCover(c.cover_data);
}

function pickCandidate(i){
  applyCandidate(scanCandidates[i]);
  toggleAlternates();
}

function toggleAlternates(){
  document.getElementById('scanAltList').classList.toggle('hidden');
}
```

- [ ] **Step 3: Reset scan state when the form opens**

The add-record entry point is `openAdd()` at `templates/index.html:2185`
(the edit path is `openEdit`, further down). Add these lines to `openAdd`
alongside the existing field resets:

```js
scanCandidates = [];
document.getElementById('scanAlternates').style.display = 'none';
document.getElementById('scanDupWarning').style.display = 'none';
document.getElementById('spotifyUrlInput').value = '';
showSpotifyError('');
```

- [ ] **Step 4: Verify the photo path end to end**

With `ANTHROPIC_API_KEY` and `MUSICBRAINZ_CONTACT` set, run `python app.py`
and scan three real sleeves from the collection:
- one US rock record — expect artist, album, genre, year, country all filled
- one MPB record (e.g. Altamiro Carrilho) — expect at minimum artist and
  album; year/country may be empty, which is correct behaviour
- one record already in the collection — expect the duplicate warning

- [ ] **Step 5: Verify the Spotify path end to end**

With `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` set:
- Share an album from the Spotify mobile app and paste the link. Fields fill.
- Paste a **track** link from that same album. The same fields fill.
- Paste an album whose Spotify entry is a **remaster**. Confirm the year is
  the original release, not the remaster year. This is the single most
  important check in the plan.
- Paste a playlist link. Expect an inline red error under the field, and the
  form remains usable.

- [ ] **Step 6: Verify graceful degradation**

Stop the app, unset `ANTHROPIC_API_KEY`, restart, and scan a photo. Expect a
toast, no crash, and a fully usable manual form.

- [ ] **Step 7: Run the whole suite**

Run: `python -m pytest tests/ -v`
Expected: PASS — 69 passed

- [ ] **Step 8: Commit**

```bash
git add templates/index.html
git commit -m "Wire scan results into the add-record form"
```

---

## Self-Review Notes

**Spec coverage:** §1 module → Tasks 1–7. §2 vision → Task 5. §3 Spotify →
Tasks 1, 7. §4 MusicBrainz → Task 3. §5 cover + duplicates → Tasks 2, 4. §6
endpoint → Task 8. §7 camera/resize → Task 9. §8 Spotify UI + branding →
Task 10. §9 form behaviour → Task 11. Known limitation (expat country) is
accepted, not implemented — correct per spec.

**Deferred deliberately:** the spec's `label` field is returned by
`extract_from_image` but never written to a form field, because `Record` has
no label column. It stays in the payload to improve MusicBrainz matching
later. No task adds a column for it.
