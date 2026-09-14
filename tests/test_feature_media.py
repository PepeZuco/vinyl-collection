"""The Features tab's videos: one clip per fixed slot, admin-uploaded, public to view.

Unlike note images there is no content-hash id and no reaping — the slot set is
fixed (four cards on the tab), so the row is addressed by slot and replaced in
place. The hash still rides along, exactly as cover_hash does for record covers,
so the URL the manifest hands out changes when the clip does and stale copies
never get served from a browser cache.
"""
import importlib
import os

import pytest

TINY_MP4 = "data:video/mp4;base64," + "AAAA"


@pytest.fixture(scope="module")
def vinyl_app(tmp_path_factory):
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
        vinyl_app.FeatureVideo.query.delete()
        vinyl_app.db.session.commit()
    yield


def a_slot(vinyl_app):
    return next(iter(vinyl_app.FEATURE_MEDIA_SLOTS))


def test_upload_requires_auth(vinyl_app):
    anon = vinyl_app.app.test_client()
    slot = a_slot(vinyl_app)
    assert anon.put(f"/api/feature-media/{slot}", json={"data": TINY_MP4}).status_code == 401


def test_upload_rejects_an_unknown_slot(client):
    assert client.put("/api/feature-media/not-a-real-slot", json={"data": TINY_MP4}).status_code == 404


def test_upload_rejects_anything_that_is_not_a_data_uri(client, vinyl_app):
    slot = a_slot(vinyl_app)
    assert client.put(f"/api/feature-media/{slot}", json={"data": "https://x/y.mp4"}).status_code == 400
    assert client.put(f"/api/feature-media/{slot}", json={}).status_code == 400


def test_upload_rejects_a_clip_over_the_cap(client, vinyl_app):
    slot = a_slot(vinyl_app)
    huge = "data:video/mp4;base64," + "A" * (vinyl_app._FEATURE_MEDIA_MAX_BYTES + 1)
    assert client.put(f"/api/feature-media/{slot}", json={"data": huge}).status_code == 413


def test_get_before_any_upload_is_404_not_500(client, vinyl_app):
    slot = a_slot(vinyl_app)
    assert client.get(f"/api/feature-media/{slot}").status_code == 404


def test_get_an_unknown_slot_is_404(client):
    assert client.get("/api/feature-media/not-a-real-slot").status_code == 404


def test_upload_then_get_serves_the_bytes_and_content_type(client, vinyl_app):
    slot = a_slot(vinyl_app)
    assert client.put(f"/api/feature-media/{slot}", json={"data": TINY_MP4}).status_code == 201

    res = client.get(f"/api/feature-media/{slot}")
    assert res.status_code == 200
    assert res.mimetype == "video/mp4"


def test_serving_is_immutable_and_carries_an_etag(client, vinyl_app):
    slot = a_slot(vinyl_app)
    client.put(f"/api/feature-media/{slot}", json={"data": TINY_MP4})
    res = client.get(f"/api/feature-media/{slot}")
    assert "immutable" in res.headers["Cache-Control"]
    assert res.get_etag()[0]


def test_delete_requires_auth(vinyl_app):
    anon = vinyl_app.app.test_client()
    slot = a_slot(vinyl_app)
    assert anon.delete(f"/api/feature-media/{slot}").status_code == 401


def test_delete_clears_the_slot(client, vinyl_app):
    slot = a_slot(vinyl_app)
    client.put(f"/api/feature-media/{slot}", json={"data": TINY_MP4})
    assert client.delete(f"/api/feature-media/{slot}").status_code == 200
    assert client.get(f"/api/feature-media/{slot}").status_code == 404


def test_deleting_an_empty_slot_is_still_ok(client, vinyl_app):
    slot = a_slot(vinyl_app)
    assert client.delete(f"/api/feature-media/{slot}").status_code == 200


def test_manifest_lists_only_filled_slots(client, vinyl_app):
    slot = a_slot(vinyl_app)
    assert client.get("/api/feature-media").get_json() == {}

    client.put(f"/api/feature-media/{slot}", json={"data": TINY_MP4})
    manifest = client.get("/api/feature-media").get_json()
    assert list(manifest.keys()) == [slot]
    assert manifest[slot].startswith(f"/api/feature-media/{slot}?v=")


def test_manifest_is_public_no_auth_needed(vinyl_app):
    anon = vinyl_app.app.test_client()
    assert anon.get("/api/feature-media").status_code == 200


def test_reuploading_changes_the_manifest_url(client, vinyl_app):
    slot = a_slot(vinyl_app)
    client.put(f"/api/feature-media/{slot}", json={"data": TINY_MP4})
    first_url = client.get("/api/feature-media").get_json()[slot]

    other = "data:video/mp4;base64," + "BBBB"
    client.put(f"/api/feature-media/{slot}", json={"data": other})
    second_url = client.get("/api/feature-media").get_json()[slot]

    assert first_url != second_url


def test_a_malformed_stored_payload_is_an_absent_clip(client, vinyl_app):
    slot = a_slot(vinyl_app)
    with vinyl_app.app.app_context():
        vinyl_app.db.session.add(vinyl_app.FeatureVideo(
            slot=slot, data="not a data uri", hash="x", created="2026-01-01T00:00:00"))
        vinyl_app.db.session.commit()
    assert client.get(f"/api/feature-media/{slot}").status_code == 404
