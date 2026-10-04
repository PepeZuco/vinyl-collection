"""The genre vocabulary (genres.py) and everywhere the app is bound to it."""
import json
import pathlib
import re
from unittest.mock import patch

import pytest

import app as app_module
from genres import GENRES, canonical_genre

TEMPLATE = pathlib.Path(__file__).parent.parent / "templates" / "index.html"


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    created = []
    with app_module.app.test_client() as c:
        with c.session_transaction() as session:
            session["authed"] = True
        c.created = created
        yield c
    with app_module.app.app_context():
        for rid in created:
            r = app_module.db.session.get(app_module.Record, rid)
            if r:
                app_module.db.session.delete(r)
        app_module.db.session.commit()


def _create(client, **fields):
    res = client.post("/api/records", json={"artist": "A", "album_name": "B", **fields})
    if res.status_code == 201:
        client.created.append(res.get_json()["id"])
    return res


def _legacy_record(genre):
    """A record written straight to the table, the way pre-migration rows sit there."""
    with app_module.app.app_context():
        r = app_module.Record(artist="Old", album_name="Row", genre=genre)
        app_module.db.session.add(r)
        app_module.db.session.commit()
        return r.id


# ── the list itself ──────────────────────────────────────────────────────────

def test_the_list_is_the_nineteen_new_genres_in_alphabetical_order():
    assert len(GENRES) == 19 == len(set(GENRES))
    assert GENRES == sorted(GENRES, key=str.lower)
    assert "MPB & Samba" not in GENRES


def test_canonical_genre_folds_case_and_whitespace():
    assert canonical_genre("  soul   &  FUNK ") == "Soul & Funk"
    assert canonical_genre("") == ""
    assert canonical_genre(None) == ""
    assert canonical_genre("MPB & Samba") is None


def test_every_genre_has_a_colour_and_no_retired_one_keeps_its_own():
    src = TEMPLATE.read_text(encoding="utf-8")
    block = re.search(r"const GENRE_PALETTE = \{(.*?)\n\};", src, re.S).group(1)
    keys = re.findall(r"^\s*'([^']+)':", block, re.M)
    assert sorted(keys) == sorted(GENRES)


# ── the page ─────────────────────────────────────────────────────────────────

def test_the_page_carries_the_list_for_the_form_dropdown(client):
    html = client.get("/").get_data(as_text=True)
    m = re.search(r"const GENRES = (\[.*?\]);", html)
    assert m, "GENRES is not rendered into the page"
    assert json.loads(m.group(1)) == GENRES


# ── create / update validation ───────────────────────────────────────────────

def test_create_accepts_a_genre_on_the_list_in_its_own_spelling(client):
    res = _create(client, genre="bossa nova")
    assert res.status_code == 201
    assert res.get_json()["genre"] == "Bossa Nova"


def test_create_accepts_no_genre(client):
    assert _create(client, genre="").status_code == 201
    assert _create(client).status_code == 201


def test_create_refuses_a_retired_genre(client):
    res = _create(client, genre="MPB & Samba")
    assert res.status_code == 400
    assert "genre" in res.get_json()["error"]


def test_update_refuses_a_genre_off_the_list(client):
    rid = _create(client, genre="Rock").get_json()["id"]
    res = client.put(f"/api/records/{rid}", json={"genre": "Krautrock"})
    assert res.status_code == 400
    with app_module.app.app_context():
        assert app_module.db.session.get(app_module.Record, rid).genre == "Rock"


def test_update_canonicalises_the_genre(client):
    rid = _create(client, genre="Rock").get_json()["id"]
    res = client.put(f"/api/records/{rid}", json={"genre": "soft rock"})
    assert res.status_code == 200
    assert res.get_json()["genre"] == "Soft Rock"


def test_update_lets_a_legacy_genre_through_untouched(client):
    """A record the migration did not reach can still be edited — its other
    fields saved — without being forced off its old genre in the same save."""
    rid = _legacy_record("MPB & Samba")
    client.created.append(rid)
    res = client.put(f"/api/records/{rid}", json={"genre": "MPB & Samba", "year": "1974"})
    assert res.status_code == 200
    assert res.get_json()["genre"] == "MPB & Samba"
    assert res.get_json()["year"] == "1974"


# ── Claude's vocabulary ──────────────────────────────────────────────────────

def test_the_photo_scan_offers_claude_the_list_not_the_shelf(client):
    rid = _legacy_record("MPB & Samba")
    client.created.append(rid)
    seen = {}

    def extract(image, genres, usage_out=None):
        seen["genres"] = genres
        return {"artist": "A", "album_name": "B", "genre": None, "label": None, "catalog_number": None}

    with patch.object(app_module.scan, "extract_from_image", side_effect=extract), \
         patch.object(app_module.scan, "lookup_musicbrainz", return_value=[]), \
         patch.object(app_module.scan, "vinyl_rgids", return_value=set()), \
         patch.object(app_module.scan, "find_spotify_album", return_value=None):
        client.post("/api/scan", json={"image": "data:image/jpeg;base64,x"})

    assert seen["genres"] == GENRES


def test_the_search_genre_pass_offers_claude_the_list(client):
    rid = _legacy_record("MPB & Samba")
    client.created.append(rid)
    seen = []

    def classify(artist, album, genres, usage_out=None):
        seen.append(genres)
        return "Samba"

    with patch.object(app_module.scan, "classify_genre", side_effect=classify):
        body = client.post("/api/search/genres", json={"releases": [
            {"artist": "Cartola", "album_name": "Cartola"}]}).get_json()

    assert body["genres"] == ["Samba"]
    assert seen == [GENRES]
