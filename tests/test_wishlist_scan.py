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
        # Another test file may have repointed the app at a temp DB and
        # dropped tables (test_tracks_endpoint.py); make sure they exist.
        app_module.db.create_all()
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


def test_owned_albums_are_marked_as_duplicates(client):
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


def test_fallback_albums_group_and_match_owned_records(client):
    _connect()
    owned = _record("The Beatles", "Abbey Road", have_it=True)
    tracks = [_track("Come Together", "The Beatles", "Abbey Road (Remastered 2009)"),
              _track("Something", "The Beatles", "Abbey Road")]

    def no_claude():
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    with patch.object(spotify_sync, "playlist_tracks", return_value=(tracks, False)), \
         patch.object(scan, "_anthropic_client", no_claude):
        r = client.post("/api/spotify/wishlist-scan", json={"playlist_id": "PL"})
    albums = r.get_json()["albums"]
    assert len(albums) == 1
    assert albums[0]["duplicate_of"]["id"] == owned


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


# ── POST /api/spotify/wishlist-scan/resolve ─────────────────────────────────

def _album(artist, album, **extra):
    row = {"key": f"{artist}|{album}".lower(), "artist": artist, "album_name": album,
           "year": "1969", "songs": ["x"], "spotify_image": "https://i/s.jpg",
           "unverified": False, "duplicate_of": None, "have_it": None}
    row.update(extra)
    return row


@pytest.fixture
def offline_resolve():
    """resolve / covers / vinyl stubbed; tests override what they care about."""
    with patch.object(scan, "resolve_album",
                      side_effect=lambda a, b: {"mbid": f"rg-{b}", "year": "1970",
                                                "artist": a, "album_name": b}) as ra, \
         patch.object(scan, "search_covers",
                      side_effect=lambda rows: [r.__setitem__("cover_data", "data:c") for r in rows]), \
         patch.object(scan, "flag_vinyl",
                      side_effect=lambda rows, **kw: [r.__setitem__("vinyl", "confirmed") for r in rows]) as fv, \
         patch.object(scan, "_download_image", return_value="data:spotify"):
        yield ra, fv


def test_resolve_needs_edit_mode():
    c = app_module.app.test_client()
    r = c.post("/api/spotify/wishlist-scan/resolve", json={"albums": [_album("A", "B")]})
    assert r.status_code == 401


def test_resolve_refuses_empty_and_oversized_chunks(client):
    assert client.post("/api/spotify/wishlist-scan/resolve", json={"albums": []}).status_code == 400
    too_many = [_album("A", f"B{i}") for i in range(app_module.RESOLVE_CHUNK + 1)]
    assert app_module.RESOLVE_CHUNK == 24
    assert client.post("/api/spotify/wishlist-scan/resolve",
                       json={"albums": too_many}).status_code == 400


def test_resolve_fills_mbid_year_cover_and_vinyl_in_order(client, offline_resolve):
    r = client.post("/api/spotify/wishlist-scan/resolve",
                    json={"albums": [_album("The Beatles", "Abbey Road"),
                                     _album("Bill Withers", "Menagerie")]})
    assert r.status_code == 200
    a, b = r.get_json()["albums"]
    assert (a["album_name"], a["mbid"], a["year"], a["cover_data"], a["vinyl"]) == \
           ("Abbey Road", "rg-Abbey Road", "1970", "data:c", "confirmed")
    assert b["album_name"] == "Menagerie" and b["songs"] == ["x"]


def test_resolve_keeps_claudes_name_when_musicbrainz_has_none(client, offline_resolve):
    ra, _ = offline_resolve
    ra.side_effect = lambda a, b: None
    a = client.post("/api/spotify/wishlist-scan/resolve",
                    json={"albums": [_album("X", "Obscure")]}).get_json()["albums"][0]
    assert a["mbid"] is None and a["album_name"] == "Obscure" and a["year"] == "1969"


def test_resolve_falls_back_to_the_spotify_image(client, offline_resolve):
    with patch.object(scan, "search_covers",
                      side_effect=lambda rows: [r.__setitem__("cover_data", None) for r in rows]):
        a = client.post("/api/spotify/wishlist-scan/resolve",
                        json={"albums": [_album("X", "Y", spotify_image="https://i.scdn.co/image/s")]}).get_json()["albums"][0]
    assert a["cover_data"] == "data:spotify"


def test_resolve_skips_rows_already_owned(client, offline_resolve):
    ra, fv = offline_resolve
    owned = _album("X", "Y", duplicate_of={"id": 1, "artist": "X", "album_name": "Y"}, have_it=True)
    a = client.post("/api/spotify/wishlist-scan/resolve",
                    json={"albums": [owned]}).get_json()["albums"][0]
    assert ra.call_count == 0 and a["duplicate_of"]["id"] == 1


def test_resolve_maps_musicbrainz_down_to_502(client, offline_resolve):
    ra, _ = offline_resolve
    ra.side_effect = scan.MusicBrainzUnavailable("down")
    r = client.post("/api/spotify/wishlist-scan/resolve", json={"albums": [_album("X", "Y")]})
    assert r.status_code == 502 and "MusicBrainz" in r.get_json()["error"]


def test_resolve_banks_vinyl_spend_as_playlist(client, offline_resolve):
    _, fv = offline_resolve

    def flag(rows, usage_out=None, **kw):
        usage_out.append({"model": "claude-haiku-4-5", "input_tokens": 1, "output_tokens": 1})
        for r in rows:
            r["vinyl"] = "likely"

    fv.side_effect = flag
    client.post("/api/spotify/wishlist-scan/resolve", json={"albums": [_album("X", "Y")]})
    with app_module.app.app_context():
        assert [r.source for r in app_module.ScanSpend.query.all()] == ["playlist"]


# ── URL validation for Spotify image fallback ───────────────────────────────

def test_resolve_rejects_metadata_ssrf_url(client, offline_resolve):
    """Prevent SSRF via metadata endpoint."""
    with patch.object(scan, "search_covers",
                      side_effect=lambda rows: [r.__setitem__("cover_data", None) for r in rows]) as sc, \
         patch.object(scan, "_download_image") as di:
        a = client.post("/api/spotify/wishlist-scan/resolve",
                        json={"albums": [_album("X", "Y", spotify_image="http://169.254.169.254/latest/meta-data")]}).get_json()["albums"][0]
    assert a["cover_data"] is None
    assert di.call_count == 0


def test_resolve_rejects_https_evil_domain(client, offline_resolve):
    """Reject arbitrary HTTPS domains."""
    with patch.object(scan, "search_covers",
                      side_effect=lambda rows: [r.__setitem__("cover_data", None) for r in rows]) as sc, \
         patch.object(scan, "_download_image") as di:
        a = client.post("/api/spotify/wishlist-scan/resolve",
                        json={"albums": [_album("X", "Y", spotify_image="https://evil.example.com/x.jpg")]}).get_json()["albums"][0]
    assert a["cover_data"] is None
    assert di.call_count == 0


def test_resolve_allows_i_scdn_co(client, offline_resolve):
    """Allow Spotify CDN domain i.scdn.co."""
    with patch.object(scan, "search_covers",
                      side_effect=lambda rows: [r.__setitem__("cover_data", None) for r in rows]), \
         patch.object(scan, "_download_image", return_value="data:spotify") as di:
        a = client.post("/api/spotify/wishlist-scan/resolve",
                        json={"albums": [_album("X", "Y", spotify_image="https://i.scdn.co/image/abc")]}).get_json()["albums"][0]
    assert a["cover_data"] == "data:spotify"
    assert di.call_count == 1


def test_resolve_allows_mosaic_scdn_co(client, offline_resolve):
    """Allow Spotify CDN subdomain *.scdn.co."""
    with patch.object(scan, "search_covers",
                      side_effect=lambda rows: [r.__setitem__("cover_data", None) for r in rows]), \
         patch.object(scan, "_download_image", return_value="data:spotify") as di:
        a = client.post("/api/spotify/wishlist-scan/resolve",
                        json={"albums": [_album("X", "Y", spotify_image="https://mosaic.scdn.co/640/abc")]}).get_json()["albums"][0]
    assert a["cover_data"] == "data:spotify"
    assert di.call_count == 1
