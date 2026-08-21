import pytest
from scan import parse_spotify_url

ALBUM_ID = "4LH4d3cOWNNsVw41Gqt2kv"
TRACK_ID = "0eGsygTp906u18L0Oimnem"


@pytest.mark.parametrize("url", [
    f"https://open.spotify.com/album/{ALBUM_ID}",
    f"https://open.spotify.com/album/{ALBUM_ID}?si=abc123def456",
    f"https://open.spotify.com/intl-pt/album/{ALBUM_ID}",
    f"https://open.spotify.com/intl-de/album/{ALBUM_ID}?si=x",
    f"spotify:album:{ALBUM_ID}",
    f"  https://open.spotify.com/album/{ALBUM_ID}  ",
])
def test_album_urls_resolve(url):
    assert parse_spotify_url(url) == ("album", ALBUM_ID)


@pytest.mark.parametrize("url", [
    f"https://open.spotify.com/track/{TRACK_ID}",
    f"https://open.spotify.com/intl-pt/track/{TRACK_ID}?si=q",
    f"spotify:track:{TRACK_ID}",
])
def test_track_urls_resolve(url):
    assert parse_spotify_url(url) == ("track", TRACK_ID)


@pytest.mark.parametrize("url", [
    "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
    "https://open.spotify.com/artist/3fMbdgg4jU18AjLCKBhRSm",
    "https://example.com/album/123",
    "not a url at all",
    "",
])
def test_unsupported_urls_raise(url):
    with pytest.raises(ValueError):
        parse_spotify_url(url)
