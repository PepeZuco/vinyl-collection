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
        if path.startswith("/playlists/COMP/items") and method == "GET":
            # Someone else's compilation playlist: tracks from many albums.
            return _Response(200, {"items": [
                {"item": {"uri": "spotify:track:C1", "name": "Ain't No Sunshine", "type": "track"}},
                {"item": {"uri": "spotify:episode:E1", "name": "A podcast", "type": "episode"}},
                {"item": {"uri": "spotify:track:C2", "name": "Lovely Day", "type": "track"}}],
                "next": None})
        if path.startswith("/playlists/"):
            pid = path.split("/")[2].split("?")[0]
            if pid not in self.playlists:
                return _Response(404, {"error": {"status": 404}})
            pl = self.playlists[pid]
            if path.startswith(f"/playlists/{pid}/followers") and method == "DELETE":
                del self.playlists[pid]
                return _Response(200)
            if path == f"/playlists/{pid}/images" and method == "GET":
                return _Response(200, [{"url": f"https://mosaic.scdn.co/640/{pid}", "width": 640},
                                       {"url": f"https://mosaic.scdn.co/60/{pid}", "width": 60}])
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
    result = spotify_sync.sync(client, [rec("ALB1"), rec("ALB2")], False, DictCache(), name="Every")

    assert result["created"] is True
    (pl,) = fake.playlists.values()
    assert pl["name"] == "Every"
    assert pl["uris"] == [f"spotify:track:ALB1-{i}" for i in range(3)] + \
                         [f"spotify:track:ALB2-{i}" for i in range(3)]
    assert result["total"] == 6 and result["records"] == 2
    assert ("POST", "/me/playlists") in fake.calls


def test_resync_adds_new_and_removes_what_no_longer_belongs(fake):
    fake.playlists["X"] = {"name": "Every",
                           "uris": ["spotify:track:ALB1-0", "spotify:track:GONE"]}
    client = spotify_sync.Client("RT")
    result = spotify_sync.sync(client, [rec("ALB1")], False, DictCache(), name="Every", spotify_id="X")

    assert result["created"] is False
    assert len(fake.playlists) == 1, "a second playlist was created"
    assert fake.playlists["X"]["uris"] == ["spotify:track:ALB1-0",
                                           "spotify:track:ALB1-1", "spotify:track:ALB1-2"]
    assert (result["added"], result["removed"]) == (2, 1)


def test_unchanged_playlist_is_not_written(fake):
    fake.playlists["X"] = {"name": "Every",
                           "uris": [f"spotify:track:ALB1-{i}" for i in range(3)]}
    spotify_sync.sync(spotify_sync.Client("RT"), [rec("ALB1")], False, DictCache(), name="Every", spotify_id="X")
    assert not [c for c in fake.calls if c[0] in ("POST", "DELETE") and "/playlists" in c[1]]


def test_liked_playlist_holds_only_liked_songs(fake):
    records = [
        rec("ALB1", liked=["Satisfaction", "Not On Spotify"]),
        rec("ALB2", tracks=[{"side": "C", "title": "Reprise", "liked_at": "x"},
                            {"side": "A", "title": "Song B"}]),
        rec("ALB1", liked=[], link="https://open.spotify.com/album/NOLIKES"),
    ]
    result = spotify_sync.sync(spotify_sync.Client("RT"), records, True, DictCache(), name="Zucoloto Vinyl Collection — Liked")

    pl = next(p for p in fake.playlists.values())
    assert pl["name"] == "Zucoloto Vinyl Collection — Liked"
    assert pl["uris"] == ["spotify:track:ALB1-1", "spotify:track:ALB2-2"]
    assert result["unmatched"] == [{"label": "Artist — ALB1", "cover_url": "/c/ALB1",
                                    "songs": ["Not On Spotify"]}]
    # A record with nothing liked costs no request at all.
    assert not any("NOLIKES" in path for _, path in fake.calls)


def test_track_link_stands_for_its_album(fake):
    record = rec("ALB1", link="https://open.spotify.com/track/T1?si=abc")
    spotify_sync.sync(spotify_sync.Client("RT"), [record], False, DictCache(), name="Every")
    assert next(iter(fake.playlists.values()))["uris"][0] == "spotify:track:ALB1-0"


def test_bad_and_missing_links_are_skipped_not_fatal(fake):
    records = [rec("ALB1"),
               rec("x", link="https://open.spotify.com/artist/ZZ"),
               rec("MISSING")]
    result = spotify_sync.sync(spotify_sync.Client("RT"), records, False, DictCache(), name="Every")
    assert [b["label"] for b in result["bad_links"]] == ["Artist — x", "Artist — MISSING"]
    assert result["bad_links"][0]["cover_url"] == "/c/x"
    assert result["total"] == 3


def test_duplicate_records_add_each_track_once(fake):
    spotify_sync.sync(spotify_sync.Client("RT"), [rec("ALB1"), rec("ALB1")], False, DictCache(), name="Every")
    assert len(next(iter(fake.playlists.values()))["uris"]) == 3


def test_out_of_time_writes_nothing_and_keeps_what_it_read(fake):
    cache = DictCache()
    with pytest.raises(spotify_sync.Incomplete) as e:
        spotify_sync.sync(spotify_sync.Client("RT"), [rec("ALB1"), rec("ALB2")], False,
                          cache, name="Every", deadline=time.monotonic() - 1)
    assert (e.value.done, e.value.total) == (0, 2)
    assert fake.playlists == {}

    cache.put("https://open.spotify.com/album/ALB1", [{"uri": "c", "name": "c", "disc": 1}])
    with pytest.raises(spotify_sync.Incomplete) as e:
        spotify_sync.sync(spotify_sync.Client("RT"), [rec("ALB1"), rec("ALB2")], False,
                          cache, name="Every", deadline=time.monotonic() - 1)
    assert e.value.done == 1, "a cached album was not counted as read"


def test_revoked_login_raises_not_connected():
    bad = _Response(400, {"error": "invalid_grant"})
    with patch.object(spotify_sync.requests, "request", return_value=bad):
        with pytest.raises(spotify_sync.NotConnected):
            spotify_sync.Client("RT").call("GET", "/me")


def test_a_new_playlist_is_created_once_and_its_id_returned(fake):
    result = spotify_sync.sync(spotify_sync.Client("RT"), [rec("ALB1")], False, DictCache(),
                               name="Mine")
    assert result["created"] is True
    assert fake.playlists[result["spotify_id"]]["name"] == "Mine"
    assert result["url"] == f"https://open.spotify.com/playlist/{result['spotify_id']}"

    again = spotify_sync.sync(spotify_sync.Client("RT"), [rec("ALB1")], False, DictCache(),
                              name="Mine", spotify_id=result["spotify_id"])
    assert again["created"] is False and len(fake.playlists) == 1


def test_a_playlist_deleted_on_spotify_is_recreated(fake):
    result = spotify_sync.sync(spotify_sync.Client("RT"), [rec("ALB1")], False, DictCache(),
                               name="Mine", spotify_id="GONE")
    assert result["created"] is True and result["spotify_id"] != "GONE"
    assert fake.playlists[result["spotify_id"]]["uris"]


def test_legacy_rows_adopt_the_playlist_already_on_spotify(fake):
    fake.playlists["OLD"] = {"name": "Zucoloto Vinyl Collection", "uris": []}
    result = spotify_sync.sync(spotify_sync.Client("RT"), [rec("ALB1")], False, DictCache(),
                               name="Zucoloto Vinyl Collection", adopt_by_name=True)
    assert (result["spotify_id"], result["created"]) == ("OLD", False)
    assert len(fake.playlists) == 1


def test_without_adopt_a_same_named_playlist_is_left_alone(fake):
    fake.playlists["THEIRS"] = {"name": "Mine", "uris": ["spotify:track:keep"]}
    result = spotify_sync.sync(spotify_sync.Client("RT"), [rec("ALB1")], False, DictCache(),
                               name="Mine")
    assert result["spotify_id"] != "THEIRS"
    assert fake.playlists["THEIRS"]["uris"] == ["spotify:track:keep"]


def test_delete_unfollows_and_a_missing_one_counts_as_gone(fake):
    fake.playlists["PL9"] = {"name": "x", "uris": []}
    spotify_sync.delete_playlist(spotify_sync.Client("RT"), "PL9")
    assert "PL9" not in fake.playlists
    assert ("DELETE", "/playlists/PL9/followers") in fake.calls
    spotify_sync.delete_playlist(spotify_sync.Client("RT"), "PL9")  # no raise


# ── routes ────────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    import app as app_module
    with app_module.app.app_context():
        app_module.SpotifyPlaylist.query.delete()
        app_module.AppFlag.query.delete()
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
        app_module.db.session.commit()
    _records(app_module)


def _records(app_module):
    """The collection the route tests share: a playlist with no record in it
    is refused, so even the tests that never reach Spotify need these."""
    with app_module.app.app_context():
        app_module.db.session.add(app_module.Record(
            artist="A", album_name="One", have_it=True, year="1973", genre="Rock",
            bought_where="Tracks", spotify_url="https://open.spotify.com/album/ALB1",
            tracks=json.dumps([{"side": "A", "title": "Satisfaction", "liked_at": "2026-09-01"}])))
        app_module.db.session.add(app_module.Record(
            artist="A", album_name="Two", have_it=True, year="1991", genre="Jazz",
            spotify_url="https://open.spotify.com/album/ALB2"))
        app_module.db.session.add(app_module.Record(
            artist="A", album_name="Wish", have_it=False, year="1973", genre="Rock",
            spotify_url="https://open.spotify.com/album/ALB2"))
        app_module.db.session.commit()


def _create(client, filters, name=None):
    body = {"filters": filters}
    if name is not None:
        body["name"] = name
    return client.post("/api/spotify/playlists", json=body)

def test_visitors_cannot_sync_or_connect():
    import app as app_module
    c = app_module.app.test_client()
    assert c.post("/api/spotify/playlists/1/sync").status_code == 401
    assert c.post("/api/spotify/playlists", json={"filters": {}}).status_code == 401
    assert c.delete("/api/spotify/playlists/1").status_code == 401
    assert c.get("/api/spotify/connect").status_code == 401
    assert c.get("/api/spotify/account").status_code == 401


def test_sync_without_a_login_asks_to_connect(client):
    import app as app_module
    _records(app_module)
    pid = _create(client, {}).get_json()["playlist"]["id"]
    r = client.post(f"/api/spotify/playlists/{pid}/sync")
    assert r.status_code == 409 and r.get_json()["connect"] is True


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


def test_unknown_playlist_is_404(client):
    assert client.post("/api/spotify/playlists/999/sync").status_code == 404
    assert client.delete("/api/spotify/playlists/999").status_code == 404


def test_create_lists_and_suggests_a_name(client):
    import app as app_module
    _connect(app_module)
    r = _create(client, {"genres": ["Rock"]})
    assert r.status_code == 201 and r.get_json()["existed"] is False
    p = r.get_json()["playlist"]
    assert p["name"] == "Zucoloto Vinyl — Liked · Rock"
    assert p["summary"] == "liked songs · Rock"
    assert p["url"] == "" and p["last_synced_at"] is None
    d = client.get("/api/spotify/playlists").get_json()
    assert [x["id"] for x in d["playlists"]] == [p["id"]]
    assert d["genres"] == ["Jazz", "Rock"] and d["places"] == ["Tracks"]


def test_the_same_filters_return_the_existing_playlist(client):
    import app as app_module
    _records(app_module)
    first = _create(client, {"genres": ["Rock", "jazz"]}, name="Mine").get_json()["playlist"]
    again = _create(client, {"genres": [" JAZZ ", "rock"]}, name="Other name")
    assert again.status_code == 200 and again.get_json()["existed"] is True
    assert again.get_json()["playlist"]["id"] == first["id"]
    assert again.get_json()["playlist"]["name"] == "Mine"


def test_a_race_on_the_unique_key_still_returns_one_row(client, monkeypatch):
    import app as app_module
    _records(app_module)
    first = _create(client, {"year_from": 1970}).get_json()["playlist"]
    # The second request's lookup misses (as if it ran before the first commit),
    # so only the unique constraint stands between it and a duplicate.
    real = app_module._playlist_by_key
    calls = {"n": 0}

    def miss_once(key):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(key)
    monkeypatch.setattr(app_module, "_playlist_by_key", miss_once)
    r = _create(client, {"year_from": 1970})
    assert r.get_json()["existed"] is True and r.get_json()["playlist"]["id"] == first["id"]
    with app_module.app.app_context():
        assert app_module.SpotifyPlaylist.query.count() == 1


def test_a_bad_filter_is_400_with_its_field(client):
    r = _create(client, {"pepe_min": 9})
    assert r.status_code == 400 and r.get_json()["field"] == "pepe_min"


def test_filters_that_match_no_record_are_refused(client):
    import app as app_module
    _records(app_module)
    r = _create(client, {"genres": ["Jazz"]})  # Two is jazz, but nothing on it is liked
    assert r.status_code == 400 and r.get_json()["field"] == "filters"
    assert _create(client, {"year_from": 2000, "liked": False}).status_code == 400
    assert _create(client, {"genres": ["Jazz"], "liked": False}).status_code == 201
    with app_module.app.app_context():
        assert app_module.SpotifyPlaylist.query.count() == 1


def test_a_typed_name_is_tidied_and_capped(client):
    import app as app_module
    _records(app_module)
    p = _create(client, {"liked": False}, name="  My   list " + "x" * 200).get_json()["playlist"]
    assert p["name"].startswith("My list x") and len(p["name"]) == 100


def test_sync_applies_the_filters_and_stores_the_result(client, fake):
    import app as app_module
    _connect(app_module)
    pid = _create(client, {"liked": False, "year_from": 1970, "year_to": 1979}).get_json()["playlist"]["id"]
    r = client.post(f"/api/spotify/playlists/{pid}/sync")
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["created"] is True and d["total"] == 3
    uris = fake.playlists[d["spotify_id"]]["uris"]
    assert uris and all("ALB1" in u for u in uris), "the 1991 record or the wishlist got in"
    p = d["playlist"]
    assert p["url"] == d["url"] and p["last_total"] == 3 and p["last_records"] == 1
    assert p["last_synced_at"]
    assert p["cover_url"] == f"https://mosaic.scdn.co/640/{d['spotify_id']}"

    fake.calls.clear()
    again = client.post(f"/api/spotify/playlists/{pid}/sync").get_json()
    assert again["created"] is False and again["spotify_id"] == d["spotify_id"]
    assert not any(path.startswith("/albums/") for _, path in fake.calls), "album was re-read"


def test_sync_reports_progress_when_out_of_time(client, fake, monkeypatch):
    import app as app_module
    _connect(app_module)
    monkeypatch.setattr(app_module, "_SPOTIFY_READ_BUDGET", -1)
    pid = _create(client, {"liked": False}).get_json()["playlist"]["id"]
    r = client.post(f"/api/spotify/playlists/{pid}/sync")
    assert r.status_code == 202
    assert r.get_json() == {"incomplete": True, "done": 0, "total": 2}


def test_a_sync_failing_after_creating_keeps_the_new_id(client, fake):
    import app as app_module
    _connect(app_module)
    pid = _create(client, {"liked": False}).get_json()["playlist"]["id"]
    real = fake.request
    failed = []

    def fail_first_write(method, url, **kw):
        if method == "POST" and "/items" in url and not failed:
            failed.append(url)
            return _Response(500, {"error": {"status": 500}})
        return real(method, url, **kw)
    with patch.object(spotify_sync.requests, "request", side_effect=fail_first_write):
        assert client.post(f"/api/spotify/playlists/{pid}/sync").status_code == 502
    (sid,) = fake.playlists
    with app_module.app.app_context():
        assert app_module.db.session.get(app_module.SpotifyPlaylist, pid).spotify_id == sid

    d = client.post(f"/api/spotify/playlists/{pid}/sync").get_json()
    assert (d["spotify_id"], d["created"]) == (sid, False)
    assert len(fake.playlists) == 1, "the failed sync's playlist was orphaned"


def test_delete_removes_it_on_spotify_and_here(client, fake):
    import app as app_module
    _connect(app_module)
    pid = _create(client, {"liked": False}).get_json()["playlist"]["id"]
    sid = client.post(f"/api/spotify/playlists/{pid}/sync").get_json()["spotify_id"]
    assert client.delete(f"/api/spotify/playlists/{pid}").status_code == 200
    assert sid not in fake.playlists
    assert client.get("/api/spotify/playlists").get_json()["playlists"] == []


def test_deleting_a_never_synced_playlist_needs_no_spotify(client):
    import app as app_module
    _records(app_module)
    pid = _create(client, {}).get_json()["playlist"]["id"]
    assert client.delete(f"/api/spotify/playlists/{pid}").status_code == 200


def test_deleting_a_never_synced_legacy_row_removes_its_playlist_by_name(client, fake):
    import app as app_module
    _connect(app_module)
    fake.playlists["OLD"] = {"name": "Zucoloto Vinyl Collection", "uris": []}
    fake.playlists["KEEP"] = {"name": "Something else", "uris": []}
    with app_module.app.app_context():
        app_module._seed_legacy_playlists()
    rows = client.get("/api/spotify/playlists").get_json()["playlists"]
    assert client.delete(f"/api/spotify/playlists/{rows[0]['id']}").status_code == 200
    assert list(fake.playlists) == ["KEEP"]
    # Its sibling has nothing of that name on Spotify: it simply goes.
    assert client.delete(f"/api/spotify/playlists/{rows[1]['id']}").status_code == 200
    assert client.get("/api/spotify/playlists").get_json()["playlists"] == []


def test_deleting_a_legacy_row_without_a_login_asks_to_connect(client):
    import app as app_module
    with app_module.app.app_context():
        app_module._seed_legacy_playlists()
    pid = client.get("/api/spotify/playlists").get_json()["playlists"][0]["id"]
    r = client.delete(f"/api/spotify/playlists/{pid}")
    assert r.status_code == 409 and r.get_json()["connect"] is True


def test_a_spotify_failure_on_delete_keeps_the_row(client, fake):
    import app as app_module
    _connect(app_module)
    pid = _create(client, {"liked": False}).get_json()["playlist"]["id"]
    client.post(f"/api/spotify/playlists/{pid}/sync")
    with patch.object(spotify_sync, "delete_playlist",
                      side_effect=spotify_sync.SpotifyError("Spotify returned 500", status=500)):
        r = client.delete(f"/api/spotify/playlists/{pid}")
    assert r.status_code == 502
    assert len(client.get("/api/spotify/playlists").get_json()["playlists"]) == 1


def test_legacy_seed_adopts_the_playlist_already_on_spotify(client, fake):
    import app as app_module
    _connect(app_module)
    fake.playlists["OLD"] = {"name": "Zucoloto Vinyl Collection", "uris": []}
    with app_module.app.app_context():
        app_module._seed_legacy_playlists()
        app_module._seed_legacy_playlists()  # idempotent
    rows = client.get("/api/spotify/playlists").get_json()["playlists"]
    assert [r["name"] for r in rows] == ["Zucoloto Vinyl Collection",
                                         "Zucoloto Vinyl Collection — Liked"]
    assert [r["filters"]["liked"] for r in rows] == [False, True]
    d = client.post(f"/api/spotify/playlists/{rows[0]['id']}/sync").get_json()
    assert (d["spotify_id"], d["created"]) == ("OLD", False)
    # Adopted once: from now on it is found by id, never by name.
    with app_module.app.app_context():
        assert app_module.db.session.get(app_module.SpotifyPlaylist, rows[0]["id"]).legacy is False


def test_account_no_longer_lists_fixed_playlists(client):
    assert "playlists" not in client.get("/api/spotify/account").get_json()


def test_visitors_see_only_synced_playlists_as_links(client):
    import app as app_module
    with app_module.app.app_context():
        app_module.db.session.add_all([
            app_module.SpotifyPlaylist(name="Made", spotify_id="PL1", filters='{"liked": true}',
                                       filter_key="a", last_total=12, cover_url="https://c/1"),
            app_module.SpotifyPlaylist(name="Never synced", filters='{"liked": false}',
                                       filter_key="b"),
        ])
        app_module.db.session.commit()
    visitor = app_module.app.test_client()
    r = visitor.get("/api/spotify/playlists")
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {"playlists"}
    [p] = body["playlists"]
    assert p["name"] == "Made"
    assert p["url"] == spotify_sync.playlist_url("PL1")
    assert set(p) == {"id", "name", "summary", "url", "cover_url", "last_total"}


def test_playlist_link_is_read_as_a_compilation(fake):
    comp = "https://open.spotify.com/playlist/COMP"
    every = spotify_sync.sync(spotify_sync.Client("RT"), [rec("Greatest Hits", link=comp)],
                              False, DictCache(), name="Every")
    assert fake.playlists[every["spotify_id"]]["uris"] == ["spotify:track:C1", "spotify:track:C2"]
    assert every["bad_links"] == []

    liked = spotify_sync.sync(spotify_sync.Client("RT"), [rec("Greatest Hits", link=comp, liked=["Lovely Day"])],
                              True, DictCache(), name="Liked")
    assert fake.playlists[liked["spotify_id"]]["uris"] == ["spotify:track:C2"]
