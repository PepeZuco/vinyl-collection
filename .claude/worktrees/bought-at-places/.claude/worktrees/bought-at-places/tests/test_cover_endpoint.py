"""Covers are served as their own cacheable resource, not inlined in the record JSON.

Before this, /api/records returned every cover as a base64 data URI in one blob —
45MB for a 292-record collection, with nothing on screen until all of it landed.
These tests pin the two halves of the fix: the record list stays small and carries
only a URL, and the cover route serves real bytes that a browser can cache.
"""
import base64
import importlib
import io
import os

import pytest


# A one-pixel JPEG and a one-pixel PNG, so the tests can tell the content types
# apart without depending on an image library.
JPEG_1PX = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
    "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAA"
    "AAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=="
)
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture(scope="module")
def vinyl_app(tmp_path_factory):
    """A fresh app bound to a throwaway sqlite file.

    Same guard as tests/test_import.py: DATABASE_URL wins over DATA_DIR in
    app.py, and these tests write records, so the resolved URI is checked
    before anything touches the database.
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
def _empty_collection(vinyl_app):
    """Each test starts from an empty table, so ids and counts are its own."""
    with vinyl_app.app.app_context():
        vinyl_app.Record.query.delete()
        vinyl_app.db.session.commit()
    yield


def make_record(client, cover=JPEG_1PX, mime="image/jpeg", **fields):
    """Create a record carrying `cover`, and return its id."""
    body = {"artist": "Tim Maia", "album_name": "Uma Onda"}
    if cover is not None:
        body["cover_data"] = f"data:{mime};base64," + base64.b64encode(cover).decode()
    body.update(fields)
    resp = client.post("/api/records", json=body)
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def cover_url_of(client, rid):
    """The cover_url the record list reports for `rid`."""
    rows = client.get("/api/records").get_json()
    row = next(r for r in rows if r["id"] == rid)
    return row["cover_url"]


def test_cover_route_returns_the_decoded_image_bytes(client):
    rid = make_record(client)

    resp = client.get(f"/api/records/{rid}/cover")

    assert resp.status_code == 200
    assert resp.data == JPEG_1PX
    assert resp.mimetype == "image/jpeg"


def test_cover_route_reports_the_stored_content_type(client):
    rid = make_record(client, cover=PNG_1PX, mime="image/png")

    resp = client.get(f"/api/records/{rid}/cover")

    assert resp.data == PNG_1PX
    assert resp.mimetype == "image/png"


def test_cover_route_404s_for_a_record_with_no_cover(client):
    rid = make_record(client, cover=None)

    assert client.get(f"/api/records/{rid}/cover").status_code == 404


def test_cover_route_404s_for_an_unknown_record(client):
    assert client.get("/api/records/123456/cover").status_code == 404


def test_cover_route_404s_rather_than_500s_on_an_undecodable_cover(client, vinyl_app):
    rid = make_record(client)
    with vinyl_app.app.app_context():
        rec = vinyl_app.db.session.get(vinyl_app.Record, rid)
        rec.cover_data = "data:image/jpeg;base64,not-valid-base64!!"
        vinyl_app.db.session.commit()

    assert client.get(f"/api/records/{rid}/cover").status_code == 404


def test_cover_response_is_immutably_cacheable(client):
    rid = make_record(client)

    resp = client.get(f"/api/records/{rid}/cover")

    cache = resp.headers["Cache-Control"]
    assert "immutable" in cache, cache
    assert "max-age=31536000" in cache, cache
    assert resp.headers.get("ETag"), "no ETag, so a client cannot revalidate"


def test_cover_revalidation_returns_304_without_the_body(client):
    rid = make_record(client)
    etag = client.get(f"/api/records/{rid}/cover").headers["ETag"]

    resp = client.get(f"/api/records/{rid}/cover", headers={"If-None-Match": etag})

    assert resp.status_code == 304
    assert resp.data == b""


# ── the record list ────────────────────────────────────────────────────────────

def test_record_list_no_longer_carries_cover_data(client):
    make_record(client)

    row = client.get("/api/records").get_json()[0]

    assert "cover_data" not in row, "the 45MB blob is back in the record list"


def test_record_list_carries_a_cover_url_that_serves_the_cover(client):
    rid = make_record(client)

    resp = client.get(cover_url_of(client, rid))

    assert resp.status_code == 200
    assert resp.data == JPEG_1PX


def test_cover_url_is_empty_for_a_record_without_a_cover(client):
    rid = make_record(client, cover=None)

    assert cover_url_of(client, rid) == ""


def test_cover_url_changes_when_the_cover_changes(client):
    rid = make_record(client)
    before = cover_url_of(client, rid)

    client.put(f"/api/records/{rid}", json={
        "cover_data": "data:image/png;base64," + base64.b64encode(PNG_1PX).decode()})

    after = cover_url_of(client, rid)
    assert after != before, (
        "the URL is immutable-cached, so an unchanged URL means the old cover "
        "is served forever")
    assert client.get(after).data == PNG_1PX


def test_record_list_stays_small_however_large_the_covers_are(client):
    heavy = b"\xff\xd8\xff" + os.urandom(200_000)
    for _ in range(5):
        make_record(client, cover=heavy)

    payload = client.get("/api/records").get_data()

    assert len(payload) < 5_000, (
        f"record list is {len(payload)} bytes for 5 records — covers are still inline")


def test_record_list_never_selects_the_cover_column(client, vinyl_app):
    """The payload being small is not enough: the blobs must not leave the database.

    A to_dict() that reads self.cover_data would lazy-load one blob per row and
    move all 45MB through the process even though none of it reaches the client.
    """
    from sqlalchemy import event

    make_record(client)
    statements = []
    with vinyl_app.app.app_context():
        engine = vinyl_app.db.engine

    def record_sql(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_sql)
    try:
        client.get("/api/records")
    finally:
        event.remove(engine, "before_cursor_execute", record_sql)

    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert selects, "no SELECT captured — the listener is not wired up"
    offenders = [s for s in selects if "cover_data" in s]
    assert not offenders, f"cover_data was selected: {offenders}"


# ── write paths ────────────────────────────────────────────────────────────────

def test_updating_a_record_without_a_cover_key_keeps_the_cover(client):
    """The edit form no longer holds the cover bytes, so it must omit the field.

    If a save that leaves the cover alone sends nothing, the cover has to
    survive — otherwise editing a rating silently destroys the artwork.
    """
    rid = make_record(client)
    before = cover_url_of(client, rid)

    client.put(f"/api/records/{rid}", json={"my_rating": 4})

    assert cover_url_of(client, rid) == before
    assert client.get(f"/api/records/{rid}/cover").data == JPEG_1PX


def test_updating_a_record_with_an_empty_cover_clears_it(client):
    """Explicitly sending "" is how the form's 'remove cover' says so."""
    rid = make_record(client)

    client.put(f"/api/records/{rid}", json={"cover_data": ""})

    assert cover_url_of(client, rid) == ""
    assert client.get(f"/api/records/{rid}/cover").status_code == 404


def test_export_still_carries_the_cover_bytes(client):
    make_record(client)

    body = client.get("/api/export").get_data(as_text=True)

    assert "cover_image_base64" in body.splitlines()[0]
    assert base64.b64encode(JPEG_1PX).decode() in body


def test_imported_covers_are_servable(client):
    encoded = base64.b64encode(PNG_1PX).decode()
    csv_body = (
        "artist,album_name,cover_image_base64\n"
        f"Chico Buarque,Volume 3,\"data:image/png;base64,{encoded}\"\n"
    ).encode()

    resp = client.post("/api/import", data={"file": (io.BytesIO(csv_body), "c.csv")},
                       content_type="multipart/form-data")
    assert resp.status_code == 200, resp.get_data(as_text=True)

    rows = client.get("/api/records").get_json()
    assert len(rows) == 1
    assert rows[0]["cover_url"], "an imported cover has no URL, so it renders as nothing"
    assert client.get(rows[0]["cover_url"]).data == PNG_1PX


# ── the upgrade path ───────────────────────────────────────────────────────────

def test_boot_backfills_cover_hash_for_a_database_written_before_the_column(tmp_path):
    """The deployed collection has 292 covers and no cover_hash column yet.

    Without a backfill every one of them reports an empty cover_url on the
    first boot after deploy, so the whole collection renders coverless until
    each record is edited by hand.
    """
    import importlib
    import sqlite3

    db_path = tmp_path / "vinyl.db"
    cover = "data:image/png;base64," + base64.b64encode(PNG_1PX).decode()
    con = sqlite3.connect(db_path)
    # the schema as it stood before cover_hash existed
    con.execute("""CREATE TABLE record (
        id INTEGER PRIMARY KEY, artist VARCHAR(200), album_name VARCHAR(200),
        year VARCHAR(10), genre VARCHAR(100), bought_date VARCHAR(50),
        bought_where VARCHAR(200), bought_by VARCHAR(100), condition VARCHAR(10),
        my_rating FLOAT, wife_rating FLOAT, have_it BOOLEAN, play_count INTEGER,
        play_dates TEXT, last_cleaned VARCHAR(50), cleaned_dates TEXT,
        cover_data TEXT, notes TEXT, country VARCHAR(2))""")
    con.executemany(
        "INSERT INTO record (artist, album_name, have_it, cover_data) VALUES (?,?,1,?)",
        [("Chico Buarque", "Volume 3", cover), ("Tim Maia", "Uma Onda", "")])
    con.commit()
    con.close()

    previous = {n: os.environ.get(n) for n in ("DATA_DIR", "DATABASE_URL")}
    os.environ["DATA_DIR"] = str(tmp_path)
    os.environ.pop("DATABASE_URL", None)
    try:
        module = importlib.reload(importlib.import_module("app"))
        assert str(tmp_path) in module.app.config["SQLALCHEMY_DATABASE_URI"]
        rows = module.app.test_client().get("/api/records").get_json()
        by_artist = {r["artist"]: r for r in rows}

        assert by_artist["Chico Buarque"]["cover_url"], "existing cover lost its URL on upgrade"
        served = module.app.test_client().get(by_artist["Chico Buarque"]["cover_url"])
        assert served.data == PNG_1PX
        assert by_artist["Tim Maia"]["cover_url"] == "", "a coverless row invented a URL"
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        importlib.reload(importlib.import_module("app"))
