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


@pytest.fixture(autouse=True)
def _clean_records():
    with app_module.app.app_context():
        app_module.Record.query.delete()
        app_module.db.session.commit()
    yield


def _seed(artist, album):
    with app_module.app.app_context():
        app_module.db.session.add(
            app_module.Record(artist=artist, album_name=album, genre="MPB & Samba"))
        app_module.db.session.commit()


DISCOGRAPHY = [
    {"mbid": "m1", "year": "1970", "country": "BR", "artist": "Jorge Ben",
     "credited": "Jorge Ben", "canonical": "Jorge Ben Jor",
     "album_name": "Força bruta", "type": "Album", "label": None},
    {"mbid": "m2", "year": "1976", "country": "BR", "artist": "Jorge Ben",
     "credited": "Jorge Ben", "canonical": "Jorge Ben Jor",
     "album_name": "África Brasil", "type": "Album", "label": None},
]


def test_returns_the_discography(client):
    with patch.object(scan, "parse_search_query",
                      return_value={"artist": "Jorge Ben", "album": None}), \
         patch.object(scan, "lookup_artist",
                      return_value={"mbid": "19499124", "name": "Jorge Ben Jor",
                                    "country": "BR"}), \
         patch.object(scan, "lookup_discography",
                      return_value=[dict(r) for r in DISCOGRAPHY]), \
         patch.object(scan, "search_covers"):
        res = client.post("/api/search", json={"query": "jorge ben"})

    assert res.status_code == 200
    body = res.get_json()
    assert body["artist"] == "Jorge Ben Jor"
    assert [r["album_name"] for r in body["results"]] == [
        "Força bruta", "África Brasil"]


def test_a_record_you_already_own_is_flagged_per_row(client):
    """The collection files this artist as "Jorge Ben"; MusicBrainz
    canonicalises to "Jorge Ben Jor". Matching only the canonical spelling
    would badge nothing."""
    _seed("Jorge Ben", "África Brasil")

    with patch.object(scan, "parse_search_query",
                      return_value={"artist": "Jorge Ben", "album": None}), \
         patch.object(scan, "lookup_artist",
                      return_value={"mbid": "19499124", "name": "Jorge Ben Jor",
                                    "country": "BR"}), \
         patch.object(scan, "lookup_discography",
                      return_value=[dict(r) for r in DISCOGRAPHY]), \
         patch.object(scan, "search_covers"):
        body = client.post("/api/search", json={"query": "jorge ben"}).get_json()

    assert body["results"][0]["duplicate_of"] is None
    assert body["results"][1]["duplicate_of"]["album_name"] == "África Brasil"


def test_a_collection_filed_under_the_canonical_name_is_also_matched(client):
    _seed("Jorge Ben Jor", "Força bruta")

    with patch.object(scan, "parse_search_query",
                      return_value={"artist": "Jorge Ben", "album": None}), \
         patch.object(scan, "lookup_artist",
                      return_value={"mbid": "19499124", "name": "Jorge Ben Jor",
                                    "country": "BR"}), \
         patch.object(scan, "lookup_discography",
                      return_value=[dict(r) for r in DISCOGRAPHY]), \
         patch.object(scan, "search_covers"):
        body = client.post("/api/search", json={"query": "jorge ben"}).get_json()

    assert body["results"][0]["duplicate_of"]["album_name"] == "Força bruta"


def test_the_credited_name_is_tried_before_the_canonical_one(client):
    """The same album sits in the collection under BOTH spellings. If
    _search_duplicate tried the canonical name first, it would report the
    canonical row here instead — this only fails if that order is reversed."""
    _seed("Jorge Ben", "Força bruta")
    _seed("Jorge Ben Jor", "Força bruta")

    with patch.object(scan, "parse_search_query",
                      return_value={"artist": "Jorge Ben", "album": None}), \
         patch.object(scan, "lookup_artist",
                      return_value={"mbid": "19499124", "name": "Jorge Ben Jor",
                                    "country": "BR"}), \
         patch.object(scan, "lookup_discography",
                      return_value=[dict(r) for r in DISCOGRAPHY]), \
         patch.object(scan, "search_covers"):
        body = client.post("/api/search", json={"query": "jorge ben"}).get_json()

    dup = body["results"][0]["duplicate_of"]
    assert dup is not None
    assert dup["artist"] == "Jorge Ben"


def test_no_such_artist_is_an_empty_list_not_an_error(client):
    with patch.object(scan, "parse_search_query",
                      return_value={"artist": "Zzz", "album": None}), \
         patch.object(scan, "lookup_artist", return_value=None):
        res = client.post("/api/search", json={"query": "zzzzz"})

    assert res.status_code == 200
    assert res.get_json()["results"] == []


def test_an_unreachable_musicbrainz_is_502_not_an_empty_result(client):
    """"Nothing matched" and "the database was down" call for different words
    and different next steps — that is why MusicBrainzUnavailable exists."""
    with patch.object(scan, "parse_search_query",
                      return_value={"artist": "Jorge Ben", "album": None}), \
         patch.object(scan, "lookup_artist",
                      side_effect=scan.MusicBrainzUnavailable("busy")):
        res = client.post("/api/search", json={"query": "jorge ben"})

    assert res.status_code == 502
    assert "musicbrainz" in res.get_json()["error"].lower()


def test_a_missing_api_key_is_503(client):
    with patch.object(scan, "parse_search_query",
                      side_effect=RuntimeError("ANTHROPIC_API_KEY is not set")):
        res = client.post("/api/search", json={"query": "jorge ben"})

    assert res.status_code == 503


def test_an_unparseable_query_is_400(client):
    with patch.object(scan, "parse_search_query",
                      side_effect=ValueError("Type an artist or album name")):
        res = client.post("/api/search", json={"query": "   "})

    assert res.status_code == 400


def test_spend_is_banked_even_when_musicbrainz_dies_afterwards(client):
    """The Claude call was billed the moment it returned."""
    def spend(query, usage_out=None):
        usage_out.append({"model": "claude-haiku-4-5",
                          "input_tokens": 100, "output_tokens": 20})
        return {"artist": "Jorge Ben", "album": None}

    with patch.object(scan, "parse_search_query", side_effect=spend), \
         patch.object(scan, "lookup_artist",
                      side_effect=scan.MusicBrainzUnavailable("busy")):
        client.post("/api/search", json={"query": "jorge ben"})

    with app_module.app.app_context():
        rows = app_module.ScanSpend.query.filter_by(source="search").all()
    assert len(rows) == 1


def test_the_usage_endpoint_quotes_a_search_estimate(client):
    body = client.get("/api/scan/usage").get_json()
    assert "search" in body["estimate"]
