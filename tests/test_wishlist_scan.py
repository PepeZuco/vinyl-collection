"""The wishlist scan routes: reading a playlist, naming its albums, and
resolving them in chunks. Spotify, Claude and MusicBrainz are all stubbed at
the module boundary (spotify_sync / scan functions), never at the socket."""

from unittest.mock import patch

import pytest

import app as app_module
import scan
import spotify_sync


@pytest.fixture
def client():
    with app_module.app.app_context():
        app_module.SpotifyAccount.query.delete()
        app_module.Record.query.delete()
        app_module.ScanSpend.query.delete()
        app_module.db.session.commit()
    c = app_module.app.test_client()
    with c.session_transaction() as s:
        s["authed"] = True
    return c


def _connect():
    with app_module.app.app_context():
        app_module.db.session.add(app_module.SpotifyAccount(
            id=1, refresh_token="RT", display_name="Me"))
        app_module.db.session.commit()


def _record(artist, album, have_it=True):
    with app_module.app.app_context():
        r = app_module.Record(artist=artist, album_name=album, have_it=have_it)
        app_module.db.session.add(r)
        app_module.db.session.commit()
        return r.id


def _track(title, artist, album):
    return {"title": title, "artists": [artist], "album": album,
            "release_year": "1969", "image_url": f"https://i/{album}.jpg"}


def _identified(artist, album, unverified=False, year="1969"):
    return {"artist": artist, "album": album, "year": year, "unverified": unverified}


# ── GET /api/spotify/me/playlists ───────────────────────────────────────────

def test_playlists_need_edit_mode():
    c = app_module.app.test_client()
    assert c.get("/api/spotify/me/playlists").status_code == 401


def test_playlists_not_connected_is_409(client):
    r = client.get("/api/spotify/me/playlists")
    assert r.status_code == 409 and r.get_json()["connect"] is True


def test_playlists_lists_the_account(client):
    _connect()
    rows = [{"id": "P1", "name": "Road trip", "image_url": "", "track_count": 3, "owner": "Me"}]
    with patch.object(spotify_sync, "user_playlists", return_value=rows):
        r = client.get("/api/spotify/me/playlists")
    assert r.status_code == 200 and r.get_json() == {"playlists": rows}


def test_playlists_spotify_error_is_502(client):
    _connect()
    with patch.object(spotify_sync, "user_playlists",
                      side_effect=spotify_sync.SpotifyError("Spotify returned 500")):
        r = client.get("/api/spotify/me/playlists")
    assert r.status_code == 502


# ── POST /api/spotify/wishlist-scan ─────────────────────────────────────────

def _scan(client, tracks, identified, truncated=False):
    with patch.object(spotify_sync, "playlist_tracks", return_value=(tracks, truncated)) as pt, \
         patch.object(scan, "identify_albums", return_value=identified) as ia:
        r = client.post("/api/spotify/wishlist-scan", json={"playlist_id": "PL"})
    return r, pt, ia


def test_scan_needs_edit_mode():
    c = app_module.app.test_client()
    assert c.post("/api/spotify/wishlist-scan", json={"playlist_id": "PL"}).status_code == 401


def test_scan_needs_a_playlist_id(client):
    _connect()
    assert client.post("/api/spotify/wishlist-scan", json={}).status_code == 400


def test_scan_not_connected_is_409(client):
    r = client.post("/api/spotify/wishlist-scan", json={"playlist_id": "PL"})
    assert r.status_code == 409


def test_scan_login_expired_is_409_connect(client):
    _connect()
    with patch.object(spotify_sync, "playlist_tracks",
                      side_effect=spotify_sync.NotConnected("revoked")):
        r = client.post("/api/spotify/wishlist-scan", json={"playlist_id": "PL"})
    assert r.status_code == 409 and r.get_json()["connect"] is True


def test_scan_reads_with_the_cap(client):
    _connect()
    _, pt, _ = _scan(client, [], [])
    assert pt.call_args.args[1] == "PL"
    assert pt.call_args.kwargs["cap"] == app_module.PLAYLIST_SCAN_CAP == 500


def test_scan_groups_songs_by_normalised_album(client):
    _connect()
    tracks = [_track("Come Together", "The Beatles", "Abbey Road (Remastered 2009)"),
              _track("Something", "The Beatles", "1"),
              _track("Lovely Day", "Bill Withers", "Menagerie")]
    identified = [_identified("The Beatles", "Abbey Road"),
                  _identified("the beatles", "Abbey  Road"),
                  _identified("Bill Withers", "Menagerie", year="1977")]
    r, _, _ = _scan(client, tracks, identified)
    d = r.get_json()
    assert r.status_code == 200
    assert d["song_count"] == 3 and d["unplaced"] == 0 and d["truncated"] is False
    assert [a["album_name"] for a in d["albums"]] == ["Abbey Road", "Menagerie"]
    abbey = d["albums"][0]
    assert abbey["songs"] == ["Come Together", "Something"]
    assert abbey["artist"] == "The Beatles" and abbey["year"] == "1969"
    assert abbey["spotify_image"] == "https://i/Abbey Road (Remastered 2009).jpg"
    assert abbey["key"] == "beatles|abbey road"
    assert abbey["duplicate_of"] is None and abbey["have_it"] is None


def test_scan_counts_unplaced_songs_and_drops_them(client):
    _connect()
    r, _, _ = _scan(client, [_track("Single", "X", "Single")],
                    [{"artist": "X", "album": None, "year": None, "unverified": False}])
    d = r.get_json()
    assert d["albums"] == [] and d["unplaced"] == 1


def test_scan_keeps_the_unverified_flag(client):
    _connect()
    r, _, _ = _scan(client, [_track("A", "X", "Y")], [_identified("X", "Y", unverified=True)])
    assert r.get_json()["albums"][0]["unverified"] is True


def test_owned_albums_are_marked_and_not_resolved(client):
    _connect()
    owned = _record("The Beatles", "Abbey Road", have_it=True)
    wished = _record("Bill Withers", "Menagerie", have_it=False)
    r, _, _ = _scan(client,
                    [_track("Come Together", "The Beatles", "Abbey Road"),
                     _track("Lovely Day", "Bill Withers", "Menagerie")],
                    [_identified("The Beatles", "Abbey Road"),
                     _identified("Bill Withers", "Menagerie")])
    a, b = r.get_json()["albums"]
    assert a["duplicate_of"]["id"] == owned and a["have_it"] is True
    assert b["duplicate_of"]["id"] == wished and b["have_it"] is False


def test_scan_reports_truncation(client):
    _connect()
    r, _, _ = _scan(client, [], [], truncated=True)
    assert r.get_json()["truncated"] is True


def test_scan_banks_claude_spend_as_playlist(client):
    _connect()

    def identify(tracks, usage_out=None):
        usage_out.append({"model": "claude-haiku-4-5", "input_tokens": 10, "output_tokens": 5})
        return [_identified("X", "Y")]

    with patch.object(spotify_sync, "playlist_tracks", return_value=([_track("A", "X", "Y")], False)), \
         patch.object(scan, "identify_albums", side_effect=identify):
        client.post("/api/spotify/wishlist-scan", json={"playlist_id": "PL"})
    with app_module.app.app_context():
        rows = app_module.ScanSpend.query.all()
        assert [r.source for r in rows] == ["playlist"]
