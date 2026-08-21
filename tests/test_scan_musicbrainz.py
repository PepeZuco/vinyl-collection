from unittest.mock import patch, Mock

import pytest

import scan
from conftest import load_fixture


@pytest.fixture(autouse=True)
def no_real_sleeping(monkeypatch):
    """Neutralise the 1 req/sec throttle so the suite doesn't crawl.

    Without this, every lookup in this module blocks for a real second.
    """
    monkeypatch.setattr(scan.time, "sleep", lambda _s: None)
    monkeypatch.setattr(scan, "_mb_last_call", 0.0)


def _response(payload, status=200):
    mock = Mock()
    mock.status_code = status
    mock.json.return_value = payload
    mock.raise_for_status = Mock()
    return mock


def test_returns_year_and_country():
    responses = [
        _response(load_fixture("mb_release_group_withers")),
        _response(load_fixture("mb_artist_withers")),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("Bill Withers", "Live at Carnegie Hall")

    assert candidates[0]["year"] == "1973"
    assert candidates[0]["country"] == "US"
    assert candidates[0]["mbid"] == "8f1318d9-8a6f-3c4c-a6de-bcdabc7123e4"
    assert candidates[0]["album_name"] == "Live at Carnegie Hall"


def test_missing_release_date_yields_no_year():
    responses = [
        _response(load_fixture("mb_release_group_withers")),
        _response(load_fixture("mb_artist_withers")),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("Bill Withers", "Para Sempre")

    assert candidates[1]["year"] is None
    assert candidates[1]["country"] == "US"


def test_country_falls_back_to_area_iso_code():
    """When the artist's `country` field is null, fall back to
    `area.iso-3166-1-codes[0]` rather than leaving country unset.
    """
    responses = [
        _response(load_fixture("mb_release_group_withers")),
        _response(load_fixture("mb_artist_country_fallback")),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("Bill Withers", "Live at Carnegie Hall")

    assert candidates[0]["country"] == "GB"


def test_country_none_when_both_country_and_area_missing():
    """Neither `country` nor `area` present: country comes back None,
    not a raised exception or a bogus value.
    """
    responses = [
        _response(load_fixture("mb_release_group_withers")),
        _response({"id": "cccccccc-0000-0000-0000-000000000003", "name": "No Country Artist"}),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("Bill Withers", "Live at Carnegie Hall")

    assert candidates[0]["country"] is None


def test_no_match_returns_empty_list():
    with patch.object(scan.requests, "get", return_value=_response({"release-groups": []})):
        assert scan.lookup_musicbrainz("Nobody", "Nothing") == []


def test_network_error_returns_empty_list():
    with patch.object(scan.requests, "get", side_effect=scan.requests.RequestException):
        assert scan.lookup_musicbrainz("Bill Withers", "Menagerie") == []


def test_sends_identifying_user_agent():
    with patch.object(scan.requests, "get", return_value=_response({"release-groups": []})) as get:
        scan.lookup_musicbrainz("Bill Withers", "Menagerie")

    headers = get.call_args.kwargs["headers"]
    assert "VinylCollection" in headers["User-Agent"]


def test_throttle_enforces_one_second_gap():
    sleeps = []
    with patch.object(scan.time, "sleep", side_effect=sleeps.append):
        with patch.object(scan.time, "monotonic", side_effect=[0.0, 0.0, 0.2, 0.2]):
            scan._throttle_musicbrainz()
            scan._throttle_musicbrainz()

    assert sleeps and sleeps[0] > 0
