"""resolve_album: the cheap MusicBrainz lookup the wishlist scan uses.

One throttled call per album and no country lookup — lookup_musicbrainz's
three extra artist calls per album would make a playlist of a hundred
albums take five minutes.
"""

import pytest

import scan


def _group(mbid, title, artist="The Beatles", date="1969-09-26", kind="Album"):
    return {"id": mbid, "title": title, "first-release-date": date,
            "primary-type": kind, "score": 100,
            "artist-credit": [{"artist": {"id": "a1", "name": artist}}]}


def test_returns_the_best_ranked_group(monkeypatch):
    calls = []

    def fake_get(path, params, attempts=scan.MB_MAX_ATTEMPTS):
        calls.append((path, params))
        return {"release-groups": [_group("rg-abbey", "Abbey Road")]}

    monkeypatch.setattr(scan, "_mb_get", fake_get)
    assert scan.resolve_album("The Beatles", "Abbey Road") == {
        "mbid": "rg-abbey", "year": "1969", "artist": "The Beatles",
        "album_name": "Abbey Road"}
    assert len(calls) == 1 and calls[0][0] == "/release-group/"


def test_no_groups_is_none(monkeypatch):
    monkeypatch.setattr(scan, "_mb_get", lambda *a, **k: {"release-groups": []})
    assert scan.resolve_album("Nobody", "Nothing") is None


def test_no_artist_or_album_asks_nothing(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("asked MusicBrainz")
    monkeypatch.setattr(scan, "_mb_get", boom)
    assert scan.resolve_album("", "Abbey Road") is None
    assert scan.resolve_album("The Beatles", "") is None


def test_an_unreachable_musicbrainz_raises(monkeypatch):
    def down(*a, **k):
        raise scan.MusicBrainzUnavailable("down")
    monkeypatch.setattr(scan, "_mb_get", down)
    with pytest.raises(scan.MusicBrainzUnavailable):
        scan.resolve_album("The Beatles", "Abbey Road")


def test_a_group_with_no_date_has_no_year(monkeypatch):
    monkeypatch.setattr(scan, "_mb_get", lambda *a, **k: {
        "release-groups": [_group("rg", "Abbey Road", date="")]})
    assert scan.resolve_album("The Beatles", "Abbey Road")["year"] is None
