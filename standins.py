"""Build a Spotify playlist that stands in for a record Spotify does not have.

Some records are not on Spotify as an album — a regional pressing, a
compilation nobody uploaded — but most of their songs are, scattered over
singles, best-ofs and reissues. A stand-in is a playlist of those songs, found
one by one by title and artist, with the record's cover and facts on it. Once
the owner links it to the record (app.py's match route), spotify_sync reads it
like any album: a playlist link already means "these tracks, in this order".

Everything here talks to Spotify through a spotify_sync.Client — the owner's
login, since a playlist belongs to a person.
"""

import io
import re
import urllib.parse

from PIL import Image, ImageOps

import cover_art
import scan
import spotify_sync

# Spotify refuses a description over 300 characters.
MAX_DESCRIPTION = 300
COVER_SIZE = 640
_SEARCH_LIMIT = 10
# Spotify caps an add at 100 URIs per request.
_BATCH = 100

# Wording that marks a take other than the studio one. A hit carrying it still
# counts — a song only out live beats no song — but loses to one without.
_VARIANT = re.compile(r"\b(live|ao vivo|en vivo|en directo|demo|remix|karaoke|instrumental|"
                      r"acoustic|acustico|rehearsal|session)\b")


# What joins the artists of a duo or a guest credit: "Elis Regina & Tom
# Jobim", "Kleiton e Kledir", "A feat. B". Bands named that way ("Earth, Wind
# & Fire") still match whole, since the full name is always tried too.
_ARTIST_JOIN = re.compile(r"\s*(?:&|,|\+|/|\bfeat\.?|\bft\.?|\bwith\b|\be\b|\band\b|\by\b)\s*",
                          re.IGNORECASE)


def _artists(artist):
    """The record's artist whole, then each artist a duo or guest credit names."""
    parts = [p for p in _ARTIST_JOIN.split(artist or "") if p and p.strip()]
    out = [(artist or "").strip()]
    out += [p.strip() for p in parts if p.strip() not in out]
    return out


def _credits(track):
    names = [a.get("name") or "" for a in track.get("artists") or []]
    return {scan._normalise(n) for n in names} | {scan._normalise(", ".join(names))}


def _variant(track):
    words = spotify_sync._norm(f"{track.get('name')} {(track.get('album') or {}).get('name')}",
                               strip_extras=False)
    return bool(_VARIANT.search(words))


def _hit(track):
    album = track.get("album") or {}
    return {"uri": track["uri"], "name": track.get("name") or "",
            "album": album.get("name") or "",
            "year": (album.get("release_date") or "")[:4],
            "image_url": spotify_sync._first_image(album.get("images"))}


def pick_hit(title, artist, album, items):
    """The search result that is this record's song, or None.

    A hit must credit the record's artist and be the same song once titles are
    folded (accents, case, " - Remastered" tails, bracketed words). Among hits:
    the record's own album first, then a studio take over a live/demo/remix,
    then an exact title over a folded one, then the earliest release.
    """
    want_artists = {scan._normalise(a) for a in _artists(artist)} - {""}
    strict = spotify_sync._norm(title, strip_extras=False)
    loose = spotify_sync._norm(title, strip_extras=True)
    own_album = spotify_sync._norm(album, strip_extras=True)
    if not loose:
        return None
    ranked = []
    for t in items or []:
        if not t or not t.get("uri") or not (want_artists & _credits(t)):
            continue
        exact = spotify_sync._norm(t.get("name"), strip_extras=False) == strict
        if not exact and spotify_sync._norm(t.get("name"), strip_extras=True) != loose:
            continue
        t_album = t.get("album") or {}
        ranked.append(((spotify_sync._norm(t_album.get("name"), strip_extras=True) != own_album,
                        _variant(t), not exact, t_album.get("release_date") or "9999"), t))
    if not ranked:
        return None
    ranked.sort(key=lambda pair: pair[0])
    return _hit(ranked[0][1])


def _quoted(value):
    # A double quote inside the field query would end it early.
    return (value or "").replace('"', " ").strip()


def _search(client, title, artist):
    query = urllib.parse.urlencode({
        "q": f'track:"{_quoted(title)}" artist:"{_quoted(artist)}"',
        "type": "track",
        "limit": _SEARCH_LIMIT,
    })
    return (client.call("GET", f"/search?{query}").get("tracks") or {}).get("items")


def find_song(client, title, artist, album):
    """A Spotify search for a song by the record's artist; its best hit or None.

    A duo's record ("A & B") is searched as written first; on a miss, again by
    its first artist, since Spotify credits the two separately.
    """
    names = _artists(artist)
    hit = pick_hit(title, artist, album, _search(client, title, names[0]))
    if hit is None and len(names) > 1:
        hit = pick_hit(title, artist, album, _search(client, title, names[1]))
    return hit


def preview(client, record):
    """Every song on the record's tracklist with its Spotify hit (or None), in order.

    `record` is a dict with artist, album_name and tracks (the parsed list of
    {side, title}). Untitled rows are skipped: there is nothing to search for.
    """
    out = []
    for song in record.get("tracks") or []:
        title = (song.get("title") or "").strip()
        if not title:
            continue
        out.append({"side": song.get("side") or "A", "title": title,
                    "hit": find_song(client, title, record.get("artist"), record.get("album_name"))})
    return out


def _one_line(value):
    return " ".join(str(value or "").split())


def description(record, found, total):
    """What the playlist says about the record, within Spotify's 300 characters."""
    head = f"{_one_line(record.get('artist'))} — {_one_line(record.get('album_name'))}"
    year = _one_line(record.get("year"))
    if year:
        head += f" ({year})"
    place = _one_line(record.get("bought_where"))
    parts = [head, _one_line(record.get("genre")), _one_line(record.get("country")),
             f"bought at {place}" if place else "",
             f"vinyl stand-in, {found} of {total} songs found", "Zucoloto vinyl collection"]
    text = " · ".join(p for p in parts if p)
    if len(text) > MAX_DESCRIPTION:
        text = text[:MAX_DESCRIPTION - 1].rstrip() + "…"
    return text


def cover_jpeg(image_bytes):
    """The record's cover as the square JPEG Spotify takes, or None if it cannot be read."""
    if not image_bytes:
        return None
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception:
        return None
    img = ImageOps.fit(img, (COVER_SIZE, COVER_SIZE), Image.LANCZOS)
    return cover_art.to_spotify_jpeg(img)


def create(client, name, description_text, uris, on_created):
    """Make the private playlist and fill it; returns its Spotify id.

    `on_created(spotify_id)` hears of it before anything is added, so a fill
    that fails partway leaves a playlist the app knows about, not an orphan.
    """
    spotify_id = client.call("POST", "/me/playlists", json={
        "name": name, "description": description_text, "public": False})["id"]
    on_created(spotify_id)
    for i in range(0, len(uris), _BATCH):
        client.call("POST", f"/playlists/{spotify_id}/items", json={"uris": uris[i:i + _BATCH]})
    return spotify_id
