import csv
import importlib
import io
import os

import pytest


def _csv_of_at_least(nbytes: int):
    """Build a valid collection CSV of at least nbytes, plus its row count.

    Rows are padded via `notes` rather than one giant field so we stay under
    the 10MB csv.field_size_limit app.py sets.
    """
    header = "artist,album_name,notes\n"
    row = 'Padded Artist,Padded Album,"' + "x" * 100_000 + '"\n'
    rows = (nbytes - len(header)) // len(row) + 1
    return (header + row * rows).encode("utf-8"), rows


@pytest.fixture(scope="module")
def vinyl_app(tmp_path_factory):
    """A fresh app bound to a throwaway sqlite file.

    Import wipes the table (`Record.query.delete()`), so this must never point
    at a real collection. Setting DATA_DIR is NOT enough on its own: app.py
    reads `os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR}/vinyl.db")`,
    so a DATABASE_URL in the environment wins outright and the padding rows
    land in whatever it names. Railway injects exactly that variable, and
    `railway run pytest` is a normal thing to type. So DATABASE_URL is removed
    for the duration and the resolved URI is checked before anything touches
    the database.
    """
    data_dir = tmp_path_factory.mktemp("data")
    previous = {name: os.environ.get(name) for name in ("DATA_DIR", "DATABASE_URL")}
    os.environ["DATA_DIR"] = str(data_dir)
    os.environ.pop("DATABASE_URL", None)
    try:
        module = importlib.reload(importlib.import_module("app"))
        uri = module.app.config["SQLALCHEMY_DATABASE_URI"]
        # Refuse to run rather than delete someone's records.
        assert uri == f"sqlite:///{data_dir}/vinyl.db", (
            f"test database escaped the tmp dir, refusing to wipe it: {uri}")
        with module.app.app_context():
            module.db.create_all()
        yield module
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        # importlib.reload rebinds sys.modules["app"] in place, so without this
        # every later test module keeps the throwaway database.
        importlib.reload(importlib.import_module("app"))


@pytest.fixture
def client(vinyl_app):
    c = vinyl_app.app.test_client()
    assert c.post("/api/auth/login", json={"password": vinyl_app.EDIT_PASSWORD}).status_code == 200
    return c


def test_import_accepts_a_csv_larger_than_32_mib(client):
    payload, rows = _csv_of_at_least(34 * 1024 * 1024)

    resp = client.post(
        "/api/import",
        data={"file": (io.BytesIO(payload), "vinyl_collection.csv")},
        content_type="multipart/form-data",
    )

    assert resp.status_code == 200, f"upload of {len(payload)} bytes rejected with {resp.status_code}"
    assert resp.get_json()["imported"] == rows


@pytest.mark.parametrize("raw,expected_mb", [
    ("64", 64),
    ("", 128),        # unset-but-present, e.g. an empty Railway variable
    ("128MB", 128),   # the unit typo people actually make
    ("abc", 128),
    ("0", 1),         # a ceiling of zero would reject every upload
])
def test_upload_ceiling_survives_a_malformed_variable(vinyl_app, monkeypatch, raw, expected_mb):
    """A bad MAX_UPLOAD_MB must not raise.

    _upload_ceiling_bytes() runs at import time, so a typo in the deployed
    variable would take the whole app down on boot rather than showing up as a
    legible error.
    """
    monkeypatch.setenv("MAX_UPLOAD_MB", raw)
    assert vinyl_app._upload_ceiling_bytes() == expected_mb * 1024 * 1024


def _rows(n, prefix="Row"):
    return [{"artist": f"{prefix} {i}", "album_name": f"Album {i}"} for i in range(n)]


def test_import_replaces_the_collection(vinyl_app):
    """The streaming path round-trips, including across a batch boundary."""
    app_module = vinyl_app
    n = vinyl_app._IMPORT_BATCH_ROWS + 7   # force more than one batch
    with app_module.app.app_context():
        app_module.import_records_from_csv_rows(iter(_rows(n)))
        assert app_module.Record.query.count() == n

        # A second import replaces rather than appends.
        app_module.import_records_from_csv_rows(iter(_rows(3, prefix="Second")))
        assert app_module.Record.query.count() == 3
        assert app_module.Record.query.first().artist == "Second 0"


def test_a_failed_import_leaves_the_existing_collection_intact(vinyl_app):
    """Import wipes the table first, so a partial import would be data loss.

    Batching the inserts must not turn one transaction into many: if a row
    part-way through blows up, the delete has to roll back with it.
    """
    app_module = vinyl_app
    with app_module.app.app_context():
        app_module.import_records_from_csv_rows(iter(_rows(4, prefix="Original")))
        assert app_module.Record.query.count() == 4

        def exploding_rows():
            # Enough rows to cross a batch boundary and actually hit the DB
            # before the failure, so a per-batch commit would be caught.
            for row in _rows(vinyl_app._IMPORT_BATCH_ROWS + 2, prefix="New"):
                yield row
            raise ValueError("truncated CSV")

        with pytest.raises(ValueError):
            app_module.import_records_from_csv_rows(exploding_rows())
        app_module.db.session.rollback()

        assert app_module.Record.query.count() == 4, "the old collection was destroyed"
        assert app_module.Record.query.first().artist == "Original 0"


def _reset_records_and_places(vinyl_app):
    """Wipe Record and Place so a test asserting on the whole table is not at
    the mercy of what an earlier test in this module-scoped db left behind.

    /api/import already wipes Record, but Place is deliberately NOT wiped by
    import (a place the CSV doesn't mention is still a real place) — so
    without this, Place rows from one test leak into the next test's exact-
    equality assertion on Place.query.all().
    """
    with vinyl_app.app.app_context():
        vinyl_app.Record.query.delete()
        vinyl_app.Place.query.delete()
        vinyl_app.db.session.commit()


def test_export_carries_each_record_s_place_link(client, vinyl_app):
    _reset_records_and_places(vinyl_app)
    # a place with a link, and a record bought there
    authed = client
    authed.post("/api/places", json={"name": "Tracks Rio", "url": "tracksrio.com"})
    authed.post("/api/records", json={"artist": "Tim Maia", "album_name": "Racional",
                                      "bought_where": "Tracks Rio"})

    body = authed.get("/api/export").get_data(as_text=True)
    header = body.splitlines()[0].split(",")

    assert header.index("bought_where_url") == header.index("bought_where") + 1
    rows = list(csv.DictReader(io.StringIO(body)))
    assert rows[0]["bought_where_url"] == "https://tracksrio.com"


def test_import_rebuilds_places_from_the_url_column(client, vinyl_app):
    _reset_records_and_places(vinyl_app)
    authed = client
    csv_text = (
        "artist,album_name,bought_where,bought_where_url\n"
        "Tim Maia,Racional,Tracks Rio,https://tracksrio.com\n"
        "Jorge Ben,A Tábua,Tracks Rio,https://tracksrio.com\n"
        "Novos Baianos,Acabou,Feira da Glória,\n"
    )
    authed.post("/api/import", data={"file": (io.BytesIO(csv_text.encode()), "c.csv")},
                content_type="multipart/form-data")

    with vinyl_app.app.app_context():
        got = {p.name: p.url for p in vinyl_app.Place.query.all()}
    assert got == {"Tracks Rio": "https://tracksrio.com", "Feira da Glória": ""}


def test_import_of_an_old_csv_with_no_url_column_still_works(client, vinyl_app):
    _reset_records_and_places(vinyl_app)
    authed = client
    csv_text = "artist,album_name,bought_where\nTim Maia,Racional,Tracks Rio\n"
    r = authed.post("/api/import", data={"file": (io.BytesIO(csv_text.encode()), "c.csv")},
                    content_type="multipart/form-data")

    assert r.status_code == 200
    with vinyl_app.app.app_context():
        assert {p.name: p.url for p in vinyl_app.Place.query.all()} == {"Tracks Rio": ""}


def test_import_leaves_an_existing_link_alone_when_the_csv_has_none(client, vinyl_app):
    _reset_records_and_places(vinyl_app)
    authed = client
    authed.post("/api/places", json={"name": "Tracks Rio", "url": "tracksrio.com"})
    csv_text = "artist,album_name,bought_where,bought_where_url\nTim Maia,R,Tracks Rio,\n"
    authed.post("/api/import", data={"file": (io.BytesIO(csv_text.encode()), "c.csv")},
                content_type="multipart/form-data")

    with vinyl_app.app.app_context():
        assert (vinyl_app.Place.query.filter_by(name="Tracks Rio").one().url
                == "https://tracksrio.com")


def test_import_trims_bought_where_so_a_later_place_rename_still_finds_it(client, vinyl_app):
    """Task 4 review: place names join to bought_where by exact match after
    trim, and import was the one writer that did NOT trim. A record imported
    with padded whitespace was invisible to a later rename of the place —
    records_updated stayed 0 and the record kept its padded value. This pins
    the one-line trim in _record_mapping that closes that orphaning path.
    """
    _reset_records_and_places(vinyl_app)
    authed = client
    authed.post("/api/places", json={"name": "Tracks", "url": "tracks.com"})
    csv_text = "artist,album_name,bought_where\nTim Maia,Racional, Tracks \n"
    r = authed.post("/api/import", data={"file": (io.BytesIO(csv_text.encode()), "c.csv")},
                    content_type="multipart/form-data")
    assert r.status_code == 200

    with vinyl_app.app.app_context():
        place = vinyl_app.Place.query.filter_by(name="Tracks").one()

    resp = authed.put(f"/api/places/{place.id}", json={"name": "Tracks Rio"})
    assert resp.status_code == 200
    assert resp.get_json()["records_updated"] == 1

    with vinyl_app.app.app_context():
        rec = vinyl_app.Record.query.filter_by(artist="Tim Maia").one()
        assert rec.bought_where == "Tracks Rio"
