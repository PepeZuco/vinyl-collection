"""Which records a filtered Spotify playlist holds, and what to call it.

A playlist is defined by one small JSON object of filters. Everything here is
pure — no database, no Spotify — so the rules can be tested on their own and
mirrored in static/playlist_filters.js for the popup's live count. Both are
held to tests/fixtures/playlist_filter_cases.json.

Filters (all optional; absent means "does not filter"; they combine with AND):

  liked                    bool, default True — hearted songs only, else every track
  decades                  any of these release decades, as their first year (1970 = 1970s)
  year_from, year_to       release year range, inclusive (older playlists; the form now
                           picks decades)
  genres                   any of these genres
  pepe_min, jenni_min      minimum stars, 0.5–5 in halves
  rating_mode              "and" | "or" — only kept when both minimums are set
  places                   any of these bought-at places
  countries                any of these pressing countries, as ISO 3166-1 alpha-2 codes
  bought_from, bought_to   YYYY-MM-DD purchase range, inclusive
  source                   "albums" (default) | "compilations" | "all" — which kind of
                           Spotify link counts: an album (or track) link, or a playlist
                           someone made for a compilation that is not an album on Spotify.
                           A record flagged spotify_standin counts as an album whatever
                           its link: that playlist stands in for an album Spotify lacks.
  owned                    "owned" (default) | "wishlist" | "all" — records you have,
                           records on the wishlist, or both

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
_PLAYLIST_LINK = re.compile(r"^(?:https?://open\.spotify\.com/(?:intl-[a-z]+/)?playlist/|spotify:playlist:)",
                            re.IGNORECASE)

SOURCES = ("albums", "compilations", "all")
OWNED = ("owned", "wishlist", "all")


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


def _countries(v):
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        raise FilterError("countries", "must be a list")
    out = set()
    for x in v:
        c = _tidy(x).upper()
        if not c:
            continue
        if not re.fullmatch(r"[A-Z]{2}", c):
            raise FilterError("countries", "must be two-letter country codes")
        out.add(c)
    return sorted(out)


def _decades(v):
    if not isinstance(v, (list, tuple)):
        v = [v]
    out = set()
    for x in v:
        d = _year("decades", x)
        if d % 10:
            raise FilterError("decades", "must be the first year of a decade, like 1970")
        out.add(d)
    return sorted(out)


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
    if not _blank(raw.get("decades")):
        f["decades"] = _decades(raw["decades"])

    if not _blank(raw.get("countries")):
        codes = _countries(raw["countries"])
        if codes:
            f["countries"] = codes

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

    source = raw.get("source") or "albums"
    if source not in SOURCES:
        raise FilterError("source", "must be albums, compilations or all")
    # The default stays out of the canonical form, so playlists made before
    # this filter existed keep their key.
    if source != "albums":
        f["source"] = source

    owned = raw.get("owned") or "owned"
    if owned not in OWNED:
        raise FilterError("owned", "must be owned, wishlist or all")
    # Same as source: the default stays out, so older playlists keep their key.
    if owned != "owned":
        f["owned"] = owned

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
    keyed = {k: ([x.lower() if isinstance(x, str) else x for x in v] if isinstance(v, list) else v)
             for k, v in filters.items()}
    return json.dumps(keyed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _num(x):
    return str(int(x)) if float(x).is_integer() else str(x)


def _span(lo, hi):
    if lo is not None and hi is not None:
        return str(lo) if lo == hi else f"{lo}–{hi}"
    return f"≥{lo}" if lo is not None else f"≤{hi}"


def decade_names(decades):
    return [f"{d}s" for d in decades]


def _parts(f):
    out = []
    if f.get("genres"):
        out.append(", ".join(f["genres"]))
    if f.get("decades"):
        out.append(", ".join(decade_names(f["decades"])))
    if "year_from" in f or "year_to" in f:
        out.append(_span(f.get("year_from"), f.get("year_to")))
    ratings = []
    if "pepe_min" in f:
        ratings.append(f"Pepe ≥{_num(f['pepe_min'])}")
    if "jenni_min" in f:
        ratings.append(f"Jenni ≥{_num(f['jenni_min'])}")
    if ratings:
        out.append((" or " if f.get("rating_mode") == "or" else " and ").join(ratings))
    if f.get("countries"):
        out.append(", ".join(f["countries"]))
    if f.get("places"):
        out.append(", ".join(f["places"]))
    if "bought_from" in f or "bought_to" in f:
        out.append("bought " + _span(f.get("bought_from"), f.get("bought_to")))
    if f.get("source") == "compilations":
        out.append("compilations only")
    elif f.get("source") == "all":
        out.append("+ compilations")
    if f.get("owned") == "wishlist":
        out.append("wishlist")
    elif f.get("owned") == "all":
        out.append("+ wishlist")
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


def link_kind(link):
    """"playlist" for a playlist link, else "album" — an album or track link,
    or anything unreadable, which the sync reports as a bad link."""
    return "playlist" if _PLAYLIST_LINK.match(str(link or "").strip()) else "album"


def _matches(r, f):
    # A record without the flag counts as owned, like the column's default.
    have = r.get("have_it", True) is not False
    owned = f.get("owned", "owned")
    if owned != "all" and have != (owned == "owned"):
        return False
    source = f.get("source", "albums")
    # A stand-in is a playlist built for an album Spotify does not have: the
    # record is still an album, so it sits with the albums.
    kind = "album" if r.get("spotify_standin") else link_kind(r.get("spotify_url"))
    if source != "all" and kind != ("playlist" if source == "compilations" else "album"):
        return False
    if "year_from" in f or "year_to" in f:
        y = record_year(r.get("year"))
        if y is None or y < f.get("year_from", y) or y > f.get("year_to", y):
            return False
    if f.get("decades"):
        y = record_year(r.get("year"))
        if y is None or y // 10 * 10 not in f["decades"]:
            return False
    if f.get("genres") and _fold(r.get("genre")) not in {g.lower() for g in f["genres"]}:
        return False
    if f.get("countries") and _tidy(r.get("country")).upper() not in set(f["countries"]):
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
