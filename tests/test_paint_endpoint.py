"""vinyl_color and label_color across the record API and the CSV backup.

Unset means "unpainted" — the renderer treats that as black vinyl / white
label, not a stored color nobody chose, so '' round-trips rather than a
literal '#000000'/'#ffffff' default being written to the database.
"""

import io
import json

import pytest

# See test_tracks_endpoint.py for why this is `import app as app_module`
# rather than `from app import app, db, Record`.
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
        app_module.db.create_all()


def test_a_new_record_is_unpainted_by_default(client):
    r = client.post("/api/records", json={"album_name": "Transa"})
    assert r.status_code == 201
    assert r.get_json()["vinyl_color"] == ""
    assert r.get_json()["label_color"] == ""


def test_colors_round_trip_on_create(client):
    r = client.post("/api/records", json={
        "album_name": "Africa Brasil", "vinyl_color": "#ff8800", "label_color": "#112233"})
    assert r.status_code == 201
    assert r.get_json()["vinyl_color"] == "#ff8800"
    assert r.get_json()["label_color"] == "#112233"


def test_colors_can_be_set_by_a_put(client):
    made = client.post("/api/records", json={"album_name": "x"})
    rid = made.get_json()["id"]
    r = client.put(f"/api/records/{rid}", json={"vinyl_color": "#abcdef", "label_color": "#ffffff"})
    assert r.status_code == 200
    assert r.get_json()["vinyl_color"] == "#abcdef"
    assert r.get_json()["label_color"] == "#ffffff"


def test_a_color_can_be_cleared_back_to_unpainted(client):
    made = client.post("/api/records", json={"album_name": "x", "vinyl_color": "#abcdef"})
    rid = made.get_json()["id"]
    r = client.put(f"/api/records/{rid}", json={"vinyl_color": ""})
    assert r.status_code == 200
    assert r.get_json()["vinyl_color"] == ""


@pytest.mark.parametrize("bad", ["orange", "#fff", "#gggggg", "ff0000", "#12345"])
def test_a_malformed_hex_is_dropped_not_stored(client, bad):
    r = client.post("/api/records", json={"album_name": "x", "vinyl_color": bad})
    assert r.get_json()["vinyl_color"] == ""


def test_export_carries_the_colors(client):
    client.post("/api/records", json={
        "album_name": "The Wall", "vinyl_color": "#ff8800", "label_color": "#112233"})
    csv_text = client.get("/api/export").get_data(as_text=True)
    header = csv_text.splitlines()[0]
    assert "vinyl_color" in header and "label_color" in header
    assert "#ff8800" in csv_text and "#112233" in csv_text


def test_import_restores_the_colors(client):
    client.post("/api/records", json={
        "album_name": "The Wall", "vinyl_color": "#ff8800", "label_color": "#112233"})
    csv_text = client.get("/api/export").get_data(as_text=True)

    with app_module.app.app_context():
        app_module.db.drop_all()
        app_module.db.create_all()

    r = client.post("/api/import", data={
        "file": (io.BytesIO(csv_text.encode()), "backup.csv")},
        content_type="multipart/form-data")
    assert r.status_code == 200

    with app_module.app.app_context():
        rec = app_module.Record.query.filter_by(album_name="The Wall").one()
        assert rec.vinyl_color == "#ff8800"
        assert rec.label_color == "#112233"


def test_a_csv_without_the_columns_still_imports(client):
    """A backup taken before this feature has no such columns."""
    csv_text = "artist,album_name\r\nJorge Ben,Africa Brasil\n"
    r = client.post("/api/import", data={
        "file": (io.BytesIO(csv_text.encode()), "old.csv")},
        content_type="multipart/form-data")
    assert r.status_code == 200
    with app_module.app.app_context():
        rec = app_module.Record.query.filter_by(album_name="Africa Brasil").one()
        assert rec.vinyl_color in ("", None)
        assert rec.label_color in ("", None)
