from unittest.mock import patch, Mock

import scan

CANDIDATE = {
    "mbid": "8f1318d9-8a6f-3c4c-a6de-bcdabc7123e4",
    "artist": "Bill Withers",
    "album_name": "Live at Carnegie Hall",
    "year": "1973", "country": "US", "label": None,
}


def _image(status=200, content=b"\xff\xd8\xffbytes", ctype="image/jpeg"):
    mock = Mock()
    mock.status_code = status
    mock.content = content
    mock.headers = {"Content-Type": ctype}
    return mock


def test_prefers_cover_art_archive():
    with patch.object(scan.requests, "get", return_value=_image()) as get:
        result = scan.fetch_cover(CANDIDATE)

    assert result.startswith("data:image/jpeg;base64,")
    assert "coverartarchive.org" in get.call_args_list[0].args[0]


def test_falls_back_to_itunes_when_archive_404s():
    itunes_json = Mock(status_code=200)
    itunes_json.json.return_value = {
        "results": [{"artworkUrl100": "https://is1.example.com/a/100x100bb.jpg"}]
    }
    responses = [_image(status=404), itunes_json, _image()]
    with patch.object(scan.requests, "get", side_effect=responses) as get:
        result = scan.fetch_cover(CANDIDATE)

    assert result.startswith("data:image/jpeg;base64,")
    assert "600x600bb" in get.call_args_list[2].args[0]


def test_falls_back_to_spotify_image_last():
    responses = [_image(status=404), Mock(status_code=200, **{"json.return_value": {"results": []}}), _image()]
    with patch.object(scan.requests, "get", side_effect=responses) as get:
        result = scan.fetch_cover(CANDIDATE, spotify_image_url="https://i.scdn.co/image/x")

    assert result.startswith("data:image/jpeg;base64,")
    assert get.call_args_list[2].args[0] == "https://i.scdn.co/image/x"


def test_returns_none_when_everything_misses():
    responses = [_image(status=404), Mock(status_code=200, **{"json.return_value": {"results": []}})]
    with patch.object(scan.requests, "get", side_effect=responses):
        assert scan.fetch_cover(CANDIDATE) is None


def test_returns_none_on_timeout():
    with patch.object(scan.requests, "get", side_effect=scan.requests.Timeout):
        assert scan.fetch_cover(CANDIDATE) is None


def test_no_mbid_skips_archive():
    itunes_json = Mock(status_code=200)
    itunes_json.json.return_value = {"results": []}
    with patch.object(scan.requests, "get", side_effect=[itunes_json]) as get:
        assert scan.fetch_cover({**CANDIDATE, "mbid": None}) is None

    assert "itunes" in get.call_args_list[0].args[0]
