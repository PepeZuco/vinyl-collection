"""Note images are stored once per distinct image and served from their own URL.

The notes column is read off /api/records by six client-side consumers and is
not deferred, so image bytes cannot live in it — see the spec. These tests pin
the storage half: an image is addressed by its own content hash, uploading the
same photo twice is a no-op, and a broken payload is an absent image rather
than a 500.
"""
import base64
import importlib
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
    """A fresh app bound to a throwaway sqlite file.

    Same guard as tests/test_cover_endpoint.py: DATABASE_URL wins over DATA_DIR
    in app.py, and these tests write, so the resolved URI is checked first.
    """
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


@pytest.fixture(autouse=True)
def _empty(vinyl_app):
    with vinyl_app.app.app_context():
        vinyl_app.Record.query.delete()
        vinyl_app.NoteImage.query.delete()
        vinyl_app.db.session.commit()
    yield


def test_upload_returns_the_images_own_content_hash(client, vinyl_app):
    res = client.post("/api/note-images", json={"data": JPEG_1PX})
    assert res.status_code == 201
    assert res.get_json()["id"] == vinyl_app._note_image_id(JPEG_1PX)


def test_uploading_the_same_image_twice_reuses_the_one_row(client, vinyl_app):
    first = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    second = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    assert first == second
    with vinyl_app.app.app_context():
        assert vinyl_app.NoteImage.query.count() == 1


def test_upload_requires_auth(vinyl_app):
    anon = vinyl_app.app.test_client()
    assert anon.post("/api/note-images", json={"data": JPEG_1PX}).status_code == 401


def test_upload_rejects_anything_that_is_not_a_data_uri(client):
    assert client.post("/api/note-images", json={"data": "https://x/y.jpg"}).status_code == 400
    assert client.post("/api/note-images", json={}).status_code == 400


def test_upload_rejects_an_image_over_the_cap(client, vinyl_app):
    huge = "data:image/jpeg;base64," + "A" * (vinyl_app._NOTE_IMAGE_MAX_BYTES + 1)
    assert client.post("/api/note-images", json={"data": huge}).status_code == 413


def test_serving_returns_the_bytes_and_the_right_content_type(client):
    jpeg_id = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    png_id = client.post("/api/note-images", json={"data": PNG_1PX}).get_json()["id"]

    jpeg = client.get(f"/api/note-images/{jpeg_id}")
    assert jpeg.status_code == 200
    assert jpeg.mimetype == "image/jpeg"
    assert jpeg.data == base64.b64decode(JPEG_1PX.partition(",")[2])

    assert client.get(f"/api/note-images/{png_id}").mimetype == "image/png"


def test_serving_is_immutable_because_the_url_is_the_content(client):
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    res = client.get(f"/api/note-images/{iid}")
    assert "immutable" in res.headers["Cache-Control"]
    assert res.get_etag()[0] == iid


def test_an_unknown_id_is_404_not_500(client):
    assert client.get("/api/note-images/" + "0" * 32).status_code == 404


def test_a_malformed_stored_payload_is_an_absent_image(client, vinyl_app):
    with vinyl_app.app.app_context():
        vinyl_app.db.session.add(vinyl_app.NoteImage(
            id="f" * 32, data="not a data uri", created="2026-01-01T00:00:00"))
        vinyl_app.db.session.commit()
    assert client.get("/api/note-images/" + "f" * 32).status_code == 404


def _note(text, images=None):
    import json
    return json.dumps([{"date": "2026-01-01", "text": text, "images": images or []}])


def test_dropping_an_image_from_a_note_deletes_it(client, vinyl_app):
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    rid = client.post("/api/records", json={"artist": "A", "notes": _note("has one", [iid])}).get_json()["id"]

    client.put(f"/api/records/{rid}", json={"notes": _note("now none", [])})

    with vinyl_app.app.app_context():
        assert vinyl_app.NoteImage.query.count() == 0


def test_an_image_another_record_still_uses_survives(client, vinyl_app):
    """Content-hash ids mean two records photographing the same thing share a row.

    Deleting on the first record's say-so would blank the second — this guard is
    load-bearing, not defensive.
    """
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    keeper = client.post("/api/records", json={"artist": "Keeper", "notes": _note("mine too", [iid])}).get_json()["id"]
    dropper = client.post("/api/records", json={"artist": "Dropper", "notes": _note("mine", [iid])}).get_json()["id"]

    client.put(f"/api/records/{dropper}", json={"notes": _note("not any more", [])})

    with vinyl_app.app.app_context():
        assert vinyl_app.NoteImage.query.count() == 1
    assert client.get(f"/api/note-images/{iid}").status_code == 200


def test_deleting_the_whole_note_deletes_its_image(client, vinyl_app):
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    rid = client.post("/api/records", json={"artist": "A", "notes": _note("bye", [iid])}).get_json()["id"]

    client.put(f"/api/records/{rid}", json={"notes": ""})

    with vinyl_app.app.app_context():
        assert vinyl_app.NoteImage.query.count() == 0


def test_a_save_that_does_not_mention_notes_reaps_nothing(client, vinyl_app):
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    rid = client.post("/api/records", json={"artist": "A", "notes": _note("keep", [iid])}).get_json()["id"]

    client.put(f"/api/records/{rid}", json={"my_rating": 5})

    with vinyl_app.app.app_context():
        assert vinyl_app.NoteImage.query.count() == 1


def test_the_sweep_deletes_an_orphan_past_the_grace_window(client, vinyl_app):
    """A photo uploaded into a form the user then abandoned."""
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    with vinyl_app.app.app_context():
        vinyl_app.db.session.get(vinyl_app.NoteImage, iid).created = "2020-01-01T00:00:00"
        vinyl_app.db.session.commit()
        assert vinyl_app._sweep_note_images() == 1
        assert vinyl_app.NoteImage.query.count() == 0


def test_the_sweep_spares_an_orphan_inside_the_grace_window(client, vinyl_app):
    """The window is what stops the sweep eating a form that is open right now."""
    client.post("/api/note-images", json={"data": JPEG_1PX})
    with vinyl_app.app.app_context():
        assert vinyl_app._sweep_note_images() == 0
        assert vinyl_app.NoteImage.query.count() == 1


def test_the_sweep_spares_a_referenced_image_however_old(client, vinyl_app):
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    client.post("/api/records", json={"artist": "A", "notes": _note("keep", [iid])})
    with vinyl_app.app.app_context():
        vinyl_app.db.session.get(vinyl_app.NoteImage, iid).created = "2020-01-01T00:00:00"
        vinyl_app.db.session.commit()
        assert vinyl_app._sweep_note_images() == 0


def test_the_record_list_never_carries_image_bytes(client):
    """The regression guard the whole design exists for."""
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    client.post("/api/records", json={"artist": "A", "notes": _note("look", [iid])})

    body = client.get("/api/records").get_data(as_text=True)
    assert "base64" not in body
    assert iid in body  # the id travels; the bytes do not


def test_ids_are_read_out_of_notes_json_forgivingly(vinyl_app):
    assert vinyl_app._note_image_ids("") == set()
    assert vinyl_app._note_image_ids("not json") == set()
    assert vinyl_app._note_image_ids('"a legacy string note"') == set()
    assert vinyl_app._note_image_ids('[{"date":"d","text":"t"}]') == set()
    assert vinyl_app._note_image_ids('[{"images":["a","b"]},{"images":["b","c"]}]') == {"a", "b", "c"}


def test_deleting_a_record_reaps_its_images(client, vinyl_app):
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    rid = client.post("/api/records", json={"artist": "A", "notes": _note("shot", [iid])}).get_json()["id"]

    assert client.delete(f"/api/records/{rid}").status_code == 200

    with vinyl_app.app.app_context():
        assert vinyl_app.NoteImage.query.count() == 0


def test_deleting_a_record_spares_an_image_another_record_uses(client, vinyl_app):
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    keeper = client.post("/api/records", json={"artist": "Keeper", "notes": _note("mine too", [iid])}).get_json()["id"]
    doomed = client.post("/api/records", json={"artist": "Doomed", "notes": _note("mine", [iid])}).get_json()["id"]

    client.delete(f"/api/records/{doomed}")

    with vinyl_app.app.app_context():
        assert vinyl_app.NoteImage.query.count() == 1
    assert client.get(f"/api/note-images/{iid}").status_code == 200


def test_a_wildcard_id_cannot_make_an_image_look_used(client, vinyl_app):
    """The images array is client-supplied, so an id can contain a LIKE wildcard.

    A bare '%' as another record's image id would match every notes column under
    a plain substring guard, making the real image permanently unreapable.
    """
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    client.post("/api/records", json={"artist": "Noise", "notes": _note("wildcard", ["%"])})
    rid = client.post("/api/records", json={"artist": "A", "notes": _note("shot", [iid])}).get_json()["id"]

    client.put(f"/api/records/{rid}", json={"notes": _note("now none", [])})

    with vinyl_app.app.app_context():
        assert vinyl_app.NoteImage.query.count() == 0
