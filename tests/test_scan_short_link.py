"""spotify.link share-sheet short links.

The Spotify mobile share sheet emits `spotify.link/<code>`, not an
open.spotify.com URL — so this is the *primary* path for "paste from your
phone". Resolving it needs a network hop, which is why it lives in
_resolve_short_link and not in parse_spotify_url: that function stays pure.
"""
import logging
from unittest.mock import patch, Mock

import pytest

import scan
from conftest import load_fixture

SHORT_LINK = "https://spotify.link/aBcD1234xyz"
APP_LINK = "https://spotify.app.link/aBcD1234xyz"
ALBUM_URL = "https://open.spotify.com/album/4LH4d3cOWNNsVw41Gqt2kv?si=abc"


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "secret")
    scan._spotify_token = None
    scan._spotify_token_expiry = 0.0


def _redirect(location, status=302):
    mock = Mock()
    mock.status_code = status
    mock.headers = {"Location": location}
    return mock


def _json_response(payload, status=200):
    mock = Mock()
    mock.status_code = status
    mock.headers = {}
    mock.json.return_value = payload
    return mock


def _token_response():
    return _json_response({"access_token": "tok", "expires_in": 3600})


# ── _resolve_short_link in isolation ──────────────────────────────────────────

def test_short_link_resolves_to_the_album_url():
    with patch.object(scan.requests, "get", return_value=_redirect(ALBUM_URL)) as get:
        assert scan._resolve_short_link(SHORT_LINK) == ALBUM_URL

    # allow_redirects must be off: each hop is vetted before the next request.
    assert get.call_args.kwargs["allow_redirects"] is False
    assert get.call_args.kwargs["timeout"] == scan.SHORT_LINK_TIMEOUT


def test_multiple_hops_are_followed():
    responses = [_redirect(APP_LINK), _redirect(ALBUM_URL)]
    with patch.object(scan.requests, "get", side_effect=responses):
        assert scan._resolve_short_link(SHORT_LINK) == ALBUM_URL


def test_relative_redirect_is_resolved_against_the_short_link():
    responses = [_redirect("/OtherCode"), _redirect(ALBUM_URL)]
    with patch.object(scan.requests, "get", side_effect=responses) as get:
        assert scan._resolve_short_link(SHORT_LINK) == ALBUM_URL

    assert get.call_args_list[1].args[0] == "https://spotify.link/OtherCode"


def test_redirect_to_an_unexpected_host_is_rejected(caplog):
    """An open redirect must never make this function fetch an arbitrary host."""
    with caplog.at_level(logging.WARNING, logger="scan"):
        with patch.object(
            scan.requests, "get", return_value=_redirect("https://evil.example.com/x")
        ) as get:
            assert scan._resolve_short_link(SHORT_LINK) == SHORT_LINK

    # One request only — to spotify.link. The off-Spotify hop is never fetched.
    assert get.call_count == 1
    assert "evil.example.com" in caplog.text


def test_timeout_returns_the_input_unchanged(caplog):
    with caplog.at_level(logging.WARNING, logger="scan"):
        with patch.object(scan.requests, "get", side_effect=scan.requests.Timeout):
            assert scan._resolve_short_link(SHORT_LINK) == SHORT_LINK

    assert caplog.records, "an unresolvable short link must leave a log record"


def test_non_redirect_response_returns_the_input_unchanged():
    with patch.object(scan.requests, "get", return_value=_json_response({}, status=200)):
        assert scan._resolve_short_link(SHORT_LINK) == SHORT_LINK


def test_a_redirect_loop_terminates():
    with patch.object(scan.requests, "get", return_value=_redirect(SHORT_LINK)) as get:
        assert scan._resolve_short_link(SHORT_LINK) == SHORT_LINK

    assert get.call_count == scan._MAX_SHORT_LINK_HOPS


@pytest.mark.parametrize("url", [
    "https://open.spotify.com/album/4LH4d3cOWNNsVw41Gqt2kv",
    "spotify:album:4LH4d3cOWNNsVw41Gqt2kv",
    "not a url at all",
    "",
])
def test_non_short_links_pass_through_without_a_request(url):
    with patch.object(scan.requests, "get") as get:
        assert scan._resolve_short_link(url) == url

    get.assert_not_called()


def test_parse_spotify_url_stays_pure():
    """The parser must not have grown a network dependency."""
    with patch.object(scan.requests, "get") as get:
        with pytest.raises(ValueError):
            scan.parse_spotify_url(SHORT_LINK)

    get.assert_not_called()


# ── end to end through extract_from_spotify ───────────────────────────────────

def test_short_link_scan_resolves_the_album():
    responses = [_redirect(ALBUM_URL), _json_response(load_fixture("spotify_album"))]
    with patch.object(scan.requests, "post", return_value=_token_response()):
        with patch.object(scan.requests, "get", side_effect=responses) as get:
            result = scan.extract_from_spotify(SHORT_LINK)

    assert result["artist"] == "Bill Withers"
    assert result["album_name"] == "Live at Carnegie Hall"
    assert "/albums/4LH4d3cOWNNsVw41Gqt2kv" in get.call_args_list[1].args[0]


def test_unresolvable_short_link_still_raises_value_error():
    """The 400 path app.py depends on must survive a failed resolution."""
    with patch.object(scan.requests, "get", side_effect=scan.requests.ConnectionError):
        with pytest.raises(ValueError):
            scan.extract_from_spotify(SHORT_LINK)


def test_short_link_redirecting_off_spotify_raises_value_error():
    with patch.object(scan.requests, "get", return_value=_redirect("https://evil.example.com/x")):
        with pytest.raises(ValueError):
            scan.extract_from_spotify(SHORT_LINK)


def test_short_link_to_a_playlist_raises_value_error():
    playlist = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
    with patch.object(scan.requests, "get", return_value=_redirect(playlist)):
        with pytest.raises(ValueError):
            scan.extract_from_spotify(SHORT_LINK)
