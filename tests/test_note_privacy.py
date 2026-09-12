"""Notes marked private are visible only in edit mode.

The boundary is the server, not the browser: /api/records is public and ships
the notes column verbatim to every visitor, so a private note that is merely
hidden by the client is not private at all — it is one View Source away. These
tests pin the stripping at the endpoints, and pin the two places where
"private" collides with machinery that must keep reading the raw column: the
image reaper, which would otherwise garbage-collect a private note's photos,
and the CSV export, which is a backup and must carry everything.
"""
import importlib
import json
import os

import pytest

JPEG_1PX = (
    "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsL"
    "DBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAAB"
    "AAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=="
)
PNG_1PX = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture(scope="module")
def vinyl_app(tmp_path_factory):
    """A fresh app bound to a throwaway sqlite file. Same guard as test_note_images."""
    data_dir = tmp_path_factory.mktemp("data")
    previous = {name: os.environ.get(name) for name in ("DATA_DIR", "DATABASE_URL")}
    os.environ["DATA_DIR"] = str(data_dir)
    os.environ.pop("DATABASE_URL", None)
    try:
        module = importlib.reload(importlib.import_module("app"))
        uri = module.app.config["SQLALCHEMY_DATABASE_URI"]
        assert uri == f"sqlite:///{data_dir}/vinyl.db", (
            f"test database escaped the tmp dir, refusing to write to it: {uri}")
        with module.app.app_context():
            module.db.create_all()
        yield module
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        importlib.reload(importlib.import_module("app"))


@pytest.fixture
def client(vinyl_app):
    c = vinyl_app.app.test_client()
    assert c.post("/api/auth/login", json={"password": vinyl_app.EDIT_PASSWORD}).status_code == 200
    return c


@pytest.fixture
def visitor(vinyl_app):
    return vinyl_app.app.test_client()


@pytest.fixture(autouse=True)
def _empty(vinyl_app):
    with vinyl_app.app.app_context():
        vinyl_app.Record.query.delete()
        vinyl_app.NoteImage.query.delete()
        vinyl_app.db.session.commit()
    yield


def make_record(client, notes):
    """A record whose notes column holds `notes`, returned as its id."""
    res = client.post("/api/records", json={
        "artist": "Slint", "album_name": "Spiderland",
        "notes": json.dumps(notes) if not isinstance(notes, str) else notes})
    assert res.status_code == 201
    return res.get_json()["id"]


def notes_seen_by(http, rid):
    """The notes column as one client sees it on /api/records."""
    rows = http.get("/api/records").get_json()
    row = next(r for r in rows if r["id"] == rid)
    return json.loads(row["notes"]) if row["notes"] else []


# ── /api/records ─────────────────────────────────────────────────────────────

def test_a_visitor_does_not_receive_a_private_note(client, visitor):
    rid = make_record(client, [{"date": "2026-01-02", "text": "the seam is split", "private": True}])
    assert notes_seen_by(visitor, rid) == []


def test_edit_mode_receives_the_private_note(client):
    rid = make_record(client, [{"date": "2026-01-02", "text": "the seam is split", "private": True}])
    assert notes_seen_by(client, rid) == [
        {"date": "2026-01-02", "text": "the seam is split", "private": True}]


def test_a_visitor_still_receives_the_public_notes_around_a_private_one(client, visitor):
    rid = make_record(client, [
        {"date": "2026-01-01", "text": "first pressing"},
        {"date": "2026-01-02", "text": "paid too much", "private": True},
        {"date": "2026-01-03", "text": "sounds enormous"},
    ])
    assert notes_seen_by(visitor, rid) == [
        {"date": "2026-01-01", "text": "first pressing"},
        {"date": "2026-01-03", "text": "sounds enormous"},
    ]


def test_a_record_whose_notes_are_all_private_reads_as_having_none(client, visitor):
    rid = make_record(client, [{"date": "2026-01-02", "text": "hidden", "private": True}])
    rows = visitor.get("/api/records").get_json()
    assert next(r for r in rows if r["id"] == rid)["notes"] == ""


def test_a_legacy_plain_string_notes_column_reaches_a_visitor_untouched(client, visitor):
    """Notes written before the column held JSON are a bare string, not an error."""
    rid = make_record(client, "bought it at the fair")
    rows = visitor.get("/api/records").get_json()
    assert next(r for r in rows if r["id"] == rid)["notes"] == "bought it at the fair"


def test_private_is_only_honoured_when_it_is_true(client, visitor):
    """A note is public unless it says otherwise — the absent flag is the default."""
    rid = make_record(client, [
        {"date": "2026-01-01", "text": "no flag"},
        {"date": "2026-01-02", "text": "explicitly public", "private": False},
    ])
    assert len(notes_seen_by(visitor, rid)) == 2


# ── /api/export ──────────────────────────────────────────────────────────────

def test_a_visitor_cannot_export(visitor):
    assert visitor.get("/api/export").status_code == 401


def test_an_export_in_edit_mode_carries_private_notes(client):
    make_record(client, [{"date": "2026-01-02", "text": "the seam is split", "private": True}])
    body = client.get("/api/export").get_data(as_text=True)
    assert "the seam is split" in body


# ── /api/note-images ─────────────────────────────────────────────────────────

def test_a_visitor_cannot_fetch_a_photo_that_only_a_private_note_holds(client, visitor):
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    make_record(client, [{"date": "2026-01-02", "text": "", "images": [iid], "private": True}])
    assert visitor.get(f"/api/note-images/{iid}").status_code == 404


def test_a_visitor_can_still_fetch_a_photo_on_a_public_note(client, visitor):
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    make_record(client, [{"date": "2026-01-02", "text": "the sleeve", "images": [iid]}])
    assert visitor.get(f"/api/note-images/{iid}").status_code == 200


def test_the_same_photo_on_both_a_private_and_a_public_note_stays_visible(client, visitor):
    """Ids are content hashes, so one photo can be on two notes. Public wins."""
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    make_record(client, [{"date": "2026-01-02", "text": "", "images": [iid], "private": True}])
    make_record(client, [{"date": "2026-01-03", "text": "same sleeve", "images": [iid]}])
    assert visitor.get(f"/api/note-images/{iid}").status_code == 200


def test_edit_mode_fetches_a_private_notes_photo(client):
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    make_record(client, [{"date": "2026-01-02", "text": "", "images": [iid], "private": True}])
    assert client.get(f"/api/note-images/{iid}").status_code == 200


def test_a_photo_not_yet_filed_on_any_note_is_still_visible_in_edit_mode(client):
    """The form uploads a photo before the note holding it is saved."""
    iid = client.post("/api/note-images", json={"data": PNG_1PX}).get_json()["id"]
    assert client.get(f"/api/note-images/{iid}").status_code == 200


# ── the reaper must keep reading the raw column ──────────────────────────────

def test_a_photo_held_only_by_a_private_note_survives_an_edit_elsewhere(client, vinyl_app):
    """The reaper asks "does any note still hold this?" — private notes count."""
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    keeper = make_record(client, [
        {"date": "2026-01-02", "text": "", "images": [iid], "private": True}])
    borrower = make_record(client, [{"date": "2026-01-03", "text": "x", "images": [iid]}])

    # The public note lets the photo go; the private one still holds it.
    client.put(f"/api/records/{borrower}", json={"notes": json.dumps(
        [{"date": "2026-01-03", "text": "x"}])})

    with vinyl_app.app.app_context():
        assert vinyl_app.db.session.get(vinyl_app.NoteImage, iid) is not None
    assert client.get(f"/api/note-images/{iid}").status_code == 200
    assert notes_seen_by(client, keeper)[0]["images"] == [iid]
