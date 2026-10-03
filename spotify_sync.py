"""Mirror the collection into two Spotify playlists on the owner's account.

scan.py talks to Spotify with client credentials: an app-only token that can
read the catalogue and nothing else. A playlist belongs to a person, so this
module runs the authorization-code flow instead and keeps the refresh token the
owner grants once.

Each playlist is a pure function of the collection: the caller picks the
records (playlist_filters.select) and says whether only hearted songs count.
A sync makes the playlist match that list exactly: missing tracks are
appended (so new records land at the end), and tracks that no longer qualify
— an unliked song, a removed link, a sold record — are taken out.

Endpoints follow Spotify's February 2026 API: POST /me/playlists to create,
/playlists/{id}/items (not /tracks) to read and edit, and the per-entry track
under `item`. There is no batch album endpoint any more, so every record costs
one request; album tracklists never change, so the caller caches them and a
second sync is nearly free.
"""

import base64
import os
import re
import time
import unicodedata
from urllib.parse import urlencode

import requests

import scan

API = "https://api.spotify.com/v1"
ACCOUNTS = "https://accounts.spotify.com"
TIMEOUT = 10.0
SCOPES = "playlist-read-private playlist-modify-private playlist-modify-public"

DESCRIPTION = "Made from the Zucoloto vinyl collection."

# Spotify caps both adds and removes at 100 URIs per request.
_BATCH = 100
# A Retry-After longer than this is not worth holding a gunicorn worker for.
_MAX_RETRY_WAIT = 10


class SpotifyError(RuntimeError):
    """Spotify answered with something this module cannot carry on from."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class NotConnected(SpotifyError):
    """The refresh token is gone or was revoked; the owner must connect again."""


class Incomplete(Exception):
    """The time budget ran out while reading albums.

    Nothing was written to the playlist. Every album read so far is already in
    the cache, so calling again picks up where this one stopped.
    """

    def __init__(self, done, total):
        super().__init__(f"read {done} of {total} albums")
        self.done = done
        self.total = total


# ── OAuth ─────────────────────────────────────────────────────────────────────

def _credentials():
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise SpotifyError("SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET are not set")
    return client_id, client_secret


def configured():
    return bool(os.environ.get("SPOTIFY_CLIENT_ID") and os.environ.get("SPOTIFY_CLIENT_SECRET"))


def authorize_url(redirect_uri, state):
    client_id, _ = _credentials()
    return f"{ACCOUNTS}/authorize?" + urlencode({
        "response_type": "code",
        "client_id": client_id,
        "scope": SCOPES,
        "redirect_uri": redirect_uri,
        "state": state,
    })


def _token_request(data):
    client_id, client_secret = _credentials()
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")
    response = requests.request(
        "POST", f"{ACCOUNTS}/api/token", data=data, timeout=TIMEOUT,
        headers={"Authorization": f"Basic {basic}",
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code != 200 or not payload.get("access_token"):
        # invalid_grant is a revoked or expired refresh token: nothing to retry.
        if payload.get("error") == "invalid_grant":
            raise NotConnected("Spotify no longer accepts the saved login")
        raise SpotifyError(f"Spotify token request failed ({response.status_code})")
    return payload


def exchange_code(code, redirect_uri):
    """Trade the callback's code for {access_token, refresh_token, ...}."""
    return _token_request({"grant_type": "authorization_code", "code": code,
                           "redirect_uri": redirect_uri})


class Client:
    """A user-authorised Spotify session built from a stored refresh token.

    Spotify may rotate the refresh token on any refresh; `on_new_refresh_token`
    is how the caller gets to persist the new one.
    """

    def __init__(self, refresh_token, on_new_refresh_token=None):
        self.refresh_token = refresh_token
        self.on_new_refresh_token = on_new_refresh_token
        self._access = None

    def _refresh(self):
        payload = _token_request({"grant_type": "refresh_token",
                                  "refresh_token": self.refresh_token})
        self._access = payload["access_token"]
        rotated = payload.get("refresh_token")
        if rotated and rotated != self.refresh_token:
            self.refresh_token = rotated
            if self.on_new_refresh_token:
                self.on_new_refresh_token(rotated)

    def call(self, method, path, **kwargs):
        url = path if path.startswith("https://") else f"{API}{path}"
        if self._access is None:
            self._refresh()
        refreshed = False
        for _ in range(4):
            response = requests.request(
                method, url, timeout=TIMEOUT,
                headers={"Authorization": f"Bearer {self._access}"}, **kwargs)
            if response.status_code == 401 and not refreshed:
                refreshed = True
                self._refresh()
                continue
            if response.status_code == 429:
                wait = int(response.headers.get("Retry-After", "1") or 1)
                if wait > _MAX_RETRY_WAIT:
                    raise SpotifyError(f"Spotify asked to wait {wait}s — try again later")
                time.sleep(wait)
                continue
            if response.status_code >= 400:
                raise SpotifyError(f"Spotify returned {response.status_code} for {method} {path}",
                                   status=response.status_code)
            if response.status_code == 204 or not response.content:
                return {}
            return response.json()
        raise SpotifyError(f"Spotify kept refusing {method} {path}")

    def pages(self, path):
        """Every item of a paging object, following `next`."""
        while path:
            page = self.call("GET", path)
            yield from page.get("items") or []
            path = page.get("next")


# ── what belongs in each playlist ─────────────────────────────────────────────

_PLAYLIST_LINK = re.compile(
    r"^(?:https?://open\.spotify\.com/(?:intl-[a-z]+/)?playlist/|spotify:playlist:)([A-Za-z0-9]+)",
    re.IGNORECASE)


def album_tracks(client, link):
    """The album behind a record's link: [{uri, name, disc}] in album order.

    A track link stands for its whole album — the record is the album. A
    playlist link is a compilation that is not an album on Spotify: its
    tracks, in playlist order, with no disc (they come from many albums).
    Raises ValueError for a link that is none of those.
    """
    link = scan._resolve_short_link(link)
    m = _PLAYLIST_LINK.match((link or "").strip())
    if m:
        out = []
        for entry in client.pages(f"/playlists/{m.group(1)}/items?limit=50&additional_types=track"):
            item = (entry or {}).get("item") or (entry or {}).get("track") or {}
            if item.get("uri") and item.get("type", "track") == "track":
                out.append({"uri": item["uri"], "name": item.get("name") or "", "disc": None})
        return out
    kind, spotify_id = scan.parse_spotify_url(link)
    if kind == "track":
        album = (client.call("GET", f"/tracks/{spotify_id}").get("album") or {})
        spotify_id = album.get("id")
        if not spotify_id:
            raise SpotifyError("Spotify returned a track with no album")
    return [{"uri": t["uri"], "name": t.get("name") or "", "disc": t.get("disc_number") or 1}
            for t in client.pages(f"/albums/{spotify_id}/tracks?limit=50")
            if t and t.get("uri")]


_BRACKETS = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
_NON_WORD = re.compile(r"[^a-z0-9]+")


def _norm(title, strip_extras):
    """Fold a title down to what two catalogues agree on.

    The vinyl's sleeve says "Satisfaction"; Spotify says "(I Can't Get No)
    Satisfaction - Mono Version". With strip_extras the " - …" tail and anything
    bracketed go, which is what lets those two meet.
    """
    t = unicodedata.normalize("NFKD", title or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    if strip_extras:
        t = t.split(" - ")[0]
        t = _BRACKETS.sub("", t)
    t = t.replace("&", " and ")
    return _NON_WORD.sub(" ", t).strip()


def _disc_of(side):
    """A/B are disc 1, C/D disc 2 — the same rule static/tracks.js uses."""
    s = (side or "A").strip().upper()[:1] or "A"
    return max(0, ord(s) - ord("A")) // 2 + 1


def match_track(title, side, candidates):
    """The Spotify track a tracklist song is, or None.

    Tries progressively looser comparisons and stops at the first that finds
    anything; among several hits the one on the song's own disc wins, which is
    what keeps a reprise on side D from landing on side A's original.
    """
    disc = _disc_of(side)
    tests = (
        lambda a, b: a == b,
        lambda a, b: a == b,
        lambda a, b: len(a) >= 4 and len(b) >= 4 and (a.startswith(b) or b.startswith(a)),
    )
    for step, same in enumerate(tests):
        mine = _norm(title, strip_extras=step > 0)
        if not mine:
            continue
        hits = [c for c in candidates if same(mine, _norm(c["name"], strip_extras=step > 0))]
        if hits:
            return next((c for c in hits if c["disc"] == disc), hits[0])
    return None


def _label(record):
    return f"{record.get('artist') or '?'} — {record.get('album_name') or '?'}"


def _skipped(record):
    """A report entry: enough for the panel to show which record it is."""
    return {"label": _label(record), "cover_url": record.get("cover_url") or ""}


def desired_tracks(client, records, liked, cache, deadline=None):
    """The ordered, de-duplicated track URIs a playlist should hold.

    `records` are dicts with artist, album_name, spotify_url, cover_url and
    tracks (the parsed tracklist). `cache` maps a link to its album_tracks() result —
    anything with get/put. Returns (uris, report); raises Incomplete when
    `deadline` (a time.monotonic() value) passes before every album is read.
    """
    if liked:
        records = [r for r in records if any(t.get("liked_at") for t in r.get("tracks") or [])]

    uris, seen = [], set()
    report = {"records": 0, "bad_links": [], "unmatched": []}
    for i, record in enumerate(records):
        link = (record.get("spotify_url") or "").strip()
        tracks = cache.get(link)
        if tracks is None:
            if deadline is not None and time.monotonic() > deadline:
                raise Incomplete(i, len(records))
            try:
                tracks = album_tracks(client, link)
            except ValueError:
                report["bad_links"].append(_skipped(record))
                continue
            except SpotifyError as e:
                # A pulled or mistyped album — or someone else's playlist
                # Spotify will not show us — is one record's problem, not the sync's.
                if e.status not in (400, 403, 404):
                    raise
                report["bad_links"].append(_skipped(record))
                continue
            cache.put(link, tracks)

        if not liked:
            picked = tracks
        else:
            picked, missing = [], []
            for song in record.get("tracks") or []:
                if not song.get("liked_at"):
                    continue
                hit = match_track(song.get("title"), song.get("side"), tracks)
                if hit:
                    picked.append(hit)
                else:
                    missing.append(song.get("title") or "?")
            if missing:
                report["unmatched"].append({**_skipped(record), "songs": missing})

        if picked:
            report["records"] += 1
        for t in picked:
            if t["uri"] not in seen:
                seen.add(t["uri"])
                uris.append(t["uri"])
    return uris, report


# ── the playlist itself ───────────────────────────────────────────────────────

def playlist_url(spotify_id):
    return f"https://open.spotify.com/playlist/{spotify_id}"


def playlist_cover(client, spotify_id):
    """The playlist's cover image URL (Spotify's mosaic, or one set by hand), or ""."""
    images = client.call("GET", f"/playlists/{spotify_id}/images") or []
    # Largest first, but a bare list may be unsorted or carry null sizes.
    images = sorted((i for i in images if i and i.get("url")),
                    key=lambda i: -(i.get("width") or 0))
    return images[0]["url"] if images else ""


def find_owned_by_name(client, name):
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


def playlist_uris(client, playlist_id):
    """The URIs on a playlist, in order. Local files and episodes have none we manage."""
    out = []
    for entry in client.pages(f"/playlists/{playlist_id}/items?limit=50&additional_types=track"):
        item = (entry or {}).get("item") or (entry or {}).get("track") or {}
        if item.get("uri"):
            out.append(item["uri"])
    return out


def mirror(client, playlist_id, desired):
    """Make the playlist hold exactly `desired`. Returns (added, removed) counts.

    Removal by URI drops every copy of a track, so a track sitting on the
    playlist twice is removed and then added back once.
    """
    current = playlist_uris(client, playlist_id)
    wanted = set(desired)
    counts = {}
    for u in current:
        counts[u] = counts.get(u, 0) + 1
    remove = [u for u in counts if u not in wanted or counts[u] > 1]
    keep = set(counts) - set(remove)
    add = [u for u in desired if u not in keep]

    for i in range(0, len(remove), _BATCH):
        client.call("DELETE", f"/playlists/{playlist_id}/items",
                    json={"items": [{"uri": u} for u in remove[i:i + _BATCH]]})
    for i in range(0, len(add), _BATCH):
        client.call("POST", f"/playlists/{playlist_id}/items", json={"uris": add[i:i + _BATCH]})
    removed = sum(1 for u in remove if u not in wanted)
    added = sum(1 for u in add if u not in counts)
    return added, removed


def sync(client, records, liked, cache, *, name, spotify_id=None, adopt_by_name=False,
         deadline=None, on_created=None):
    """Read the albums, then bring the playlist in line. Raises Incomplete first if out of time.

    `spotify_id` is the playlist this app made last time; a playlist deleted on
    Spotify since answers 404 and is made again. `adopt_by_name` is for the two
    playlists made before ids were stored: they are found by name, once.
    `on_created(spotify_id)` hears of a new playlist before anything is written
    to it, so a sync that fails partway does not leave it orphaned.
    """
    desired, report = desired_tracks(client, records, liked, cache, deadline)
    if not spotify_id and adopt_by_name:
        spotify_id = find_owned_by_name(client, name)
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
        if on_created:
            on_created(spotify_id)
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
