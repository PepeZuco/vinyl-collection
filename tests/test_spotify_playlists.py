"""The Spotify playlist sync: what each playlist holds, and how it is mirrored.

Spotify is replaced by FakeSpotify, a small in-memory account that answers the
handful of endpoints spotify_sync uses — under their February 2026 paths, so a
regression to the removed /tracks endpoints fails here rather than in prod.
"""

import json
import time
from unittest.mock import patch

import pytest

import spotify_sync


class _Response:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.content = b"" if body is None else json.dumps(body).encode()

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


ALBUMS = {
    "ALB1": [("Intro", 1), ("Satisfaction - Mono Version", 1), ("Outro", 1)],
    "ALB2": [("Reprise", 1), ("Song B", 1), ("Reprise", 2)],
}


class FakeSpotify:
    def __init__(self, playlists=None):
        self.playlists = playlists or {}   # id -> {"name", "uris"}
        self.calls = []
        self.refreshes = 0

    def request(self, method, url, headers=None, json=None, data=None, timeout=None, **kw):
        path = url.replace(spotify_sync.API, "")
        self.calls.append((method, path))
        if url.endswith("/api/token"):
            self.refreshes += 1
            return _Response(200, {"access_token": "AT", "expires_in": 3600})
        if path == "/me":
            return _Response(200, {"id": "me", "display_name": "Me"})
        if path.startswith("/me/playlists") and method == "GET":
            items = [{"id": pid, "name": p["name"], "owner": {"id": "me"},
                      "external_urls": {"spotify": f"https://open.spotify.com/playlist/{pid}"}}
                     for pid, p in self.playlists.items()]
            return _Response(200, {"items": items, "next": None})
        if path == "/me/playlists" and method == "POST":
            pid = f"PL{len(self.playlists) + 1}"
            self.playlists[pid] = {"name": json["name"], "uris": []}
            return _Response(201, {"id": pid, "name": json["name"],
                                   "external_urls": {"spotify": f"https://open.spotify.com/playlist/{pid}"}})
        if path.startswith("/tracks/"):
            return _Response(200, {"album": {"id": "ALB1"}})
        if path.startswith("/albums/"):
            aid = path.split("/")[2]
            if aid not in ALBUMS:
                return _Response(404, {"error": {"status": 404}})
            items = [{"uri": f"spotify:track:{aid}-{i}", "name": n, "disc_number": d}
                     for i, (n, d) in enumerate(ALBUMS[aid])]
            return _Response(200, {"items": items, "next": None})
        if path.startswith("/playlists/"):
            pid = path.split("/")[2].split("?")[0]
            pl = self.playlists[pid]
            assert "/items" in path, f"used a removed endpoint: {method} {path}"
            if method == "GET":
                return _Response(200, {"items": [{"item": {"uri": u}} for u in pl["uris"]],
                                       "next": None})
            if method == "POST":
                pl["uris"].extend(json["uris"])
                return _Response(201, {"snapshot_id": "s"})
            if method == "DELETE":
                gone = {i["uri"] for i in json["items"]}
                pl["uris"] = [u for u in pl["uris"] if u not in gone]
                return _Response(200, {"snapshot_id": "s"})
        raise AssertionError(f"unexpected Spotify call {method} {path}")


class DictCache(dict):
    def put(self, k, v):
        self[k] = v


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "secret")


@pytest.fixture
def fake():
    f = FakeSpotify()
    with patch.object(spotify_sync.requests, "request", side_effect=f.request):
        yield f


def rec(album, liked=(), link=None, tracks=None):
    tracks = tracks if tracks is not None else [
        {"side": "A", "title": t, "liked_at": "2026-09-01"} for t in liked]
    return {"artist": "Artist", "album_name": album,
            "spotify_url": link or f"https://open.spotify.com/album/{album}",
            "cover_url": f"/c/{album}", "tracks": tracks}


# ── matching a tracklist song to a Spotify track ──────────────────────────────

def _cands(*names):
    return [{"uri": f"u{i}", "name": n, "disc": 1} for i, n in enumerate(names)]


def test_match_ignores_case_accents_and_version_suffixes():
    cands = _cands("Intro", "Águas de Março - Remastered 2011")
    assert spotify_sync.match_track("aguas de marco", "A", cands)["uri"] == "u1"


def test_match_drops_bracketed_words():
    cands = _cands("(I Can't Get No) Satisfaction")
    assert spotify_sync.match_track("Satisfaction", "A", cands)["uri"] == "u0"


def test_match_prefers_the_songs_own_disc():
    cands = [{"uri": "d1", "name": "Reprise", "disc": 1},
             {"uri": "d2", "name": "Reprise", "disc": 2}]
    assert spotify_sync.match_track("Reprise", "C", cands)["uri"] == "d2"
    assert spotify_sync.match_track("Reprise", "B", cands)["uri"] == "d1"


def test_no_match_returns_none():
    assert spotify_sync.match_track("Nowhere", "A", _cands("Intro", "Outro")) is None


# ── sync ──────────────────────────────────────────────────────────────────────

def test_first_sync_creates_the_playlist_with_every_album_track(fake):
    client = spotify_sync.Client("RT")
    result = spotify_sync.sync(client, [rec("ALB1"), rec("ALB2")], "all", DictCache())

    assert result["created"] is True
    (pl,) = fake.playlists.values()
    assert pl["name"] == "Zucoloto Vinyl Collection"
    assert pl["uris"] == [f"spotify:track:ALB1-{i}" for i in range(3)] + \
                         [f"spotify:track:ALB2-{i}" for i in range(3)]
    assert result["total"] == 6 and result["records"] == 2
    assert ("POST", "/me/playlists") in fake.calls


def test_resync_adds_new_and_removes_what_no_longer_belongs(fake):
    fake.playlists["X"] = {"name": "Zucoloto Vinyl Collection",
                           "uris": ["spotify:track:ALB1-0", "spotify:track:GONE"]}
    client = spotify_sync.Client("RT")
    result = spotify_sync.sync(client, [rec("ALB1")], "all", DictCache())

    assert result["created"] is False
    assert len(fake.playlists) == 1, "a second playlist was created"
    assert fake.playlists["X"]["uris"] == ["spotify:track:ALB1-0",
                                           "spotify:track:ALB1-1", "spotify:track:ALB1-2"]
    assert (result["added"], result["removed"]) == (2, 1)


def test_unchanged_playlist_is_not_written(fake):
    fake.playlists["X"] = {"name": "Zucoloto Vinyl Collection",
                           "uris": [f"spotify:track:ALB1-{i}" for i in range(3)]}
    spotify_sync.sync(spotify_sync.Client("RT"), [rec("ALB1")], "all", DictCache())
    assert not [c for c in fake.calls if c[0] in ("POST", "DELETE") and "/playlists" in c[1]]


def test_liked_playlist_holds_only_liked_songs(fake):
    records = [
        rec("ALB1", liked=["Satisfaction", "Not On Spotify"]),
        rec("ALB2", tracks=[{"side": "C", "title": "Reprise", "liked_at": "x"},
                            {"side": "A", "title": "Song B"}]),
        rec("ALB1", liked=[], link="https://open.spotify.com/album/NOLIKES"),
    ]
    result = spotify_sync.sync(spotify_sync.Client("RT"), records, "liked", DictCache())

    pl = next(p for p in fake.playlists.values())
    assert pl["name"] == "Zucoloto Vinyl Collection — Liked"
    assert pl["uris"] == ["spotify:track:ALB1-1", "spotify:track:ALB2-2"]
    assert result["unmatched"] == [{"label": "Artist — ALB1", "cover_url": "/c/ALB1",
                                    "songs": ["Not On Spotify"]}]
    # A record with nothing liked costs no request at all.
    assert not any("NOLIKES" in path for _, path in fake.calls)


def test_track_link_stands_for_its_album(fake):
    record = rec("ALB1", link="https://open.spotify.com/track/T1?si=abc")
    spotify_sync.sync(spotify_sync.Client("RT"), [record], "all", DictCache())
    assert next(iter(fake.playlists.values()))["uris"][0] == "spotify:track:ALB1-0"


def test_bad_and_missing_links_are_skipped_not_fatal(fake):
    records = [rec("ALB1"),
               rec("x", link="https://open.spotify.com/artist/ZZ"),
               rec("MISSING")]
    result = spotify_sync.sync(spotify_sync.Client("RT"), records, "all", DictCache())
    assert [b["label"] for b in result["bad_links"]] == ["Artist — x", "Artist — MISSING"]
    assert result["bad_links"][0]["cover_url"] == "/c/x"
    assert result["total"] == 3


def test_duplicate_records_add_each_track_once(fake):
    spotify_sync.sync(spotify_sync.Client("RT"), [rec("ALB1"), rec("ALB1")], "all", DictCache())
    assert len(next(iter(fake.playlists.values()))["uris"]) == 3


def test_out_of_time_writes_nothing_and_keeps_what_it_read(fake):
    cache = DictCache()
    with pytest.raises(spotify_sync.Incomplete) as e:
        spotify_sync.sync(spotify_sync.Client("RT"), [rec("ALB1"), rec("ALB2")], "all",
                          cache, deadline=time.monotonic() - 1)
    assert (e.value.done, e.value.total) == (0, 2)
    assert fake.playlists == {}

    cache.put("https://open.spotify.com/album/ALB1", [{"uri": "c", "name": "c", "disc": 1}])
    with pytest.raises(spotify_sync.Incomplete) as e:
        spotify_sync.sync(spotify_sync.Client("RT"), [rec("ALB1"), rec("ALB2")], "all",
                          cache, deadline=time.monotonic() - 1)
    assert e.value.done == 1, "a cached album was not counted as read"


def test_revoked_login_raises_not_connected():
    bad = _Response(400, {"error": "invalid_grant"})
    with patch.object(spotify_sync.requests, "request", return_value=bad):
        with pytest.raises(spotify_sync.NotConnected):
            spotify_sync.Client("RT").call("GET", "/me")


# ── routes ────────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    import app as app_module
    with app_module.app.app_context():
        app_module.SpotifyAccount.query.delete()
        app_module.SpotifyAlbumCache.query.delete()
        app_module.Record.query.delete()
        app_module.db.session.commit()
    c = app_module.app.test_client()
    with c.session_transaction() as s:
        s["authed"] = True
    return c


def _connect(app_module):
    with app_module.app.app_context():
        app_module.db.session.add(app_module.SpotifyAccount(id=1, refresh_token="RT",
                                                            display_name="Me"))
        app_module.db.session.add(app_module.Record(
            artist="A", album_name="One", have_it=True,
            spotify_url="https://open.spotify.com/album/ALB1"))
        app_module.db.session.add(app_module.Record(
            artist="A", album_name="Wish", have_it=False,
            spotify_url="https://open.spotify.com/album/ALB2"))
        app_module.db.session.commit()


def test_visitors_cannot_sync_or_connect():
    import app as app_module
    c = app_module.app.test_client()
    assert c.post("/api/spotify/playlists/all").status_code == 401
    assert c.get("/api/spotify/connect").status_code == 401
    assert c.get("/api/spotify/account").status_code == 401


def test_sync_without_a_login_asks_to_connect(client):
    r = client.post("/api/spotify/playlists/all")
    assert r.status_code == 409 and r.get_json()["connect"] is True


def test_unknown_playlist_kind_is_404(client):
    assert client.post("/api/spotify/playlists/everything").status_code == 404


def test_connect_redirects_to_spotify_with_a_state(client):
    r = client.get("/api/spotify/connect")
    assert r.status_code == 302
    assert r.location.startswith("https://accounts.spotify.com/authorize?")
    assert "playlist-modify-private" in r.location
    with client.session_transaction() as s:
        assert s["spotify_state"] in r.location


def test_callback_with_a_forged_state_is_refused(client):
    with client.session_transaction() as s:
        s["spotify_state"] = "real"
    r = client.get("/api/spotify/callback?code=c&state=forged")
    assert r.location.endswith("/?spotify=failed")


def test_callback_saves_the_login(client, fake):
    import app as app_module
    with client.session_transaction() as s:
        s["spotify_state"] = "st"
    with patch.object(spotify_sync, "exchange_code",
                      return_value={"access_token": "AT", "refresh_token": "RT2"}):
        r = client.get("/api/spotify/callback?code=c&state=st")
    assert r.location.endswith("/?spotify=connected")
    with app_module.app.app_context():
        acct = app_module.db.session.get(app_module.SpotifyAccount, 1)
        assert (acct.refresh_token, acct.display_name) == ("RT2", "Me")
    assert client.get("/api/spotify/account").get_json()["connected"] is True


def test_sync_route_mirrors_owned_records_only_and_caches_albums(client, fake):
    import app as app_module
    _connect(app_module)
    r = client.post("/api/spotify/playlists/all")
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["created"] is True and d["total"] == 3
    assert all("ALB1" in u for u in next(iter(fake.playlists.values()))["uris"]), \
        "a wishlist record reached the playlist"

    fake.calls.clear()
    assert client.post("/api/spotify/playlists/all").get_json()["created"] is False
    assert not any(p.startswith("/albums/") for _, p in fake.calls), "album was re-read"


def test_sync_route_reports_progress_when_out_of_time(client, fake, monkeypatch):
    import app as app_module
    _connect(app_module)
    monkeypatch.setattr(app_module, "_SPOTIFY_READ_BUDGET", -1)
    r = client.post("/api/spotify/playlists/all")
    assert r.status_code == 202
    assert r.get_json() == {"incomplete": True, "done": 0, "total": 1}
