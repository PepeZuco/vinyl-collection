"""Record identification: sleeve photos and Spotify links to record fields."""
import base64
import os
import re
import threading
import time
import unicodedata

import requests

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
    key = (_normalise(artist), _normalise(album))
    if not key[0] or not key[1]:
        return None
    for record in existing:
        if (_normalise(record.get("artist", "")),
                _normalise(record.get("album_name", ""))) == key:
            return record
    return None


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
