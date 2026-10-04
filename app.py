import os, io, base64, csv, json, re, time, uuid, hashlib, hmac, threading, urllib.parse
# 64MB per field, not 10: note_images packs every photo on one record into a
# single field, where the old ceiling (sized for one cover) would reject a
# photo-heavy row on import — an export that cannot be restored. The whole-upload
# bound is MAX_CONTENT_LENGTH, not this.
csv.field_size_limit(64 * 1024 * 1024)
from flask import Flask, request, jsonify, send_file, session, render_template, stream_with_context, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.exceptions import NotFound
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from functools import wraps
from contextlib import contextmanager

import requests

import backup
import cover_art
import pricing
import scan
import playlist_filters
import spotify_sync
from genres import GENRES, canonical_genre


def _on_railway():
    return bool(os.environ.get("RAILWAY_ENVIRONMENT_NAME") or os.environ.get("RAILWAY_ENVIRONMENT"))

def _required_secret(name, dev_default):
    """A secret from the environment, with a fallback only off Railway.

    The fallbacks are in this public repo, so serving with one is serving with
    no secret at all: SECRET_KEY signs the session cookie, and whoever knows it
    can mint an `authed` cookie without ever touching the password. On Railway
    a missing, blank or default value therefore stops the boot, where it shows
    up in the deploy log, instead of quietly running unlocked.
    """
    value = (os.environ.get(name) or "").strip()
    if value and value != dev_default:
        return value
    if _on_railway():
        raise RuntimeError(f"{name} must be set to a non-default value in the Railway variables")
    return value or dev_default

app = Flask(__name__)
app.secret_key = _required_secret("SECRET_KEY", "change-me-in-production")

_default_sqlite_path = os.path.join(os.environ.get("DATA_DIR", "."), "vinyl.db")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", f"sqlite:///{_default_sqlite_path}")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
def _upload_ceiling_bytes():
    """Upload ceiling in bytes, from MAX_UPLOAD_MB.

    Covers ride along in the CSV as base64, so a collection export runs far
    larger than the record count suggests and the old fixed 32MB cap rejected
    it. A malformed value falls back to the default instead of raising: this
    runs at import time, so a typo in the Railway variable would otherwise be
    a boot loop rather than a legible error.

    Note the ceiling is not free capacity. The import reads the whole body,
    decodes it, and builds every row in memory before committing, costing
    roughly 8x the file size in RSS (a 120MB CSV peaks near 950MB). Raise this
    past ~64MB only if the process has the memory to match.
    """
    try:
        return max(1, int(os.environ.get("MAX_UPLOAD_MB", "128"))) * 1024 * 1024
    except ValueError:
        return 128 * 1024 * 1024

app.config["MAX_CONTENT_LENGTH"] = _upload_ceiling_bytes()

EDIT_PASSWORD = _required_secret("EDIT_PASSWORD", "vinyl123")

BACKUP_DIR = os.path.join(os.environ.get("DATA_DIR", "."), "backups")

db = SQLAlchemy(app)


def _cover_hash(cover):
    """Short content hash of a stored cover, used as its ETag and cache buster.

    Not a security boundary — it only has to change when the bytes change, so
    a truncated digest is plenty and keeps the URL readable.
    """
    return hashlib.sha256((cover or "").encode("utf-8")).hexdigest()[:16]

_NOTE_IMAGE_MAX_BYTES = 2 * 1024 * 1024


def _note_image_id(data):
    """A note image's primary key: the image is its own address.

    Deliberately not _cover_hash. A cover's URL is keyed by a record, so it
    changes meaning when the cover does and needs a ?v= buster. An image id is
    keyed by content, so /api/note-images/<id> can never mean anything else —
    which is what lets the response be immutably cached with no buster, and
    what makes two identical photos collapse to one row.
    """
    return hashlib.sha256((data or "").encode("utf-8")).hexdigest()[:32]

_NOTE_IMAGE_GRACE_SECONDS = 6 * 3600


def _note_image_ids(notes_json):
    """Every image id a notes column refers to.

    Forgiving on purpose: the column also holds legacy plain strings and notes
    written before images existed, and neither is an error.
    """
    try:
        parsed = json.loads(notes_json or "")
    except (TypeError, ValueError):
        return set()
    if not isinstance(parsed, list):
        return set()
    found = set()
    for note in parsed:
        if isinstance(note, dict):
            for image_id in note.get("images") or []:
                if isinstance(image_id, str) and image_id:
                    found.add(image_id)
    return found


def _public_notes(notes_json):
    """The notes column with every note marked private removed.

    The stripping lives here, on the server, because /api/records is public and
    ships this column verbatim: a private note hidden only by the browser is
    one View Source away from being read.

    Forgiving in the same way _note_image_ids is — a legacy plain-string column
    is not JSON and holds no flags, so it comes back untouched rather than
    being destroyed by a parse it was never meant to survive. Returns "" when
    nothing public is left, because "" is this column's empty value and every
    reader already treats it that way.
    """
    try:
        parsed = json.loads(notes_json or "")
    except (TypeError, ValueError):
        return notes_json or ""
    if not isinstance(parsed, list):
        return notes_json or ""
    # `is True` rather than truthiness: the flag is written by the client, and
    # a note is public unless it explicitly says otherwise.
    public = [n for n in parsed
              if not (isinstance(n, dict) and n.get("private") is True)]
    if len(public) == len(parsed):
        return notes_json or ""
    return json.dumps(public) if public else ""


def _image_is_public(image_id):
    """Is `image_id` held by at least one note a visitor is allowed to see?

    The LIKE narrows the candidates cheaply and _note_image_ids then confirms
    exactly, for the same reason the reaper does it that way: the id arrives
    from a URL, and a `%` or `_` in one would otherwise broaden the match. The
    confirm is exact, so a broadened LIKE can only cost work, never access.
    """
    return any(
        image_id in _note_image_ids(_public_notes(notes))
        for (notes,) in db.session.query(Record.notes)
                          .filter(Record.notes.like(f"%{image_id}%")).all())


def _reap_note_images(dropped_ids):
    """Delete images from `dropped_ids` that no note refers to any more.

    Call AFTER the record's own notes are committed, so the LIKE below sees the
    new truth and the record cannot be its own stale reference.

    The check is per-id rather than a blanket delete because content-hash ids
    dedupe: an image dropped from one record may still be the same photo on
    another, and deleting it would blank that one.
    """
    reaped = 0
    for image_id in dropped_ids:
        # LIKE narrows the candidates cheaply; _note_image_ids then confirms
        # exactly. The confirm matters because the ids come out of a
        # client-supplied JSON blob, and a `%` or `_` in one would otherwise
        # broaden the LIKE into matching notes that never mentioned this image
        # — leaving it permanently unreapable.
        still_used = any(
            image_id in _note_image_ids(notes)
            for (notes,) in db.session.query(Record.notes)
                              .filter(Record.notes.like(f"%{image_id}%")).all())
        if not still_used:
            NoteImage.query.filter(NoteImage.id == image_id).delete(
                synchronize_session=False)
            reaped += 1
    if reaped:
        db.session.commit()
    return reaped


def _sweep_note_images():
    """Delete images no note anywhere refers to, past the grace window.

    Catches photos uploaded into a form that was never saved. The window is
    what keeps it from deleting an image belonging to a form open right now.

    Queries ids rather than rows: loading every image's blob to decide what to
    delete would be the same mistake defer(Record.cover_data) exists to avoid.
    """
    referenced = set()
    for (notes,) in db.session.query(Record.notes).all():
        referenced |= _note_image_ids(notes)
    cutoff = (datetime.now() - timedelta(seconds=_NOTE_IMAGE_GRACE_SECONDS)
              ).strftime("%Y-%m-%dT%H:%M:%S")
    candidates = db.session.query(NoteImage.id).filter(NoteImage.created < cutoff).all()
    stale = [image_id for (image_id,) in candidates if image_id not in referenced]
    if stale:
        NoteImage.query.filter(NoteImage.id.in_(stale)).delete(synchronize_session=False)
        db.session.commit()
    return len(stale)


_SIDE_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_SIZES = {"", "7", "10", "12"}


def _disc_count(value, fallback=1):
    """A disc count is a whole number of discs, and there is always at least one."""
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return max(1, int(fallback or 1))


def _size(value):
    """An unknown size is '' — the collection genuinely does not know, and
    guessing 12" would put a fact in the database nobody checked."""
    v = str(value or "").strip()
    return v if v in _SIZES else ""


_SPOTIFY_URI   = re.compile(r"^spotify:([a-z]+):([A-Za-z0-9]+)$")
_SPOTIFY_WEB   = re.compile(r"^https?://open\.spotify\.com/(?:intl-[a-z]+/)?([a-z]+/[A-Za-z0-9]+)(?:[/?#].*)?$")


def _spotify_url(value):
    """Tidy a pasted Spotify link without ever rejecting one: a spotify: URI
    becomes its open.spotify.com URL, and the share sheet's ?si= tracking tail
    and locale segment are dropped. Anything else is stored as typed, since a
    scan can hand back any link and a refused save would lose it. Mirrors
    cleanLink in static/spotify.js."""
    v = str(value or "").strip()
    m = _SPOTIFY_URI.match(v)
    if m:
        return f"https://open.spotify.com/{m.group(1)}/{m.group(2)}"
    m = _SPOTIFY_WEB.match(v)
    return f"https://open.spotify.com/{m.group(1)}" if m else v


_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _hex_color(value):
    """A stored color is a bare '#rrggbb' or '' — '' means unpainted, which
    the renderer treats as black vinyl / white label rather than a color
    nobody chose. Anything that isn't a valid hex triplet is dropped rather
    than stored malformed, since it lands straight in a CSS custom property."""
    v = str(value or "").strip()
    return v if _HEX_COLOR.match(v) else ""


_PLACE_HTTP_PREFIX  = re.compile(r"^https?://", re.I)           # already an http(s) url
_PLACE_HOST_PORT    = re.compile(r"^[^\s:/?#]+:\d+(?:[/?#]|$)")  # host:port, not a scheme
_PLACE_OTHER_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")  # some other scheme — refuse
_PLACE_HTTP         = re.compile(r"^https?://(?:[^\s/?#@]+@)?[^\s/?#@:]+(?::\d+)?(?:[/?#][^\s]*)?$", re.I)


def _place_url(raw):
    """A place's link: '' for none, the normalized url, or None to refuse it.

    Mirrors normalizeUrl in static/places.js, and is the enforcing copy — the
    browser's is a courtesy so the form can complain before the round trip.
    The refusal matters: the drawer renders this value as an href, so a stored
    'javascript:' url would be a click target.

    host:port is distinguished from a scheme because both look like
    "token:something" — a bare colon alone can't tell them apart. A scheme
    token (RFC 3986) never starts with a digit right after the colon's
    prefix, but the real tell used here is what follows the colon: a run of
    digits (a port) versus letters (a scheme name like javascript, data,
    ftp). Treating 'tracksrio.com:8080' as a scheme would refuse a
    legitimate host:port link; treating every 'word:' as host:port would let
    'javascript:alert(1)' through as if 'javascript' were a hostname. So
    host:port is checked, and prepended with https://, before the general
    scheme check runs.

    A non-string, non-None `raw` (a number, list, dict, bool from a
    hand-rolled POST body) is refused with None rather than coerced to a
    string. normalizeUrl in the browser never faces this: it only ever reads
    input.value, which is always a string. This path is reachable only by a
    request that skipped the form, and for that caller a typed refusal is
    more honest than silently turning 12345 into a hostname — the enforcing
    copy is allowed to be the stricter of the two.
    """
    if raw is None:
        return ""
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return ""
    if _PLACE_HTTP_PREFIX.match(s):
        pass  # already http(s) — leave as typed
    elif _PLACE_HOST_PORT.match(s):
        s = "https://" + s
    elif _PLACE_OTHER_SCHEME.match(s):
        return None
    else:
        s = "https://" + s.lstrip("/")
    return s if _PLACE_HTTP.match(s) else None


def _clean_tracks(raw, disc_count, strict=True):
    """Validated tracks JSON, or ValueError naming what was wrong.

    A side letter outside the record's discs is refused rather than dropped: it
    is a song no surface would ever render, and swallowing it would hide the
    bug in the data instead of at the request that wrote it. An empty title is
    different — that is an unfilled row, and dropping it is what the form
    expects.

    `strict=False` is for CSV import only (see `_record_mapping`): a row there
    is a backup being restored, not a live request a user is waiting on, so an
    out-of-range side is DROPPED instead of aborting the whole import — the
    same DROP-not-abort trade `create_record`/`update_record` already make for
    an empty title. `strict` (the default) keeps rejecting with a ValueError
    for the live POST/PUT path, where a 400 that names the bad side is more
    useful than a track that silently disappeared.
    """
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        if strict:
            raise ValueError("tracks is not valid JSON")
        return ""  # a backup row's garbage is no tracklist, not an aborted import
    if not isinstance(parsed, list):
        if strict:
            raise ValueError("tracks must be a list")
        return ""

    allowed = set(_SIDE_LETTERS[: _disc_count(disc_count) * 2])
    out = []
    for t in parsed:
        if not isinstance(t, dict):
            continue
        title = str(t.get("title") or "").strip()
        if not title:
            continue
        side = str(t.get("side") or "").strip().upper()[:1]
        if side not in allowed:
            if strict:
                raise ValueError(
                    f"side {side!r} is not on a record with {_disc_count(disc_count)} disc(s)")
            continue
        row = {"side": side, "title": title}
        # The per-song artist names WHICH of a compilation's semicolon-separated
        # artists played this song. It is deliberately NOT checked against the
        # record's own artist column: a PUT may send tracks alone, long after
        # that column moved in some other request, and refusing then would leave
        # a stale tab unable to save. The picker in the form is what keeps the
        # two lists in step; here the name is only trimmed.
        artist = str(t.get("artist") or "").strip()
        if artist:
            row["artist"] = artist
        liked = str(t.get("liked_at") or "").strip()
        if liked:
            row["liked_at"] = liked
        out.append(row)
    return json.dumps(out) if out else ""

# Every dated field on a record — bought_date, play_dates, cleaned_dates and a
# note's date — holds the same two shapes, and the app only ever reads them, never
# computes on them, so they stay opaque strings here:
#
#   'YYYY-MM-DD'            recorded before times were kept. Ordered as midnight,
#                           but never shown with a clock — the collection does not
#                           know when in the day it happened.
#   'YYYY-MM-DDTHH:MM:SS'   a LOCAL wall clock, no zone suffix. What is written
#                           now, so the collection keeps the order things happened
#                           in. Deliberately not UTC: everything downstream reads
#                           the first 10 characters as the calendar day, and a UTC
#                           stamp files an evening event on the following day.
#
# static/grouping.js momentOf() is the one reader of these, and also converts the
# UTC stamps the play buttons wrote before this.
class Record(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    artist      = db.Column(db.String(200))
    album_name  = db.Column(db.String(200))
    year        = db.Column(db.String(10))
    genre       = db.Column(db.String(100))
    bought_date = db.Column(db.String(50))  # a stamp — see the note above
    bought_where= db.Column(db.String(200))
    bought_by   = db.Column(db.String(100))
    condition   = db.Column(db.String(10))  # '' | 'new' | 'used'
    my_rating   = db.Column(db.Float, default=0)
    wife_rating = db.Column(db.Float, default=0)
    have_it     = db.Column(db.Boolean, default=True)
    play_count  = db.Column(db.Integer, default=0)
    play_dates  = db.Column(db.Text)      # JSON array of stamps, one per play
    last_cleaned= db.Column(db.String(50))  # deprecated: superseded by cleaned_dates, kept for migration only
    cleaned_dates = db.Column(db.Text)    # JSON array of stamps, one per cleaning
    cover_data  = db.Column(db.Text)      # base64 data URI
    # Content hash of cover_data, maintained on every write. It exists so a
    # record can advertise its cover's URL without the blob being loaded:
    # to_dict() runs on a query that defers cover_data, and reading that column
    # there would lazy-load one ~155KB blob per row — the very cost this whole
    # arrangement removes. Also the cache buster; see record_cover().
    cover_hash  = db.Column(db.String(64))
    notes       = db.Column(db.Text)      # JSON array of {date: stamp, text: markdown}
    country     = db.Column(db.String(2)) # ISO 3166-1 alpha-2 country code, e.g. "BR", "US"
    # The songs, as JSON: [{side, title, liked_at?}]. The side LETTER carries
    # which disc a song is on — disc 1 is A/B, disc 2 is C/D — so a double
    # needs no nesting and no disc field per track. Small enough to ride in the
    # record list (a 26-song double is about 1KB), unlike the covers that had
    # to become a URL.
    tracks      = db.Column(db.Text)
    disc_count  = db.Column(db.Integer, default=1)
    size        = db.Column(db.String(5))   # '' | '7' | '10' | '12', in inches
    censored    = db.Column(db.Boolean, default=False)  # cover has explicit art; blurred client-side until revealed
    spotify_url = db.Column(db.String(500))  # free text: whatever link the scan or the user handed in
    spotify_missing = db.Column(db.Boolean, default=False)  # marked as not on Spotify; a link overrides it
    vinyl_color = db.Column(db.String(7))  # '#rrggbb' or unset — unset renders as black
    label_color = db.Column(db.String(7))  # '#rrggbb' or unset — unset renders as white

    def to_dict(self, private=True):
        """The record as the API sends it.

        `private=False` strips the notes marked admin-only — what a visitor
        gets. It defaults to True because every other caller (the write
        endpoints' responses, the CSV backup) is already behind auth and needs
        the whole truth.
        """
        return {
            "id": self.id,
            "artist": self.artist or "",
            "album_name": self.album_name or "",
            "year": self.year or "",
            "genre": self.genre or "",
            "bought_date": self.bought_date or "",
            "bought_where": self.bought_where or "",
            "bought_by": self.bought_by or "",
            "condition": self.condition or "",
            "my_rating": self.my_rating or 0,
            "wife_rating": self.wife_rating or 0,
            "have_it": bool(self.have_it),
            "play_count": self.play_count or 0,
            "play_dates": self.play_dates or "",
            "cleaned_dates": self.cleaned_dates or "",
            # Deliberately a URL, not the bytes. Inlining every cover as base64
            # made this endpoint a 45MB response that blocked the first paint.
            "cover_url": f"/api/records/{self.id}/cover?v={self.cover_hash}" if self.cover_hash else "",
            "notes": (self.notes or "") if private else _public_notes(self.notes),
            "country": self.country or "",
            "tracks": self.tracks or "",
            "disc_count": self.disc_count or 1,
            "size": self.size or "",
            "censored": bool(self.censored),
            "spotify_url": self.spotify_url or "",
            "spotify_missing": bool(self.spotify_missing) and not self.spotify_url,
            "vinyl_color": self.vinyl_color or "",
            "label_color": self.label_color or "",
        }

# One row per distinct note image, addressed by its own content hash.
#
# The bytes are here rather than in Record.notes because notes is NOT deferred
# in the record-list query and six client-side consumers read it straight off
# /api/records. Base64 in that column would rebuild the 45MB response the cover
# arrangement above exists to prevent.
class NoteImage(db.Model):
    id      = db.Column(db.String(32), primary_key=True)  # _note_image_id(data)
    data    = db.Column(db.Text)      # base64 data URI, same shape as cover_data
    created = db.Column(db.String(50))  # a stamp — the sweep's grace window reads it

# One clip per Features-tab card. Unlike NoteImage there is no content-hash id
# and no reaping: the slot set is fixed (one row per card on the tab), so a
# re-upload replaces the row in place rather than orphaning the old one. hash
# rides along exactly as Record.cover_hash does, so the manifest can hand out
# a URL that changes when the clip does — see /api/feature-media.
FEATURE_MEDIA_SLOTS = frozenset({"ai_scan", "spotify_match", "musicbrainz", "timeline_stats"})
_FEATURE_MEDIA_MAX_BYTES = 40 * 1024 * 1024

# A slot holds either uploaded bytes (data) or a YouTube video id (youtube_id),
# never both: the database can't sensibly hold a clip past the cap, so longer
# ones go up to YouTube as unlisted and the card embeds them instead.
class FeatureVideo(db.Model):
    slot       = db.Column(db.String(30), primary_key=True)
    data       = db.Column(db.Text)      # base64 data URI
    hash       = db.Column(db.String(64))
    created    = db.Column(db.String(50))
    youtube_id = db.Column(db.String(11))

_YOUTUBE_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com",
                  "youtu.be", "www.youtube-nocookie.com", "youtube-nocookie.com"}


def _youtube_id(url):
    """The 11-char video id out of any link form YouTube's share buttons hand
    out (watch?v=, youtu.be/, /shorts/, /embed/, /live/) or a bare id; None
    for anything else. The host is checked so a lookalike domain can't ride in."""
    from urllib.parse import urlparse, parse_qs
    url = (url or "").strip()
    if _YOUTUBE_ID.fullmatch(url):
        return url
    if "://" not in url:
        url = "https://" + url
    u = urlparse(url)
    if (u.hostname or "").lower() not in _YOUTUBE_HOSTS:
        return None
    if u.hostname.lower() == "youtu.be":
        candidate = u.path.strip("/").split("/")[0]
    elif u.path == "/watch":
        candidate = (parse_qs(u.query).get("v") or [""])[0]
    else:
        parts = u.path.strip("/").split("/")
        candidate = parts[1] if len(parts) >= 2 and parts[0] in ("shorts", "embed", "live") else ""
    return candidate if _YOUTUBE_ID.fullmatch(candidate) else None


def _youtube_embed(vid):
    return f"https://www.youtube-nocookie.com/embed/{vid}"

# A place a record was bought at. The NAME is the key, and record.bought_where
# holds it verbatim — so sort, group, filter, search, the scan autofill and the
# CSV all keep reading the column they always read, and this table only adds the
# link. The join is an exact match after trim, which is why every writer of
# bought_where trims.
class Place(db.Model):
    id   = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    url  = db.Column(db.String(500))

    def to_dict(self):
        return {"id": self.id, "name": self.name or "", "url": self.url or ""}

# One row per Claude API call a scan made. Anthropic publishes no balance or
# remaining-credits endpoint, so what this app spends is only knowable if this
# app writes it down — hence a ledger rather than a lookup.
class ScanSpend(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    scan_id       = db.Column(db.String(32))  # groups the calls of one scan
    at            = db.Column(db.String(50))  # a stamp — see the note above
    source        = db.Column(db.String(10))  # 'photo' | 'spotify'
    model         = db.Column(db.String(60))
    input_tokens  = db.Column(db.Integer, default=0)
    output_tokens = db.Column(db.Integer, default=0)
    cost_usd      = db.Column(db.Float, default=0.0)


# The owner's Spotify login, for the playlist sync. One row at most (id=1).
# Kept in the database rather than the session: Flask's session is a signed but
# readable cookie, and a refresh token is a standing key to the account.
class SpotifyAccount(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    refresh_token = db.Column(db.Text)
    display_name  = db.Column(db.String(200))
    connected_at  = db.Column(db.String(50))

# A record's Spotify link -> its album's tracklist, as JSON [{uri, name, disc}].
# Spotify dropped its batch album endpoint, so reading ~300 albums is ~300
# requests; a tracklist never changes, so each is read once and a re-sync only
# pays for the records added since.
class SpotifyAlbumCache(db.Model):
    link   = db.Column(db.String(500), primary_key=True)
    tracks = db.Column(db.Text)


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
    cover_url      = db.Column(db.String(500))

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
            "cover_url": self.cover_url or "",
        }


_LEGACY_PLAYLISTS = (
    ("Zucoloto Vinyl Collection", {"liked": False}),
    ("Zucoloto Vinyl Collection — Liked", {"liked": True}),
)


# One-off facts about this database, such as a seed that has already run.
class AppFlag(db.Model):
    key   = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.String(200))


_PLAYLISTS_SEEDED = "spotify_playlists_seeded"


def _seed_legacy_playlists():
    """The two playlists the app synced before filters existed, as saved rows.

    The rows and the flag saying so land in one commit: a boot that dies
    halfway leaves neither, and the next boot seeds again.
    """
    for name, raw in _LEGACY_PLAYLISTS:
        f = playlist_filters.normalize_filters(raw)
        key = playlist_filters.filter_key(f)
        if SpotifyPlaylist.query.filter_by(filter_key=key).first() is None:
            db.session.add(SpotifyPlaylist(
                name=name, filters=json.dumps(f), filter_key=key, legacy=True,
                created_at=datetime.now().strftime("%Y-%m-%dT%H:%M:%S")))
    if db.session.get(AppFlag, _PLAYLISTS_SEEDED) is None:
        db.session.add(AppFlag(key=_PLAYLISTS_SEEDED,
                               value=datetime.now().strftime("%Y-%m-%dT%H:%M:%S")))
    db.session.commit()


def _seed_legacy_playlists_once():
    """Seed unless this database ever was, so deleting both legacy rows sticks."""
    if db.session.get(AppFlag, _PLAYLISTS_SEEDED) is None:
        _seed_legacy_playlists()


@contextmanager
def _startup_lock():
    """Hold the boot-time schema work to one process at a time.

    gunicorn's workers each import this module, so without it two of them
    race through create_all, the ALTER TABLEs and the seeds against one
    database. The lock is released on exit: tests import the app again in
    the same process. Native Windows has no flock — and no gunicorn either.
    """
    data_dir = os.environ.get("DATA_DIR") or "."
    os.makedirs(data_dir, exist_ok=True)
    try:
        import fcntl
    except ImportError:
        yield
        return
    with open(os.path.join(data_dir, ".startup.lock"), "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)

with app.app_context(), _startup_lock():
    from sqlalchemy import inspect, text
    db.create_all()
    # lightweight auto-migration: db.create_all() only creates missing tables,
    # it won't add new columns to a table that already exists (e.g. on Railway's
    # persisted Postgres/SQLite). Add any columns that are missing.
    # Only record, feature_video and spotify_playlist are covered: a new
    # column on any other table needs its own entry here.
    inspector = inspect(db.engine)
    existing_cols = [c["name"] for c in inspector.get_columns("record")]
    missing_cols = {
        "country": "VARCHAR(2)",
        "play_dates": "TEXT",
        "cleaned_dates": "TEXT",
        "condition": "VARCHAR(10)",
        "cover_hash": "VARCHAR(64)",
        "tracks": "TEXT",
        "disc_count": "INTEGER",
        "size": "VARCHAR(5)",
        "censored": "BOOLEAN",
        "spotify_url": "VARCHAR(500)",
        "spotify_missing": "BOOLEAN",
        "vinyl_color": "VARCHAR(7)",
        "label_color": "VARCHAR(7)",
    }
    if "youtube_id" not in [c["name"] for c in inspector.get_columns("feature_video")]:
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE feature_video ADD COLUMN youtube_id VARCHAR(11)"))
            conn.commit()
    if "cover_url" not in [c["name"] for c in inspector.get_columns("spotify_playlist")]:
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE spotify_playlist ADD COLUMN cover_url VARCHAR(500)"))
            conn.commit()

    added_cleaned_dates = "cleaned_dates" not in existing_cols
    added_cover_hash = "cover_hash" not in existing_cols
    for col, ddl_type in missing_cols.items():
        if col not in existing_cols:
            with db.engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE record ADD COLUMN {col} {ddl_type}"))
                conn.commit()

    # one-time backfill: seed cleaned_dates from the old single-value last_cleaned
    # column for any row that hasn't been migrated yet
    if added_cleaned_dates:
        stale = Record.query.filter(
            Record.last_cleaned.isnot(None), Record.last_cleaned != "",
            (Record.cleaned_dates.is_(None)) | (Record.cleaned_dates == "")
        ).all()
        for r in stale:
            r.cleaned_dates = json.dumps([r.last_cleaned])
        if stale:
            db.session.commit()

    # one-time backfill: hash every existing cover, so rows written before this
    # column existed still advertise a cover_url. Done in batches by id rather
    # than with one .all(): the whole point of the column is that the blobs are
    # expensive, and loading all of them at boot to compute their hashes would
    # reproduce the very spike this avoids.
    if added_cover_hash:
        BATCH = 50
        last_id = 0
        while True:
            rows = (db.session.query(Record.id, Record.cover_data)
                    .filter(Record.id > last_id,
                            Record.cover_data.isnot(None), Record.cover_data != "")
                    .order_by(Record.id).limit(BATCH).all())
            if not rows:
                break
            db.session.bulk_update_mappings(Record, [
                {"id": rid, "cover_hash": _cover_hash(cover)} for rid, cover in rows])
            db.session.commit()
            last_id = rows[-1][0]

    # One-time backfill: the place table is empty, so seed it from the names
    # already in the collection. Links start empty — there is nowhere to get
    # them from. Distinct is case-sensitive on purpose: if the data holds both
    # 'Tracks' and 'tracks' this produces two places and the rename-merge in
    # PUT /api/places/<id> is how they get collapsed. Picking a canonical
    # casing here would silently rewrite records during a deploy.
    if Place.query.first() is None:
        names = {(n or "").strip() for (n,) in
                 db.session.query(Record.bought_where).distinct().all()}
        names.discard("")
        if names:
            db.session.execute(db.insert(Place),
                               [{"name": n, "url": ""} for n in sorted(names)])
            db.session.commit()

    _seed_legacy_playlists_once()

    # Photos uploaded into a form that was then abandoned have nothing pointing
    # at them and nothing that will ever call the save-time reap. This is the
    # only thing that collects them.
    _sweep_note_images()

# ── auth helpers ──────────────────────────────────────────────────────────────

def is_authed():
    return session.get("authed") is True

def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_authed():
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper

# ── pages ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    # Analytics is opt-in: with no website id the tracker is never rendered,
    # so local runs and the test suite report nothing. Read per request rather
    # than at import so a Railway variable change needs no code path reload.
    return render_template(
        "index.html",
        umami_website_id=os.environ.get("UMAMI_WEBSITE_ID", ""),
        umami_script_url=os.environ.get("UMAMI_SCRIPT_URL") or "https://cloud.umami.is/script.js",
        genres=GENRES,
    )

# ── auth endpoints ────────────────────────────────────────────────────────────

# Failed logins per client, kept in memory: a restart or a deploy forgets them,
# and each gunicorn worker counts on its own, so the real ceiling is
# LOGIN_MAX_FAILURES per worker. Still enough to turn a password guesser from
# thousands of tries a minute into a handful an hour.
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 15 * 60
_login_failures = {}  # client ip -> monotonic times of recent failures
_login_failures_lock = threading.Lock()

def _client_ip():
    # Railway's proxy appends the address it saw to X-Forwarded-For, so the
    # last entry is the real client; everything left of it is client-supplied.
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.remote_addr or "unknown"

def _recent_failures(ip, now):
    cutoff = now - LOGIN_WINDOW_SECONDS
    times = [t for t in _login_failures.get(ip, ()) if t > cutoff]
    if times:
        _login_failures[ip] = times
    else:
        _login_failures.pop(ip, None)
    return times

@app.route("/api/auth/login", methods=["POST"])
def login():
    ip = _client_ip()
    now = time.monotonic()
    with _login_failures_lock:
        failures = _recent_failures(ip, now)
        if len(failures) >= LOGIN_MAX_FAILURES:
            retry = int(failures[0] + LOGIN_WINDOW_SECONDS - now) + 1
            resp = jsonify({"error": "Too many attempts. Try again later."})
            resp.headers["Retry-After"] = str(retry)
            return resp, 429

    data = request.get_json(silent=True) or {}
    password = data.get("password")
    # compare_digest takes as long for a near miss as for a far one.
    if isinstance(password, str) and hmac.compare_digest(password.encode(), EDIT_PASSWORD.encode()):
        with _login_failures_lock:
            _login_failures.pop(ip, None)
        session["authed"] = True
        return jsonify({"ok": True})
    with _login_failures_lock:
        _login_failures.setdefault(ip, []).append(now)
    return jsonify({"error": "Wrong password"}), 403

@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/api/auth/status")
def auth_status():
    return jsonify({"authed": is_authed()})

# ── records API ───────────────────────────────────────────────────────────────

@app.route("/api/records")
def list_records():
    # defer(cover_data) is the load-bearing part: without it this query pulls
    # ~45MB of base64 through the process on every page load. to_dict() must
    # therefore never touch cover_data, or each row lazy-loads it right back.
    recs = (Record.query.options(defer(Record.cover_data))
            .order_by(Record.artist).all())
    # The only public read of the notes column. POST/PUT answer behind auth and
    # there is no GET for a single record, so this is the whole boundary.
    private = is_authed()
    return jsonify([r.to_dict(private=private) for r in recs])

@app.route("/api/places")
def list_places():
    # Public, like /api/records: the drawer and the crate headers need the link
    # for a visitor too, and a place name is already visible on every record.
    places = Place.query.order_by(func.lower(Place.name)).all()
    return jsonify([p.to_dict() for p in places])

def _ensure_place(name):
    """Put a bought_where value on the places list if it is not there already.

    The backfill above only runs on the boot that creates the table, and the
    record form still takes bought_where as free text — so without this, a shop
    first typed into a record after that boot would never appear in the places
    popup and could never be given a link. import_records_from_csv_rows already
    upserts places the same way.

    Matched case-insensitively, because POST /api/places refuses a name that
    clashes with an existing one only by case: a record write must not create
    through the back door what the API refuses at the front. The existing row
    keeps its own spelling; collapsing the two is what the rename-merge is for.
    """
    name = (name or "").strip()
    if not name:
        return
    if Place.query.filter(func.lower(Place.name) == name.lower()).first():
        return
    db.session.add(Place(name=name, url=""))

@app.route("/api/places", methods=["POST"])
@require_auth
def create_place():
    d = request.get_json(silent=True) or {}
    raw_name = d.get("name")
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if not name:
        return jsonify({"error": "a place needs a name"}), 400
    url = _place_url(d.get("url"))
    if url is None:
        return jsonify({"error": "a link has to be http:// or https://"}), 400
    clash = Place.query.filter(func.lower(Place.name) == name.lower()).first()
    if clash:
        return jsonify({"error": f"'{clash.name}' is already on the list"}), 409
    p = Place(name=name, url=url)
    db.session.add(p)
    db.session.commit()
    return jsonify(p.to_dict()), 201

@app.route("/api/places/<int:pid>", methods=["PUT"])
@require_auth
def update_place(pid):
    place = db.session.get(Place, pid)
    if place is None:
        raise NotFound()
    d = request.get_json(silent=True) or {}
    raw_name = d.get("name")
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if not name:
        return jsonify({"error": "a place needs a name"}), 400
    url = _place_url(d.get("url"))
    if url is None:
        return jsonify({"error": "a link has to be http:// or https://"}), 400

    # Every name this rename has to pull records off: the place's own old name,
    # plus the name of any place it is being merged into — but only the ones
    # that actually differ from the typed name. Typing a place's own existing
    # spelling verbatim (the natural way to merge onto it) must not count
    # those rows twice, so a name identical to `name` is excluded rather than
    # rewritten. One bulk UPDATE over the survivors' rowcount is the count:
    # with a single statement there's no second WHERE to double-match rows
    # the first one just renamed.
    absorbed = Place.query.filter(func.lower(Place.name) == name.lower(),
                                  Place.id != place.id).first()
    if absorbed:
        db.session.delete(absorbed)

    candidates = (place.name, absorbed.name) if absorbed else (place.name,)
    names_to_move = [n for n in candidates if n != name]
    updated = 0
    if names_to_move:
        updated = (Record.query.filter(Record.bought_where.in_(names_to_move))
                   .update({Record.bought_where: name},
                           synchronize_session=False))
    place.name = name
    place.url = url
    db.session.commit()
    return jsonify({"place": place.to_dict(), "records_updated": updated})

@app.route("/api/places/<int:pid>", methods=["DELETE"])
@require_auth
def delete_place(pid):
    """Remove a place. Any record still pointing at it by name has its
    bought_where blanked out rather than left dangling on a place that no
    longer exists — the same bulk UPDATE-by-name the rename-merge above uses,
    just onto "" instead of onto another place's name."""
    place = db.session.get(Place, pid)
    if place is None:
        raise NotFound()
    updated = (Record.query.filter(Record.bought_where == place.name)
               .update({Record.bought_where: ""}, synchronize_session=False))
    db.session.delete(place)
    db.session.commit()
    return jsonify({"records_updated": updated})

def get_record_or_404(rid):
    """A record by id, or a 404 — through Session.get rather than the legacy
    Query.get that get_or_404 still calls under SQLAlchemy 2.0."""
    record = db.session.get(Record, rid)
    if record is None:
        raise NotFound()
    return record


def _genre(value, current=None):
    """The GENRES spelling of value, or ValueError if it is not on the list.

    Blank is allowed. So is a record's own current genre (current), so a
    record still on a retired genre can have its other fields saved without
    being forced onto a new one in the same edit.
    """
    if current and value == current:
        return current
    if value is not None and not isinstance(value, str):
        raise ValueError("genre must be a string")
    genre = canonical_genre(value)
    if genre is None:
        raise ValueError(f"unknown genre {value!r}; pick one of the {len(GENRES)} genres")
    return genre


@app.route("/api/records", methods=["POST"])
@require_auth
def create_record():
    d = request.get_json(silent=True) or {}
    disc_count = _disc_count(d.get("disc_count"))
    try:
        tracks = _clean_tracks(d.get("tracks", ""), disc_count)
        genre = _genre(d.get("genre", ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    r = Record(
        artist      = d.get("artist",""),
        album_name  = d.get("album_name",""),
        year        = d.get("year",""),
        genre       = genre,
        bought_date = d.get("bought_date",""),
        bought_where= (d.get("bought_where","") or "").strip(),
        bought_by   = d.get("bought_by",""),
        condition   = d.get("condition",""),
        my_rating   = float(d.get("my_rating") or 0),
        wife_rating = float(d.get("wife_rating") or 0),
        have_it     = bool(d.get("have_it", True)),
        play_count  = int(d.get("play_count") or 0),
        play_dates  = d.get("play_dates",""),
        cleaned_dates = d.get("cleaned_dates",""),
        cover_data  = d.get("cover_data",""),
        cover_hash  = _cover_hash(d.get("cover_data","")) if d.get("cover_data") else None,
        notes       = d.get("notes",""),
        country     = (d.get("country") or "").strip().upper()[:2],
        tracks      = tracks,
        disc_count  = disc_count,
        size        = _size(d.get("size")),
        censored    = bool(d.get("censored", False)),
        spotify_url = _spotify_url(d.get("spotify_url")),
        spotify_missing = bool(d.get("spotify_missing", False)),
        vinyl_color = _hex_color(d.get("vinyl_color")),
        label_color = _hex_color(d.get("label_color")),
    )
    db.session.add(r)
    _ensure_place(r.bought_where)
    db.session.commit()
    return jsonify(r.to_dict()), 201

@app.route("/api/records/<int:rid>", methods=["PUT"])
@require_auth
def update_record(rid):
    r = get_record_or_404(rid)
    d = request.get_json(silent=True) or {}
    # Read before the assignment below overwrites it: what the record used to
    # point at is the only way to know what it just stopped pointing at.
    images_before = _note_image_ids(r.notes) if "notes" in d else set()
    if "genre" in d:
        try:
            r.genre = _genre(d["genre"], current=r.genre)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    for field in ["artist","album_name","year","bought_date","bought_by","condition"]:
        if field in d:
            setattr(r, field, d[field])
    # Trimmed, not passed through: the place table joins to this column by
    # exact name, so a stray space would orphan the record from its link.
    if "bought_where" in d:
        r.bought_where = (d["bought_where"] or "").strip()
        _ensure_place(r.bought_where)
    if "my_rating"   in d: r.my_rating   = float(d["my_rating"] or 0)
    if "wife_rating" in d: r.wife_rating  = float(d["wife_rating"] or 0)
    if "have_it"     in d: r.have_it      = bool(d["have_it"])
    if "play_count"  in d: r.play_count   = int(d["play_count"] or 0)
    if "play_dates"  in d: r.play_dates   = d["play_dates"]
    if "cleaned_dates" in d: r.cleaned_dates = d["cleaned_dates"]
    if "cover_data"  in d:
        r.cover_data = d["cover_data"]
        r.cover_hash = _cover_hash(d["cover_data"]) if d["cover_data"] else None
    if "notes"       in d: r.notes        = d["notes"]
    if "country"     in d: r.country      = (d["country"] or "").strip().upper()[:2]
    if "censored"    in d: r.censored     = bool(d["censored"])
    if "spotify_url" in d: r.spotify_url  = _spotify_url(d["spotify_url"])
    if "spotify_missing" in d: r.spotify_missing = bool(d["spotify_missing"])
    if "vinyl_color" in d: r.vinyl_color  = _hex_color(d["vinyl_color"])
    if "label_color" in d: r.label_color  = _hex_color(d["label_color"])
    # disc_count first: the tracks it is about to validate are checked against
    # it. A PUT that sends tracks alone is checked against what the record
    # already is, or every partial update to a double would reject its C side.
    disc_count_changed = "disc_count" in d
    if "disc_count"  in d: r.disc_count   = _disc_count(d["disc_count"], r.disc_count)
    if "size"        in d: r.size         = _size(d["size"])
    if "tracks"      in d:
        try:
            r.tracks = _clean_tracks(d["tracks"], r.disc_count)
        except ValueError as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 400
    elif disc_count_changed and r.tracks:
        # disc_count moved but this PUT did not also send tracks, so the
        # branch above never re-checked them. Without this, the STORED
        # tracks stay validated against the OLD disc_count forever: a PUT of
        # {disc_count: 1} alone could leave a track parked on side C — hidden
        # in the drawer, still counted by the liked chip, still firing in the
        # Calendar, and (per invariant 2.3) this is exactly the silent data
        # loss/orphaning the disc-count-lowering rule exists to prevent, so
        # it 400s instead of saving.
        try:
            r.tracks = _clean_tracks(r.tracks, r.disc_count)
        except ValueError as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 400
    db.session.commit()
    # After the commit, so the reap's "is anyone still using this" query sees
    # the notes that were just written rather than the ones being replaced.
    if images_before:
        _reap_note_images(images_before - _note_image_ids(r.notes))
    return jsonify(r.to_dict())

def _decode_data_uri(value):
    """(bytes, mimetype) for a stored data URI, or None if there is nothing to serve.

    Shared by covers and note images. Anything that is absent, not a data URI,
    or whose base64 payload is malformed is treated as having nothing to serve
    rather than raising: a broken image is an absent image, not a 500.
    """
    if not value or not value.startswith("data:"):
        return None
    header, _, payload = value.partition(",")
    if not payload:
        return None
    mime = header[len("data:"):].split(";")[0] or "image/jpeg"
    try:
        return base64.b64decode(payload), mime
    except Exception:
        return None


@app.route("/api/records/<int:rid>/cover")
def record_cover(rid):
    """Serve one record's cover as its own cacheable resource.

    Immutable caching is safe because the URL carries a content hash (see
    cover_url in Record.to_dict): editing a cover changes the hash, which
    changes the URL, which is a fresh cache entry. The `v` parameter is never
    read here — it only has to differ.
    """
    row = db.session.query(Record.cover_data).filter(Record.id == rid).first()
    decoded = _decode_data_uri(row[0]) if row else None
    if decoded is None:
        return jsonify({"error": "No cover"}), 404
    data, mime = decoded
    resp = app.response_class(data, mimetype=mime)
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    resp.set_etag(_cover_hash(row[0]))
    return resp.make_conditional(request)


@app.route("/api/note-images", methods=["POST"])
@require_auth
def create_note_image():
    """Store one note image and return its id.

    Idempotent by construction: the id is the content hash, so re-uploading the
    same photo returns the id that already exists and writes nothing.
    """
    d = request.get_json(silent=True) or {}
    data = d.get("data", "")
    if not isinstance(data, str) or not data.startswith("data:"):
        return jsonify({"error": "Not an image"}), 400
    # Measured encoded, because that is what gets stored.
    if len(data.encode("utf-8")) > _NOTE_IMAGE_MAX_BYTES:
        return jsonify({"error": "Image too large"}), 413
    if _decode_data_uri(data) is None:
        return jsonify({"error": "Not an image"}), 400
    image_id = _note_image_id(data)
    if db.session.get(NoteImage, image_id) is None:
        db.session.add(NoteImage(
            id=image_id, data=data,
            created=datetime.now().strftime("%Y-%m-%dT%H:%M:%S")))
        db.session.commit()
    return jsonify({"id": image_id}), 201


@app.route("/api/note-images/<image_id>")
def note_image(image_id):
    """Serve one note image.

    Immutable with no cache buster, unlike record_cover: the id IS the content
    hash, so this URL's bytes can never change. A different image is a
    different URL.
    """
    # A visitor may only see a photo some public note still holds. Not blanket
    # auth: photos on public notes have to keep loading for everyone. An image
    # no note holds yet — the form uploads before the note is saved — is
    # therefore edit-mode only, which is exactly who is composing it.
    if not is_authed() and not _image_is_public(image_id):
        return jsonify({"error": "No image"}), 404
    row = db.session.query(NoteImage.data).filter(NoteImage.id == image_id).first()
    decoded = _decode_data_uri(row[0]) if row else None
    if decoded is None:
        return jsonify({"error": "No image"}), 404
    data, mime = decoded
    resp = app.response_class(data, mimetype=mime)
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    resp.set_etag(image_id)
    return resp.make_conditional(request)


# ── feature-tab media (About/Features page) ─────────────────────────────────

@app.route("/api/feature-media")
def list_feature_media():
    """Which slots have a clip, and the (cache-busted) URL to fetch each one.

    Public — the whole point of the tab is that visitors see it without
    logging in. Only filled slots are listed; the page treats an absent key as
    an empty placeholder.

    A YouTube slot's URL is the embed URL itself; the page tells the two apart
    by that prefix.
    """
    rows = db.session.query(FeatureVideo.slot, FeatureVideo.hash, FeatureVideo.youtube_id).all()
    manifest = {}
    for slot, h, vid in rows:
        if vid:
            manifest[slot] = _youtube_embed(vid)
        elif h:
            manifest[slot] = f"/api/feature-media/{slot}?v={h}"
    return jsonify(manifest)


@app.route("/api/feature-media/<slot>")
def feature_media(slot):
    """Serve one slot's clip. Public, and immutable like record_cover: the `v`
    the manifest hands out is the content hash, so a stale cache entry can
    only be served under a URL nothing links to any more."""
    if slot not in FEATURE_MEDIA_SLOTS:
        return jsonify({"error": "Unknown slot"}), 404
    row = db.session.query(FeatureVideo.data).filter(FeatureVideo.slot == slot).first()
    decoded = _decode_data_uri(row[0]) if row else None
    if decoded is None:
        return jsonify({"error": "No video"}), 404
    data, mime = decoded
    resp = app.response_class(data, mimetype=mime)
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    resp.set_etag(_cover_hash(row[0]))
    return resp.make_conditional(request)


@app.route("/api/feature-media/<slot>", methods=["PUT"])
@require_auth
def upload_feature_media(slot):
    if slot not in FEATURE_MEDIA_SLOTS:
        return jsonify({"error": "Unknown slot"}), 404
    d = request.get_json(silent=True) or {}
    data = d.get("data", "")
    if not isinstance(data, str) or not data.startswith("data:"):
        return jsonify({"error": "Not a video"}), 400
    if len(data.encode("utf-8")) > _FEATURE_MEDIA_MAX_BYTES:
        return jsonify({"error": "File too large"}), 413
    if _decode_data_uri(data) is None:
        return jsonify({"error": "Not a video"}), 400
    h = _cover_hash(data)
    row = db.session.get(FeatureVideo, slot)
    if row is None:
        db.session.add(FeatureVideo(
            slot=slot, data=data, hash=h,
            created=datetime.now().strftime("%Y-%m-%dT%H:%M:%S")))
    else:
        row.data = data
        row.hash = h
        row.youtube_id = None
    db.session.commit()
    return jsonify({"slot": slot, "url": f"/api/feature-media/{slot}?v={h}"}), 201


@app.route("/api/feature-media/<slot>/youtube", methods=["PUT"])
@require_auth
def set_feature_youtube(slot):
    """Point a slot at a YouTube video (upload it as Unlisted — Private ones
    refuse to play for anyone but invited accounts). Drops any uploaded bytes."""
    if slot not in FEATURE_MEDIA_SLOTS:
        return jsonify({"error": "Unknown slot"}), 404
    d = request.get_json(silent=True) or {}
    vid = _youtube_id(d.get("url") if isinstance(d.get("url"), str) else "")
    if vid is None:
        return jsonify({"error": "Not a YouTube link"}), 400
    row = db.session.get(FeatureVideo, slot)
    if row is None:
        db.session.add(FeatureVideo(
            slot=slot, youtube_id=vid,
            created=datetime.now().strftime("%Y-%m-%dT%H:%M:%S")))
    else:
        row.youtube_id = vid
        row.data = None
        row.hash = None
    db.session.commit()
    return jsonify({"slot": slot, "url": _youtube_embed(vid)}), 201


@app.route("/api/feature-media/<slot>", methods=["DELETE"])
@require_auth
def delete_feature_media(slot):
    if slot not in FEATURE_MEDIA_SLOTS:
        return jsonify({"error": "Unknown slot"}), 404
    row = db.session.get(FeatureVideo, slot)
    if row is not None:
        db.session.delete(row)
        db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/records/<int:rid>", methods=["DELETE"])
@require_auth
def delete_record(rid):
    r = get_record_or_404(rid)
    # Read before the row goes: once it is deleted there is nothing left to ask
    # what it used to point at.
    images_before = _note_image_ids(r.notes)
    db.session.delete(r)
    db.session.commit()
    # After the commit, so the reap's "is anyone still using this" query sees a
    # world where this record is already gone.
    if images_before:
        _reap_note_images(images_before)
    return jsonify({"ok": True})

# ── scan (photo / Spotify autofill) ───────────────────────────────────────────

def _sse(event, payload):
    """One Server-Sent Events frame.

    separators keeps the JSON on a single line: a raw newline inside the data
    would terminate the frame early, and the client would see one event torn
    into two halves it cannot parse.
    """
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"

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
    # The fixed list, not the shelf's distinct genres: a record the migration
    # did not reach would otherwise keep a retired genre on offer to Claude.
    genres = GENRES

    source = "photo" if image else "spotify"
    # Filled by the Claude calls below and banked in the finally, so a scan
    # that dies after the API answered still records what it spent — the call
    # was billed the moment it returned, and nothing downstream refunds it.
    spent = []

    def run():
        """The whole pipeline, yielding one frame per stage.

        A generator rather than straight-line code so the streaming and JSON
        paths are the same pipeline: there is no second copy to drift.
        """
        # The whole pipeline runs inside one try/except: lookup_musicbrainz,
        # fetch_cover and find_duplicate are documented never to raise, but
        # that contract isn't airtight (e.g. a 200 with an unexpected JSON
        # shape can still blow up a caller). The route doesn't trust it
        # absolutely — any escape here must still degrade to a JSON error,
        # never a 500 HTML page.
        try:
            if image:
                yield _sse("step", {"id": "vision", "state": "run"})
                fields = scan.extract_from_image(image, genres, usage_out=spent)
                spotify_image = None
                yield _sse("step", {"id": "vision", "state": "done",
                                    "detail": f"{fields.get('artist') or '?'} — "
                                              f"{fields.get('album_name') or '?'}"})
            else:
                yield _sse("step", {"id": "spotify", "state": "run"})
                resolved = scan.extract_from_spotify(spotify_url)
                spotify_image = resolved.get("image_url")
                yield _sse("step", {"id": "spotify", "state": "done",
                                    "detail": f"{resolved['artist']} — {resolved['album_name']}"})
                yield _sse("step", {"id": "genre", "state": "run"})
                genre = scan.classify_genre(resolved["artist"], resolved["album_name"],
                                            genres, usage_out=spent)
                yield _sse("step", {"id": "genre", "state": "done", "detail": genre or "—"})
                fields = {"artist": resolved["artist"],
                          "album_name": resolved["album_name"],
                          "genre": genre, "label": None, "catalog_number": None}

            artist = fields.get("artist") or ""
            album = fields.get("album_name") or ""

            # A sleeve says nothing about Spotify, so a photo scan looks the
            # album up there to fill the link the form would otherwise leave
            # for the user to paste. A link scan already has its link. Never
            # raises: a miss or an outage just leaves the field empty.
            found_spotify_url = ""
            if image:
                yield _sse("step", {"id": "spotify_find", "state": "run"})
                found = scan.find_spotify_album(artist, album)
                if found:
                    found_spotify_url = found["url"]
                    spotify_image = found.get("image_url")
                yield _sse("step", {"id": "spotify_find",
                                    "state": "done" if found else "skip",
                                    "detail": "link added" if found
                                              else "not found on Spotify"})

            # Caught here rather than by the handlers below, which would
            # answer 502 and throw away a sleeve the vision call already read
            # and billed for. An unreachable MusicBrainz costs the year, the
            # country and the alternates — not the identification. It is a
            # normal, expected outcome that degrades to lookup_failed, never
            # an "error" event.
            #
            # Collected by the callback and drained after the call:
            # lookup_musicbrainz is not a generator, so it cannot yield.
            ticks = []
            yield _sse("step", {"id": "mb", "state": "run"})
            try:
                candidates = scan.lookup_musicbrainz(
                    artist, album, on_progress=lambda done, total: ticks.append((done, total)))
                lookup_failed = False
                for done, total in ticks:
                    yield _sse("step", {"id": "mb", "state": "run", "n": done, "of": total})
                yield _sse("step", {"id": "mb", "state": "done",
                                    "detail": f"{len(candidates)} pressing(s) found"
                                              if candidates else "no match on MusicBrainz"})
            except scan.MusicBrainzUnavailable:
                app.logger.warning("MusicBrainz unavailable for %r / %r", artist, album)
                candidates = []
                lookup_failed = True
                yield _sse("step", {"id": "mb", "state": "skip",
                                    "detail": "MusicBrainz unavailable — no year or alternates"})

            yield _sse("step", {"id": "cover", "state": "run"})
            for i, candidate in enumerate(candidates):
                yield _sse("step", {"id": "cover", "state": "run",
                                    "n": i + 1, "of": len(candidates)})
                candidate["cover_data"] = scan.fetch_cover(candidate, spotify_image)
            found = sum(1 for c in candidates if c.get("cover_data"))
            if candidates:
                yield _sse("step", {"id": "cover", "state": "done",
                                    "detail": f"{found} of {len(candidates)} had artwork"})
            else:
                yield _sse("step", {"id": "cover", "state": "skip",
                                    "detail": "nothing to fetch artwork for"})

            # Not sorted vinyl-first the way the search grid is: candidates[0]
            # is the best match, it fills the form and supplies the year, and
            # a badge must not get to decide which pressing the user is
            # holding.
            #
            # Spotify has everything, including albums that were never
            # records, and MusicBrainz having no release group for one leaves
            # nothing to badge — so the album itself gets a verdict too, and
            # the form can say so even when the candidate grid is empty.
            album_row = [{"mbid": None, "artist": artist, "album_name": album}]
            yield _sse("step", {"id": "vinyl", "state": "run"})
            scan.flag_vinyl(candidates or album_row, usage_out=spent)
            vinyl = (candidates or album_row)[0]["vinyl"]
            yield _sse("step", {"id": "vinyl", "state": "done", "detail": vinyl})

            yield _sse("step", {"id": "shelf", "state": "run"})
            existing = [{"id": r.id, "artist": r.artist or "",
                         "album_name": r.album_name or ""} for r in rows]
            duplicate = scan.find_duplicate(artist, album, existing)
            yield _sse("step", {"id": "shelf", "state": "done",
                                "detail": "already on your shelf" if duplicate
                                          else "not a duplicate"})

            year = candidates[0]["year"] if candidates else ""
            yield _sse("done", {
                "source": source,
                "artist": artist,
                "album_name": album,
                "genre": fields.get("genre") or "",
                # The album's own verdict, which survives an empty candidate
                # list — see flag_vinyl above.
                "vinyl": vinyl,
                "candidates": candidates,
                # An empty candidate list has two very different meanings and
                # the form has to word them differently: MusicBrainz has no
                # such release, or MusicBrainz could not be reached and
                # retrying is worth the user's time.
                "lookup_failed": lookup_failed,
                # Only a photo scan fills this; see find_spotify_album above.
                "spotify_url": found_spotify_url,
                "duplicate_of": {"id": duplicate["id"], "artist": duplicate["artist"],
                                 "album_name": duplicate["album_name"]} if duplicate else None,
                "search_string": " ".join(p for p in [artist, album, year, "vinyl cover"] if p),
            })
        except ValueError as e:
            yield _sse("error", {"error": str(e), "status": 400})
        except RuntimeError as e:
            message = str(e)
            yield _sse("error", {"error": message,
                                 "status": 503 if "not set" in message else 502})
        except Exception as e:
            yield _sse("error", {"error": str(e), "status": 502})
        finally:
            # Inside the generator, not the route: Flask closes the generator
            # when the client disconnects, and a cancelled scan was still
            # billed the moment the API answered.
            _record_scan_spend(source, spent)

    if "text/event-stream" in (request.headers.get("Accept") or ""):
        return app.response_class(stream_with_context(run()),
                                  mimetype="text/event-stream",
                                  headers={"Cache-Control": "no-cache",
                                           "X-Accel-Buffering": "no"})

    # The JSON path runs the same generator and keeps only its last frame, so
    # the two can never answer differently.
    last = None
    for frame in run():
        last = frame
    event, _, data = last.partition("\ndata: ")
    payload = json.loads(data.strip())
    if event == "event: error":
        return jsonify({"error": payload["error"]}), payload["status"]
    return jsonify(payload)

# ── scan spend ────────────────────────────────────────────────────────────────

# What one scan costs before any has been measured. Both are replaced by the
# running average as soon as the ledger has a scan of that source in it, so
# these only ever show on a fresh collection.
SEED_ESTIMATE_USD = {"photo": 0.006, "spotify": 0.0004, "search": 0.0005}

# How many past scans the estimate averages. Short enough that switching model
# or photo size shows up in the number within a few scans.
ESTIMATE_WINDOW = 20


def _record_scan_spend(source, spent):
    """Write one ledger row per API call the scan made.

    Never raises: this runs in the scan route's finally, and a bookkeeping
    failure must not turn a scan the user already paid for into an error.
    """
    if not spent:
        return
    scan_id = uuid.uuid4().hex
    at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    try:
        db.session.execute(db.insert(ScanSpend), [{
            "scan_id": scan_id,
            "at": at,
            "source": source,
            "model": call["model"],
            "input_tokens": call["input_tokens"],
            "output_tokens": call["output_tokens"],
            "cost_usd": pricing.cost_usd(
                call["model"], call["input_tokens"], call["output_tokens"]),
        } for call in spent])
        db.session.commit()
    except Exception:
        app.logger.warning("Could not record scan spend", exc_info=True)
        db.session.rollback()


def _scan_estimate(source):
    """Mean cost of the last ESTIMATE_WINDOW scans from this source.

    Grouped by scan_id, not by row: a scan is one or more API calls, and the
    form is quoting the price of a scan.
    """
    recent = (db.session.query(func.sum(ScanSpend.cost_usd))
              .filter(ScanSpend.source == source)
              .group_by(ScanSpend.scan_id)
              .order_by(func.max(ScanSpend.id).desc())
              .limit(ESTIMATE_WINDOW).all())
    if not recent:
        return SEED_ESTIMATE_USD[source]
    return sum(total for (total,) in recent) / len(recent)


def _spend_over(query):
    """(dollars, scans) for a ScanSpend query — scans counted, not calls."""
    cost, scans = query.with_entities(
        func.coalesce(func.sum(ScanSpend.cost_usd), 0.0),
        func.count(func.distinct(ScanSpend.scan_id)),
    ).one()
    return float(cost or 0.0), int(scans or 0)


@app.route("/api/scan/usage")
@require_auth
def scan_usage():
    """What scanning has cost. There is no credits balance to read — Anthropic
    publishes no such endpoint — so this reports spend from our own ledger."""
    month = datetime.now().strftime("%Y-%m")
    month_usd, month_scans = _spend_over(
        ScanSpend.query.filter(ScanSpend.at.startswith(month)))
    total_usd, total_scans = _spend_over(ScanSpend.query)
    return jsonify({
        "month": month,
        "month_usd": month_usd,
        "month_scans": month_scans,
        "total_usd": total_usd,
        "total_scans": total_scans,
        "estimate": {"photo": _scan_estimate("photo"),
                     "spotify": _scan_estimate("spotify"),
                     "search": _scan_estimate("search")},
    })

# ── search by name ────────────────────────────────────────────────────────────

# Records you can actually buy come first, and the rest stay listed underneath
# rather than being hidden: MusicBrainz's format data is thin enough that a
# hard filter would drop real pressings. Sorted server-side, not in the
# browser — searchPicked holds indices into this list and reads them back by
# index when the picks are added, so a client-side re-sort would quietly add
# the wrong records.
_VINYL_ORDER = {"confirmed": 0, "likely": 1, "none": 2}


@app.route("/api/search", methods=["POST"])
@require_auth
def search_records():
    """Releases matching a loose artist/album query.

    Unlike /api/scan this returns a LIST of releases rather than one record's
    fields, which is why it is its own route. Same streaming/JSON split as
    scan_record, and the same reason: one generator so the two paths cannot
    answer differently.
    """
    d = request.get_json(silent=True) or {}
    query = (d.get("query") or "").strip()

    rows = db.session.query(
        Record.id, Record.artist, Record.album_name, Record.genre
    ).all()

    # Filled by parse_search_query / flag_vinyl and banked in the finally —
    # same load-bearing reason as scan_record's `spent`: a call is billed the
    # moment it returns, so a client that hangs up mid-stream must not make
    # that spend vanish.
    spent = []

    def run():
        """The whole pipeline, yielding one frame per stage.

        Unlike /api/scan, an unreachable MusicBrainz is FATAL here: a scan
        still has a sleeve photo to show even with no year or alternates, but
        a search has nothing at all without MusicBrainz, so
        MusicBrainzUnavailable becomes an "error" event, never a "skip".
        lookup_artist returning None is a different thing entirely — a
        legitimate "no such artist" — so that one plus every stage after it
        degrades to "skip" and the stream still ends in a normal "done" with
        an empty results list, exactly like the JSON path's 200.
        """
        try:
            yield _sse("step", {"id": "parse", "state": "run"})
            parsed = scan.parse_search_query(query, usage_out=spent)
            yield _sse("step", {"id": "parse", "state": "done",
                                "detail": parsed["artist"] +
                                          (f" — {parsed['album']}" if parsed.get("album") else "")})

            yield _sse("step", {"id": "artist", "state": "run"})
            artist = scan.lookup_artist(parsed["artist"])
            if artist is None:
                yield _sse("step", {"id": "artist", "state": "skip",
                                    "detail": "no artist matched"})
            else:
                yield _sse("step", {"id": "artist", "state": "done",
                                    "detail": artist["name"]})

            # discography's "skip" fires only when there was no artist to ask
            # about at all — a call that ran and found zero releases is still
            # a "done", the same way scan's mb stage reports "no match" as
            # done rather than skip.
            yield _sse("step", {"id": "discography", "state": "run"})
            if artist is None:
                results = []
                yield _sse("step", {"id": "discography", "state": "skip",
                                    "detail": "no artist to search"})
            else:
                results = scan.lookup_discography(artist["mbid"], parsed["album"])
                yield _sse("step", {"id": "discography", "state": "done",
                                    "detail": f"{len(results)} release(s) found"
                                              if results else "no releases found"})

            # covers/vinyl/shelf all key off whether there is anything to work
            # on, not off why: an empty `results` means the same "nothing to
            # do" whether the artist was unmatched or the discography was
            # empty — mirrors scan's cover stage skipping on empty candidates
            # regardless of whether that emptiness came from a real miss or a
            # degraded mb lookup.
            yield _sse("step", {"id": "covers", "state": "run"})
            if results:
                scan.search_covers(results)
                found = sum(1 for r in results if r.get("cover_data"))
                yield _sse("step", {"id": "covers", "state": "done",
                                    "detail": f"{found} of {len(results)} had artwork"})
            else:
                yield _sse("step", {"id": "covers", "state": "skip",
                                    "detail": "nothing to fetch artwork for"})

            yield _sse("step", {"id": "vinyl", "state": "run"})
            if results:
                scan.flag_vinyl(results, arid=artist["mbid"], usage_out=spent)
                confirmed = sum(1 for r in results if r.get("vinyl") == "confirmed")
                yield _sse("step", {"id": "vinyl", "state": "done",
                                    "detail": f"{confirmed} confirmed on vinyl"})
            else:
                yield _sse("step", {"id": "vinyl", "state": "skip",
                                    "detail": "nothing to flag"})
            # Sorted unconditionally (a no-op on an empty list): matches the
            # JSON path, which only ever sorted after flag_vinyl ran.
            results.sort(key=lambda r: _VINYL_ORDER.get(r.get("vinyl"), 1))

            yield _sse("step", {"id": "shelf", "state": "run"})
            if results:
                existing = [{"id": r.id, "artist": r.artist or "",
                             "album_name": r.album_name or ""} for r in rows]
                dupes = 0
                for row in results:
                    row["duplicate_of"] = _search_duplicate(row, existing)
                    if row["duplicate_of"]:
                        dupes += 1
                yield _sse("step", {"id": "shelf", "state": "done",
                                    "detail": f"{dupes} already on your shelf"})
            else:
                yield _sse("step", {"id": "shelf", "state": "skip",
                                    "detail": "nothing to check"})

            yield _sse("done", {
                "query": query,
                "artist": artist["name"] if artist else None,
                "album": parsed["album"],
                "results": results,
            })
        except ValueError as e:
            yield _sse("error", {"error": str(e), "status": 400})
        except scan.MusicBrainzUnavailable:
            # Fatal here, unlike scan's mb stage: there is no sleeve reading
            # to fall back on, so the caller gets nothing and must be told to
            # retry rather than shown an empty results list.
            app.logger.warning("MusicBrainz unavailable for search %r", query)
            yield _sse("error", {"error": "Couldn't reach MusicBrainz — try again in "
                                          "a moment", "status": 502})
        except RuntimeError as e:
            message = str(e)
            yield _sse("error", {"error": message,
                                 "status": 503 if "not set" in message else 502})
        except Exception as e:
            yield _sse("error", {"error": str(e), "status": 502})
        finally:
            # Inside the generator, not the route: Flask closes the generator
            # when the client disconnects, and a cancelled search was still
            # billed the moment the API answered.
            _record_scan_spend("search", spent)

    if "text/event-stream" in (request.headers.get("Accept") or ""):
        return app.response_class(stream_with_context(run()),
                                  mimetype="text/event-stream",
                                  headers={"Cache-Control": "no-cache",
                                           "X-Accel-Buffering": "no"})

    # The JSON path runs the same generator and keeps only its last frame, so
    # the two can never answer differently.
    last = None
    for frame in run():
        last = frame
    event, _, data = last.partition("\ndata: ")
    payload = json.loads(data.strip())
    if event == "event: error":
        return jsonify({"error": payload["error"]}), payload["status"]
    return jsonify(payload)


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
    # (r or {}).get("artist") below assumes each entry is falsy or a dict; a
    # truthy non-dict (a bare string, say) raises AttributeError uncaught,
    # turning a bad request into a 500. Same class of bug as
    # parse_search_query's, and the same fix: reject it before the try.
    if not all(isinstance(r, dict) for r in releases):
        return jsonify({"error": "each release must be an object"}), 400
    if not releases:
        return jsonify({"genres": []})

    vocabulary = GENRES

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

# ── CSV import / export ───────────────────────────────────────────────────────

@app.route("/api/export")
@require_auth
def export_csv():
    # Behind auth because this is a backup: it carries covers, note photos and
    # the private notes verbatim, and one that silently dropped them would not
    # be a backup you could restore from.
    recs = Record.query.order_by(Record.artist).all()
    cols = ["id","artist","album_name","year","genre","bought_date","bought_where",
            "bought_where_url","bought_by","condition","my_rating","wife_rating","have_it","play_count","play_dates","cleaned_dates","cover_image_base64","notes","country","note_images","tracks","disc_count","size","vinyl_color","label_color"]
    # One dict for the whole export rather than a lookup per row: there are a
    # few dozen places against hundreds of records, and unlike the note images
    # below these are short strings, so holding them all costs nothing.
    place_urls = dict(db.session.query(Place.name, Place.url).all())

    def generate():
        yield ",".join(cols) + "\n"
        for r in recs:
            d = r.to_dict()
            # to_dict() reports a URL now, but a backup has to carry the bytes.
            d["cover_image_base64"] = r.cover_data or ""
            # The link belongs to the place, but the backup is one flat table,
            # so every row carries its place's link and the importer rebuilds
            # the place table from the pairs it sees.
            d["bought_where_url"] = place_urls.get((r.bought_where or "").strip(), "") or ""
            # Looked up per row rather than preloaded: this generator streams to
            # keep a whole-collection export off the heap, and a dict of every
            # image would put it straight back.
            image_ids = sorted(_note_image_ids(r.notes))
            images = dict(db.session.query(NoteImage.id, NoteImage.data)
                          .filter(NoteImage.id.in_(image_ids)).all()) if image_ids else {}
            d["note_images"] = json.dumps(images) if images else ""
            row = []
            for c in cols:
                v = str(d.get(c,""))
                if "," in v or '"' in v or "\n" in v:
                    v = '"' + v.replace('"','""') + '"'
                row.append(v)
            yield ",".join(row) + "\n"

    return app.response_class(stream_with_context(generate()), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=vinyl_collection.csv"})

# Rows are inserted in batches so a large restore never holds the whole
# collection on the heap at once. Covers are base64 data URIs, so a few hundred
# rows is already tens of MB — this is the knob that bounds it.
_IMPORT_BATCH_ROWS = 500


def _row_note_images(row):
    """{id: data uri} for one CSV row, or {} if the column is absent or broken.

    A CSV written before this feature simply has no column, which is not an
    error — and neither is a value that will not parse.
    """
    try:
        parsed = json.loads(row.get("note_images", "") or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {k: v for k, v in parsed.items()
            if isinstance(k, str) and isinstance(v, str) and v.startswith("data:")}


def _record_mapping(row):
    """Turn one CSV row into a Record column mapping."""
    cover = row.get("cover_image_base64","") or row.get("cover_data","")
    if cover and not cover.startswith("data:"):
        cover = "data:image/jpeg;base64," + cover
    cleaned_dates = row.get("cleaned_dates","")
    if not cleaned_dates and row.get("last_cleaned",""):
        cleaned_dates = json.dumps([row["last_cleaned"]])
    disc_count = _disc_count(row.get("disc_count"))
    return {
        "artist":      row.get("artist",""),
        "album_name":  row.get("album_name",""),
        "year":        row.get("year",""),
        "genre":       row.get("genre",""),
        "bought_date": row.get("bought_date",""),
        "bought_where":(row.get("bought_where","") or "").strip(),
        "bought_by":   row.get("bought_by",""),
        "condition":   row.get("condition",""),
        "my_rating":   float(row.get("my_rating") or 0),
        "wife_rating": float(row.get("wife_rating") or 0),
        "have_it":     row.get("have_it","").lower() in ("true","1","yes"),
        "play_count":  int(row.get("play_count") or 0),
        "play_dates":  row.get("play_dates",""),
        "cleaned_dates": cleaned_dates,
        "cover_data":  cover,
        "cover_hash":  _cover_hash(cover) if cover else None,
        "notes":       row.get("notes",""),
        "country":     (row.get("country","") or "").strip().upper()[:2],
        # A CSV written before this feature simply has no such column, which is
        # not an error — the same rule _row_note_images already follows.
        #
        # Unlike create_record/update_record, an invalid row here does not
        # 400 back to a human waiting on the request — it is a batch restore,
        # and rejecting one bad row would abort the whole import per
        # import_records_from_csv_rows' one-transaction contract. So this
        # DROPS an out-of-range track (strict=False) rather than raising: a
        # lossy restore of that one song beats a failed restore of everything.
        "tracks":      _clean_tracks(row.get("tracks",""), disc_count, strict=False),
        "disc_count":  disc_count,
        "size":        _size(row.get("size")),
        "vinyl_color": _hex_color(row.get("vinyl_color")),
        "label_color": _hex_color(row.get("label_color")),
    }


def import_records_from_csv_rows(rows):
    """Replace the whole collection from an iterable of CSV row dicts.

    Inserted in batches to bound memory, but still ONE transaction: the delete
    and every batch commit together at the end. A failure part-way therefore
    rolls back to the existing collection rather than leaving it half-replaced
    — this wipes the table first, so a partial import would be data loss.

    Note images are wiped and restored alongside: they are only reachable
    through a note, so any that survived a restore that removed their note
    would be unreachable rows nothing would ever collect.
    """
    Record.query.delete()
    NoteImage.query.delete()
    count = 0
    batch = []
    image_batch = []
    # Only ids, so this stays small however many rows name the same photo.
    seen_images = set()
    stamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    # name -> url, first non-empty url per name wins. Places are NOT wiped like
    # the records are: a link the CSV does not know about (a place added after
    # the export) is still true, and losing it would make a restore lossy in a
    # way the export cannot see.
    places_seen = {}

    def flush():
        if batch:
            db.session.execute(db.insert(Record), batch)
            batch.clear()
        if image_batch:
            db.session.execute(db.insert(NoteImage), image_batch)
            image_batch.clear()

    for row in rows:
        batch.append(_record_mapping(row))
        for image_id, data in _row_note_images(row).items():
            if image_id not in seen_images:
                seen_images.add(image_id)
                image_batch.append({"id": image_id, "data": data, "created": stamp})
        place_name = (row.get("bought_where","") or "").strip()
        if place_name:
            place_url = _place_url(row.get("bought_where_url")) or ""
            if place_url or place_name not in places_seen:
                places_seen.setdefault(place_name, "")
                if place_url:
                    places_seen[place_name] = place_url
        count += 1
        if len(batch) >= _IMPORT_BATCH_ROWS:
            flush()
    flush()
    if places_seen:
        existing = {p.name: p for p in
                    Place.query.filter(Place.name.in_(list(places_seen))).all()}
        for name, url in places_seen.items():
            p = existing.get(name)
            if p is None:
                db.session.add(Place(name=name, url=url))
            elif url:
                p.url = url
    db.session.commit()
    return count


def import_records_from_csv_text(text):
    """Import from a CSV already held in memory. Prefer the streaming path."""
    return import_records_from_csv_rows(csv.DictReader(io.StringIO(text)))


@app.route("/api/import", methods=["POST"])
@require_auth
def import_csv():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file"}), 400
    try:
        # Read the upload as a stream. Werkzeug spools anything large to a temp
        # file, so this stays off the heap; file.read().decode() used to make
        # three full-size copies of the CSV before parsing even began, which is
        # most of why a 120MB import peaked near 950MB of RSS.
        stream = io.TextIOWrapper(file.stream, encoding="utf-8",
                                  errors="replace", newline="")
        count = import_records_from_csv_rows(csv.DictReader(stream))
        return jsonify({"imported": count})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# ── Spotify playlists ─────────────────────────────────────────────────────────
# Two playlists on the owner's account mirror the collection: every album with
# a link, and only the liked songs. See spotify_sync.py for what each holds.

# How long one sync request may spend reading albums. Under gunicorn's 120s
# timeout with room for the playlist writes; the client calls again if it runs
# out, and the cache makes each call start where the last one stopped.
_SPOTIFY_READ_BUDGET = 60


def _spotify_redirect_uri():
    """Where Spotify sends the owner back. Must be registered on the app verbatim.

    Spotify accepts plain http only for a loopback IP; Railway terminates TLS at
    its proxy, so the request itself looks like http and would build the wrong
    URI. SPOTIFY_REDIRECT_URI overrides the guess outright.
    """
    explicit = os.environ.get("SPOTIFY_REDIRECT_URI")
    if explicit:
        return explicit
    uri = url_for("spotify_callback", _external=True)
    host = request.host.split(":")[0]
    if uri.startswith("http://") and host not in ("127.0.0.1", "[::1]"):
        uri = "https://" + uri[len("http://"):]
    return uri


def _spotify_account():
    return db.session.get(SpotifyAccount, 1)


@app.route("/api/spotify/account")
@require_auth
def spotify_account():
    acct = _spotify_account()
    return jsonify({
        "configured": spotify_sync.configured(),
        "connected": bool(acct and acct.refresh_token),
        "display_name": (acct.display_name if acct else "") or "",
        "redirect_uri": _spotify_redirect_uri(),
    })


@app.route("/api/spotify/connect")
@require_auth
def spotify_connect():
    if not spotify_sync.configured():
        return redirect("/?spotify=unconfigured")
    state = uuid.uuid4().hex
    session["spotify_state"] = state
    return redirect(spotify_sync.authorize_url(_spotify_redirect_uri(), state))


@app.route("/api/spotify/callback")
def spotify_callback():
    # A browser navigation, not a fetch: every outcome is a redirect back into
    # the app, which reads ?spotify= and reopens the playlists panel.
    if not is_authed():
        return redirect("/?spotify=unauthorized")
    expected = session.pop("spotify_state", None)
    if not expected or request.args.get("state") != expected:
        return redirect("/?spotify=failed")
    code = request.args.get("code")
    if not code:
        return redirect("/?spotify=denied")
    try:
        token = spotify_sync.exchange_code(code, _spotify_redirect_uri())
        client = spotify_sync.Client(token["refresh_token"])
        client._access = token["access_token"]
        me = client.call("GET", "/me")
    except (spotify_sync.SpotifyError, KeyError, requests.RequestException):
        app.logger.warning("Spotify connect failed", exc_info=True)
        return redirect("/?spotify=failed")
    acct = _spotify_account() or SpotifyAccount(id=1)
    acct.refresh_token = token["refresh_token"]
    acct.display_name = me.get("display_name") or me.get("id") or ""
    acct.connected_at = datetime.now().isoformat(timespec="seconds")
    db.session.add(acct)
    db.session.commit()
    return redirect("/?spotify=connected")


@app.route("/api/spotify/disconnect", methods=["POST"])
@require_auth
def spotify_disconnect():
    acct = _spotify_account()
    if acct:
        db.session.delete(acct)
        db.session.commit()
    return jsonify({"ok": True})


class _AlbumCache:
    """spotify_sync's cache interface over SpotifyAlbumCache, committing each
    album as it lands so a sync cut short keeps what it read."""

    def get(self, link):
        row = db.session.get(SpotifyAlbumCache, link)
        return json.loads(row.tracks) if row else None

    def put(self, link, tracks):
        db.session.merge(SpotifyAlbumCache(link=link, tracks=json.dumps(tracks)))
        db.session.commit()


def _playlist_has_records(f):
    """Whether any record passes `f` — with a hearted song, for a liked
    playlist. The same count the form's preview shows (playlist_filters.js)."""
    for r in playlist_filters.select(_playlist_records(), f):
        if not f.get("liked", True) or any(t.get("liked_at") for t in r["tracks"] if isinstance(t, dict)):
            return True
    return False


def _playlist_records():
    """Records with a Spotify link, owned or wishlist, oldest purchase first — so the
    playlist reads as the collection's own history and a new record's
    tracks land at the end, where a sync appends them anyway."""
    rows = (db.session.query(Record.id, Record.cover_hash, Record.artist, Record.album_name,
                             Record.spotify_url, Record.tracks, Record.year, Record.genre,
                             Record.my_rating, Record.wife_rating, Record.bought_where,
                             Record.bought_date, Record.have_it)
            .filter(Record.spotify_url.isnot(None), Record.spotify_url != "")
            .order_by(Record.bought_date, Record.id).all())
    out = []
    for (rid, cover_hash, artist, album, link, tracks, year, genre,
         my_rating, wife_rating, bought_where, bought_date, have_it) in rows:
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
                    "bought_date": bought_date, "have_it": bool(have_it)})
    return out


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
    """Non-empty values of a Record column, owned or wishlist, one per spelling-insensitive name."""
    seen = {}
    for (v,) in db.session.query(column).distinct().all():
        t = " ".join((v or "").split())
        if t and t.lower() not in seen:
            seen[t.lower()] = t
    return sorted(seen.values(), key=str.lower)


# Public: the Spotify tab shows visitors the playlists that exist on Spotify,
# as links. They get only what a link needs — the filters and the sync
# history are the owner's working state, like the form's genre/place choices.
@app.route("/api/spotify/playlists")
def spotify_playlists():
    rows = SpotifyPlaylist.query.order_by(SpotifyPlaylist.id).all()
    if not is_authed():
        return jsonify({"playlists": [
            {k: d[k] for k in ("id", "name", "filters", "summary", "url", "cover_url", "last_total")}
            for d in (r.to_dict() for r in rows) if d["url"]]})
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
    if not _playlist_has_records(f):
        return jsonify({"error": "no records match these filters — the playlist would be empty",
                        "field": "filters"}), 400
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

    def keep_new_id(new_id):
        # Stored before the playlist is filled: if filling fails, the next
        # sync finds this one instead of making another.
        row.spotify_id = new_id
        row.legacy = False
        db.session.commit()
    try:
        result = spotify_sync.sync(_spotify_client(acct), records, f.get("liked", True),
                                   _AlbumCache(), name=row.name, spotify_id=row.spotify_id,
                                   adopt_by_name=bool(row.legacy), deadline=deadline,
                                   on_created=keep_new_id)
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
    spotify = _spotify_client(acct)
    cover = _upload_generated_cover(spotify, row.spotify_id, f, result["total"])
    # Spotify takes a moment to process an upload (or to redraw its mosaic),
    # so the URL read back may still be the old picture until the next sync.
    try:
        row.cover_url = spotify_sync.playlist_cover(spotify, row.spotify_id) or row.cover_url
    except (spotify_sync.SpotifyError, spotify_sync.NotConnected, requests.RequestException):
        app.logger.info("Spotify playlist cover unavailable", exc_info=True)
    db.session.commit()
    return jsonify({**result, "cover": cover, "playlist": row.to_dict()})


def _upload_generated_cover(spotify, spotify_id, filters, total):
    """Draw the playlist's cover and set it on Spotify. Never fails the sync:
    "uploaded", "needs_reconnect" (a login from before covers asked for
    ugc-image-upload) or "failed"."""
    try:
        jpeg = cover_art.render(filters, total)
    except Exception:
        # A drawing bug must not undo a sync Spotify has already applied.
        app.logger.exception("Playlist cover could not be drawn")
        return "failed"
    try:
        spotify_sync.upload_cover(spotify, spotify_id, jpeg)
        return "uploaded"
    except spotify_sync.SpotifyError as e:
        if e.status in (401, 403):
            return "needs_reconnect"
        app.logger.warning("Spotify playlist cover upload failed", exc_info=True)
    except (spotify_sync.NotConnected, requests.RequestException):
        app.logger.warning("Spotify playlist cover upload failed", exc_info=True)
    return "failed"


@app.route("/api/spotify/playlists/<int:pid>", methods=["DELETE"])
@require_auth
def spotify_delete_playlist(pid):
    row = _playlist_or_404(pid)
    # A legacy row not yet synced has no id, but its playlist from before
    # this table is still on Spotify under its name.
    if row.spotify_id or row.legacy:
        acct = _spotify_account()
        if not acct or not acct.refresh_token:
            return _not_connected()
        try:
            client = _spotify_client(acct)
            spotify_id = row.spotify_id or spotify_sync.find_owned_by_name(client, row.name)
            if spotify_id:
                spotify_sync.delete_playlist(client, spotify_id)
        except spotify_sync.NotConnected:
            return _login_expired(acct)
        except (spotify_sync.SpotifyError, requests.RequestException) as e:
            app.logger.warning("Spotify playlist delete failed", exc_info=True)
            return jsonify({"error": str(e)}), 502
    db.session.delete(row)
    db.session.commit()
    return jsonify({"ok": True})

# ── spotify playlist → wishlist ───────────────────────────────────────────────
# The admin page's tool: read one of the owner's playlists, name each song's
# studio album, and offer the albums for the wishlist. Split in two routes
# because the MusicBrainz half is throttled to a call a second — a big
# playlist cannot be resolved inside gunicorn's 120 s, so the browser feeds
# the albums back to /resolve in chunks (see RESOLVE_CHUNK).

PLAYLIST_SCAN_CAP = 500


def _album_key(artist, album):
    return f"{scan._normalise(artist)}|{scan._normalise(album)}"


@app.route("/api/spotify/me/playlists")
@require_auth
def spotify_my_playlists():
    acct = _spotify_account()
    if not acct or not acct.refresh_token:
        return _not_connected()
    try:
        return jsonify({"playlists": spotify_sync.user_playlists(_spotify_client(acct))})
    except spotify_sync.NotConnected:
        return _login_expired(acct)
    except (spotify_sync.SpotifyError, requests.RequestException) as e:
        app.logger.warning("Spotify playlists could not be read", exc_info=True)
        return jsonify({"error": str(e)}), 502


@app.route("/api/spotify/wishlist-scan", methods=["POST"])
@require_auth
def spotify_wishlist_scan():
    d = request.get_json(silent=True) or {}
    playlist_id = str(d.get("playlist_id") or "").strip()
    if not playlist_id:
        return jsonify({"error": "pick a playlist first"}), 400
    acct = _spotify_account()
    if not acct or not acct.refresh_token:
        return _not_connected()

    spent = []
    try:
        try:
            tracks, truncated = spotify_sync.playlist_tracks(
                _spotify_client(acct), playlist_id, cap=PLAYLIST_SCAN_CAP)
        except spotify_sync.NotConnected:
            return _login_expired(acct)
        except (spotify_sync.SpotifyError, requests.RequestException) as e:
            return jsonify({"error": str(e)}), 502

        identified = scan.identify_albums(tracks, usage_out=spent)

        albums, by_key, unplaced = [], {}, 0
        for track, found in zip(tracks, identified):
            if not found.get("album"):
                unplaced += 1
                continue
            key = _album_key(found["artist"], found["album"])
            row = by_key.get(key)
            if row is None:
                row = by_key[key] = {
                    "key": key, "artist": found["artist"], "album_name": found["album"],
                    "year": found.get("year"), "songs": [],
                    "spotify_image": track.get("image_url") or "",
                    "unverified": bool(found.get("unverified")),
                    "duplicate_of": None, "have_it": None}
                albums.append(row)
            row["songs"].append(track["title"])

        owned = {r.id: r.have_it for r in Record.query.with_entities(Record.id, Record.have_it)}
        existing = [{"id": r.id, "artist": r.artist or "", "album_name": r.album_name or ""}
                    for r in Record.query.with_entities(Record.id, Record.artist, Record.album_name)]
        for row in albums:
            dup = _search_duplicate({"credited": row["artist"], "album_name": row["album_name"]},
                                    existing)
            if dup:
                row["duplicate_of"] = dup
                row["have_it"] = bool(owned.get(dup["id"]))

        return jsonify({"albums": albums, "truncated": truncated,
                        "unplaced": unplaced, "song_count": len(tracks)})
    finally:
        _record_scan_spend("playlist", spent)


# One chunk is at most what search_covers will fetch artwork for, so no row
# in a chunk comes back without a cover for want of budget — and 24 throttled
# MusicBrainz calls is about 25 s, far inside the worker timeout.
RESOLVE_CHUNK = scan.COVER_FETCH_LIMIT


def _spotify_image_url_ok(url):
    """Check if URL is safe to fetch as Spotify CDN fallback — client input must be validated."""
    if not url or not isinstance(url, str):
        return False
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        return False
    hostname = parsed.hostname or ""
    return hostname == "i.scdn.co" or hostname.endswith(".scdn.co") or hostname.endswith(".spotifycdn.com")


@app.route("/api/spotify/wishlist-scan/resolve", methods=["POST"])
@require_auth
def spotify_wishlist_resolve():
    d = request.get_json(silent=True) or {}
    albums = d.get("albums")
    if not isinstance(albums, list) or not albums:
        return jsonify({"error": "no albums to check"}), 400
    if len(albums) > RESOLVE_CHUNK:
        return jsonify({"error": f"at most {RESOLVE_CHUNK} albums per call"}), 400

    rows = [dict(a) for a in albums if isinstance(a, dict)]
    todo = [r for r in rows if not r.get("duplicate_of")]
    spent = []
    try:
        try:
            for row in todo:
                found = scan.resolve_album(row.get("artist") or "", row.get("album_name") or "")
                row["mbid"] = found["mbid"] if found else None
                if found and found.get("year"):
                    row["year"] = found["year"]
        except scan.MusicBrainzUnavailable:
            app.logger.warning("MusicBrainz unavailable for the wishlist scan")
            return jsonify({"error": "Couldn't reach MusicBrainz — try again in a moment"}), 502

        # search_covers and flag_vinyl both read artist / album_name / mbid,
        # which is exactly what these rows carry.
        scan.search_covers(todo)
        for row in todo:
            if not row.get("cover_data") and _spotify_image_url_ok(row.get("spotify_image")):
                row["cover_data"] = scan._download_image(row["spotify_image"])
        scan.flag_vinyl(todo, usage_out=spent)
        return jsonify({"albums": rows})
    finally:
        _record_scan_spend("playlist", spent)

# ── daily backups ─────────────────────────────────────────────────────────────

@app.route("/api/backups")
@require_auth
def list_backups():
    # Behind auth for the same reason /api/export is: a snapshot is the whole
    # database, private notes and all.
    return jsonify({"backups": backup.list_backups(BACKUP_DIR), "keep_days": backup.KEEP_DAYS})


@app.route("/api/backups/<name>")
@require_auth
def download_backup(name):
    # Only ever serve a name this module itself produced. Nothing else in the
    # folder — least of all the live vinyl.db one level up — is downloadable,
    # and the pattern leaves no room for a path to walk out of BACKUP_DIR.
    if not backup.NAME_RE.match(name):
        raise NotFound()
    path = os.path.join(BACKUP_DIR, name)
    if not os.path.isfile(path):
        raise NotFound()
    return send_file(path, as_attachment=True, download_name=name,
                     mimetype="application/vnd.sqlite3")


def start_backups(stop=None):
    """Start the daily snapshot thread, unless there is nothing to snapshot.

    Returns the thread, or None when backups are switched off or the database
    is not a local SQLite file. Railway injects DATABASE_URL into every service
    that has a database plugin attached, so the Postgres case is a real one and
    not hypothetical: there is no file to copy there, and a loop dutifully
    writing empty snapshots would be worse than no backups, because the folder
    would still look healthy.
    """
    if os.environ.get("BACKUP_ENABLED", "1") == "0":
        return None
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite:///"):
        return None
    return backup.start_scheduler(uri[len("sqlite:///"):], BACKUP_DIR, stop=stop)


start_backups()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

#
