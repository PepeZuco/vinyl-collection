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
