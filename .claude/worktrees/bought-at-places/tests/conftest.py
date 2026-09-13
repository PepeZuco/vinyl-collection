import json
import os
import pathlib
import socket
import tempfile

import pytest

# Point every test at a throwaway database BEFORE any test module is imported.
# conftest runs first, which matters: test modules do `import app` at module
# scope, and app.py resolves its database at import time. With DATA_DIR unset
# that resolves to the repo's own instance/vinyl.db — the real collection —
# and DATABASE_URL would override it outright. Nothing writes to it today, so
# the suite is currently safe by luck rather than by construction; one test
# that POSTs a record would be enough to lose data.
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="vinyl-tests-")
os.environ["DATA_DIR"] = _TEST_DATA_DIR
os.environ.pop("DATABASE_URL", None)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True, scope="session")
def _throwaway_database():
    """Create the schema in the throwaway database, and prove it is not the real one."""
    import app as app_module

    uri = app_module.app.config["SQLALCHEMY_DATABASE_URI"]
    assert _TEST_DATA_DIR in uri, f"tests are bound to a real database: {uri}"
    with app_module.app.app_context():
        app_module.db.create_all()
    yield


def load_fixture(name: str) -> dict:
    """Load a recorded API response by filename stem."""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """Fail loudly if any test opens a real socket.

    Every external call in scan.py is meant to be mocked. Without this guard a
    forgotten patch turns into a silent live request to MusicBrainz, iTunes,
    Spotify or the Claude API — slow, flaky, and billable.
    """
    def _blocked(self, address, *args, **kwargs):
        raise AssertionError(f"test attempted a real network connection to {address!r}")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
