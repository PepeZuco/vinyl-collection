"""The tracks, disc_count and size fields across the record API and the CSV backup.

The validation tested here is the reason the endpoint has any: a side letter
that does not exist on a record with this many discs is a song nothing will
ever render, and accepting it quietly would hide the bug in the data rather
than at the request that caused it.
"""

import io
import json

import pytest

# `import app as app_module` rather than `from app import app, db, Record`:
# other test files in this suite (test_import.py) reload the app module via
# importlib.reload() inside a module-scoped fixture, which rebinds app.app /
# app.db / app.Record to fresh objects in place. A name captured once at
# collection time (`from app import db`) would then be a stale object whose
# routes resolve `db` through the *current* module globals — a different
# instance than the one the stale Flask app was actually registered with,
# raising "the current Flask app is not registered with this SQLAlchemy
# instance" the moment another such test file runs first. Looking the names
# up through `app_module` at fixture time, like test_search_endpoint.py does,
# always gets the live, self-consistent set.
import app as app_module


@pytest.fixture
def client(tmp_path):
    app_module.app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path}/test.db"
    app_module.app.config["TESTING"] = True
    with app_module.app.app_context():
        app_module.db.drop_all()
        app_module.db.create_all()
    with app_module.app.test_client() as c:
        with c.session_transaction() as sess:
            sess["authed"] = True
        yield c
    with app_module.app.app_context():
        app_module.db.drop_all()


def test_a_new_record_defaults_to_one_disc_and_unknown_size(client):
    r = client.post("/api/records", json={"album_name": "Transa"})
    assert r.status_code == 201
    assert r.get_json()["disc_count"] == 1
    assert r.get_json()["size"] == ""
    assert r.get_json()["tracks"] == ""


def test_tracks_round_trip(client):
    tracks = json.dumps([
        {"side": "A", "title": "Ponta de Lanca", "liked_at": "2026-09-09T21:40:00"},
        {"side": "B", "title": "Taj Mahal"},
    ])
    r = client.post("/api/records", json={"album_name": "Africa Brasil",
                                          "tracks": tracks, "size": "12"})
    assert r.status_code == 201
    got = json.loads(r.get_json()["tracks"])
    assert got[0]["title"] == "Ponta de Lanca"
    assert got[0]["liked_at"] == "2026-09-09T21:40:00"
    assert "liked_at" not in got[1]


def test_a_side_that_does_not_exist_is_refused(client):
    tracks = json.dumps([{"side": "C", "title": "nowhere"}])
    r = client.post("/api/records", json={"album_name": "x", "tracks": tracks})
    assert r.status_code == 400
    assert "C" in r.get_json()["error"]


def test_the_same_side_is_fine_on_a_double(client):
    tracks = json.dumps([{"side": "C", "title": "Hey You"}])
    r = client.post("/api/records", json={"album_name": "The Wall",
                                          "disc_count": 2, "tracks": tracks})
    assert r.status_code == 201


def test_an_empty_title_is_dropped_not_stored(client):
    tracks = json.dumps([{"side": "A", "title": "  "}, {"side": "A", "title": "real"}])
    r = client.post("/api/records", json={"album_name": "x", "tracks": tracks})
    stored = json.loads(r.get_json()["tracks"])
    assert [t["title"] for t in stored] == ["real"]


def test_an_unknown_size_becomes_unknown(client):
    r = client.post("/api/records", json={"album_name": "x", "size": "14"})
    assert r.get_json()["size"] == ""


def test_disc_count_is_floored_at_one(client):
    r = client.post("/api/records", json={"album_name": "x", "disc_count": 0})
    assert r.get_json()["disc_count"] == 1


def test_put_validates_against_the_stored_disc_count(client):
    """A PUT that sends tracks but not disc_count is checked against what the
    record already is — otherwise the default of 1 would reject a double's
    C-side on every partial update."""
    made = client.post("/api/records", json={"album_name": "The Wall", "disc_count": 2})
    rid = made.get_json()["id"]
    r = client.put(f"/api/records/{rid}",
                   json={"tracks": json.dumps([{"side": "D", "title": "The Trial"}])})
    assert r.status_code == 200


def test_a_like_can_be_added_by_patching_tracks_alone(client):
    made = client.post("/api/records", json={
        "album_name": "x",
        "tracks": json.dumps([{"side": "A", "title": "Mother"}])})
    rid = made.get_json()["id"]
    r = client.put(f"/api/records/{rid}", json={"tracks": json.dumps(
        [{"side": "A", "title": "Mother", "liked_at": "2026-08-02"}])})
    assert json.loads(r.get_json()["tracks"])[0]["liked_at"] == "2026-08-02"


def test_export_carries_the_new_columns(client):
    client.post("/api/records", json={
        "album_name": "The Wall", "disc_count": 2, "size": "12",
        "tracks": json.dumps([{"side": "A", "title": "Mother"}])})
    csv_text = client.get("/api/export").get_data(as_text=True)
    header = csv_text.splitlines()[0]
    assert "tracks" in header and "disc_count" in header and "size" in header
    assert "Mother" in csv_text


def test_import_restores_the_new_columns(client):
    client.post("/api/records", json={
        "album_name": "The Wall", "disc_count": 2, "size": "12",
        "tracks": json.dumps([{"side": "C", "title": "Hey You"}])})
    csv_text = client.get("/api/export").get_data(as_text=True)

    r = client.post("/api/import", data={
        "file": (io.BytesIO(csv_text.encode()), "backup.csv")},
        content_type="multipart/form-data")
    assert r.status_code == 200

    with app_module.app.app_context():
        rec = app_module.Record.query.filter_by(album_name="The Wall").one()
        assert rec.disc_count == 2
        assert rec.size == "12"
        assert json.loads(rec.tracks)[0]["title"] == "Hey You"


def test_a_csv_without_the_columns_still_imports(client):
    """Every backup taken before this feature has no such columns. That is not
    an error — the same rule _row_note_images already follows."""
    csv_text = "artist,album_name\r\nJorge Ben,Africa Brasil\n"
    r = client.post("/api/import", data={
        "file": (io.BytesIO(csv_text.encode()), "old.csv")},
        content_type="multipart/form-data")
    assert r.status_code == 200
    with app_module.app.app_context():
        rec = app_module.Record.query.filter_by(album_name="Africa Brasil").one()
        assert rec.disc_count == 1
        assert rec.tracks in ("", None)
