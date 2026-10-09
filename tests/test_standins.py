"""Stand-in playlists: a Spotify playlist built song by song for a record that
is not on Spotify as an album, and linked to it so the filtered playlists use it.

Spotify is the in-memory FakeSpotify from the playlist sync tests, taught the
search endpoint the stand-in build needs.
"""

import base64
import io
import json
from unittest.mock import Mock, patch

import pytest
from PIL import Image

import cover_art
import spotify_sync
import standins
from test_spotify_playlists import FakeSpotify, _Response


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "secret")


@pytest.fixture
def client():
    import app as app_module
    with app_module.app.app_context():
        app_module.StandInPlaylist.query.delete()
        app_module.SpotifyPlaylist.query.delete()
        app_module.AppFlag.query.delete()
        app_module.SpotifyAccount.query.delete()
        app_module.SpotifyAlbumCache.query.delete()
        app_module.ScanSpend.query.delete()
        app_module.Record.query.delete()
        app_module.db.session.commit()
    c = app_module.app.test_client()
    with c.session_transaction() as s:
        s["authed"] = True
    return c


def _add_record(**fields):
    import app as app_module
    with app_module.app.app_context():
        r = app_module.Record(**{"have_it": True, **fields})
        app_module.db.session.add(r)
        app_module.db.session.commit()
        return r.id


def _record(rid):
    import app as app_module
    with app_module.app.app_context():
        return app_module.db.session.get(app_module.Record, rid).to_dict()


# ── the flag ──────────────────────────────────────────────────────────────────

def test_a_record_is_not_a_stand_in_by_default(client):
    rid = _add_record(artist="A", album_name="B")
    assert _record(rid)["spotify_standin"] is False


def test_changing_the_link_by_hand_clears_the_stand_in_flag(client):
    rid = _add_record(artist="A", album_name="B", spotify_standin=True,
                      spotify_url="https://open.spotify.com/playlist/S")
    r = client.put(f"/api/records/{rid}", json={"spotify_url": "https://open.spotify.com/album/X"})
    assert r.status_code == 200
    assert _record(rid)["spotify_standin"] is False


def test_a_put_that_keeps_the_link_keeps_the_flag(client):
    rid = _add_record(artist="A", album_name="B", spotify_standin=True,
                      spotify_url="https://open.spotify.com/playlist/S")
    client.put(f"/api/records/{rid}", json={"spotify_url": "https://open.spotify.com/playlist/S",
                                            "genre": "Rock"})
    assert _record(rid)["spotify_standin"] is True


# ── standins.py: picking a song's Spotify track ──────────────────────────────

def _track(name, artist="Artist", album="Album", date="1975-01-01", uri=None):
    return {"uri": uri or f"spotify:track:{name}-{album}-{date}", "name": name,
            "artists": [{"name": a} for a in ([artist] if isinstance(artist, str) else artist)],
            "album": {"name": album, "release_date": date,
                      "images": [{"url": f"https://i.scdn.co/{album}"}]}}


def test_a_hit_must_credit_the_records_artist():
    items = [_track("Song", artist="Someone Else")]
    assert standins.pick_hit("Song", "Artist", "Album", items) is None


def test_a_hit_must_be_the_same_song():
    items = [_track("Another Song")]
    assert standins.pick_hit("Song", "Artist", "Album", items) is None


def test_a_hit_carries_what_the_preview_shows():
    hit = standins.pick_hit("Song", "Artist", "Album", [_track("Song", uri="spotify:track:1")])
    assert hit == {"uri": "spotify:track:1", "name": "Song", "album": "Album",
                   "year": "1975", "image_url": "https://i.scdn.co/Album"}


def test_the_records_own_album_wins():
    items = [_track("Song", album="Greatest Hits", date="1970"),
             _track("Song", album="The Record", date="1990", uri="spotify:track:own")]
    assert standins.pick_hit("Song", "Artist", "The Record", items)["uri"] == "spotify:track:own"


def test_a_studio_take_beats_a_live_one_then_the_earliest_wins():
    items = [_track("Song - Live", album="Live at the Hall", date="1971"),
             _track("Song", album="Best Of", date="1999"),
             _track("Song", album="Single", date="1974", uri="spotify:track:first")]
    assert standins.pick_hit("Song", "Artist", "Missing Album", items)["uri"] == "spotify:track:first"


def test_titles_meet_across_accents_and_version_tails():
    items = [_track("Águas de Março - Remastered 2011", artist="Elis Regina", uri="spotify:track:aguas")]
    assert standins.pick_hit("Aguas de Marco", "Elis Regina", "Elis", items)["uri"] == "spotify:track:aguas"


def test_one_of_several_credited_artists_is_enough():
    items = [_track("Song", artist=["Elis Regina", "Tom Jobim"], uri="spotify:track:duo")]
    assert standins.pick_hit("Song", "Tom Jobim", "Elis & Tom", items)["uri"] == "spotify:track:duo"


def test_a_duo_record_finds_songs_credited_to_either_artist():
    items = [_track("Águas de Março", artist=["Elis Regina", "Antônio Carlos Jobim"], uri="spotify:track:duo")]
    assert standins.pick_hit("Aguas de Marco", "Elis Regina & Tom Jobim", "Elis & Tom", items)["uri"] \
        == "spotify:track:duo"


def test_a_duo_record_searches_again_by_its_first_artist(spotify):
    hit = standins.find_song(spotify_sync.Client("RT"), "Intro", "Artist & Friend", "Album")
    assert hit["uri"] == "spotify:track:intro"
    searches = [p for _, p in spotify.calls if p.startswith("/search")]
    assert len(searches) == 2
    assert "artist%3A%22Artist+%26+Friend%22" in searches[0] and "artist%3A%22Artist%22" in searches[1]


def test_a_band_name_with_an_ampersand_is_searched_whole_first(spotify):
    spotify.catalogue["Shining Star"] = [_track("Shining Star", artist="Earth, Wind & Fire", uri="spotify:track:ewf")]
    hit = standins.find_song(spotify_sync.Client("RT"), "Shining Star", "Earth, Wind & Fire", "That's the Way")
    assert hit["uri"] == "spotify:track:ewf"
    assert len([p for _, p in spotify.calls if p.startswith("/search")]) == 1


def test_a_live_only_song_is_still_found():
    items = [_track("Song - Ao Vivo", album="Ao Vivo", uri="spotify:track:live")]
    assert standins.pick_hit("Song", "Artist", "Album", items)["uri"] == "spotify:track:live"


# ── standins.py: the description ──────────────────────────────────────────────

def test_the_description_names_the_record_and_skips_empty_parts():
    text = standins.description({"artist": "Elis Regina", "album_name": "Elis", "year": "1972",
                                 "genre": "MPB", "country": "BR", "bought_where": ""}, 9, 12)
    assert text == ("Elis Regina — Elis (1972) · MPB · BR · vinyl stand-in, 9 of 12 songs "
                    "found · Zucoloto vinyl collection")


def test_the_description_fits_spotify_and_has_no_newlines():
    text = standins.description({"artist": "A\nB", "album_name": "x" * 400, "year": "",
                                 "genre": "", "country": "", "bought_where": "Shop"}, 1, 1)
    assert len(text) <= 300 and "\n" not in text
    assert text.endswith("…")


# ── standins.py: the cover ────────────────────────────────────────────────────

def _png(size, mode="RGBA"):
    buf = io.BytesIO()
    img = Image.effect_noise(size, 90).convert(mode)
    img.save(buf, "PNG")
    return buf.getvalue()


def test_a_cover_becomes_a_square_jpeg_spotify_takes():
    jpeg = standins.cover_jpeg(_png((1600, 1200)))
    img = Image.open(io.BytesIO(jpeg))
    assert img.format == "JPEG" and img.size == (640, 640)
    assert len(base64.b64encode(jpeg)) <= cover_art.MAX_BASE64


def test_an_unreadable_cover_is_no_cover():
    assert standins.cover_jpeg(b"not an image") is None
    assert standins.cover_jpeg(None) is None


# ── standins.py: talking to Spotify ───────────────────────────────────────────

class SearchingSpotify(FakeSpotify):
    """FakeSpotify plus /search, answering from `catalogue` by title."""

    def __init__(self, catalogue=None):
        super().__init__()
        self.catalogue = catalogue or {}   # title -> [track objects]
        self.created = []                  # bodies of POST /me/playlists

    def request(self, method, url, headers=None, json=None, data=None, timeout=None, **kw):
        path = url.replace(spotify_sync.API, "")
        if path.startswith("/search"):
            self.calls.append((method, path))
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(url).query)["q"][0]
            # Like Spotify's field filter, near enough: the title and one credited artist.
            items = [t for title, ts in self.catalogue.items() if f'track:"{title}"' in q for t in ts
                     if any(f'artist:"{a["name"]}"' in q for a in t["artists"])]
            return _Response(200, {"tracks": {"items": items, "next": None}})
        if path == "/me/playlists" and method == "POST":
            self.created.append(json)
        return super().request(method, url, headers=headers, json=json, data=data,
                               timeout=timeout, **kw)


@pytest.fixture
def spotify():
    f = SearchingSpotify({
        "Intro": [_track("Intro", uri="spotify:track:intro")],
        "Outro": [_track("Outro", uri="spotify:track:outro")],
    })
    with patch.object(spotify_sync.requests, "request", side_effect=f.request):
        yield f


def test_preview_searches_each_song_by_title_and_artist(spotify):
    songs = standins.preview(spotify_sync.Client("RT"), {
        "artist": "Artist", "album_name": "Album",
        "tracks": [{"side": "A", "title": "Intro"}, {"side": "A", "title": "Lost"},
                   {"side": "B", "title": "Outro"}, {"side": "B", "title": ""}]})
    assert [(s["side"], s["title"], (s["hit"] or {}).get("uri")) for s in songs] == [
        ("A", "Intro", "spotify:track:intro"), ("A", "Lost", None), ("B", "Outro", "spotify:track:outro")]
    search = [p for _, p in spotify.calls if p.startswith("/search")][0]
    assert "track%3A%22Intro%22" in search and "artist%3A%22Artist%22" in search


def test_create_makes_a_private_playlist_and_reports_its_id_before_filling_it(spotify):
    seen = []

    def on_created(pid):
        seen.append(pid)
        assert spotify.playlists[pid]["uris"] == [], "filled before the id was handed over"

    uris = [f"spotify:track:{i}" for i in range(150)]
    pid = standins.create(spotify_sync.Client("RT"), "Artist — Album", "desc", uris, on_created)
    assert seen == [pid]
    assert spotify.playlists[pid]["uris"] == uris
    assert spotify.created == [{"name": "Artist — Album", "description": "desc", "public": False}]


# ── routes ────────────────────────────────────────────────────────────────────

def _connect():
    import app as app_module
    with app_module.app.app_context():
        app_module.db.session.add(app_module.SpotifyAccount(id=1, refresh_token="RT", display_name="Me"))
        app_module.db.session.commit()


def _cover_uri():
    return "data:image/png;base64," + base64.b64encode(_png((300, 300))).decode()


def _lost_record(**fields):
    """A record Spotify does not have: no link, a tracklist, a cover."""
    return _add_record(**{
        "artist": "Artist", "album_name": "Album", "year": "1975", "genre": "MPB",
        "country": "BR", "bought_where": "Shop",
        "tracks": json.dumps([{"side": "A", "title": "Intro", "liked_at": "2026-09-01"},
                              {"side": "B", "title": "Outro"}]),
        "cover_data": _cover_uri(), **fields})


def _build(client, rid, uris=("spotify:track:intro", "spotify:track:outro")):
    return client.post("/api/spotify/stand-ins", json={"record_id": rid, "uris": list(uris)})


def test_visitors_cannot_reach_stand_ins():
    import app as app_module
    c = app_module.app.test_client()
    assert c.get("/api/spotify/stand-ins").status_code == 401
    assert c.post("/api/spotify/stand-ins/preview", json={"record_id": 1}).status_code == 401


def test_candidates_are_the_records_without_a_link(client):
    lost = _lost_record()
    _add_record(artist="Artist", album_name="On Spotify", spotify_url="https://open.spotify.com/album/X")
    missing = _add_record(artist="Artist", album_name="Marked", spotify_missing=True)
    d = client.get("/api/spotify/stand-ins").get_json()
    assert {c["id"] for c in d["candidates"]} == {lost, missing}
    by_id = {c["id"]: c for c in d["candidates"]}
    assert by_id[lost]["has_tracks"] is True and by_id[missing]["has_tracks"] is False
    assert by_id[missing]["spotify_missing"] is True
    assert d["stand_ins"] == []


def test_preview_lists_each_song_with_its_hit(client, spotify):
    _connect()
    rid = _lost_record()
    r = client.post("/api/spotify/stand-ins/preview", json={"record_id": rid})
    assert r.status_code == 200
    assert [(s["title"], s["hit"]["uri"]) for s in r.get_json()["songs"]] == [
        ("Intro", "spotify:track:intro"), ("Outro", "spotify:track:outro")]


def test_preview_needs_a_tracklist(client, spotify):
    _connect()
    rid = _add_record(artist="Artist", album_name="Bare")
    r = client.post("/api/spotify/stand-ins/preview", json={"record_id": rid})
    assert r.status_code == 400 and "tracklist" in r.get_json()["error"]


def test_preview_without_a_login_asks_to_connect(client):
    rid = _lost_record()
    r = client.post("/api/spotify/stand-ins/preview", json={"record_id": rid})
    assert r.status_code == 409 and r.get_json()["connect"] is True


def test_preview_of_an_unknown_record_is_404(client):
    _connect()
    assert client.post("/api/spotify/stand-ins/preview", json={"record_id": 999}).status_code == 404


def test_create_builds_the_playlist_with_the_records_cover_and_facts(client, spotify):
    _connect()
    rid = _lost_record()
    r = _build(client, rid)
    assert r.status_code == 201
    d = r.get_json()
    assert d["cover"] == "uploaded"
    s = d["stand_in"]
    pid = s["url"].rsplit("/", 1)[1]
    assert spotify.playlists[pid]["uris"] == ["spotify:track:intro", "spotify:track:outro"]
    (body,) = spotify.created
    assert body["name"] == "Artist — Album" and body["public"] is False
    assert body["description"].startswith("Artist — Album (1975) · MPB · BR · bought at Shop")
    assert "2 of 2 songs found" in body["description"]
    content_type, data = spotify.covers[pid]
    assert content_type == "image/jpeg"
    assert Image.open(io.BytesIO(base64.b64decode(data))).size == (640, 640)
    assert s["track_count"] == 2 and s["song_count"] == 2 and s["matched"] is False
    assert s["cover_url"] == f"https://mosaic.scdn.co/640/{pid}"
    assert s["record"]["album_name"] == "Album"
    assert _record(rid)["spotify_url"] == "", "creating must not link the record"


def test_create_without_a_cover_leaves_spotifys_own(client, spotify):
    _connect()
    rid = _lost_record(cover_data="")
    d = _build(client, rid).get_json()
    assert d["cover"] == "none" and not spotify.covers


def test_create_refuses_no_songs_and_bad_uris(client, spotify):
    _connect()
    rid = _lost_record()
    assert _build(client, rid, uris=[]).status_code == 400
    assert _build(client, rid, uris=["https://evil"]).status_code == 400
    assert not spotify.playlists


def test_create_refuses_a_record_that_has_a_link(client, spotify):
    _connect()
    rid = _lost_record(spotify_url="https://open.spotify.com/album/X")
    assert _build(client, rid).status_code == 400
    assert not spotify.playlists


def test_a_fill_that_fails_keeps_the_new_playlist(client, spotify):
    _connect()
    rid = _lost_record()
    real = spotify.request

    def failing(method, url, **kw):
        if method == "POST" and "/items" in url:
            return _Response(500, {"error": {"status": 500}})
        return real(method, url, **kw)
    with patch.object(spotify_sync.requests, "request", side_effect=failing):
        assert _build(client, rid).status_code == 502
    (s,) = client.get("/api/spotify/stand-ins").get_json()["stand_ins"]
    assert s["url"].endswith("/PL1")


def test_match_links_the_record_and_unmatch_undoes_it(client, spotify):
    _connect()
    rid = _lost_record(spotify_missing=True)
    s = _build(client, rid).get_json()["stand_in"]
    r = client.post(f"/api/spotify/stand-ins/{s['id']}/match")
    assert r.status_code == 200 and r.get_json()["stand_in"]["matched"] is True
    assert r.get_json()["record"]["spotify_url"] == s["url"], "the page patches its record from this"
    rec = _record(rid)
    assert rec["spotify_url"] == s["url"] and rec["spotify_standin"] is True
    assert rec["spotify_missing"] is False
    assert {c["id"] for c in client.get("/api/spotify/stand-ins").get_json()["candidates"]} == set()

    r = client.post(f"/api/spotify/stand-ins/{s['id']}/unmatch")
    assert r.status_code == 200 and r.get_json()["stand_in"]["matched"] is False
    assert r.get_json()["record"]["spotify_url"] == ""
    rec = _record(rid)
    assert rec["spotify_url"] == "" and rec["spotify_standin"] is False


def test_match_will_not_overwrite_a_link_added_since(client, spotify):
    _connect()
    rid = _lost_record()
    s = _build(client, rid).get_json()["stand_in"]
    client.put(f"/api/records/{rid}", json={"spotify_url": "https://open.spotify.com/album/REAL"})
    assert client.post(f"/api/spotify/stand-ins/{s['id']}/match").status_code == 409
    assert _record(rid)["spotify_url"] == "https://open.spotify.com/album/REAL"


def test_unmatch_leaves_a_link_that_is_no_longer_this_playlist(client, spotify):
    _connect()
    rid = _lost_record()
    s = _build(client, rid).get_json()["stand_in"]
    client.post(f"/api/spotify/stand-ins/{s['id']}/match")
    client.put(f"/api/records/{rid}", json={"spotify_url": "https://open.spotify.com/album/REAL"})
    client.post(f"/api/spotify/stand-ins/{s['id']}/unmatch")
    assert _record(rid)["spotify_url"] == "https://open.spotify.com/album/REAL"


def test_delete_unfollows_and_clears_a_matched_records_link(client, spotify):
    _connect()
    rid = _lost_record()
    s = _build(client, rid).get_json()["stand_in"]
    client.post(f"/api/spotify/stand-ins/{s['id']}/match")
    r = client.delete(f"/api/spotify/stand-ins/{s['id']}")
    assert r.status_code == 200 and r.get_json()["record"]["spotify_url"] == ""
    assert not spotify.playlists
    assert _record(rid)["spotify_url"] == ""
    assert client.get("/api/spotify/stand-ins").get_json()["stand_ins"] == []


def test_a_deleted_record_leaves_its_stand_in_listed(client, spotify):
    _connect()
    rid = _lost_record()
    _build(client, rid)
    client.delete(f"/api/records/{rid}")
    (s,) = client.get("/api/spotify/stand-ins").get_json()["stand_ins"]
    assert s["record"] is None


def test_a_matched_stand_in_feeds_the_default_filtered_playlist(client, spotify):
    _connect()
    rid = _lost_record()
    s = _build(client, rid).get_json()["stand_in"]
    client.post(f"/api/spotify/stand-ins/{s['id']}/match")
    pl = client.post("/api/spotify/playlists", json={"filters": {"liked": False}}).get_json()["playlist"]
    r = client.post(f"/api/spotify/playlists/{pl['id']}/sync")
    assert r.status_code == 200, r.get_json()
    synced = r.get_json()["playlist"]["url"].rsplit("/", 1)[1]
    assert spotify.playlists[synced]["uris"] == ["spotify:track:intro", "spotify:track:outro"]


def _claude_tracklist(payload):
    block = Mock(type="text", text=json.dumps(payload))
    return Mock(content=[block], usage=Mock(input_tokens=10, output_tokens=5))


def test_tracklist_asks_claude_and_records_the_spend(client):
    import app as app_module
    rid = _add_record(artist="Artist", album_name="Bare")
    claude = Mock()
    claude.messages.create.return_value = _claude_tracklist(
        {"tracks": [{"side": "A", "title": "One"}, {"side": "B", "title": "Two"}]})
    with patch("scan._anthropic_client", return_value=claude):
        r = client.post("/api/spotify/stand-ins/tracklist", json={"record_id": rid})
    assert r.status_code == 200
    assert r.get_json() == {"tracks": [{"side": "A", "title": "One"}, {"side": "B", "title": "Two"}],
                            "disc_count": 1}
    with app_module.app.app_context():
        (row,) = app_module.ScanSpend.query.all()
        assert row.source == "tracklist" and row.model == "claude-haiku-4-5"
    assert _record(rid)["tracks"] == "", "a suggestion is not saved until the owner confirms it"


def test_tracklist_refuses_a_record_that_has_one(client):
    rid = _lost_record()
    assert client.post("/api/spotify/stand-ins/tracklist", json={"record_id": rid}).status_code == 400


def test_tracklist_claude_does_not_know_is_422(client):
    rid = _add_record(artist="Artist", album_name="Bare")
    claude = Mock()
    claude.messages.create.return_value = _claude_tracklist({"tracks": []})
    with patch("scan._anthropic_client", return_value=claude):
        r = client.post("/api/spotify/stand-ins/tracklist", json={"record_id": rid})
    assert r.status_code == 422
