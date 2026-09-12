"""The places behind bought_where, and the link each one carries."""

import pytest

# `import app as app_module` rather than `from app import app, db, Place,
# Record`: other test files in this suite (test_import.py) reload the app
# module via importlib.reload() inside a module-scoped fixture, which rebinds
# app.app / app.db / app.Place / app.Record to fresh objects in place. A name
# captured once at collection time (`from app import db`) would then be a
# stale object whose routes resolve `db` through the *current* module
# globals — a different instance than the one the stale Flask app was
# actually registered with, raising "the current Flask app is not registered
# with this SQLAlchemy instance" the moment test_import.py runs first, which
# it always does (it collects before this file alphabetically). Looking the
# names up through `app_module` at fixture/call time, like
# test_tracks_endpoint.py and test_search_endpoint.py do, always gets the
# live, self-consistent set. Later tests appended to this file must keep
# going through `app_module` rather than binding a bare `app`/`db`/`Place`/
# `Record` name at module scope.
import app as app_module


@pytest.fixture
def client():
    """A logged-OUT client on an empty places/records table."""
    app_module.app.config["TESTING"] = True
    with app_module.app.app_context():
        app_module.Place.query.delete()
        app_module.Record.query.delete()
        app_module.db.session.commit()
    with app_module.app.test_client() as c:
        yield c


@pytest.fixture
def authed(client):
    """The same client, past the edit password.

    The login is the pattern tests/test_import.py:58 already uses — the
    password is read off the module rather than written as a literal, so it
    keeps working if the default ever changes.
    """
    assert client.post("/api/auth/login",
                       json={"password": app_module.EDIT_PASSWORD}).status_code == 200
    return client


def make_place(name, url=""):
    with app_module.app.app_context():
        p = app_module.Place(name=name, url=url)
        app_module.db.session.add(p)
        app_module.db.session.commit()
        return p.id


def test_places_lists_sorted_by_lowercased_name(client):
    make_place("tracks")
    make_place("Amoeba")
    make_place("Feira da Glória")

    body = client.get("/api/places").get_json()

    assert [p["name"] for p in body] == ["Amoeba", "Feira da Glória", "tracks"]
    assert set(body[0]) == {"id", "name", "url"}


def test_places_read_is_public(client):
    make_place("Tracks Rio", "https://tracksrio.com")
    assert client.get("/api/places").status_code == 200
