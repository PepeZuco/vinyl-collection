from unittest.mock import patch, Mock

import pytest

import scan
from conftest import load_fixture


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "secret")
    scan._spotify_token = None
    scan._spotify_token_expiry = 0.0


def _json_response(payload, status=200):
    mock = Mock()
    mock.status_code = status
    mock.json.return_value = payload
    return mock


def _token_response():
    return _json_response({"access_token": "tok", "expires_in": 3600})


def test_album_link_returns_fields():
    album = _json_response(load_fixture("spotify_album"))
    with patch.object(scan.requests, "post", return_value=_token_response()):
        with patch.object(scan.requests, "get", return_value=album):
            result = scan.extract_from_spotify(
                "https://open.spotify.com/album/4LH4d3cOWNNsVw41Gqt2kv"
            )

    assert result["artist"] == "Bill Withers"
    assert result["album_name"] == "Live at Carnegie Hall"
    assert result["image_url"] == "https://i.scdn.co/image/big"


def test_release_date_is_never_returned_as_year():
    """Guards the original-release convention: Spotify dates are reissue dates."""
    album = _json_response(load_fixture("spotify_album"))
    with patch.object(scan.requests, "post", return_value=_token_response()):
        with patch.object(scan.requests, "get", return_value=album):
            result = scan.extract_from_spotify(
                "https://open.spotify.com/album/4LH4d3cOWNNsVw41Gqt2kv"
            )

    assert "year" not in result
    assert "2015" not in str(result)


def test_track_link_resolves_via_its_album():
    track = _json_response({"album": load_fixture("spotify_album")})
    with patch.object(scan.requests, "post", return_value=_token_response()):
        with patch.object(scan.requests, "get", return_value=track) as get:
            result = scan.extract_from_spotify(
                "https://open.spotify.com/track/0eGsygTp906u18L0Oimnem"
            )

    assert "/tracks/" in get.call_args.args[0]
    assert result["album_name"] == "Live at Carnegie Hall"


def test_multiple_artists_are_joined():
    payload = load_fixture("spotify_album")
    payload["artists"] = [{"name": "Jorge Ben"}, {"name": "Gilberto Gil"}]
    with patch.object(scan.requests, "post", return_value=_token_response()):
        with patch.object(scan.requests, "get", return_value=_json_response(payload)):
            result = scan.extract_from_spotify("spotify:album:4LH4d3cOWNNsVw41Gqt2kv")

    assert result["artist"] == "Jorge Ben, Gilberto Gil"


def test_token_is_cached_across_calls():
    album = _json_response(load_fixture("spotify_album"))
    with patch.object(scan.requests, "post", return_value=_token_response()) as post:
        with patch.object(scan.requests, "get", return_value=album):
            scan.extract_from_spotify("spotify:album:4LH4d3cOWNNsVw41Gqt2kv")
            scan.extract_from_spotify("spotify:album:4LH4d3cOWNNsVw41Gqt2kv")

    assert post.call_count == 1


def test_401_triggers_exactly_one_refresh():
    album = _json_response(load_fixture("spotify_album"))
    responses = [_json_response({}, status=401), album]
    with patch.object(scan.requests, "post", return_value=_token_response()) as post:
        with patch.object(scan.requests, "get", side_effect=responses):
            result = scan.extract_from_spotify("spotify:album:4LH4d3cOWNNsVw41Gqt2kv")

    assert post.call_count == 2
    assert result["album_name"] == "Live at Carnegie Hall"


def test_missing_credentials_raise(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    with pytest.raises(RuntimeError):
        scan.extract_from_spotify("spotify:album:4LH4d3cOWNNsVw41Gqt2kv")


def test_unknown_album_raises():
    with patch.object(scan.requests, "post", return_value=_token_response()):
        with patch.object(scan.requests, "get", return_value=_json_response({}, status=404)):
            with pytest.raises(RuntimeError):
                scan.extract_from_spotify("spotify:album:4LH4d3cOWNNsVw41Gqt2kv")


def test_playlist_link_raises_value_error():
    with pytest.raises(ValueError):
        scan.extract_from_spotify("https://open.spotify.com/playlist/37i9dQZF1DX")
