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

from PIL import Image, ImageDraw, ImageOps

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


# The record in its sleeve, as the records page draws it (recordEdgeHTML): the
# sleeve keeps 86.5% of the width, and the wax — 97% of the sleeve for a 12" —
# peeks out of the right edge, resting on the bottom. Several discs climb in
# steps, back one furthest out.
_SLEEVE = 0.865
_WAX_12 = _SLEEVE * 0.97
_BG = (11, 11, 11)
_SS = 2  # supersampling for the wax, so its edge is smooth
_MAX_DISCS = 4


def _rgb(value, fallback):
    value = (value or "").strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", value):
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    return fallback


def _disc_colours(record, i):
    own = (record.get("disc_colors") or [])
    own = own[i] if i < len(own) and isinstance(own[i], dict) else {}
    return (_rgb(own.get("vinyl") or record.get("vinyl_color"), (0, 0, 0)),
            _rgb(own.get("label") or record.get("label_color"), (255, 255, 255)))


def _wax(diameter, vinyl, label):
    """One record, face on: grooved wax, a label, a spindle hole."""
    n = diameter * _SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    edge = tuple(min(255, round(c + (255 - c) * .3)) for c in vinyl)
    groove = tuple(min(255, round(c + (255 - c) * .08)) for c in vinyl)
    d.ellipse((0, 0, n - 1, n - 1), fill=vinyl, outline=edge, width=_SS)
    r = n / 2
    step = max(2 * _SS, n // 90)
    for k in range(int(r * .34), int(r) - 2 * _SS, step):
        d.ellipse((r - k, r - k, r + k, r + k), outline=groove, width=1)
    lr = r * .32
    d.ellipse((r - lr, r - lr, r + lr, r + lr), fill=label)
    hr = max(2.0, n * .045)
    d.ellipse((r - hr, r - hr, r + hr, r + hr), fill=_BG)
    return img.resize((diameter, diameter), Image.LANCZOS)


def cover_jpeg(image_bytes, record=None):
    """The record's cover as the square JPEG Spotify takes, or None if it cannot be read.

    With `record` (the to_dict() facts: size, disc_count, vinyl_color,
    label_color, disc_colors) the sleeve sits at the left with its discs
    sticking out of the right edge, as on the records page; without it, the
    cover alone fills the square.
    """
    if not image_bytes:
        return None
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception:
        return None
    if record is None:
        img = ImageOps.fit(img, (COVER_SIZE, COVER_SIZE), Image.LANCZOS)
        return cover_art.to_spotify_jpeg(img)

    sleeve = round(COVER_SIZE * _SLEEVE)
    top = (COVER_SIZE - sleeve) // 2
    canvas = Image.new("RGB", (COVER_SIZE, COVER_SIZE), _BG)
    try:
        inches = float(record.get("size") or 0)
    except (TypeError, ValueError):
        inches = 0.0
    count = min(_MAX_DISCS, max(1, int(record.get("disc_count") or 1)))
    # An unknown size is drawn as a 10", not a guessed 12" (the page dashes it).
    diameter = round(COVER_SIZE * _WAX_12 * (inches or 10) / 12)
    peek = COVER_SIZE - sleeve - round(COVER_SIZE * .01)
    room = sleeve - diameter - round(sleeve * .012)
    rise = min(round(COVER_SIZE * .045), room // (count - 1)) if count > 1 else 0
    for i in range(count - 1, -1, -1):
        vinyl, label = _disc_colours(record, i)
        x = sleeve + (peek - rise * i) - diameter
        y = top + sleeve - round(sleeve * .012) - diameter - rise * i
        wax = _wax(diameter, vinyl, label)
        canvas.paste(wax, (x, y), wax)
    canvas.paste(ImageOps.fit(img, (sleeve, sleeve), Image.LANCZOS), (0, top))
    return cover_art.to_spotify_jpeg(canvas)


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
