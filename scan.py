"""Record identification: sleeve photos and Spotify links to record fields."""
import base64
import json
import logging
import os
import re
import threading
import time
import unicodedata
import urllib.parse

import anthropic
import requests

logger = logging.getLogger(__name__)

_SPOTIFY_URL_RE = re.compile(
    r"^https?://open\.spotify\.com/(?:intl-[a-z]{2}/)?(album|track)/([A-Za-z0-9]+)",
    re.IGNORECASE,
)
_SPOTIFY_URI_RE = re.compile(r"^spotify:(album|track):([A-Za-z0-9]+)$", re.IGNORECASE)

# The mobile share sheet emits spotify.link (and, historically, spotify.app.link)
# short codes rather than an open.spotify.com URL. Those need a network hop to
# resolve, which is why they are handled by _resolve_short_link and NOT by
# parse_spotify_url — that function stays pure so it can be unit-tested and
# reasoned about without a network.
_SHORT_LINK_HOSTS = frozenset({"spotify.link", "www.spotify.link", "spotify.app.link"})
_SPOTIFY_WEB_HOSTS = frozenset({"open.spotify.com"})
_MAX_SHORT_LINK_HOPS = 5
SHORT_LINK_TIMEOUT = 4.0


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


def _hostname(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _resolve_short_link(url: str) -> str:
    """Expand a ``spotify.link`` share-sheet code into its open.spotify.com URL.

    Never raises. On any failure — a non-short-link input, a timeout, a
    non-redirect response, a hop pointing off Spotify, or too many hops — the
    input is returned unchanged, so the caller's parse_spotify_url produces the
    usual ValueError and the route answers 400 as before.
    """
    original = url
    candidate = (url or "").strip()
    if _hostname(candidate) not in _SHORT_LINK_HOSTS:
        return original

    try:
        for _ in range(_MAX_SHORT_LINK_HOPS):
            response = requests.get(
                candidate, allow_redirects=False, timeout=SHORT_LINK_TIMEOUT
            )
            location = response.headers.get("Location") or ""
            if not 300 <= response.status_code < 400 or not location:
                break
            candidate = urllib.parse.urljoin(candidate, location)
            # Vet every hop BEFORE issuing the next request: a share link must
            # stay inside Spotify, so an open redirect can never make this
            # function fetch an arbitrary host.
            host = _hostname(candidate)
            if host in _SHORT_LINK_HOSTS:
                continue
            if host in _SPOTIFY_WEB_HOSTS:
                return candidate
            logger.warning("Spotify short link redirected off Spotify to %r", host)
            return original
    except requests.RequestException:
        logger.warning("Could not resolve Spotify short link", exc_info=True)
    return original


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

# musicbrainz.org sheds load with a 503 ("the MusicBrainz web server is
# currently busy") that has nothing to do with this client's own quota: the
# responses carry X-RateLimit-Zone: global / search-global with most of the
# bucket still unspent, and Retry-After: 0. Measured back to back against the
# live API, a third to a half of identical searches came back that way. Treating
# one as "MusicBrainz has no such release" is what made the same photo scan to
# no matches and then, seconds later, to matches.
#
# So they are retried, with a widening gap rather than the throttle's flat
# second: three attempts one second apart all landed inside the same shed and
# still came back empty. The budget has to outlast the bad few seconds rather
# than fit inside them.
MB_MAX_ATTEMPTS = 4
MB_RETRY_BACKOFF = 1.0
MB_MAX_BACKOFF = 8.0

# The search is worth waiting for; the artist country is a nice-to-have on a
# form the user is watching, so it gives up sooner rather than adding seconds
# to every scan MusicBrainz is having a bad minute for.
MB_COUNTRY_ATTEMPTS = 2

# MusicBrainz scores a search hit 0-100. A real match scores 100 even through an
# accent difference or a misread letter; the tail below this is other records by
# the same artist, and offering those as candidates is what makes a scan look
# like it guessed. Never applied to the best candidate — see _rank_candidates.
MB_MIN_SCORE = 50

_mb_lock = threading.Lock()
_mb_last_call = 0.0


class MusicBrainzUnavailable(Exception):
    """MusicBrainz could not be asked — as opposed to asked and having nothing.

    The two have to stay distinguishable all the way to the form: "no release
    matched this sleeve" and "the release database was down" call for different
    words and different next steps from the user.
    """


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


def _retry_after(response, attempt: int) -> float:
    """How long to wait before the next attempt.

    Prefers the server's own Retry-After when it names a usable delay, and
    otherwise doubles the gap each time. Capped either way: MusicBrainz mostly
    sends Retry-After: 0 while shedding, and an unbounded header would let a
    remote server stall a scan the user is watching.
    """
    header = (getattr(response, "headers", None) or {}).get("Retry-After")
    try:
        named = float(header)
    except (TypeError, ValueError):
        named = 0.0
    if named > 0:
        return min(named, MB_MAX_BACKOFF)
    return min(MB_RETRY_BACKOFF * 2 ** (attempt - 1), MB_MAX_BACKOFF)


def _mb_get(path: str, params: dict, attempts: int = MB_MAX_ATTEMPTS) -> dict:
    """GET a MusicBrainz endpoint, retrying the transient failures.

    Raises MusicBrainzUnavailable once the attempt budget is spent. Callers
    decide what that costs them: the search cannot go on without it, an artist
    lookup just loses the country.
    """
    for attempt in range(1, attempts + 1):
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
        except requests.RequestException as e:
            # A 4xx is the query's fault and will fail identically next time;
            # only a timeout, a dropped connection or a 5xx is worth repeating.
            failed = getattr(e, "response", None)
            status = getattr(failed, "status_code", None)
            retryable = status is None or status >= 500
            last = attempt == attempts
            logger.warning(
                "MusicBrainz %s failed (attempt %d/%d, status %s, %s)",
                path, attempt, attempts, status,
                "retrying" if retryable and not last else "giving up",
            )
            if not retryable:
                break
            if not last:
                time.sleep(_retry_after(failed, attempt))
    raise MusicBrainzUnavailable(f"MusicBrainz did not answer for {path}")


def _artist_country(artist_mbid: str, cache: dict) -> str | None:
    if artist_mbid in cache:
        return cache[artist_mbid]
    try:
        payload = _mb_get(f"/artist/{artist_mbid}", {},
                          attempts=MB_COUNTRY_ATTEMPTS) or {}
    except MusicBrainzUnavailable:
        # Country is the one optional field here. Losing it must not lose the
        # release the user is actually trying to identify, so this failure is
        # swallowed where the search's is not. Cached as None so three
        # candidates by one artist don't each retry a server that is down.
        logger.warning("Could not read country for artist %s", artist_mbid)
        cache[artist_mbid] = None
        return None
    country = payload.get("country")
    if not country:
        codes = (payload.get("area") or {}).get("iso-3166-1-codes") or []
        country = codes[0] if codes else None
    cache[artist_mbid] = country
    return country


# Lucene's metacharacters, as they appear in ordinary sleeve text: the slash in
# AC/DC, the brackets around [Mono], the parens around (Reissue), the colon in a
# subtitle. Unescaped, they change what the query means or make it unparseable.
_LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')


def _lucene_escape(value: str) -> str:
    return _LUCENE_SPECIAL.sub(r"\\\1", value or "")


def _mb_query(artist: str, album: str) -> str:
    """Build the release-group search query.

    field:(terms), not field:"phrase". Quoting forces an exact-phrase match, and
    a sleeve almost never reads exactly the way MusicBrainz spells it: measured
    against the live API, "Space Is the Place (Reissue)", "Kind of Blue [Mono]",
    "A Divina Comédia ou Ando Meio Desligado" and a one-letter misread of
    "Carnegie" each returned zero groups quoted and the right album at score 100
    unquoted. Bare terms would over-correct — `artist:Sun Ra` binds only "Sun"
    and lets "Ra" match the default field, dragging in other artists — so the
    parens keep every term bound to its own field while leaving the match fuzzy.
    """
    query = f"artist:({_lucene_escape(artist)})"
    if album:
        query += f" AND releasegroup:({_lucene_escape(album)})"
    return query


def _rank_candidates(groups: list[dict], album: str) -> list[dict]:
    """Order search hits by how likely each is to be the record in the photo.

    MusicBrainz's own order is by score alone, which loses three ways, all of
    them reproduced against the live API:

      - "Clube da Esquina" returns "Clube da Esquina 2" at score 100 ahead of
        "Clube da Esquina" at 91, so an exact title has to outrank a score.
      - AC/DC's "Back in Black" returns the single ahead of the album, both at
        100. This is an LP collection, and the single carries a different year.
      - "Tim Maia / Racional" returns the 2002 compilation "Tim Maia Racional"
        ahead of the 1975 and 1976 originals, all three at 100.

    Sorting is stable, so hits that tie on every key keep MusicBrainz's order.
    """
    wanted = _normalise(album)

    def key(group: dict) -> tuple:
        score = group.get("score")
        secondary = group.get("secondary-types") or []
        return (
            bool(wanted) and _normalise(group.get("title") or "") == wanted,
            # A compilation scoring the same is nearly always a later repackage
            # of the record in the photo, and taking it stamps the reissue's
            # year on an original pressing. Only Compilation is demoted: "Live"
            # is a secondary type too, and a live album is an ordinary record.
            "Compilation" not in secondary,
            (group.get("primary-type") or "") == "Album",
            score if isinstance(score, int) else 0,
        )

    ranked = sorted(groups, key=key, reverse=True)
    # The floor trims the tail of same-artist noise, never the head: a weak best
    # match is still the best information there is, and emptying the list would
    # put the scan back to claiming it found nothing.
    return ranked[:1] + [
        g for g in ranked[1:]
        if isinstance(g.get("score"), int) and g["score"] >= MB_MIN_SCORE
    ]


def lookup_musicbrainz(artist: str, album: str) -> list[dict]:
    """Return up to 3 release-group candidates with year and artist country.

    An empty list means MusicBrainz has no such release. It raises
    MusicBrainzUnavailable when MusicBrainz could not be reached at all —
    the caller must not word that as "nothing matched".
    """
    if not artist:
        return []

    payload = _mb_get("/release-group/", {"query": _mb_query(artist, album),
                                          "limit": 5})
    groups = (payload or {}).get("release-groups") or []
    if not groups:
        return []

    candidates = []
    country_cache: dict = {}
    # Ranked before the cut, not after: the exact match is regularly not the
    # hit MusicBrainz put first, so truncating first can drop the right answer.
    for group in _rank_candidates(groups, album)[:3]:
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
            # Carried to the form so a Single or an EP can say so on the card
            # rather than looking like the LP the user is holding.
            "type": group.get("primary-type"),
        })
    return candidates


COVER_TIMEOUT = 4.0


def _download_image(url: str) -> str | None:
    """Download an image URL and return it as a base64 data URI."""
    try:
        response = requests.get(url, timeout=COVER_TIMEOUT)
    except requests.RequestException:
        # fetch_cover never raises; log so a persistently unreachable art
        # source is visible instead of just producing coverless candidates.
        logger.warning("Cover image download failed", exc_info=True)
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
        logger.warning(
            "iTunes artwork lookup failed for %r / %r", artist, album, exc_info=True
        )
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


def _record_usage(usage_out, model: str, response) -> None:
    """Append one call's token counts to a caller-supplied ledger.

    Never raises and never blocks the scan: accounting must not be able to
    fail a request the user already paid for. A response whose usage is absent
    or not countable is skipped rather than recorded as zero, so a missing row
    means "not measured" instead of "cost nothing".
    """
    if usage_out is None:
        return
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        logger.warning("No countable usage on the %s response", model)
        return
    usage_out.append({"model": model, "input_tokens": input_tokens,
                      "output_tokens": output_tokens})


def _sleeve_schema(genres: list[str]) -> dict:
    nullable_string = {"type": ["string", "null"]}
    return {
        "type": "object",
        "properties": {
            "artist": nullable_string,
            "album_name": nullable_string,
            # anyOf, NOT {"type": ["string","null"], "enum": genres}: `type` and
            # `enum` are ANDed, so null would fail the enum and be unreachable,
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


def extract_from_image(image_data_uri: str, genres: list[str],
                       usage_out: list | None = None) -> dict:
    """Read artist, album, genre, label and catalog number off a sleeve photo.

    Pass ``usage_out`` to have this call's token counts appended to it.
    """
    client = _anthropic_client()
    media_type, data = _media_type_and_data(image_data_uri)

    response = client.messages.create(
        model=VISION_MODEL,
        # Sonnet 5 runs adaptive thinking whenever `thinking` is omitted, and
        # thinking tokens come out of max_tokens. A tight ceiling can be spent
        # entirely on thinking, leaving no text block to parse. 16000 is the
        # documented default for non-streaming requests: a ceiling, not a spend.
        max_tokens=16000,
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
    # Recorded before the response is parsed, not after: the call was billed
    # the moment it came back, and a parse failure below must not lose the row.
    _record_usage(usage_out, VISION_MODEL, response)

    # output_config.format guarantees valid JSON only when the call succeeds;
    # truncation or an unexpected response shape must not escape as an opaque
    # StopIteration or JSONDecodeError.
    try:
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)
    except (StopIteration, ValueError) as e:
        raise RuntimeError(f"Could not parse sleeve extraction response: {e}") from e


def _genre_schema(genres: list[str]) -> dict:
    """JSON schema for classify_genre's single-field response.

    anyOf, NOT {"type": ["string","null"], "enum": genres}: `type` and `enum`
    are ANDed, so null would fail the enum and be unreachable, forcing the
    model to invent a genre it was told to omit.
    """
    return {
        "type": "object",
        "properties": {
            "genre": {"anyOf": [{"type": "string", "enum": genres},
                                 {"type": "null"}]},
        },
        "required": ["genre"],
        "additionalProperties": False,
    }


def classify_genre(artist: str, album: str, genres: list[str],
                   usage_out: list | None = None) -> str | None:
    """Pick the best-fitting genre from the collection's own vocabulary.

    Pass ``usage_out`` to have this call's token counts appended to it.
    """
    if not genres:
        return None
    try:
        client = _anthropic_client()
        response = client.messages.create(
            model=GENRE_MODEL,
            max_tokens=256,
            system="Classify the record into exactly one of the supplied "
                   "genres. Return null if none fit.",
            # No "effort" here: output_config.effort errors on Haiku 4.5 (and
            # Sonnet 4.5). It is only valid from Opus 4.5 / the 4.6+ family
            # upwards, so adding it back would 400 every genre call — and the
            # except below would swallow it. Structured outputs
            # (output_config.format) are fine on every model.
            output_config={
                "format": {"type": "json_schema", "schema": _genre_schema(genres)},
            },
            messages=[{"role": "user", "content": f"Artist: {artist}\nAlbum: {album}"}],
        )
        _record_usage(usage_out, GENRE_MODEL, response)
        text = next(b.text for b in response.content if b.type == "text")
        genre = json.loads(text).get("genre")
    except Exception:
        # classify_genre never raises — the scan degrades to an empty genre
        # field. Log it: an always-failing call (a rejected parameter, a bad
        # key) is otherwise indistinguishable from "no genre fits".
        logger.warning(
            "Genre classification failed for %r / %r", artist, album, exc_info=True
        )
        return None
    # Second line of defence: even though the schema constrains the model's
    # output, don't trust it blindly — only ever return a genre that is
    # actually in the caller's vocabulary.
    return genre if genre in genres else None


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
    # Resolve share-sheet short links first; a non-short link passes straight
    # through, and an unresolvable one falls back to the original so
    # parse_spotify_url still raises the ValueError the route turns into a 400.
    kind, spotify_id = parse_spotify_url(_resolve_short_link(url))
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
