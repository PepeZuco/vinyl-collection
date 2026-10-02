# Spotify Filtered Playlists Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two fixed Spotify playlists with saved playlists the owner builds from filters (liked/every track, release year, genre, Pepe/Jenni rating, bought at, bought date range), listed in the popup and resynced instead of duplicated.

**Architecture:** The filter rules live in one pure Python module (`playlist_filters.py`) with a JavaScript twin (`static/playlist_filters.js`) for the popup's live count and auto-name; both are checked against one shared JSON fixture so they cannot drift. `spotify_sync.py` stops knowing about named playlist kinds — it syncs "these records, liked or not, into this Spotify id (or a new one)". `app.py` gains a `SpotifyPlaylist` table and four routes; the popup lists saved rows and holds the new-playlist form.

**Tech Stack:** Flask + Flask-SQLAlchemy (SQLite locally, Postgres on Railway), plain JS in `templates/index.html` + `static/*.js`, pytest, node:test (+ jsdom for DOM tests, run through pytest wrappers).

**Spec:** `docs/superpowers/specs/2026-10-02-spotify-filtered-playlists-design.md`

## Global Constraints

- Spotify playlist names are capped at **100** characters.
- Base name: `Zucoloto Vinyl`, plus ` — Liked` when liked; parts joined with ` · `.
- Legacy names, verbatim: `Zucoloto Vinyl Collection` (every track) and `Zucoloto Vinyl Collection — Liked` (liked).
- Record pool: `have_it` true and a non-empty `spotify_url`, ordered `bought_date, id`.
- Stamps: local wall clock `datetime.now().strftime("%Y-%m-%dT%H:%M:%S")`, never UTC.
- Spotify paths follow the February 2026 API: `/me/playlists` to create, `/playlists/{id}/items` to read/edit, `/playlists/{id}/followers` to delete.
- Every `/api/spotify/*` route is behind `require_auth`; a missing or expired login answers `409 {"connect": true}`.
- Run tests from `vinyl-collection/`: `python3 -m pytest -q <path>`. JS tests run through their `tests/test_*.py` wrapper (they need env vars a bare `node --test` lacks).

## Review Focus

1. **Messy `year` text** (`"1973 (reissue)"`, `"c.1973"`, `"?"`, `""`) — first 4-digit run is the year; no run means excluded once a year bound is set. Pinned in the shared fixture (Task 1).
2. **Same filters typed differently** (`["Rock","jazz"]` vs `[" JAZZ ","rock"]`) must hit the same saved playlist, not create a second one. Pinned in Task 1 (key) and Task 3 (route).
3. **A playlist deleted by hand on Spotify** — the next sync must recreate it and store the new id, not fail with 404. Pinned in Task 2.
4. **Legacy adoption must not hijack a stranger's playlist** — only the two seeded rows ever look a playlist up by name; a new playlist whose name happens to match one already in the account gets its own. Pinned in Task 2 and Task 3.
5. **Double-click on "create & sync"** — two POSTs with the same filters must end with one row (unique key + IntegrityError fallback). Pinned in Task 3.

---

## File Structure

| File | Responsibility |
|---|---|
| `playlist_filters.py` (create) | Normalize filters, filter key, suggested name, one-line summary, record matching. No I/O. |
| `static/playlist_filters.js` (create) | Same rules for the browser: normalize, matches, countMatching, suggestName. |
| `tests/fixtures/playlist_filter_cases.json` (create) | Shared match/name cases both languages must pass. |
| `tests/test_playlist_filters.py` (create) | Python rules + fixture. |
| `tests/test_playlist_filters.js` + `tests/test_playlist_filters_js.py` (create) | JS rules + fixture, run under pytest. |
| `spotify_sync.py` (modify) | Sync into a given id or a new playlist; delete; drop `PLAYLISTS`/`find_or_create_playlist`. |
| `app.py` (modify) | `SpotifyPlaylist` model, legacy seed, record fields, routes. |
| `tests/test_spotify_playlists.py` (modify) | Sync + route tests on the new shapes. |
| `templates/index.html` (modify) | Popup list + new-playlist form, CSS, script tag. |
| `tests/test_playlists_dom.js` (modify) | DOM tests for list, form, create, delete. |
| `README.md` (modify) | Playlists section. |

---

### Task 1: Filter rules (Python) and the shared fixture

**Files:**
- Create: `playlist_filters.py`
- Create: `tests/fixtures/playlist_filter_cases.json`
- Test: `tests/test_playlist_filters.py`

**Interfaces:**
- Produces:
  - `class FilterError(ValueError)` with `.field: str`
  - `normalize_filters(raw: dict | None) -> dict` — raises `FilterError`
  - `filter_key(filters: dict) -> str`
  - `suggest_name(filters: dict) -> str`
  - `describe(filters: dict) -> str`
  - `select(records: list[dict], filters: dict) -> list[dict]` — records carry `year, genre, my_rating, wife_rating, bought_where, bought_date`
  - fixture shape: `{"match": [{why, filters, record, match}], "names": [{filters, name}]}`

- [ ] **Step 1: Write the shared fixture**

`tests/fixtures/playlist_filter_cases.json`:

```json
{
  "match": [
    {"why": "year is the first four digits", "filters": {"year_from": 1970, "year_to": 1979}, "record": {"year": "1973 (reissue)"}, "match": true},
    {"why": "year with a prefix", "filters": {"year_from": 1970, "year_to": 1979}, "record": {"year": "c.1973"}, "match": true},
    {"why": "outside the range", "filters": {"year_from": 1970, "year_to": 1979}, "record": {"year": "1980"}, "match": false},
    {"why": "unreadable year is out once a bound is set", "filters": {"year_from": 1970}, "record": {"year": "?"}, "match": false},
    {"why": "no year filter keeps a yearless record", "filters": {}, "record": {"year": ""}, "match": true},
    {"why": "reversed range is swapped", "filters": {"year_from": 1979, "year_to": 1970}, "record": {"year": "1975"}, "match": true},
    {"why": "genre ignores case and spacing", "filters": {"genres": ["Rock"]}, "record": {"genre": "  rock "}, "match": true},
    {"why": "genre matches any of several", "filters": {"genres": ["Jazz", "Rock"]}, "record": {"genre": "Jazz"}, "match": true},
    {"why": "another genre is out", "filters": {"genres": ["Jazz"]}, "record": {"genre": "Rock"}, "match": false},
    {"why": "and needs both minimums", "filters": {"pepe_min": 4, "jenni_min": 4, "rating_mode": "and"}, "record": {"my_rating": 5, "wife_rating": 3}, "match": false},
    {"why": "or needs either minimum", "filters": {"pepe_min": 4, "jenni_min": 4, "rating_mode": "or"}, "record": {"my_rating": 5, "wife_rating": 3}, "match": true},
    {"why": "mode defaults to and", "filters": {"pepe_min": 4, "jenni_min": 4}, "record": {"my_rating": 5, "wife_rating": 3}, "match": false},
    {"why": "a single minimum ignores the mode", "filters": {"pepe_min": 4, "rating_mode": "or"}, "record": {"my_rating": 3, "wife_rating": 5}, "match": false},
    {"why": "half stars count", "filters": {"jenni_min": 3.5}, "record": {"wife_rating": 3.5}, "match": true},
    {"why": "unrated never passes a minimum", "filters": {"pepe_min": 0.5}, "record": {"my_rating": 0}, "match": false},
    {"why": "a null rating is unrated", "filters": {"jenni_min": 1}, "record": {"wife_rating": null}, "match": false},
    {"why": "place ignores case", "filters": {"places": ["Tracks"]}, "record": {"bought_where": "tracks"}, "match": true},
    {"why": "bought range compares the calendar day", "filters": {"bought_from": "2024-01-01", "bought_to": "2024-01-31"}, "record": {"bought_date": "2024-01-31T18:20:00"}, "match": true},
    {"why": "same day both ends is an exact date", "filters": {"bought_from": "2024-01-31", "bought_to": "2024-01-31"}, "record": {"bought_date": "2024-01-31"}, "match": true},
    {"why": "the day after is out", "filters": {"bought_from": "2024-01-31", "bought_to": "2024-01-31"}, "record": {"bought_date": "2024-02-01"}, "match": false},
    {"why": "no purchase date is out once a bound is set", "filters": {"bought_from": "2024-01-01"}, "record": {"bought_date": ""}, "match": false},
    {"why": "filters combine with and", "filters": {"genres": ["Rock"], "year_from": 1980}, "record": {"genre": "Rock", "year": "1975"}, "match": false}
  ],
  "names": [
    {"filters": {"liked": true}, "name": "Zucoloto Vinyl — Liked"},
    {"filters": {"liked": false}, "name": "Zucoloto Vinyl"},
    {"filters": {"liked": true, "genres": ["rock", "Jazz"], "year_from": 1970, "year_to": 1979}, "name": "Zucoloto Vinyl — Liked · Jazz, rock · 1970–1979"},
    {"filters": {"liked": false, "year_from": 1990}, "name": "Zucoloto Vinyl · ≥1990"},
    {"filters": {"liked": false, "year_to": 1965}, "name": "Zucoloto Vinyl · ≤1965"},
    {"filters": {"liked": true, "pepe_min": 4, "jenni_min": 3.5, "rating_mode": "or"}, "name": "Zucoloto Vinyl — Liked · Pepe ≥4 or Jenni ≥3.5"},
    {"filters": {"liked": false, "places": ["Tracks"], "bought_from": "2024-01-01", "bought_to": "2024-06-30"}, "name": "Zucoloto Vinyl · Tracks · bought 2024-01-01–2024-06-30"},
    {"filters": {"liked": false, "bought_from": "2024-01-31", "bought_to": "2024-01-31"}, "name": "Zucoloto Vinyl · bought 2024-01-31"}
  ]
}
```

- [ ] **Step 2: Write the failing tests**

`tests/test_playlist_filters.py`:

```python
"""The playlist filter rules. The shared fixture is also run by the JS twin
(tests/test_playlist_filters.js), so a case added there pins both languages."""

import json

import pytest

import playlist_filters as pf
from conftest import FIXTURES

CASES = json.loads((FIXTURES / "playlist_filter_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES["match"], ids=[c["why"] for c in CASES["match"]])
def test_shared_match_cases(case):
    f = pf.normalize_filters(case["filters"])
    assert bool(pf.select([case["record"]], f)) is case["match"]


@pytest.mark.parametrize("case", CASES["names"], ids=[c["name"] for c in CASES["names"]])
def test_shared_name_cases(case):
    assert pf.suggest_name(pf.normalize_filters(case["filters"])) == case["name"]


def test_liked_defaults_to_true_and_empties_are_dropped():
    assert pf.normalize_filters({"year_from": "", "genres": [], "places": [" "],
                                 "pepe_min": None, "bought_to": ""}) == {"liked": True}
    assert pf.normalize_filters(None) == {"liked": True}


def test_rating_mode_only_with_both_minimums():
    assert "rating_mode" not in pf.normalize_filters({"pepe_min": 4, "rating_mode": "or"})
    assert pf.normalize_filters({"pepe_min": 4, "jenni_min": 4})["rating_mode"] == "and"


def test_key_ignores_order_case_and_spacing():
    a = pf.normalize_filters({"genres": ["Rock", "jazz"], "places": ["Tracks"]})
    b = pf.normalize_filters({"genres": [" JAZZ ", "rock", "Rock"], "places": ["tracks"]})
    assert pf.filter_key(a) == pf.filter_key(b)


def test_key_tells_liked_from_every_track():
    assert pf.filter_key(pf.normalize_filters({})) != \
           pf.filter_key(pf.normalize_filters({"liked": False}))


def test_key_does_not_care_about_number_spelling():
    assert pf.filter_key(pf.normalize_filters({"year_from": "1970", "pepe_min": "4"})) == \
           pf.filter_key(pf.normalize_filters({"year_from": 1970, "pepe_min": 4.0}))


@pytest.mark.parametrize("raw, field", [
    ({"year_from": "seventies"}, "year_from"),
    ({"year_to": 99}, "year_to"),
    ({"pepe_min": 6}, "pepe_min"),
    ({"jenni_min": 3.3}, "jenni_min"),
    ({"bought_from": "2024-13-01"}, "bought_from"),
    ({"bought_to": "yesterday"}, "bought_to"),
    ({"rating_mode": "xor", "pepe_min": 1, "jenni_min": 1}, "rating_mode"),
    ({"liked": "yes"}, "liked"),
    ({"genres": {"a": 1}}, "genres"),
])
def test_invalid_values_name_their_field(raw, field):
    with pytest.raises(pf.FilterError) as e:
        pf.normalize_filters(raw)
    assert e.value.field == field


def test_long_names_are_cut_to_100_with_an_ellipsis():
    f = pf.normalize_filters({"genres": [f"Genre number {i}" for i in range(20)]})
    name = pf.suggest_name(f)
    # <= because the cut drops a trailing space before the ellipsis.
    assert len(name) <= 100 and name.endswith("…")


def test_describe_says_what_is_in_it():
    assert pf.describe(pf.normalize_filters({})) == "liked songs · whole collection"
    assert pf.describe(pf.normalize_filters({"liked": False, "year_from": 1970, "year_to": 1979})) \
        == "every track · 1970–1979"


def test_select_keeps_order():
    recs = [{"year": "1971"}, {"year": "1990"}, {"year": "1975"}]
    assert pf.select(recs, pf.normalize_filters({"year_to": 1980})) == [recs[0], recs[2]]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 -m pytest -q tests/test_playlist_filters.py`
Expected: collection error, `ModuleNotFoundError: No module named 'playlist_filters'`

- [ ] **Step 4: Implement `playlist_filters.py`**

```python
"""Which records a filtered Spotify playlist holds, and what to call it.

A playlist is defined by one small JSON object of filters. Everything here is
pure — no database, no Spotify — so the rules can be tested on their own and
mirrored in static/playlist_filters.js for the popup's live count. Both are
held to tests/fixtures/playlist_filter_cases.json.

Filters (all optional; absent means "does not filter"; they combine with AND):

  liked                    bool, default True — hearted songs only, else every track
  year_from, year_to       release year range, inclusive
  genres                   any of these genres
  pepe_min, jenni_min      minimum stars, 0.5–5 in halves
  rating_mode              "and" | "or" — only kept when both minimums are set
  places                   any of these bought-at places
  bought_from, bought_to   YYYY-MM-DD purchase range, inclusive

`filter_key` is what makes "same filters" mean "same playlist": two filter
sets that select the same records produce the same key, whatever the order,
casing or spacing they were typed in.
"""

import json
import re
from datetime import date

BASE_NAME = "Zucoloto Vinyl"
MAX_NAME = 100  # Spotify's limit

_YEAR = re.compile(r"\d{4}")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class FilterError(ValueError):
    """A filter value that cannot mean anything; `field` names which one."""

    def __init__(self, field, message):
        super().__init__(f"{field}: {message}")
        self.field = field


def _blank(v):
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, (list, tuple)) and not v)


def _tidy(s):
    return " ".join(str(s if s is not None else "").split())


def _fold(s):
    return _tidy(s).lower()


def _year(field, v):
    try:
        y = int(str(v).strip())
    except ValueError:
        raise FilterError(field, "must be a year") from None
    if not 1000 <= y <= 9999:
        raise FilterError(field, "must be a four-digit year")
    return y


def _stars(field, v):
    try:
        s = float(v)
    except (TypeError, ValueError):
        raise FilterError(field, "must be a number of stars") from None
    if not 0.5 <= s <= 5 or (s * 2) % 1:
        raise FilterError(field, "must be 0.5 to 5, in half stars")
    return s


def _day(field, v):
    s = str(v).strip()
    try:
        if not _DAY.match(s):
            raise ValueError
        date.fromisoformat(s)
    except ValueError:
        raise FilterError(field, "must be a date, YYYY-MM-DD") from None
    return s


def _names(field, v):
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        raise FilterError(field, "must be a list")
    seen, out = set(), []
    for x in v:
        t = _tidy(x)
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return sorted(out, key=str.lower)


def _ordered(lo, hi):
    return (hi, lo) if lo is not None and hi is not None and lo > hi else (lo, hi)


def normalize_filters(raw):
    """The canonical form of a filter object. Raises FilterError on a bad value."""
    raw = raw or {}
    if not isinstance(raw, dict):
        raise FilterError("filters", "must be an object")

    liked = raw.get("liked", True)
    if not isinstance(liked, bool):
        raise FilterError("liked", "must be true or false")
    f = {"liked": liked}

    lo = None if _blank(raw.get("year_from")) else _year("year_from", raw["year_from"])
    hi = None if _blank(raw.get("year_to")) else _year("year_to", raw["year_to"])
    lo, hi = _ordered(lo, hi)
    if lo is not None:
        f["year_from"] = lo
    if hi is not None:
        f["year_to"] = hi

    for field in ("genres", "places"):
        if not _blank(raw.get(field)):
            names = _names(field, raw[field])
            if names:
                f[field] = names

    for field in ("pepe_min", "jenni_min"):
        if not _blank(raw.get(field)):
            f[field] = _stars(field, raw[field])
    if "pepe_min" in f and "jenni_min" in f:
        mode = raw.get("rating_mode") or "and"
        if mode not in ("and", "or"):
            raise FilterError("rating_mode", "must be and or or")
        f["rating_mode"] = mode

    lo = None if _blank(raw.get("bought_from")) else _day("bought_from", raw["bought_from"])
    hi = None if _blank(raw.get("bought_to")) else _day("bought_to", raw["bought_to"])
    lo, hi = _ordered(lo, hi)
    if lo is not None:
        f["bought_from"] = lo
    if hi is not None:
        f["bought_to"] = hi
    return f


def filter_key(filters):
    """A string equal for every filter set that selects the same records."""
    keyed = {k: ([x.lower() for x in v] if isinstance(v, list) else v)
             for k, v in filters.items()}
    return json.dumps(keyed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _num(x):
    return str(int(x)) if float(x).is_integer() else str(x)


def _span(lo, hi):
    if lo is not None and hi is not None:
        return str(lo) if lo == hi else f"{lo}–{hi}"
    return f"≥{lo}" if lo is not None else f"≤{hi}"


def _parts(f):
    out = []
    if f.get("genres"):
        out.append(", ".join(f["genres"]))
    if "year_from" in f or "year_to" in f:
        out.append(_span(f.get("year_from"), f.get("year_to")))
    ratings = []
    if "pepe_min" in f:
        ratings.append(f"Pepe ≥{_num(f['pepe_min'])}")
    if "jenni_min" in f:
        ratings.append(f"Jenni ≥{_num(f['jenni_min'])}")
    if ratings:
        out.append((" or " if f.get("rating_mode") == "or" else " and ").join(ratings))
    if f.get("places"):
        out.append(", ".join(f["places"]))
    if "bought_from" in f or "bought_to" in f:
        out.append("bought " + _span(f.get("bought_from"), f.get("bought_to")))
    return out


def suggest_name(filters):
    name = " · ".join([BASE_NAME + (" — Liked" if filters.get("liked", True) else "")]
                      + _parts(filters))
    return name if len(name) <= MAX_NAME else name[:MAX_NAME - 1].rstrip() + "…"


def describe(filters):
    """The one-line summary under a saved playlist's name."""
    parts = _parts(filters) or ["whole collection"]
    return " · ".join(["liked songs" if filters.get("liked", True) else "every track"] + parts)


def record_year(value):
    m = _YEAR.search(str(value or ""))
    return int(m.group()) if m else None


def _matches(r, f):
    if "year_from" in f or "year_to" in f:
        y = record_year(r.get("year"))
        if y is None or y < f.get("year_from", y) or y > f.get("year_to", y):
            return False
    if f.get("genres") and _fold(r.get("genre")) not in {g.lower() for g in f["genres"]}:
        return False
    checks = []
    if "pepe_min" in f:
        checks.append((r.get("my_rating") or 0) >= f["pepe_min"])
    if "jenni_min" in f:
        checks.append((r.get("wife_rating") or 0) >= f["jenni_min"])
    if checks and not (any(checks) if f.get("rating_mode") == "or" else all(checks)):
        return False
    if f.get("places") and _fold(r.get("bought_where")) not in {p.lower() for p in f["places"]}:
        return False
    if "bought_from" in f or "bought_to" in f:
        d = str(r.get("bought_date") or "")[:10]
        if not _DAY.match(d):
            return False
        if d < f.get("bought_from", d) or d > f.get("bought_to", d):
            return False
    return True


def select(records, filters):
    """The records the record-level filters keep, in their original order.

    `liked` is not applied here: whether a record has a hearted song that is
    also on Spotify is spotify_sync.desired_tracks' business.
    """
    return [r for r in records if _matches(r, filters)]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest -q tests/test_playlist_filters.py`
Expected: all pass (22 match cases, 8 name cases, the rest).

- [ ] **Step 6: Commit**

```bash
git add playlist_filters.py tests/fixtures/playlist_filter_cases.json tests/test_playlist_filters.py
git commit -m "feat: playlist filter rules with a shared case fixture"
```

---

### Task 2: Sync into a saved playlist; delete one

**Files:**
- Modify: `spotify_sync.py` (module docstring, remove `PLAYLISTS` at :40-49, `desired_tracks` at :261, replace `find_or_create_playlist` and `sync` at :322-379)
- Test: `tests/test_spotify_playlists.py` (FakeSpotify, existing sync tests)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `desired_tracks(client, records, liked: bool, cache, deadline=None) -> (uris, report)` — report unchanged: `{"records", "bad_links": [{label, cover_url}], "unmatched": [{label, cover_url, songs}]}`
  - `sync(client, records, liked: bool, cache, *, name: str, spotify_id: str | None = None, adopt_by_name: bool = False, deadline=None) -> dict` with keys `spotify_id, name, url, created, total, added, removed, records, bad_links, unmatched`
  - `delete_playlist(client, spotify_id: str) -> None`
  - `playlist_url(spotify_id: str) -> str`

- [ ] **Step 1: Teach FakeSpotify 404s and the followers endpoint**

In `tests/test_spotify_playlists.py`, in `FakeSpotify.request`, replace the `if path.startswith("/playlists/"):` block's first lines:

```python
        if path.startswith("/playlists/"):
            pid = path.split("/")[2].split("?")[0]
            if pid not in self.playlists:
                return _Response(404, {"error": {"status": 404}})
            pl = self.playlists[pid]
            if path.startswith(f"/playlists/{pid}/followers") and method == "DELETE":
                del self.playlists[pid]
                return _Response(200)
            assert "/items" in path, f"used a removed endpoint: {method} {path}"
```

(`_Response(200)` has no body; `Client.call` returns `{}` for an empty body.)

- [ ] **Step 2: Move the existing sync tests to the new signature, and add the new ones**

Mechanical rewrite in `tests/test_spotify_playlists.py`, every call to `spotify_sync.sync(...)` above the `# ── routes` line:
- `..., "all", DictCache()` → `..., False, DictCache(), name="Every"`
- `..., "liked", DictCache()` → `..., True, DictCache(), name="Zucoloto Vinyl Collection — Liked"`
- `..., "all",\n cache, deadline=...` → `..., False,\n cache, name="Every", deadline=...`

`test_liked_playlist_holds_only_liked_songs` keeps its `pl["name"]` assertion working because the name is now passed in.

Then append above `# ── routes`:

```python
def test_a_new_playlist_is_created_once_and_its_id_returned(fake):
    result = spotify_sync.sync(spotify_sync.Client("RT"), [rec("ALB1")], False, DictCache(),
                               name="Mine")
    assert result["created"] is True
    assert fake.playlists[result["spotify_id"]]["name"] == "Mine"
    assert result["url"] == f"https://open.spotify.com/playlist/{result['spotify_id']}"

    again = spotify_sync.sync(spotify_sync.Client("RT"), [rec("ALB1")], False, DictCache(),
                              name="Mine", spotify_id=result["spotify_id"])
    assert again["created"] is False and len(fake.playlists) == 1


def test_a_playlist_deleted_on_spotify_is_recreated(fake):
    result = spotify_sync.sync(spotify_sync.Client("RT"), [rec("ALB1")], False, DictCache(),
                               name="Mine", spotify_id="GONE")
    assert result["created"] is True and result["spotify_id"] != "GONE"
    assert fake.playlists[result["spotify_id"]]["uris"]


def test_legacy_rows_adopt_the_playlist_already_on_spotify(fake):
    fake.playlists["OLD"] = {"name": "Zucoloto Vinyl Collection", "uris": []}
    result = spotify_sync.sync(spotify_sync.Client("RT"), [rec("ALB1")], False, DictCache(),
                               name="Zucoloto Vinyl Collection", adopt_by_name=True)
    assert (result["spotify_id"], result["created"]) == ("OLD", False)
    assert len(fake.playlists) == 1


def test_without_adopt_a_same_named_playlist_is_left_alone(fake):
    fake.playlists["THEIRS"] = {"name": "Mine", "uris": ["spotify:track:keep"]}
    result = spotify_sync.sync(spotify_sync.Client("RT"), [rec("ALB1")], False, DictCache(),
                               name="Mine")
    assert result["spotify_id"] != "THEIRS"
    assert fake.playlists["THEIRS"]["uris"] == ["spotify:track:keep"]


def test_delete_unfollows_and_a_missing_one_counts_as_gone(fake):
    fake.playlists["PL9"] = {"name": "x", "uris": []}
    spotify_sync.delete_playlist(spotify_sync.Client("RT"), "PL9")
    assert "PL9" not in fake.playlists
    assert ("DELETE", "/playlists/PL9/followers") in fake.calls
    spotify_sync.delete_playlist(spotify_sync.Client("RT"), "PL9")  # no raise
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 -m pytest -q tests/test_spotify_playlists.py -k "not route and not visitors and not callback and not connect and not kind"`
Expected: FAIL — `TypeError: sync() got an unexpected keyword argument 'name'` and `AttributeError: ... 'delete_playlist'`.

- [ ] **Step 4: Implement**

In `spotify_sync.py`:

1. Replace the second paragraph of the module docstring ("Two playlists, each a pure function…" through "…are taken out.") with:

```
Each playlist is a pure function of the collection: the caller picks the
records (playlist_filters.select) and says whether only hearted songs count.
A sync makes the playlist match that list exactly: missing tracks are
appended (so new records land at the end), and tracks that no longer qualify
— an unliked song, a removed link, a sold record — are taken out.
```

2. Delete the `PLAYLISTS = {...}` constant. Add in its place:

```python
DESCRIPTION = "Made from the Zucoloto vinyl collection."
```

3. In `desired_tracks`, change the signature and the two `kind` uses:

```python
def desired_tracks(client, records, liked, cache, deadline=None):
```

docstring line "`records` are dicts with…" stays; replace

```python
    if kind == "liked":
        records = [r for r in records if any(t.get("liked_at") for t in r.get("tracks") or [])]
```
with
```python
    if liked:
        records = [r for r in records if any(t.get("liked_at") for t in r.get("tracks") or [])]
```
and `if kind == "all":` with `if not liked:`.

4. Replace `find_or_create_playlist` with:

```python
def playlist_url(spotify_id):
    return f"https://open.spotify.com/playlist/{spotify_id}"


def _owned_by_name(client, name):
    """The owner's playlist called `name`, or None. Only legacy rows ask this."""
    me = client.call("GET", "/me")
    for p in client.pages("/me/playlists?limit=50"):
        if p and p.get("name") == name and (p.get("owner") or {}).get("id") == me.get("id"):
            return p["id"]
    return None


def _create(client, name):
    return client.call("POST", "/me/playlists", json={
        "name": name, "description": DESCRIPTION, "public": False})["id"]


def delete_playlist(client, spotify_id):
    """Delete the owner's playlist — on Spotify that is unfollowing it. Gone already is fine."""
    try:
        client.call("DELETE", f"/playlists/{spotify_id}/followers")
    except SpotifyError as e:
        if e.status != 404:
            raise
```

5. Replace `sync` with:

```python
def sync(client, records, liked, cache, *, name, spotify_id=None, adopt_by_name=False,
         deadline=None):
    """Read the albums, then bring the playlist in line. Raises Incomplete first if out of time.

    `spotify_id` is the playlist this app made last time; a playlist deleted on
    Spotify since answers 404 and is made again. `adopt_by_name` is for the two
    playlists made before ids were stored: they are found by name, once.
    """
    desired, report = desired_tracks(client, records, liked, cache, deadline)
    if not spotify_id and adopt_by_name:
        spotify_id = _owned_by_name(client, name)
    created = False
    counts = None
    if spotify_id:
        try:
            counts = mirror(client, spotify_id, desired)
        except SpotifyError as e:
            if e.status != 404:
                raise
    if counts is None:
        spotify_id = _create(client, name)
        created = True
        counts = mirror(client, spotify_id, desired)
    added, removed = counts
    return {
        "spotify_id": spotify_id,
        "name": name,
        "url": playlist_url(spotify_id),
        "created": created,
        "total": len(desired),
        "added": added,
        "removed": removed,
        **report,
    }
```

- [ ] **Step 5: Run the sync tests to verify they pass**

Run: `python3 -m pytest -q tests/test_spotify_playlists.py -k "not route and not visitors and not callback and not connect and not kind"`
Expected: PASS. (The route tests still use the old routes and fail until Task 3.)

- [ ] **Step 6: Commit**

```bash
git add spotify_sync.py tests/test_spotify_playlists.py
git commit -m "feat: sync into a stored playlist id, recreate when gone, delete"
```

---

### Task 3: SpotifyPlaylist table, legacy seed, routes

**Files:**
- Modify: `app.py` — import (:18-21), model after `SpotifyAlbumCache` (:552-554), startup block (:556-557 and before `_sweep_note_images()`), `spotify_account` (:1843-1853), `_playlist_records` (:1918-1934), replace `spotify_sync_playlist` (:1937-1962)
- Test: `tests/test_spotify_playlists.py` (routes section)

**Interfaces:**
- Consumes: `playlist_filters.normalize_filters, filter_key, suggest_name, describe, select, FilterError` (Task 1); `spotify_sync.sync(..., name=, spotify_id=, adopt_by_name=, deadline=)`, `delete_playlist`, `playlist_url` (Task 2).
- Produces (HTTP, used by Task 5):
  - `GET /api/spotify/playlists` → `{"playlists": [P], "genres": [str], "places": [str]}`
  - `POST /api/spotify/playlists` body `{"filters": {...}, "name": "..."}` → `201 {"playlist": P, "existed": false}` or `200 {"playlist": P, "existed": true}`; `400 {"error", "field"}`
  - `POST /api/spotify/playlists/<id>/sync` → `202 {"incomplete", "done", "total"}` | `200 {...sync result, "playlist": P}` | `409 {"connect": true}` | `404`
  - `DELETE /api/spotify/playlists/<id>` → `200 {"ok": true}` | `409` | `502 {"error"}` | `404`
  - where `P = {"id", "name", "filters", "summary", "url", "last_synced_at", "last_total", "last_records"}` (`url` is `""` before the first sync)
  - `GET /api/spotify/account` no longer has `playlists`.

- [ ] **Step 1: Rewrite the route tests**

In `tests/test_spotify_playlists.py`, routes section:

Replace the `client` fixture's cleanup so it also clears playlists:

```python
@pytest.fixture
def client():
    import app as app_module
    with app_module.app.app_context():
        app_module.SpotifyPlaylist.query.delete()
        app_module.SpotifyAccount.query.delete()
        app_module.SpotifyAlbumCache.query.delete()
        app_module.Record.query.delete()
        app_module.db.session.commit()
    c = app_module.app.test_client()
    with c.session_transaction() as s:
        s["authed"] = True
    return c
```

Replace `_connect` so the owned record has fields the filters read:

```python
def _connect(app_module):
    with app_module.app.app_context():
        app_module.db.session.add(app_module.SpotifyAccount(id=1, refresh_token="RT",
                                                            display_name="Me"))
        app_module.db.session.add(app_module.Record(
            artist="A", album_name="One", have_it=True, year="1973", genre="Rock",
            bought_where="Tracks", spotify_url="https://open.spotify.com/album/ALB1"))
        app_module.db.session.add(app_module.Record(
            artist="A", album_name="Two", have_it=True, year="1991", genre="Jazz",
            spotify_url="https://open.spotify.com/album/ALB2"))
        app_module.db.session.add(app_module.Record(
            artist="A", album_name="Wish", have_it=False, year="1973", genre="Rock",
            spotify_url="https://open.spotify.com/album/ALB2"))
        app_module.db.session.commit()


def _create(client, filters, name=None):
    body = {"filters": filters}
    if name is not None:
        body["name"] = name
    return client.post("/api/spotify/playlists", json=body)
```

Delete `test_unknown_playlist_kind_is_404`, `test_sync_route_mirrors_owned_records_only_and_caches_albums`, `test_sync_route_reports_progress_when_out_of_time`. In `test_visitors_cannot_sync_or_connect` replace the first assertion with:

```python
    assert c.post("/api/spotify/playlists/1/sync").status_code == 401
    assert c.get("/api/spotify/playlists").status_code == 401
    assert c.post("/api/spotify/playlists", json={"filters": {}}).status_code == 401
    assert c.delete("/api/spotify/playlists/1").status_code == 401
```

Replace `test_sync_without_a_login_asks_to_connect` with:

```python
def test_sync_without_a_login_asks_to_connect(client):
    pid = _create(client, {}).get_json()["playlist"]["id"]
    r = client.post(f"/api/spotify/playlists/{pid}/sync")
    assert r.status_code == 409 and r.get_json()["connect"] is True
```

Append:

```python
def test_unknown_playlist_is_404(client):
    assert client.post("/api/spotify/playlists/999/sync").status_code == 404
    assert client.delete("/api/spotify/playlists/999").status_code == 404


def test_create_lists_and_suggests_a_name(client):
    import app as app_module
    _connect(app_module)
    r = _create(client, {"genres": ["Rock"]})
    assert r.status_code == 201 and r.get_json()["existed"] is False
    p = r.get_json()["playlist"]
    assert p["name"] == "Zucoloto Vinyl — Liked · Rock"
    assert p["summary"] == "liked songs · Rock"
    assert p["url"] == "" and p["last_synced_at"] is None
    d = client.get("/api/spotify/playlists").get_json()
    assert [x["id"] for x in d["playlists"]] == [p["id"]]
    assert d["genres"] == ["Jazz", "Rock"] and d["places"] == ["Tracks"]


def test_the_same_filters_return_the_existing_playlist(client):
    first = _create(client, {"genres": ["Rock", "jazz"]}, name="Mine").get_json()["playlist"]
    again = _create(client, {"genres": [" JAZZ ", "rock"]}, name="Other name")
    assert again.status_code == 200 and again.get_json()["existed"] is True
    assert again.get_json()["playlist"]["id"] == first["id"]
    assert again.get_json()["playlist"]["name"] == "Mine"


def test_a_race_on_the_unique_key_still_returns_one_row(client, monkeypatch):
    import app as app_module
    first = _create(client, {"year_from": 1970}).get_json()["playlist"]
    # The second request's lookup misses (as if it ran before the first commit),
    # so only the unique constraint stands between it and a duplicate.
    real = app_module._playlist_by_key
    calls = {"n": 0}

    def miss_once(key):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(key)
    monkeypatch.setattr(app_module, "_playlist_by_key", miss_once)
    r = _create(client, {"year_from": 1970})
    assert r.get_json()["existed"] is True and r.get_json()["playlist"]["id"] == first["id"]
    with app_module.app.app_context():
        assert app_module.SpotifyPlaylist.query.count() == 1


def test_a_bad_filter_is_400_with_its_field(client):
    r = _create(client, {"pepe_min": 9})
    assert r.status_code == 400 and r.get_json()["field"] == "pepe_min"


def test_a_typed_name_is_tidied_and_capped(client):
    p = _create(client, {"liked": False}, name="  My   list " + "x" * 200).get_json()["playlist"]
    assert p["name"].startswith("My list x") and len(p["name"]) == 100


def test_sync_applies_the_filters_and_stores_the_result(client, fake):
    import app as app_module
    _connect(app_module)
    pid = _create(client, {"liked": False, "year_from": 1970, "year_to": 1979}).get_json()["playlist"]["id"]
    r = client.post(f"/api/spotify/playlists/{pid}/sync")
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["created"] is True and d["total"] == 3
    uris = fake.playlists[d["spotify_id"]]["uris"]
    assert uris and all("ALB1" in u for u in uris), "the 1991 record or the wishlist got in"
    p = d["playlist"]
    assert p["url"] == d["url"] and p["last_total"] == 3 and p["last_records"] == 1
    assert p["last_synced_at"]

    fake.calls.clear()
    again = client.post(f"/api/spotify/playlists/{pid}/sync").get_json()
    assert again["created"] is False and again["spotify_id"] == d["spotify_id"]
    assert not any(path.startswith("/albums/") for _, path in fake.calls), "album was re-read"


def test_sync_reports_progress_when_out_of_time(client, fake, monkeypatch):
    import app as app_module
    _connect(app_module)
    monkeypatch.setattr(app_module, "_SPOTIFY_READ_BUDGET", -1)
    pid = _create(client, {"liked": False}).get_json()["playlist"]["id"]
    r = client.post(f"/api/spotify/playlists/{pid}/sync")
    assert r.status_code == 202
    assert r.get_json() == {"incomplete": True, "done": 0, "total": 2}


def test_delete_removes_it_on_spotify_and_here(client, fake):
    import app as app_module
    _connect(app_module)
    pid = _create(client, {"liked": False}).get_json()["playlist"]["id"]
    sid = client.post(f"/api/spotify/playlists/{pid}/sync").get_json()["spotify_id"]
    assert client.delete(f"/api/spotify/playlists/{pid}").status_code == 200
    assert sid not in fake.playlists
    assert client.get("/api/spotify/playlists").get_json()["playlists"] == []


def test_deleting_a_never_synced_playlist_needs_no_spotify(client):
    pid = _create(client, {}).get_json()["playlist"]["id"]
    assert client.delete(f"/api/spotify/playlists/{pid}").status_code == 200


def test_a_spotify_failure_on_delete_keeps_the_row(client, fake):
    import app as app_module
    _connect(app_module)
    pid = _create(client, {"liked": False}).get_json()["playlist"]["id"]
    client.post(f"/api/spotify/playlists/{pid}/sync")
    with patch.object(spotify_sync, "delete_playlist",
                      side_effect=spotify_sync.SpotifyError("Spotify returned 500", status=500)):
        r = client.delete(f"/api/spotify/playlists/{pid}")
    assert r.status_code == 502
    assert len(client.get("/api/spotify/playlists").get_json()["playlists"]) == 1


def test_legacy_seed_adopts_the_playlist_already_on_spotify(client, fake):
    import app as app_module
    _connect(app_module)
    fake.playlists["OLD"] = {"name": "Zucoloto Vinyl Collection", "uris": []}
    with app_module.app.app_context():
        app_module._seed_legacy_playlists()
        app_module._seed_legacy_playlists()  # idempotent
    rows = client.get("/api/spotify/playlists").get_json()["playlists"]
    assert [r["name"] for r in rows] == ["Zucoloto Vinyl Collection",
                                         "Zucoloto Vinyl Collection — Liked"]
    assert [r["filters"]["liked"] for r in rows] == [False, True]
    d = client.post(f"/api/spotify/playlists/{rows[0]['id']}/sync").get_json()
    assert (d["spotify_id"], d["created"]) == ("OLD", False)
    # Adopted once: from now on it is found by id, never by name.
    with app_module.app.app_context():
        assert app_module.db.session.get(app_module.SpotifyPlaylist, rows[0]["id"]).legacy is False


def test_account_no_longer_lists_fixed_playlists(client):
    assert "playlists" not in client.get("/api/spotify/account").get_json()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest -q tests/test_spotify_playlists.py`
Expected: FAIL — `AttributeError: module 'app' has no attribute 'SpotifyPlaylist'`.

- [ ] **Step 3: Implement — model and seed**

In `app.py`:

1. Imports: next to `import spotify_sync` add `import playlist_filters`, and extend the sqlalchemy import line to `from sqlalchemy import func` + a new line `from sqlalchemy.exc import IntegrityError`.

2. After `class SpotifyAlbumCache` add:

```python
# A playlist this app made on the owner's Spotify, and the filters that define
# it (see playlist_filters.py). filter_key is unique: asking for the same
# filters again finds this row and resyncs it instead of making a second
# playlist. spotify_id stays null until the first sync creates it there.
# legacy marks the two fixed playlists from before this table: they were made
# without storing an id, so their first sync looks them up by name, once.
class SpotifyPlaylist(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    spotify_id     = db.Column(db.String(64))
    name           = db.Column(db.String(100), nullable=False)
    filters        = db.Column(db.Text, nullable=False)
    filter_key     = db.Column(db.Text, nullable=False, unique=True)
    legacy         = db.Column(db.Boolean, default=False, nullable=False)
    created_at     = db.Column(db.String(50))
    last_synced_at = db.Column(db.String(50))
    last_total     = db.Column(db.Integer)
    last_records   = db.Column(db.Integer)

    def to_dict(self):
        f = json.loads(self.filters)
        return {
            "id": self.id,
            "name": self.name,
            "filters": f,
            "summary": playlist_filters.describe(f),
            "url": spotify_sync.playlist_url(self.spotify_id) if self.spotify_id else "",
            "last_synced_at": self.last_synced_at,
            "last_total": self.last_total,
            "last_records": self.last_records,
        }


_LEGACY_PLAYLISTS = (
    ("Zucoloto Vinyl Collection", {"liked": False}),
    ("Zucoloto Vinyl Collection — Liked", {"liked": True}),
)


def _seed_legacy_playlists():
    """The two playlists the app synced before filters existed, as saved rows."""
    for name, raw in _LEGACY_PLAYLISTS:
        f = playlist_filters.normalize_filters(raw)
        key = playlist_filters.filter_key(f)
        if SpotifyPlaylist.query.filter_by(filter_key=key).first() is None:
            db.session.add(SpotifyPlaylist(
                name=name, filters=json.dumps(f), filter_key=key, legacy=True,
                created_at=datetime.now().strftime("%Y-%m-%dT%H:%M:%S")))
    db.session.commit()
```

3. Startup block — change its first two lines to

```python
with app.app_context():
    from sqlalchemy import inspect, text
    # Seeded only when the table is new, so deleting both legacy playlists
    # does not bring them back on the next deploy.
    new_playlist_table = not inspect(db.engine).has_table("spotify_playlist")
    db.create_all()
```

and remove the now-duplicate `from sqlalchemy import inspect, text` line a few lines below. Just before `_sweep_note_images()` add:

```python
    if new_playlist_table:
        _seed_legacy_playlists()
```

- [ ] **Step 4: Implement — records, account, routes**

1. `spotify_account`: delete the line `"playlists": {k: v["name"] for k, v in spotify_sync.PLAYLISTS.items()},`.

2. `_playlist_records` — query and dict gain the filter fields:

```python
    rows = (db.session.query(Record.id, Record.cover_hash, Record.artist, Record.album_name,
                             Record.spotify_url, Record.tracks, Record.year, Record.genre,
                             Record.my_rating, Record.wife_rating, Record.bought_where,
                             Record.bought_date)
            .filter(Record.have_it.is_(True),
                    Record.spotify_url.isnot(None), Record.spotify_url != "")
            .order_by(Record.bought_date, Record.id).all())
    out = []
    for (rid, cover_hash, artist, album, link, tracks, year, genre,
         my_rating, wife_rating, bought_where, bought_date) in rows:
        try:
            parsed = json.loads(tracks) if tracks else []
        except ValueError:
            parsed = []
        out.append({"artist": artist, "album_name": album, "spotify_url": link,
                    # Same URL Record.to_dict hands out, so the skipped list can show it.
                    "cover_url": f"/api/records/{rid}/cover?v={cover_hash}" if cover_hash else "",
                    "tracks": parsed if isinstance(parsed, list) else [],
                    "year": year, "genre": genre, "my_rating": my_rating,
                    "wife_rating": wife_rating, "bought_where": bought_where,
                    "bought_date": bought_date})
    return out
```

3. Replace the whole `spotify_sync_playlist` route (decorators included) with:

```python
def _spotify_client(acct):
    def rotated(token):
        acct.refresh_token = token
        db.session.commit()
    return spotify_sync.Client(acct.refresh_token, on_new_refresh_token=rotated)


def _login_expired(acct):
    db.session.delete(acct)
    db.session.commit()
    return jsonify({"error": "Spotify login expired — connect again", "connect": True}), 409


def _not_connected():
    return jsonify({"error": "Spotify is not connected", "connect": True}), 409


def _playlist_or_404(pid):
    row = db.session.get(SpotifyPlaylist, pid)
    if row is None:
        raise NotFound()
    return row


def _playlist_by_key(key):
    return SpotifyPlaylist.query.filter_by(filter_key=key).first()


def _distinct_names(column):
    """Non-empty values of a Record column among owned records, one per spelling-insensitive name."""
    seen = {}
    for (v,) in db.session.query(column).filter(Record.have_it.is_(True)).distinct().all():
        t = " ".join((v or "").split())
        if t and t.lower() not in seen:
            seen[t.lower()] = t
    return sorted(seen.values(), key=str.lower)


@app.route("/api/spotify/playlists")
@require_auth
def spotify_playlists():
    rows = SpotifyPlaylist.query.order_by(SpotifyPlaylist.id).all()
    return jsonify({"playlists": [r.to_dict() for r in rows],
                    "genres": _distinct_names(Record.genre),
                    "places": _distinct_names(Record.bought_where)})


@app.route("/api/spotify/playlists", methods=["POST"])
@require_auth
def spotify_create_playlist():
    d = request.get_json(silent=True) or {}
    try:
        f = playlist_filters.normalize_filters(d.get("filters"))
    except playlist_filters.FilterError as e:
        return jsonify({"error": str(e), "field": e.field}), 400
    key = playlist_filters.filter_key(f)
    row = _playlist_by_key(key)
    if row:
        return jsonify({"playlist": row.to_dict(), "existed": True})
    name = " ".join(str(d.get("name") or "").split())[:playlist_filters.MAX_NAME]
    row = SpotifyPlaylist(name=name or playlist_filters.suggest_name(f),
                          filters=json.dumps(f), filter_key=key,
                          created_at=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
    db.session.add(row)
    try:
        db.session.commit()
    except IntegrityError:
        # A second click raced the first: its row won the unique key.
        db.session.rollback()
        return jsonify({"playlist": SpotifyPlaylist.query.filter_by(filter_key=key).first().to_dict(),
                        "existed": True})
    return jsonify({"playlist": row.to_dict(), "existed": False}), 201


@app.route("/api/spotify/playlists/<int:pid>/sync", methods=["POST"])
@require_auth
def spotify_sync_playlist(pid):
    row = _playlist_or_404(pid)
    acct = _spotify_account()
    if not acct or not acct.refresh_token:
        return _not_connected()
    f = json.loads(row.filters)
    records = playlist_filters.select(_playlist_records(), f)
    deadline = time.monotonic() + _SPOTIFY_READ_BUDGET
    try:
        result = spotify_sync.sync(_spotify_client(acct), records, f.get("liked", True),
                                   _AlbumCache(), name=row.name, spotify_id=row.spotify_id,
                                   adopt_by_name=bool(row.legacy), deadline=deadline)
    except spotify_sync.Incomplete as e:
        return jsonify({"incomplete": True, "done": e.done, "total": e.total}), 202
    except spotify_sync.NotConnected:
        return _login_expired(acct)
    except (spotify_sync.SpotifyError, requests.RequestException) as e:
        app.logger.warning("Spotify playlist sync failed", exc_info=True)
        return jsonify({"error": str(e)}), 502
    row.spotify_id = result["spotify_id"]
    row.legacy = False
    row.last_synced_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    row.last_total = result["total"]
    row.last_records = result["records"]
    db.session.commit()
    return jsonify({**result, "playlist": row.to_dict()})


@app.route("/api/spotify/playlists/<int:pid>", methods=["DELETE"])
@require_auth
def spotify_delete_playlist(pid):
    row = _playlist_or_404(pid)
    if row.spotify_id:
        acct = _spotify_account()
        if not acct or not acct.refresh_token:
            return _not_connected()
        try:
            spotify_sync.delete_playlist(_spotify_client(acct), row.spotify_id)
        except spotify_sync.NotConnected:
            return _login_expired(acct)
        except (spotify_sync.SpotifyError, requests.RequestException) as e:
            app.logger.warning("Spotify playlist delete failed", exc_info=True)
            return jsonify({"error": str(e)}), 502
    db.session.delete(row)
    db.session.commit()
    return jsonify({"ok": True})
```

Note: `test_a_race_on_the_unique_key_still_returns_one_row` patches `_playlist_by_key` to miss once; the IntegrityError branch then reads the row with a direct query (not through `_playlist_by_key`), which is why the fallback does not call the helper.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest -q tests/test_spotify_playlists.py tests/test_playlist_filters.py`
Expected: PASS.

- [ ] **Step 6: Run the whole Python suite**

Run: `python3 -m pytest -q`
Expected: PASS except `tests/test_playlists_dom.py` (the page still calls the old routes; fixed in Task 5). Anything else failing is a regression from this task — fix before committing.

- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_spotify_playlists.py
git commit -m "feat: saved Spotify playlists with filters, seeded from the two fixed ones"
```

---

### Task 4: Filter rules in the browser

**Files:**
- Create: `static/playlist_filters.js`
- Create: `tests/test_playlist_filters.js`
- Create: `tests/test_playlist_filters_js.py`
- Modify: `templates/index.html:4194` (script tag after `tracks.js`)

**Interfaces:**
- Consumes: `tests/fixtures/playlist_filter_cases.json` (Task 1).
- Produces: global `VinylPlaylistFilters` with
  - `normalize(raw) -> filters` — lenient: bad values are dropped, never thrown (the server validates)
  - `matches(record, filters) -> bool`
  - `countMatching(records, filters) -> number` — owned + Spotify link + `matches` + (liked ⇒ has a hearted song)
  - `suggestName(filters) -> string`

- [ ] **Step 1: Write the failing tests**

`tests/test_playlist_filters.js`:

```js
// The browser copy of playlist_filters.py, held to the same shared cases.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const F = require('../static/playlist_filters.js');
const CASES = JSON.parse(fs.readFileSync(
  path.join(__dirname, 'fixtures', 'playlist_filter_cases.json'), 'utf8'));

for (const c of CASES.match) {
  test('match: ' + c.why, () => {
    assert.strictEqual(F.matches(c.record, F.normalize(c.filters)), c.match);
  });
}

for (const c of CASES.names) {
  test('name: ' + c.name, () => {
    assert.strictEqual(F.suggestName(F.normalize(c.filters)), c.name);
  });
}

test('form strings become numbers and blanks disappear', () => {
  assert.deepStrictEqual(
    F.normalize({ liked: true, year_from: '1970', year_to: '', genres: [], places: [' '],
                  pepe_min: '4', jenni_min: '', bought_from: '', bought_to: '' }),
    { liked: true, year_from: 1970, pepe_min: 4 });
});

test('a bad value is dropped, not thrown', () => {
  assert.deepStrictEqual(F.normalize({ year_from: 'abc', bought_to: '2024-1-1' }), { liked: true });
});

const REC = (o) => Object.assign({ have_it: true, spotify_url: 'https://open.spotify.com/album/x',
  tracks: JSON.stringify([{ side: 'A', title: 's', liked_at: '2026-01-01' }]) }, o);

test('the count is owned records with a link that pass the filters', () => {
  const records = [
    REC({ genre: 'Rock' }),
    REC({ genre: 'Rock', have_it: false }),
    REC({ genre: 'Rock', spotify_url: '' }),
    REC({ genre: 'Jazz' }),
  ];
  assert.strictEqual(F.countMatching(records, F.normalize({ liked: false, genres: ['rock'] })), 1);
});

test('liked also needs a hearted song', () => {
  const records = [REC({}), REC({ tracks: JSON.stringify([{ side: 'A', title: 's' }]) }),
                   REC({ tracks: '' }), REC({ tracks: 'not json' })];
  assert.strictEqual(F.countMatching(records, F.normalize({ liked: true })), 1);
  assert.strictEqual(F.countMatching(records, F.normalize({ liked: false })), 4);
});
```

`tests/test_playlist_filters_js.py`:

```python
"""Run the JavaScript playlist filter rules under pytest, like tests/test_spotify_js.py."""

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_playlist_filters_js():
    result = subprocess.run(["node", "--test", "tests/test_playlist_filters.js"],
                            cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest -q tests/test_playlist_filters_js.py`
Expected: FAIL — `Cannot find module '../static/playlist_filters.js'`.

- [ ] **Step 3: Implement `static/playlist_filters.js`**

```js
/* The playlist filter rules, for the popup's live "N records match" and its
 * suggested name. playlist_filters.py is the enforcing copy — the server
 * filters and validates; this one only previews, so a bad value is dropped
 * here rather than reported. Both are held to
 * tests/fixtures/playlist_filter_cases.json.
 *
 * Loaded as a plain script in the browser, where `const VinylPlaylistFilters`
 * lands in the global lexical scope; required as a module by the tests. */

const VinylPlaylistFilters = (function () {

  const BASE = 'Zucoloto Vinyl';
  const MAX = 100;
  const DAY = /^\d{4}-\d{2}-\d{2}$/;
  const YEAR = /\d{4}/;

  const tidy = s => String(s === undefined || s === null ? '' : s).split(/\s+/).filter(Boolean).join(' ');
  const fold = s => tidy(s).toLowerCase();
  const blank = v => v === undefined || v === null || (typeof v === 'string' && !v.trim());

  function names(v) {
    const seen = new Set(), out = [];
    for (const x of (Array.isArray(v) ? v : [v])) {
      const t = tidy(x);
      if (t && !seen.has(t.toLowerCase())) { seen.add(t.toLowerCase()); out.push(t); }
    }
    return out.sort((a, b) => {
      const x = a.toLowerCase(), y = b.toLowerCase();
      return x < y ? -1 : x > y ? 1 : 0;
    });
  }

  function year(v) {
    if (blank(v) || !/^\s*\d{4}\s*$/.test(String(v))) return null;
    return parseInt(v, 10);
  }

  function stars(v) {
    if (blank(v)) return null;
    const s = Number(v);
    return Number.isFinite(s) && s >= 0.5 && s <= 5 && (s * 2) % 1 === 0 ? s : null;
  }

  function day(v) {
    if (blank(v)) return null;
    const s = String(v).trim();
    return DAY.test(s) && !isNaN(Date.parse(s)) ? s : null;
  }

  function ordered(lo, hi) {
    return lo !== null && hi !== null && lo > hi ? [hi, lo] : [lo, hi];
  }

  function normalize(raw) {
    raw = raw || {};
    const f = { liked: raw.liked !== false };
    const [yf, yt] = ordered(year(raw.year_from), year(raw.year_to));
    if (yf !== null) f.year_from = yf;
    if (yt !== null) f.year_to = yt;
    for (const k of ['genres', 'places']) {
      if (!blank(raw[k])) {
        const l = names(raw[k]);
        if (l.length) f[k] = l;
      }
    }
    const p = stars(raw.pepe_min), j = stars(raw.jenni_min);
    if (p !== null) f.pepe_min = p;
    if (j !== null) f.jenni_min = j;
    if (p !== null && j !== null) f.rating_mode = raw.rating_mode === 'or' ? 'or' : 'and';
    const [bf, bt] = ordered(day(raw.bought_from), day(raw.bought_to));
    if (bf !== null) f.bought_from = bf;
    if (bt !== null) f.bought_to = bt;
    return f;
  }

  function recordYear(v) {
    const m = YEAR.exec(String(v === undefined || v === null ? '' : v));
    return m ? parseInt(m[0], 10) : null;
  }

  function matches(r, f) {
    if ('year_from' in f || 'year_to' in f) {
      const y = recordYear(r.year);
      if (y === null) return false;
      if ('year_from' in f && y < f.year_from) return false;
      if ('year_to' in f && y > f.year_to) return false;
    }
    if (f.genres && !f.genres.some(g => g.toLowerCase() === fold(r.genre))) return false;
    const checks = [];
    if ('pepe_min' in f) checks.push((Number(r.my_rating) || 0) >= f.pepe_min);
    if ('jenni_min' in f) checks.push((Number(r.wife_rating) || 0) >= f.jenni_min);
    if (checks.length && !(f.rating_mode === 'or' ? checks.some(Boolean) : checks.every(Boolean))) return false;
    if (f.places && !f.places.some(p => p.toLowerCase() === fold(r.bought_where))) return false;
    if ('bought_from' in f || 'bought_to' in f) {
      const d = String(r.bought_date || '').slice(0, 10);
      if (!DAY.test(d)) return false;
      if ('bought_from' in f && d < f.bought_from) return false;
      if ('bought_to' in f && d > f.bought_to) return false;
    }
    return true;
  }

  function hasLiked(r) {
    let t = r.tracks;
    if (typeof t === 'string') {
      try { t = t ? JSON.parse(t) : []; } catch (e) { t = []; }
    }
    return Array.isArray(t) && t.some(s => s && s.liked_at);
  }

  function countMatching(records, f) {
    return (records || []).filter(r => r && r.have_it && tidy(r.spotify_url)
      && matches(r, f) && (!f.liked || hasLiked(r))).length;
  }

  const num = x => String(Number(x));

  function span(lo, hi) {
    const has = v => v !== undefined && v !== null;
    if (has(lo) && has(hi)) return lo === hi ? String(lo) : lo + '–' + hi;
    return has(lo) ? '≥' + lo : '≤' + hi;
  }

  function parts(f) {
    const out = [];
    if (f.genres) out.push(f.genres.join(', '));
    if ('year_from' in f || 'year_to' in f) out.push(span(f.year_from, f.year_to));
    const r = [];
    if ('pepe_min' in f) r.push('Pepe ≥' + num(f.pepe_min));
    if ('jenni_min' in f) r.push('Jenni ≥' + num(f.jenni_min));
    if (r.length) out.push(r.join(f.rating_mode === 'or' ? ' or ' : ' and '));
    if (f.places) out.push(f.places.join(', '));
    if ('bought_from' in f || 'bought_to' in f) out.push('bought ' + span(f.bought_from, f.bought_to));
    return out;
  }

  function suggestName(f) {
    const name = [BASE + (f.liked !== false ? ' — Liked' : '')].concat(parts(f)).join(' · ');
    return name.length <= MAX ? name : name.slice(0, MAX - 1).trimEnd() + '…';
  }

  return { normalize, matches, countMatching, suggestName };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylPlaylistFilters;
```

- [ ] **Step 4: Load it on the page**

In `templates/index.html`, after `<script src="/static/tracks.js"></script>` add:

```html
<script src="/static/playlist_filters.js"></script>
```

- [ ] **Step 5: Run to verify it passes**

Run: `python3 -m pytest -q tests/test_playlist_filters_js.py tests/test_playlist_filters.py`
Expected: PASS — the same fixture cases pass in both languages.

- [ ] **Step 6: Commit**

```bash
git add static/playlist_filters.js tests/test_playlist_filters.js tests/test_playlist_filters_js.py templates/index.html
git commit -m "feat: playlist filter rules in the browser, held to the shared cases"
```

---

### Task 5: The popup — saved list and new-playlist form

**Files:**
- Modify: `templates/index.html` — overlay comment + markup (:4075-4089), CSS after `.playlist-account .btn` (~:2232), JS from `// ── spotify playlists` (:10059) through the end of `syncPlaylist` (~:10191)
- Test: `tests/test_playlists_dom.js`

**Interfaces:**
- Consumes: Task 3 HTTP routes; `VinylPlaylistFilters` (Task 4); page globals `records`, `esc`, `toast`.
- Produces: page functions `loadPlaylists, renderPlaylists, renderPlaylistList, renderPlaylistForm, playlistFormInput, playlistChipAdd, playlistChipRemove, createPlaylist, syncPlaylist(id, note), deletePlaylist(id)`; `playlistResultHtml` and `skippedGroupHtml` stay as they are.

- [ ] **Step 1: Rewrite the DOM test harness and tests**

In `tests/test_playlists_dom.js`:

Update the header comment's last paragraph to: "What is worth testing: the item is edit-mode only, the panel offers to connect when there is no login, the saved playlists are listed, the form previews its count and name, a create that already exists resyncs that row, a sync keeps asking while the server reports it is still reading albums, and a delete removes the row."

Replace the start of `boot` (options) with:

```js
async function boot(opts) {
  opts = opts || {};
  const authed = !!opts.authed;
  const connected = !!opts.connected;
  // Answers for successive sync POSTs; the last one repeats.
  const syncs = opts.syncs || [];
  const saved = (opts.saved || []).map(p => Object.assign({}, p));
  const collection = opts.records || [];
  const created = opts.created || null;   // [status, body] for POST /api/spotify/playlists
  const deleted = opts.deleted || [200, { ok: true }];
  const posted = [];
```

In the fetch stub, replace the `/api/records`, `/api/spotify/account` and `/api/spotify/playlists/` branches with:

```js
    if (u.endsWith('/api/records')) return json(collection);
    if (u.endsWith('/api/spotify/account')) {
      return json({ configured: true, connected, display_name: 'Me',
                    redirect_uri: 'https://x/api/spotify/callback' });
    }
    const method = (init && init.method) || 'GET';
    const reply = ([status, body]) => ({ ok: status < 300, status, json: async () => body,
                                         text: async () => JSON.stringify(body) });
    if (u.endsWith('/api/spotify/playlists') && method === 'GET') {
      return json({ playlists: saved, genres: ['Jazz', 'Rock'], places: ['Tracks'] });
    }
    if (u.endsWith('/api/spotify/playlists') && method === 'POST') {
      posted.push(JSON.parse(init.body));
      return reply(created);
    }
    if (/\/api\/spotify\/playlists\/\d+\/sync$/.test(u)) {
      return reply(syncs.length > 1 ? syncs.shift() : syncs[0]);
    }
    if (/\/api\/spotify\/playlists\/\d+$/.test(u) && method === 'DELETE') return reply(deleted);
```

and change the return of `boot` to `return { win, doc, errors, asked, posted, read: expr => win.__peek(expr) };`.

Replace `DONE` and every test after `edit mode reveals the spotify playlists item` with:

```js
const EVERY = { id: 1, name: 'Zucoloto Vinyl Collection', filters: { liked: false },
                summary: 'every track · whole collection', url: '', last_synced_at: null,
                last_total: null, last_records: null };
const LIKED = { id: 2, name: 'Zucoloto Vinyl Collection — Liked', filters: { liked: true },
                summary: 'liked songs · whole collection',
                url: 'https://open.spotify.com/playlist/PL2', last_synced_at: '2026-10-01T10:00:00',
                last_total: 42, last_records: 7 };

const DONE = { spotify_id: 'PL1', name: 'Zucoloto Vinyl Collection', created: true,
               url: 'https://open.spotify.com/playlist/PL1', total: 42, added: 42,
               removed: 0, records: 4,
               bad_links: [{ label: 'C — D', cover_url: '' },
                           { label: 'E — F', cover_url: '/api/records/9/cover?v=h' }],
               unmatched: [{ label: 'A — B', cover_url: '/api/records/7/cover?v=h',
                             songs: ['Lost Song'] }],
               playlist: Object.assign({}, EVERY, { url: 'https://open.spotify.com/playlist/PL1',
                                                    last_synced_at: '2026-10-02T09:00:00',
                                                    last_total: 42, last_records: 4 }) };

const RECS = [
  { have_it: true, spotify_url: 'https://open.spotify.com/album/a', genre: 'Rock', year: '1973',
    tracks: JSON.stringify([{ side: 'A', title: 's', liked_at: '2026-01-01' }]) },
  { have_it: true, spotify_url: 'https://open.spotify.com/album/b', genre: 'Jazz', year: '1991',
    tracks: '' },
];

async function openPanel(opts) {
  const b = await boot(Object.assign({ authed: true, connected: true }, opts));
  press(b.win, b.doc.getElementById('playlistsBtn'));
  await settle(); await settle();
  return b;
}

const row = (doc, id) => doc.querySelector(`.playlist-row[data-id="${id}"]`);

test('without a Spotify login the panel offers to connect', async () => {
  const { win, doc } = await openPanel({ connected: false });
  try {
    assert.ok(!doc.getElementById('playlistsOverlay').classList.contains('hidden'));
    assert.ok(doc.getElementById('spotifyConnectBtn'), 'no connect button');
    assert.strictEqual(doc.querySelectorAll('.playlist-row').length, 0);
  } finally { win.close(); }
});

test('connected, the panel lists the saved playlists with their last result', async () => {
  const { win, doc } = await openPanel({ saved: [EVERY, LIKED] });
  try {
    const names = [...doc.querySelectorAll('.playlist-name')].map(e => e.textContent);
    assert.deepStrictEqual(names, ['Zucoloto Vinyl Collection', 'Zucoloto Vinyl Collection — Liked']);
    assert.match(row(doc, 1).textContent, /every track · whole collection/);
    assert.match(row(doc, 1).textContent, /never synced/);
    assert.match(row(doc, 2).textContent, /42 tracks · synced/);
    assert.strictEqual(row(doc, 2).querySelector('a').getAttribute('href'),
                       'https://open.spotify.com/playlist/PL2');
  } finally { win.close(); }
});

test('with nothing saved the new-playlist form starts open', async () => {
  const { win, doc } = await openPanel({ saved: [] });
  try {
    assert.ok(doc.getElementById('playlistNew').open);
    assert.match(doc.getElementById('playlistList').textContent, /no playlists yet/);
  } finally { win.close(); }
});

test('the form previews the match count and the name as filters change', async () => {
  const { win, doc } = await openPanel({ saved: [EVERY], records: RECS });
  try {
    assert.match(doc.getElementById('plCount').textContent, /^1 record matches/);
    assert.strictEqual(doc.getElementById('plName').value, 'Zucoloto Vinyl — Liked');

    const every = doc.querySelector('input[name="plLiked"][value="0"]');
    every.checked = true;
    win.__peek('playlistFormInput')(every);
    assert.match(doc.getElementById('plCount').textContent, /^2 records match/);

    const genre = doc.querySelector('select.pl-add[data-field="genres"]');
    genre.value = 'Jazz';
    win.__peek('playlistChipAdd')(genre);
    assert.match(doc.getElementById('plCount').textContent, /^1 record matches/);
    assert.strictEqual(doc.getElementById('plName').value, 'Zucoloto Vinyl · Jazz');

    const from = doc.querySelector('input[data-field="year_from"]');
    from.value = '2000';
    win.__peek('playlistFormInput')(from);
    assert.ok(doc.getElementById('plCount').classList.contains('warn'), '0 matches is not flagged');
  } finally { win.close(); }
});

test('a typed name stops following the filters; clearing it resumes', async () => {
  const { win, doc } = await openPanel({ saved: [EVERY], records: RECS });
  try {
    const name = doc.getElementById('plName');
    name.value = 'Road trip';
    win.__peek('playlistFormInput')(name);
    const every = doc.querySelector('input[name="plLiked"][value="0"]');
    every.checked = true;
    win.__peek('playlistFormInput')(every);
    assert.strictEqual(doc.getElementById('plName').value, 'Road trip');

    name.value = '';
    win.__peek('playlistFormInput')(name);
    assert.strictEqual(doc.getElementById('plName').value, 'Zucoloto Vinyl');
  } finally { win.close(); }
});

test('the and/or switch only shows once both ratings are set', async () => {
  const { win, doc } = await openPanel({ saved: [EVERY] });
  try {
    const mode = () => doc.getElementById('plMode');
    assert.ok(mode().hidden);
    const pepe = doc.querySelector('select[data-field="pepe_min"]');
    pepe.value = '4';
    win.__peek('playlistFormInput')(pepe);
    assert.ok(mode().hidden);
    const jenni = doc.querySelector('select[data-field="jenni_min"]');
    jenni.value = '3.5';
    win.__peek('playlistFormInput')(jenni);
    assert.ok(!mode().hidden);
  } finally { win.close(); }
});

test('create posts the filters, adds the row and syncs it', async () => {
  const NEW = Object.assign({}, EVERY, { id: 3, name: 'Zucoloto Vinyl — Liked',
                                         filters: { liked: true }, summary: 'liked songs · whole collection' });
  const { win, doc, asked, posted } = await openPanel({
    saved: [EVERY], created: [201, { playlist: NEW, existed: false }],
    syncs: [[200, Object.assign({}, DONE, { playlist: Object.assign({}, NEW, { last_total: 9,
            last_synced_at: '2026-10-02T09:00:00', url: 'https://open.spotify.com/playlist/PL3' }) })]],
  });
  try {
    press(win, doc.getElementById('plCreate'));
    await settle(); await settle();
    assert.deepStrictEqual(posted[0], { filters: { liked: true }, name: 'Zucoloto Vinyl — Liked' });
    assert.ok(asked.some(u => u.endsWith('/api/spotify/playlists/3/sync')));
    assert.match(row(doc, 3).textContent, /9 tracks · synced/);
  } finally { win.close(); }
});

test('creating filters that already exist highlights and resyncs that row', async () => {
  const { win, doc, asked } = await openPanel({
    saved: [EVERY, LIKED], created: [200, { playlist: LIKED, existed: true }],
    syncs: [[200, Object.assign({}, DONE, { playlist: LIKED })]],
  });
  try {
    press(win, doc.getElementById('plCreate'));
    await settle(); await settle();
    assert.strictEqual(doc.querySelectorAll('.playlist-row').length, 2, 'a duplicate row appeared');
    assert.ok(row(doc, 2).classList.contains('hl'));
    assert.match(row(doc, 2).textContent, /already exists — resynced/);
    assert.ok(asked.some(u => u.endsWith('/api/spotify/playlists/2/sync')));
  } finally { win.close(); }
});

test('a rejected filter shows the server error under the form', async () => {
  const { win, doc } = await openPanel({
    saved: [EVERY], created: [400, { error: 'pepe_min: must be 0.5 to 5', field: 'pepe_min' }] });
  try {
    press(win, doc.getElementById('plCreate'));
    await settle();
    const err = doc.getElementById('plError');
    assert.ok(!err.hidden);
    assert.match(err.textContent, /pepe_min/);
  } finally { win.close(); }
});

test('a sync keeps asking while the server is still reading albums', async () => {
  const { win, doc, asked } = await openPanel({
    saved: [EVERY],
    syncs: [[202, { incomplete: true, done: 100, total: 300 }],
            [202, { incomplete: true, done: 200, total: 300 }],
            [200, DONE]],
  });
  try {
    press(win, row(doc, 1).querySelector('.playlist-sync'));
    await settle(); await settle();
    assert.strictEqual(asked.filter(u => u.endsWith('/api/spotify/playlists/1/sync')).length, 3);
    const text = row(doc, 1).textContent;
    assert.match(text, /created · 42 tracks from 4 records/);
    const groups = [...doc.querySelectorAll('.skipped-group summary')].map(e => e.textContent);
    assert.match(groups[0], /^1 not found/);
    assert.match(groups[1], /^2 bad link/);
    assert.match(text, /A — B\s*Lost Song/);
    const covers = [...doc.querySelectorAll('.skipped-group img.skipped-cover')]
      .map(i => i.getAttribute('src'));
    assert.deepStrictEqual(covers, ['/api/records/7/cover?v=h', '/api/records/9/cover?v=h']);
    assert.match(text, /42 tracks · synced/, 'the row did not take the stored result');
  } finally { win.close(); }
});

test('a failed sync says so on its row', async () => {
  const { win, doc } = await openPanel({ saved: [EVERY, LIKED],
                                         syncs: [[502, { error: 'Spotify returned 500' }]] });
  try {
    press(win, row(doc, 2).querySelector('.playlist-sync'));
    await settle(); await settle();
    const st = row(doc, 2).querySelector('.playlist-status');
    assert.ok(st.classList.contains('err'));
    assert.match(st.textContent, /Spotify returned 500/);
  } finally { win.close(); }
});

test('delete confirms, calls the server and removes the row', async () => {
  const { win, doc, asked } = await openPanel({ saved: [EVERY, LIKED] });
  try {
    let asked_ = '';
    win.confirm = (m) => { asked_ = m; return true; };
    press(win, row(doc, 2).querySelector('.playlist-delete'));
    await settle(); await settle();
    assert.match(asked_, /Zucoloto Vinyl Collection — Liked/);
    assert.ok(asked.some(u => u.endsWith('/api/spotify/playlists/2')));
    assert.strictEqual(row(doc, 2), null);
    assert.ok(row(doc, 1));
  } finally { win.close(); }
});

test('a failed delete keeps the row and says why', async () => {
  const { win, doc } = await openPanel({ saved: [LIKED], deleted: [502, { error: 'Spotify returned 500' }] });
  try {
    press(win, row(doc, 2).querySelector('.playlist-delete'));
    await settle(); await settle();
    assert.ok(row(doc, 2));
    assert.match(row(doc, 2).querySelector('.playlist-status').textContent, /delete failed/);
  } finally { win.close(); }
});
```

(Keep the two existing tests `a visitor is not offered…` and `edit mode reveals…` as they are.)

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest -q tests/test_playlists_dom.py`
Expected: FAIL — e.g. `Cannot read properties of null (reading 'open')` for `playlistNew`, rows not found by `data-id`.

- [ ] **Step 3: Implement — overlay comment and width**

Replace the HTML comment above `<div class="overlay hidden" id="playlistsOverlay">` with:

```html
<!-- spotify playlists: the playlists this app made on the owner's Spotify,
     each defined by filters (liked/every track, year, genre, ratings, bought
     at, bought dates), plus a form to make another. Each sync creates the
     playlist when it is missing and otherwise adds and removes until it
     matches. See spotify_sync.py and playlist_filters.py. -->
```

and change that modal's `style="max-width:460px"` to `style="max-width:520px"`.

- [ ] **Step 4: Implement — CSS**

After `.playlist-account .btn{margin-left:auto}` add:

```css
.playlist-heading{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--label);padding:10px 2px 0}
.playlist-row.hl{background:color-mix(in srgb,var(--accent) 10%,transparent);border-radius:6px}
.playlist-last a{color:var(--accent)}
.playlist-new{margin-top:12px;border-top:1px solid var(--border);padding-top:8px}
.playlist-new summary{cursor:pointer;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--label);padding:6px 2px}
.pl-field{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px;padding:6px 2px;font-size:12px}
.pl-label{flex:0 0 72px;color:var(--muted)}
.pl-field input,.pl-field select{font:inherit;font-size:12px;padding:4px 6px;border:1px solid var(--border);
  border-radius:6px;background:var(--bg);color:inherit;min-width:0}
.pl-field input[type=radio]{padding:0}
.pl-num{width:76px}
.pl-name{flex:1 1 160px}
.pl-chip{display:inline-flex;align-items:center;gap:4px;padding:2px 4px 2px 8px;border-radius:999px;
  background:var(--border);font-size:11px}
.pl-chip button{background:none;border:none;color:var(--muted);cursor:pointer;padding:0 4px;font-size:13px}
.pl-mode[hidden]{display:none}
.pl-count{font-size:12px;color:var(--muted);padding:8px 2px}
.pl-count.warn{color:var(--danger)}
.pl-actions{display:flex;justify-content:flex-end;padding:6px 2px}
@media (max-width:480px){.pl-label{flex-basis:100%}}
```

- [ ] **Step 5: Implement — JS**

Replace from the line `// ── spotify playlists ───…` through the closing `}` of `async function syncPlaylist` with the block below. Keep `playlistResultHtml` and `skippedGroupHtml` exactly as they are (they sit between `renderPlaylists` and `syncPlaylist` today — move them below this block unchanged), and keep `disconnectSpotify` and `playlistsReturn` after it.

```js
// ── spotify playlists ──────────────────────────────────────────────────────
// The server does the work (spotify_sync.py, playlist_filters.py); this panel
// connects the account, lists the playlists made so far, and makes new ones
// from filters. A first sync reads every album once and may need several
// requests to do it — the server answers 202 with its progress each time it
// runs out of budget, and the loop in syncPlaylist simply asks again.
let playlistAccount = null;
let savedPlaylists = [];
let playlistChoices = {genres: [], places: []};
const playlistStatus = {};      // playlist id -> {html, err}
let playlistBusy = false;
let playlistHighlight = null;   // id of the row a duplicate create pointed at

function blankPlaylistForm(){
  return {liked: true, year_from: '', year_to: '', genres: [], pepe_min: '', jenni_min: '',
          rating_mode: 'and', places: [], bought_from: '', bought_to: '', name: '', nameTouched: false};
}
let playlistForm = blankPlaylistForm();

function openPlaylists(){
  document.getElementById('playlistsOverlay').classList.remove('hidden');
  document.getElementById('morePanel').classList.add('hidden');
  loadPlaylists();
}

function closePlaylists(){
  document.getElementById('playlistsOverlay').classList.add('hidden');
}

async function loadPlaylists(){
  renderPlaylists(null);
  try{
    const r=await fetch('/api/spotify/account');
    if(!r.ok)throw new Error('HTTP '+r.status);
    playlistAccount=await r.json();
    if(playlistAccount.configured&&playlistAccount.connected){
      const s=await fetch('/api/spotify/playlists');
      if(!s.ok)throw new Error('HTTP '+s.status);
      const d=await s.json();
      savedPlaylists=d.playlists||[];
      playlistChoices={genres:d.genres||[],places:d.places||[]};
    }
    renderPlaylists(playlistAccount);
  }catch(err){
    renderPlaylists('error');
  }
}

function renderPlaylists(acct){
  const body=document.getElementById('playlistsBody');
  if(acct===null){body.innerHTML='<div class="backup-note">loading…</div>';return;}
  if(acct==='error'){
    body.innerHTML='<div class="backup-note">could not reach the server — try again.</div>';
    return;
  }
  if(!acct.configured){
    body.innerHTML='<div class="backup-note">Spotify is not configured on the server: set '
      +'SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET.</div>';
    return;
  }
  if(!acct.connected){
    body.innerHTML=`<div class="backup-note">connect your Spotify account so the app can
      create and edit the playlists. The Spotify app must list this redirect URI:<br>
      <code>${esc(acct.redirect_uri)}</code></div>
      <div style="padding-top:12px"><button class="btn btn-primary btn-sm" id="spotifyConnectBtn"
        onclick="window.location.href='/api/spotify/connect'"><i class="ti ti-brand-spotify"></i>
        <span>connect spotify</span></button></div>`;
    return;
  }
  // Kept across re-renders: a sync finishing must not snap the form shut.
  const prev=document.getElementById('playlistNew');
  const open=prev?prev.open:!savedPlaylists.length;
  body.innerHTML=`<div class="playlist-account"><i class="ti ti-brand-spotify"></i>
      <span>connected as <b>${esc(acct.display_name||'Spotify')}</b></span>
      <button class="btn btn-ghost btn-sm" onclick="disconnectSpotify()">disconnect</button></div>
    <div class="playlist-heading">your playlists</div>
    <div id="playlistList"></div>
    <details class="playlist-new" id="playlistNew" ${open?'open':''}>
      <summary>new playlist</summary><div id="playlistFormBody"></div></details>
    <div class="backup-note">a sync creates the playlist if it is missing, adds what is new and
      removes what no longer belongs — the playlist always mirrors the collection.</div>`;
  renderPlaylistList();
  renderPlaylistForm();
}

// "today", "yesterday", "3 days ago" — from a local stamp's calendar day.
function playlistAgo(stamp){
  const day=s=>{const [y,m,d]=s.slice(0,10).split('-').map(Number);return new Date(y,m-1,d);};
  const n=Math.round((day(new Date().toLocaleDateString('sv'))-day(stamp))/86400000);
  return n<=0?'today':n===1?'yesterday':n+' days ago';
}

function renderPlaylistList(){
  const list=document.getElementById('playlistList');
  if(!list)return;
  if(!savedPlaylists.length){
    list.innerHTML='<div class="place-empty">no playlists yet — make one below.</div>';
    return;
  }
  list.innerHTML=savedPlaylists.map(p=>{
    const st=playlistStatus[p.id]||{};
    const last=p.last_synced_at
      ?`${p.last_total} tracks · synced ${esc(playlistAgo(p.last_synced_at))}`
        +(p.url?` · <a href="${esc(p.url)}" target="_blank" rel="noopener">open ↗</a>`:'')
      :'never synced';
    return `<div class="playlist-row${playlistHighlight===p.id?' hl':''}" data-id="${p.id}">
      <span class="playlist-name">${esc(p.name)}</span>
      <button class="btn btn-primary btn-sm playlist-sync" ${playlistBusy?'disabled':''}
        onclick="syncPlaylist(${p.id})"><i class="ti ti-refresh"></i><span>sync</span></button>
      <button class="btn btn-ghost btn-sm playlist-delete" ${playlistBusy?'disabled':''}
        title="delete" aria-label="delete" onclick="deletePlaylist(${p.id})"><i class="ti ti-trash"></i></button>
      <span class="playlist-sub">${esc(p.summary)}</span>
      <span class="playlist-sub playlist-last">${last}</span>
      ${st.html?`<div class="playlist-status${st.err?' err':''}">${st.html}</div>`:''}
    </div>`;
  }).join('');
}

function renderPlaylistForm(){
  const el=document.getElementById('playlistFormBody');
  if(!el)return;
  const f=playlistForm;
  const chips=(field,choices)=>{
    const taken=new Set(f[field].map(x=>x.toLowerCase()));
    const left=choices.filter(c=>!taken.has(c.toLowerCase()));
    return f[field].map((c,i)=>`<span class="pl-chip">${esc(c)}<button type="button" aria-label="remove"
        onclick="playlistChipRemove('${field}',${i})">×</button></span>`).join('')
      +(left.length?`<select class="pl-add" data-field="${field}" onchange="playlistChipAdd(this)">
        <option value="">+ add</option>${left.map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join('')}
        </select>`:'');
  };
  const stars=field=>`<select data-field="${field}" onchange="playlistFormInput(this)">
      <option value="">–</option>${[1,2,3,4,5,6,7,8,9,10].map(i=>{const v=String(i/2);
        return `<option value="${v}" ${String(f[field])===v?'selected':''}>${v}</option>`;}).join('')}</select>`;
  const radio=(name,field,value,label,on)=>`<label><input type="radio" name="${name}" value="${value}"
      data-field="${field}" ${on?'checked':''} onchange="playlistFormInput(this)"> ${label}</label>`;
  const input=(field,type,ph,cls)=>`<input ${cls?`class="${cls}"`:''} type="${type}" data-field="${field}"
      ${ph?`placeholder="${ph}"`:''} value="${esc(f[field])}" oninput="playlistFormInput(this)">`;
  el.innerHTML=`
    <div class="pl-field"><span class="pl-label">songs</span>
      ${radio('plLiked','liked','1','liked',f.liked)} ${radio('plLiked','liked','0','every track',!f.liked)}</div>
    <div class="pl-field"><span class="pl-label">year</span>
      ${input('year_from','number','from','pl-num')} – ${input('year_to','number','to','pl-num')}</div>
    <div class="pl-field"><span class="pl-label">genre</span>${chips('genres',playlistChoices.genres)}</div>
    <div class="pl-field"><span class="pl-label">rating</span>Pepe ≥ ${stars('pepe_min')}
      <span class="pl-mode" id="plMode">${radio('plMode','rating_mode','and','and',f.rating_mode!=='or')}
        ${radio('plMode','rating_mode','or','or',f.rating_mode==='or')}</span>
      Jenni ≥ ${stars('jenni_min')}</div>
    <div class="pl-field"><span class="pl-label">bought at</span>${chips('places',playlistChoices.places)}</div>
    <div class="pl-field"><span class="pl-label">bought</span>
      ${input('bought_from','date')} – ${input('bought_to','date')}</div>
    <div class="pl-count" id="plCount"></div>
    <div class="pl-field"><span class="pl-label">name</span>
      <input class="pl-name" id="plName" data-field="name" maxlength="100"
        value="${esc(f.name)}" oninput="playlistFormInput(this)"></div>
    <div class="pl-actions"><button class="btn btn-primary btn-sm" id="plCreate" ${playlistBusy?'disabled':''}
      onclick="createPlaylist()"><i class="ti ti-playlist-add"></i><span>create &amp; sync</span></button></div>
    <div class="playlist-status err" id="plError" hidden></div>`;
  updatePlaylistPreview();
}

function playlistFilters(){
  const f=playlistForm;
  return VinylPlaylistFilters.normalize({liked:f.liked,year_from:f.year_from,year_to:f.year_to,
    genres:f.genres,pepe_min:f.pepe_min,jenni_min:f.jenni_min,rating_mode:f.rating_mode,
    places:f.places,bought_from:f.bought_from,bought_to:f.bought_to});
}

// Updated in place rather than re-rendered, so typing in a field keeps focus.
function updatePlaylistPreview(){
  const filters=playlistFilters();
  const n=VinylPlaylistFilters.countMatching(records,filters);
  const count=document.getElementById('plCount');
  if(count){
    count.textContent=(n===1?'1 record matches':n+' records match')+(n===0?' — the playlist would be empty':'');
    count.classList.toggle('warn',n===0);
  }
  if(!playlistForm.nameTouched){
    playlistForm.name=VinylPlaylistFilters.suggestName(filters);
    const name=document.getElementById('plName');
    if(name)name.value=playlistForm.name;
  }
  const mode=document.getElementById('plMode');
  if(mode)mode.hidden=!(playlistForm.pepe_min&&playlistForm.jenni_min);
}

function playlistFormInput(el){
  const field=el.dataset.field;
  if(field==='liked')playlistForm.liked=el.value==='1';
  else if(field==='name'){
    playlistForm.name=el.value;
    // Clearing the name hands it back to the filters.
    playlistForm.nameTouched=el.value.trim()!=='';
  }
  else playlistForm[field]=el.value;
  updatePlaylistPreview();
}

function playlistChipAdd(sel){
  if(sel.value)playlistForm[sel.dataset.field].push(sel.value);
  renderPlaylistForm();
}

function playlistChipRemove(field,i){
  playlistForm[field].splice(i,1);
  renderPlaylistForm();
}

async function createPlaylist(){
  if(playlistBusy)return;
  const err=document.getElementById('plError');
  err.hidden=true;
  let d;
  try{
    const r=await fetch('/api/spotify/playlists',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({filters:playlistFilters(),name:playlistForm.name})});
    d=await r.json().catch(()=>({}));
    if(!r.ok)throw new Error(d.error||('HTTP '+r.status));
  }catch(e){
    err.textContent=e.message;
    err.hidden=false;
    return;
  }
  const p=d.playlist;
  if(!savedPlaylists.some(x=>x.id===p.id))savedPlaylists.push(p);
  playlistHighlight=p.id;
  // A new playlist clears the form for the next one; an existing match keeps
  // it, since the filters were probably meant to differ and may need a tweak.
  if(!d.existed)playlistForm=blankPlaylistForm();
  renderPlaylists(playlistAccount);
  const row=document.querySelector(`.playlist-row[data-id="${p.id}"]`);
  if(row)row.scrollIntoView({block:'nearest'});
  await syncPlaylist(p.id,d.existed?'already exists — resynced · ':'');
}

async function syncPlaylist(id,note){
  if(playlistBusy)return;
  playlistBusy=true;
  playlistStatus[id]={html:'reading albums…'};
  renderPlaylistList();
  try{
    // Bounded so a server that never finishes cannot spin forever.
    for(let round=0;round<30;round++){
      const r=await fetch('/api/spotify/playlists/'+id+'/sync',{method:'POST'});
      const d=await r.json().catch(()=>({}));
      if(r.status===202&&d.incomplete){
        playlistStatus[id]={html:`reading albums… ${d.done} / ${d.total}`};
        renderPlaylistList();
        continue;
      }
      if(r.status===409&&d.connect){
        playlistAccount.connected=false;
        toast(d.error||'connect Spotify again');
        return;
      }
      if(!r.ok)throw new Error(d.error||('HTTP '+r.status));
      if(d.playlist){
        const i=savedPlaylists.findIndex(x=>x.id===id);
        if(i>=0)savedPlaylists[i]=d.playlist;
      }
      playlistStatus[id]={html:esc(note||'')+playlistResultHtml(d)};
      return;
    }
    throw new Error('the sync did not finish — try again');
  }catch(err){
    playlistStatus[id]={html:esc('sync failed — '+err.message),err:true};
  }finally{
    playlistBusy=false;
    renderPlaylists(playlistAccount);
  }
}

async function deletePlaylist(id){
  const p=savedPlaylists.find(x=>x.id===id);
  if(!p||playlistBusy)return;
  if(!confirm(`Delete “${p.name}” from Spotify too?`))return;
  playlistBusy=true;
  try{
    const r=await fetch('/api/spotify/playlists/'+id,{method:'DELETE'});
    const d=await r.json().catch(()=>({}));
    if(r.status===409&&d.connect){
      playlistAccount.connected=false;
      toast(d.error||'connect Spotify again');
      return;
    }
    if(!r.ok)throw new Error(d.error||('HTTP '+r.status));
    savedPlaylists=savedPlaylists.filter(x=>x.id!==id);
    delete playlistStatus[id];
    if(playlistHighlight===id)playlistHighlight=null;
  }catch(err){
    playlistStatus[id]={html:esc('delete failed — '+err.message),err:true};
  }finally{
    playlistBusy=false;
    renderPlaylists(playlistAccount);
  }
}
```

- [ ] **Step 6: Run to verify it passes**

Run: `python3 -m pytest -q tests/test_playlists_dom.py`
Expected: PASS.

- [ ] **Step 7: Run the whole suite**

Run: `python3 -m pytest -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add templates/index.html tests/test_playlists_dom.js
git commit -m "feat: playlists popup lists saved playlists and builds new ones from filters"
```

---

### Task 6: README and a real-app check

**Files:**
- Modify: `README.md` (section `## Playlists no Spotify`, the paragraph and list before "Cada **sync**…")

- [ ] **Step 1: Rewrite the opening of the section**

Replace from "Em modo de edição, menu…" through the end of the bullet list with:

```markdown
Em modo de edição, menu **⋯ → spotify playlists** lista as playlists que o app
criou na sua conta e permite criar novas a partir de filtros. Todas usam só os
discos que você tem (não a wishlist) e que têm link do Spotify, na ordem de
compra. Filtros (todos opcionais, combinados com E):

- **Músicas** — só as curtidas (padrão) ou todas as faixas de cada álbum. As
  curtidas são casadas pelo título com as faixas do álbum no Spotify; as que
  não casam aparecem em "not found", com a capa do disco.
- **Ano de lançamento** — de / até.
- **Gênero** e **Comprado em** — qualquer um dos escolhidos.
- **Nota** — mínimo da Pepe e/ou da Jenni, exigindo as duas (and) ou uma (or).
- **Comprado entre** — datas de / até (o mesmo dia nas duas = data exata).

Pedir os mesmos filtros de novo não cria outra playlist: a que já existe é
sincronizada. As duas playlists antigas (**Zucoloto Vinyl Collection** e
**— Liked**) viram itens da lista e continuam sendo as mesmas no Spotify.
Apagar uma playlist no painel apaga também no Spotify.
```

- [ ] **Step 2: Check it in the real app**

Use the `run` skill to start the app locally at `http://127.0.0.1:5000`, log into edit mode, open **⋯ → spotify playlists** and confirm: both legacy playlists are listed, the form's count and name change as filters change, and the layout holds at 375px wide. A live Spotify sync needs the owner's login, so leave that to them and say so.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: filtered Spotify playlists"
```
