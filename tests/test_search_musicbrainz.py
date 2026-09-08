from unittest.mock import patch, Mock

import pytest

import scan
from conftest import load_fixture


@pytest.fixture(autouse=True)
def no_real_sleeping(monkeypatch):
    """Neutralise the 1 req/sec throttle so the suite doesn't crawl."""
    monkeypatch.setattr(scan.time, "sleep", lambda _s: None)
    monkeypatch.setattr(scan, "_mb_last_call", 0.0)


def _response(payload, status=200):
    mock = Mock()
    mock.status_code = status
    mock.json.return_value = payload
    mock.raise_for_status = Mock()
    return mock


# ── lookup_artist ───────────────────────────────────────────────────────────

def test_resolves_the_top_scoring_artist():
    with patch.object(scan.requests, "get",
                      return_value=_response(load_fixture("mb_artist_search_jorge_ben"))):
        found = scan.lookup_artist("jorge ben")

    assert found == {"mbid": "19499124-36d4-4ccc-b28d-04dde3d2076f",
                     "name": "Jorge Ben Jor", "country": "BR"}


def test_no_artists_returns_none():
    with patch.object(scan.requests, "get",
                      return_value=_response({"count": 0, "artists": []})):
        assert scan.lookup_artist("zzzzzzzz") is None


def test_a_weak_top_score_returns_none():
    """Below MB_MIN_SCORE the top hit is noise, and offering it makes the
    search look like it guessed — the same reason the scan applies this."""
    weak = {"count": 1, "artists": [
        {"id": "aaaa", "name": "Something Else", "score": 12, "country": "US"}]}
    with patch.object(scan.requests, "get", return_value=_response(weak)):
        assert scan.lookup_artist("jorge ben") is None


def test_an_unreachable_musicbrainz_propagates():
    with patch.object(scan, "_mb_get",
                      side_effect=scan.MusicBrainzUnavailable("down")):
        with pytest.raises(scan.MusicBrainzUnavailable):
            scan.lookup_artist("jorge ben")


# ── lookup_discography ──────────────────────────────────────────────────────

def test_lists_the_discography_chronologically():
    responses = [
        _response(load_fixture("mb_discography_jorge_ben")),
        _response(load_fixture("mb_artist_jorge_ben")),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        rows = scan.lookup_discography("19499124-36d4-4ccc-b28d-04dde3d2076f")

    assert [r["album_name"] for r in rows] == [
        "Ben é samba bom", "Força bruta", "África Brasil", "Grandes nomes"]
    assert [r["year"] for r in rows] == ["1964", "1970", "1976", None]


def test_rows_use_the_credited_artist_name_not_the_canonical_one():
    """MusicBrainz canonicalises to "Jorge Ben Jor"; the collection says
    "Jorge Ben". Filling the form with the canonical name would split the
    artist in the shelf's crates, and duplicate detection would never match."""
    responses = [
        _response(load_fixture("mb_discography_jorge_ben")),
        _response(load_fixture("mb_artist_jorge_ben")),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        rows = scan.lookup_discography("19499124-36d4-4ccc-b28d-04dde3d2076f")

    assert rows[0]["artist"] == "Jorge Ben"
    assert rows[0]["credited"] == "Jorge Ben"
    assert rows[0]["canonical"] == "Jorge Ben Jor"
    # The row with no separate credit falls back to the canonical spelling.
    assert rows[3]["artist"] == "Jorge Ben Jor"


def test_the_query_asks_for_albums_by_mbid_and_excludes_comps():
    responses = [
        _response(load_fixture("mb_discography_jorge_ben")),
        _response(load_fixture("mb_artist_jorge_ben")),
    ]
    with patch.object(scan.requests, "get", side_effect=responses) as get:
        scan.lookup_discography("19499124-36d4-4ccc-b28d-04dde3d2076f")

    query = get.call_args_list[0].kwargs["params"]["query"]
    # arid:, not artist:(name) — the fuzzy artist match returns 3655 rows
    # scoring 100 apiece and is worthless on its own.
    assert "arid:19499124-36d4-4ccc-b28d-04dde3d2076f" in query
    assert "primarytype:Album" in query
    assert "-secondarytype:Compilation" in query
    assert "-secondarytype:Live" in query
    assert get.call_args_list[0].kwargs["params"]["limit"] == scan.MB_SEARCH_LIMIT


def test_an_album_narrows_the_query():
    responses = [
        _response(load_fixture("mb_discography_jorge_ben")),
        _response(load_fixture("mb_artist_jorge_ben")),
    ]
    with patch.object(scan.requests, "get", side_effect=responses) as get:
        scan.lookup_discography("19499124-36d4-4ccc-b28d-04dde3d2076f",
                                album="Africa Brasil")

    query = get.call_args_list[0].kwargs["params"]["query"]
    assert "releasegroup:(Africa Brasil)" in query


def test_the_artist_country_is_fetched_once_for_the_whole_discography():
    responses = [
        _response(load_fixture("mb_discography_jorge_ben")),
        _response(load_fixture("mb_artist_jorge_ben")),
    ]
    with patch.object(scan.requests, "get", side_effect=responses) as get:
        rows = scan.lookup_discography("19499124-36d4-4ccc-b28d-04dde3d2076f")

    assert {r["country"] for r in rows} == {"BR"}
    assert get.call_count == 2   # the search, then one artist lookup — not one per row
