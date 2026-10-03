from unittest.mock import patch, Mock

import pytest

import scan


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


def _album(spotify_id, name, *artists, image="https://i.scdn.co/image/big"):
    return {"id": spotify_id, "name": name,
            "artists": [{"name": a} for a in artists],
            "images": [{"url": image}] if image else []}


def _search(*albums):
    return _json_response({"albums": {"items": list(albums)}})


def _find(results, artist="Bill Withers", album="Live at Carnegie Hall"):
    with patch.object(scan.requests, "post", return_value=_token_response()), \
         patch.object(scan.requests, "get", return_value=results) as get:
        return scan.find_spotify_album(artist, album), get


def test_an_exact_match_returns_its_link_and_artwork():
    found, get = _find(_search(_album("4LH4", "Live at Carnegie Hall", "Bill Withers")))

    assert found == {"url": "https://open.spotify.com/album/4LH4",
                     "image_url": "https://i.scdn.co/image/big"}
    assert "/search" in get.call_args.args[0]
    assert "type=album" in get.call_args.args[0]


def test_a_remaster_tail_still_matches():
    found, _ = _find(_search(
        _album("rm", "Live at Carnegie Hall (Remastered 2015)", "Bill Withers")))
    assert found["url"].endswith("/rm")


def test_a_dash_suffix_still_matches():
    found, _ = _find(_search(
        _album("dx", "Live at Carnegie Hall - Deluxe Edition", "Bill Withers")))
    assert found["url"].endswith("/dx")


def test_accents_and_case_do_not_matter():
    found, _ = _find(_search(_album("cb", "Construção", "Chico Buarque")),
                     artist="chico buarque", album="CONSTRUCAO")
    assert found["url"].endswith("/cb")


def test_the_first_exact_match_wins_over_a_looser_earlier_hit():
    found, _ = _find(_search(
        _album("other", "Live at Carnegie Hall Volume 2", "Bill Withers"),
        _album("right", "Live at Carnegie Hall", "Bill Withers"),
    ))
    assert found["url"].endswith("/right")


def test_a_different_artist_is_not_accepted():
    found, _ = _find(_search(_album("cover", "Live at Carnegie Hall", "Tribute Band")))
    assert found is None


def test_a_longer_title_is_not_accepted():
    """Clube da Esquina 2 is not Clube da Esquina — a wrong link is worse than none."""
    found, _ = _find(_search(_album("two", "Clube da Esquina 2", "Milton Nascimento")),
                     artist="Milton Nascimento", album="Clube da Esquina")
    assert found is None


def test_one_of_several_credited_artists_is_enough():
    found, _ = _find(_search(_album("dup", "Gil e Jorge", "Gilberto Gil", "Jorge Ben")),
                     artist="Gilberto Gil", album="Gil e Jorge")
    assert found["url"].endswith("/dup")


def test_joined_credits_match_too():
    found, _ = _find(_search(_album("dup", "Gil e Jorge", "Gilberto Gil", "Jorge Ben")),
                     artist="Gilberto Gil, Jorge Ben", album="Gil e Jorge")
    assert found["url"].endswith("/dup")


def test_no_artwork_is_fine():
    found, _ = _find(_search(_album("na", "Live at Carnegie Hall", "Bill Withers", image=None)))
    assert found == {"url": "https://open.spotify.com/album/na", "image_url": None}


def test_no_results_returns_none():
    found, _ = _find(_search())
    assert found is None


def test_missing_fields_skip_the_request():
    with patch.object(scan.requests, "get") as get:
        assert scan.find_spotify_album("", "Live at Carnegie Hall") is None
        assert scan.find_spotify_album("Bill Withers", "") is None
    get.assert_not_called()


def test_a_spotify_failure_never_raises():
    found, _ = _find(_json_response({}, status=500))
    assert found is None


def test_missing_credentials_never_raise(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID")
    assert scan.find_spotify_album("Bill Withers", "Live at Carnegie Hall") is None
