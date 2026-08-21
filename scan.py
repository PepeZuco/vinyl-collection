"""Record identification: sleeve photos and Spotify links to record fields."""
import re
import unicodedata

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
