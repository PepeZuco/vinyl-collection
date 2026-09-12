"""The places behind bought_where, and the link each one carries."""

import pytest

import app as app_module
from app import app, db, Place, Record


@pytest.fixture
def client():
    """A logged-OUT client on an empty places/records table."""
    app.config["TESTING"] = True
    with app.app_context():
        Place.query.delete()
        Record.query.delete()
        db.session.commit()
    with app.test_client() as c:
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
    with app.app_context():
        p = Place(name=name, url=url)
        db.session.add(p)
        db.session.commit()
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
