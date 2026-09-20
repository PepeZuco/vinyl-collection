"""The Spotify album link a record carries.

Free text, no format validation on write — see tests/test_places.py for what
a validated link field looks like; this one is deliberately not that, since a
scan can hand back any link the user pasted and a rejected save would lose it.
"""
import pytest

# See tests/test_places.py's comment on why this suite goes through
# app_module rather than binding `app`/`db`/`Record` at module scope.
import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.app_context():
        app_module.Record.query.delete()
        app_module.db.session.commit()
    with app_module.app.test_client() as c:
        yield c


@pytest.fixture
def authed(client):
    assert client.post("/api/auth/login",
                       json={"password": app_module.EDIT_PASSWORD}).status_code == 200
    return client


def test_create_stores_the_spotify_link(authed):
    r = authed.post("/api/records", json={
        "artist": "a", "album_name": "b",
        "spotify_url": "https://open.spotify.com/album/4LH4d3cOWNNsVw41Gqt2kv",
    })

    assert r.status_code == 201
    assert r.get_json()["spotify_url"] == "https://open.spotify.com/album/4LH4d3cOWNNsVw41Gqt2kv"


def test_create_without_a_link_leaves_it_empty(authed):
    r = authed.post("/api/records", json={"artist": "a", "album_name": "b"})

    assert r.status_code == 201
    assert r.get_json()["spotify_url"] == ""


def test_update_sets_the_link(authed):
    rid = authed.post("/api/records", json={"artist": "a", "album_name": "b"}).get_json()["id"]

    r = authed.put(f"/api/records/{rid}",
                   json={"spotify_url": "https://open.spotify.com/album/xyz"})

    assert r.status_code == 200
    assert r.get_json()["spotify_url"] == "https://open.spotify.com/album/xyz"


def test_update_can_clear_the_link(authed):
    rid = authed.post("/api/records", json={
        "artist": "a", "album_name": "b",
        "spotify_url": "https://open.spotify.com/album/xyz",
    }).get_json()["id"]

    r = authed.put(f"/api/records/{rid}", json={"spotify_url": ""})

    assert r.status_code == 200
    assert r.get_json()["spotify_url"] == ""


def test_update_without_the_field_leaves_the_link_alone(authed):
    rid = authed.post("/api/records", json={
        "artist": "a", "album_name": "b",
        "spotify_url": "https://open.spotify.com/album/xyz",
    }).get_json()["id"]

    r = authed.put(f"/api/records/{rid}", json={"artist": "a2"})

    assert r.status_code == 200
    assert r.get_json()["spotify_url"] == "https://open.spotify.com/album/xyz"


# ── cleaned-up links ────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, stored", [
    ("https://open.spotify.com/album/xyz?si=abc123",
     "https://open.spotify.com/album/xyz"),
    ("  https://open.spotify.com/album/xyz?si=abc&utm_source=copy-link  ",
     "https://open.spotify.com/album/xyz"),
    ("https://open.spotify.com/intl-pt/album/xyz?si=abc",
     "https://open.spotify.com/album/xyz"),
    ("spotify:album:xyz", "https://open.spotify.com/album/xyz"),
    ("https://example.com/whatever?si=1", "https://example.com/whatever?si=1"),
])
def test_links_are_cleaned_on_save(authed, raw, stored):
    r = authed.post("/api/records", json={"artist": "a", "album_name": "b",
                                          "spotify_url": raw})
    assert r.get_json()["spotify_url"] == stored


def test_update_cleans_the_link_too(authed):
    rid = authed.post("/api/records", json={"artist": "a", "album_name": "b"}).get_json()["id"]
    r = authed.put(f"/api/records/{rid}",
                   json={"spotify_url": "spotify:album:xyz"})
    assert r.get_json()["spotify_url"] == "https://open.spotify.com/album/xyz"


# ── not on Spotify ──────────────────────────────────────────────────────────

def test_spotify_missing_defaults_to_false(authed):
    r = authed.post("/api/records", json={"artist": "a", "album_name": "b"})
    assert r.get_json()["spotify_missing"] is False


def test_create_and_update_the_missing_flag(authed):
    rid = authed.post("/api/records", json={
        "artist": "a", "album_name": "b", "spotify_missing": True,
    }).get_json()["id"]
    r = authed.put(f"/api/records/{rid}", json={"spotify_missing": False})
    assert r.get_json()["spotify_missing"] is False


def test_update_without_the_flag_leaves_it_alone(authed):
    rid = authed.post("/api/records", json={
        "artist": "a", "album_name": "b", "spotify_missing": True,
    }).get_json()["id"]
    r = authed.put(f"/api/records/{rid}", json={"artist": "a2"})
    assert r.get_json()["spotify_missing"] is True


def test_a_link_wins_over_the_flag(authed):
    r = authed.post("/api/records", json={
        "artist": "a", "album_name": "b", "spotify_missing": True,
        "spotify_url": "https://open.spotify.com/album/xyz",
    })
    assert r.get_json()["spotify_missing"] is False
