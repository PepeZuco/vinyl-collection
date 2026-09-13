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


def test_create_a_place(authed):
    r = authed.post("/api/places", json={"name": "  Tracks Rio  ", "url": "tracksrio.com"})

    assert r.status_code == 201
    body = r.get_json()
    assert body["name"] == "Tracks Rio"
    assert body["url"] == "https://tracksrio.com"


def test_create_keeps_an_empty_link_empty(authed):
    r = authed.post("/api/places", json={"name": "Feira da Glória"})
    assert r.status_code == 201
    assert r.get_json()["url"] == ""


def test_create_refuses_a_duplicate_name_ignoring_case(authed):
    authed.post("/api/places", json={"name": "Tracks Rio"})
    r = authed.post("/api/places", json={"name": "tracks rio"})

    assert r.status_code == 409
    assert "error" in r.get_json()


def test_create_refuses_an_empty_name(authed):
    assert authed.post("/api/places", json={"name": "   "}).status_code == 400


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "ftp://x.com",
                                 "data:text/html,hi", "https://",
                                 "https:///", "https://:8080", "https://@"])
def test_create_refuses_a_link_that_is_not_http(authed, bad):
    r = authed.post("/api/places", json={"name": "Somewhere", "url": bad})
    assert r.status_code == 400


def test_create_requires_auth(client):
    r = client.post("/api/places", json={"name": "Tracks Rio"})
    assert r.status_code in (401, 403)


def test_create_accepts_a_bare_host_port(authed):
    r = authed.post("/api/places", json={"name": "Tracks Rio Loja",
                                          "url": "tracksrio.com:8080/loja"})
    assert r.status_code == 201
    assert r.get_json()["url"] == "https://tracksrio.com:8080/loja"


def test_create_accepts_localhost_port(authed):
    r = authed.post("/api/places", json={"name": "Dev Store", "url": "localhost:3000"})
    assert r.status_code == 201
    assert r.get_json()["url"] == "https://localhost:3000"


@pytest.mark.parametrize("bad", [12345, ["a"], {"a": 1}, True])
def test_create_refuses_a_non_string_url(authed, bad):
    r = authed.post("/api/places", json={"name": "Somewhere", "url": bad})
    assert r.status_code == 400
    with app_module.app.app_context():
        assert app_module.Place.query.count() == 0


@pytest.mark.parametrize("bad", [12345, ["a"], {"a": 1}, True])
def test_create_refuses_a_non_string_name(authed, bad):
    r = authed.post("/api/places", json={"name": bad})
    assert r.status_code == 400
    with app_module.app.app_context():
        assert app_module.Place.query.count() == 0


def test_create_accepts_a_null_url_as_no_link(authed):
    r = authed.post("/api/places", json={"name": "Feira da Glória", "url": None})
    assert r.status_code == 201
    assert r.get_json()["url"] == ""


def make_record(where):
    with app_module.app.app_context():
        r = app_module.Record(artist="a", album_name="b", bought_where=where)
        app_module.db.session.add(r)
        app_module.db.session.commit()
        return r.id


def wheres():
    with app_module.app.app_context():
        return sorted((r.bought_where or "") for r in app_module.Record.query.all())


def test_edit_just_the_link(authed):
    pid = make_place("Tracks Rio")
    make_record("Tracks Rio")

    r = authed.put(f"/api/places/{pid}",
                   json={"name": "Tracks Rio", "url": "tracksrio.com"})

    assert r.status_code == 200
    assert r.get_json()["place"]["url"] == "https://tracksrio.com"
    assert r.get_json()["records_updated"] == 0
    assert wheres() == ["Tracks Rio"]


def test_a_rename_rewrites_every_matching_record_and_leaves_others_alone(authed):
    pid = make_place("Tracks")
    make_record("Tracks")
    make_record("Tracks")
    make_record("Amoeba")

    r = authed.put(f"/api/places/{pid}", json={"name": "Tracks Rio", "url": ""})

    assert r.get_json()["records_updated"] == 2
    assert wheres() == ["Amoeba", "Tracks Rio", "Tracks Rio"]


def test_a_rename_onto_an_existing_name_merges_them(authed):
    keep = make_place("Tracks", "https://tracksrio.com")
    absorbed = make_place("tracks rio")
    make_record("Tracks")
    make_record("tracks rio")

    r = authed.put(f"/api/places/{keep}", json={"name": "Tracks RIO", "url": ""})

    assert r.status_code == 200
    assert r.get_json()["records_updated"] == 2
    # the casing typed into the rename wins, and the absorbed row is gone
    assert wheres() == ["Tracks RIO", "Tracks RIO"]
    with app_module.app.app_context():
        assert app_module.db.session.get(app_module.Place, absorbed) is None
        assert app_module.db.session.get(app_module.Place, keep).name == "Tracks RIO"


def test_a_rename_typed_as_the_absorbed_places_exact_spelling_does_not_double_count(authed):
    # The natural way to merge: rename the edited place onto the OTHER place's
    # name, typed exactly as that other place already has it. Nothing here is
    # a new spelling — "Tracks Rio"'s 2 records already read the right thing —
    # so only the 3 "Tracks" records actually change.
    edited = make_place("Tracks")
    absorbed = make_place("Tracks Rio")
    make_record("Tracks")
    make_record("Tracks")
    make_record("Tracks")
    make_record("Tracks Rio")
    make_record("Tracks Rio")

    r = authed.put(f"/api/places/{edited}", json={"name": "Tracks Rio", "url": ""})

    assert r.status_code == 200
    assert r.get_json()["records_updated"] == 3
    assert wheres() == ["Tracks Rio"] * 5
    with app_module.app.app_context():
        assert app_module.db.session.get(app_module.Place, absorbed) is None
        assert app_module.Place.query.count() == 1


def test_a_verbatim_merge_still_applies_the_requests_name_and_url(authed):
    edited = make_place("Tracks")
    make_place("Tracks Rio")
    make_record("Tracks")
    make_record("Tracks Rio")

    r = authed.put(f"/api/places/{edited}",
                   json={"name": "Tracks Rio", "url": "https://tracksrio.com"})

    body = r.get_json()["place"]
    assert body["name"] == "Tracks Rio"
    assert body["url"] == "https://tracksrio.com"


def test_edit_refuses_a_bad_link_and_an_empty_name(authed):
    pid = make_place("Tracks Rio")

    assert authed.put(f"/api/places/{pid}",
                      json={"name": "Tracks Rio", "url": "javascript:alert(1)"}
                      ).status_code == 400
    assert authed.put(f"/api/places/{pid}", json={"name": " "}).status_code == 400


def test_edit_404s_on_an_unknown_place(authed):
    assert authed.put("/api/places/99999", json={"name": "x"}).status_code == 404


def test_edit_requires_auth(client):
    pid = make_place("Tracks Rio")
    assert client.put(f"/api/places/{pid}", json={"name": "x"}).status_code in (401, 403)


def test_a_record_write_trims_bought_where(authed):
    authed.post("/api/records", json={"artist": "a", "album_name": "b",
                                      "bought_where": "  Tracks Rio  "})
    assert wheres() == ["Tracks Rio"]

    rid = make_record("Tracks Rio")
    authed.put(f"/api/records/{rid}", json={"bought_where": "  Amoeba "})
    assert wheres() == ["Amoeba", "Tracks Rio"]


@pytest.mark.parametrize("bad", [12345, ["a"], {"a": 1}, True])
def test_edit_refuses_a_non_string_name(authed, bad):
    pid = make_place("Tracks Rio")
    r = authed.put(f"/api/places/{pid}", json={"name": bad})
    assert r.status_code == 400


@pytest.mark.parametrize("bad", [12345, ["a"], {"a": 1}, True])
def test_edit_refuses_a_non_string_url(authed, bad):
    pid = make_place("Tracks Rio")
    r = authed.put(f"/api/places/{pid}", json={"name": "Tracks Rio", "url": bad})
    assert r.status_code == 400
