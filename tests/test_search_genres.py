from unittest.mock import patch

import pytest

import app as app_module
import scan


@pytest.fixture
def client():
    """An authed client over an empty ledger.

    The database is session-scoped, so rows left by another test would land in
    this module's scan ledger.
    """
    app_module.app.config["TESTING"] = True
    with app_module.app.app_context():
        app_module.ScanSpend.query.delete()
        app_module.db.session.commit()
    with app_module.app.test_client() as c:
        with c.session_transaction() as session:
            session["authed"] = True
        yield c


def test_genres_line_up_with_the_releases_sent(client):
    with patch.object(scan, "classify_genre",
                      side_effect=["MPB & Samba", "Soul & Funk"]):
        body = client.post("/api/search/genres", json={"releases": [
            {"artist": "Jorge Ben", "album_name": "Força bruta"},
            {"artist": "Tim Maia", "album_name": "Racional"},
        ]}).get_json()

    assert body["genres"] == ["MPB & Samba", "Soul & Funk"]


def test_an_unclassifiable_record_comes_back_as_null(client):
    with patch.object(scan, "classify_genre", side_effect=["Rock", None]):
        body = client.post("/api/search/genres", json={"releases": [
            {"artist": "Pink Floyd", "album_name": "Animals"},
            {"artist": "Unknown", "album_name": "Unknown"},
        ]}).get_json()

    assert body["genres"] == ["Rock", None]


def test_the_whole_batch_is_one_scan_id(client):
    """A queue's genre work is one act, so _scan_estimate prices it as one."""
    def spend(artist, album, genres, usage_out=None):
        usage_out.append({"model": "claude-haiku-4-5",
                          "input_tokens": 50, "output_tokens": 10})
        return "Rock"

    with patch.object(scan, "classify_genre", side_effect=spend):
        client.post("/api/search/genres", json={"releases": [
            {"artist": "A", "album_name": "1"},
            {"artist": "B", "album_name": "2"},
            {"artist": "C", "album_name": "3"},
        ]})

    with app_module.app.app_context():
        rows = app_module.ScanSpend.query.filter_by(source="search").all()
    assert len(rows) == 3                       # one ledger row per call
    assert len({r.scan_id for r in rows}) == 1  # all under one scan


def test_an_oversized_list_is_refused(client):
    """One request must not become an unbounded fan-out of billed calls."""
    releases = [{"artist": "A", "album_name": str(i)}
                for i in range(scan.MB_SEARCH_LIMIT + 1)]
    with patch.object(scan, "classify_genre") as classify:
        res = client.post("/api/search/genres", json={"releases": releases})

    assert res.status_code == 400
    classify.assert_not_called()


def test_an_empty_list_costs_nothing(client):
    with patch.object(scan, "classify_genre") as classify:
        body = client.post("/api/search/genres", json={"releases": []}).get_json()

    assert body["genres"] == []
    classify.assert_not_called()


def test_a_malformed_item_is_400_not_a_500(client):
    """(r or {}).get("artist") assumes each entry is falsy or a dict. A bare
    string is truthy and has no .get, so it must be rejected before the try
    that would otherwise let AttributeError escape as a raw 500."""
    with patch.object(scan, "classify_genre") as classify:
        res = client.post("/api/search/genres", json={"releases": [
            {"artist": "A", "album_name": "1"},
            "not a release",
        ]})

    assert res.status_code == 400
    classify.assert_not_called()
