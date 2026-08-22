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
    at the real instance/vinyl.db.
    """
    previous = os.environ.get("DATA_DIR")
    os.environ["DATA_DIR"] = str(tmp_path_factory.mktemp("data"))
    try:
        module = importlib.reload(importlib.import_module("app"))
        with module.app.app_context():
            module.db.create_all()
        yield module
    finally:
        if previous is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = previous


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
