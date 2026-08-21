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
