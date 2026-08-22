from unittest.mock import patch

import pytest

import app as app_module


@pytest.fixture
def client(monkeypatch, tmp_path):
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        with test_client.session_transaction() as session:
            session["authed"] = True
        yield test_client


def test_requires_auth():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as anon:
        assert anon.post("/api/scan", json={"image": "data:image/jpeg;base64,x"}).status_code == 401


def test_rejects_both_inputs(client):
    response = client.post("/api/scan", json={"image": "x", "spotify_url": "y"})
    assert response.status_code == 400


def test_rejects_neither_input(client):
    assert client.post("/api/scan", json={}).status_code == 400


def test_photo_path_returns_merged_fields(client):
    extracted = {"artist": "Bill Withers", "album_name": "Live at Carnegie Hall",
                 "genre": "Soul & Funk", "label": "Sussex", "catalog_number": None}
    candidate = {"mbid": "abc", "year": "1973", "country": "US", "label": None,
                 "artist": "Bill Withers", "album_name": "Live at Carnegie Hall"}

    with patch.object(app_module.scan, "extract_from_image", return_value=extracted), \
         patch.object(app_module.scan, "lookup_musicbrainz", return_value=[candidate]), \
         patch.object(app_module.scan, "fetch_cover", return_value="data:image/jpeg;base64,zz"):
        response = client.post("/api/scan", json={"image": "data:image/jpeg;base64,x"})

    body = response.get_json()
    assert response.status_code == 200
    assert body["source"] == "photo"
    assert body["artist"] == "Bill Withers"
    assert body["genre"] == "Soul & Funk"
    assert body["candidates"][0]["year"] == "1973"
    assert body["candidates"][0]["cover_data"] == "data:image/jpeg;base64,zz"
    assert "Bill Withers Live at Carnegie Hall 1973 vinyl cover" == body["search_string"]


def test_spotify_path_classifies_genre(client):
    resolved = {"artist": "Bill Withers", "album_name": "Live at Carnegie Hall",
                "image_url": "https://i.scdn.co/image/big"}
    candidate = {"mbid": "abc", "year": "1973", "country": "US", "label": None,
                 "artist": "Bill Withers", "album_name": "Live at Carnegie Hall"}

    with patch.object(app_module.scan, "extract_from_spotify", return_value=resolved), \
         patch.object(app_module.scan, "classify_genre", return_value="Soul & Funk"), \
         patch.object(app_module.scan, "lookup_musicbrainz", return_value=[candidate]), \
         patch.object(app_module.scan, "fetch_cover", return_value=None):
        response = client.post("/api/scan",
                               json={"spotify_url": "spotify:album:4LH4d3cOWNNsVw41Gqt2kv"})

    body = response.get_json()
    assert body["source"] == "spotify"
    assert body["genre"] == "Soul & Funk"


def test_musicbrainz_miss_still_returns_vision_fields(client):
    extracted = {"artist": "Obscure", "album_name": "Unknown", "genre": "Jazz",
                 "label": None, "catalog_number": None}

    with patch.object(app_module.scan, "extract_from_image", return_value=extracted), \
         patch.object(app_module.scan, "lookup_musicbrainz", return_value=[]):
        response = client.post("/api/scan", json={"image": "data:image/jpeg;base64,x"})

    body = response.get_json()
    assert response.status_code == 200
    assert body["artist"] == "Obscure"
    assert body["candidates"] == []


def test_missing_api_key_returns_503(client):
    with patch.object(app_module.scan, "extract_from_image",
                      side_effect=RuntimeError("ANTHROPIC_API_KEY is not set")):
        response = client.post("/api/scan", json={"image": "data:image/jpeg;base64,x"})

    assert response.status_code == 503


def test_bad_spotify_url_returns_400(client):
    with patch.object(app_module.scan, "extract_from_spotify",
                      side_effect=ValueError("nope")):
        response = client.post("/api/scan", json={"spotify_url": "https://example.com"})

    assert response.status_code == 400


def test_unexpected_scan_error_returns_json_not_500_page(client):
    """A violated never-raise contract must still degrade to a JSON error."""
    extracted = {"artist": "A", "album_name": "B", "genre": None,
                 "label": None, "catalog_number": None}
    with patch.object(app_module.scan, "extract_from_image", return_value=extracted), \
         patch.object(app_module.scan, "lookup_musicbrainz",
                      side_effect=TypeError("contract violated")):
        response = client.post("/api/scan", json={"image": "data:image/jpeg;base64,x"})

    assert response.status_code == 502
    assert response.is_json
    assert "error" in response.get_json()
