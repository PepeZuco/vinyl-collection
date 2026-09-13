# Bought-at places with links — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `bought_where` becomes a pick from a known list of places, each place can carry a link, and that link is clickable in the record drawer and in the crate header when grouping by place.

**Architecture:** A new `place` table keyed by **name**, holding `name` + `url`. `Record.bought_where` keeps the place's name verbatim, so every existing reader (sort, group, filter, search, scan autofill, CSV) is untouched. The name→url map reaches the browser through a new `GET /api/places`; writes go through `POST /api/places` and `PUT /api/places/<id>`, where a rename rewrites every matching record. The form's free-typing input becomes a hidden input plus a button and a panel, so `formValues()` and the draft machinery keep reading `#fWhere.value` exactly as they do today.

**Tech Stack:** Flask + Flask-SQLAlchemy (SQLite locally, the Railway volume in production), vanilla JS in `templates/index.html` with pure rules extracted to `static/*.js`, pytest + `node --test` (run through pytest wrappers).

**Spec:** `docs/superpowers/specs/2026-09-12-bought-at-places-design.md`

## Global Constraints

- `Record.bought_where` keeps the place name as text. No `place_id` foreign key, no column rename, no change to `/api/records`' bare-array response shape.
- Place names join to `bought_where` by **exact match after trim**. Every write of `bought_where` (`create_record`, `update_record`, `import_records_from_csv_rows`, the rename in `PUT /api/places/<id>`) trims first.
- A place URL is stored only when it is `http://` or `https://` after normalization. A scheme-less value gets `https://` prepended; anything else is rejected with `400`. This is a security rule, not tidiness — the drawer turns the value into an `href`.
- Duplicate place names are refused **case-insensitively** on create. `PUT` renaming one place onto another's name (also matched case-insensitively) **merges** them, and the casing typed into the rename wins.
- There is no `DELETE /api/places`.
- Place writes sit behind the existing `@require_auth`. `GET /api/places` is public, like `/api/records`.
- The `✎` edit affordance in the picker renders only when the client's `authed` is true.
- New pure JS rules go in `static/places.js` following `static/notes.js`: an IIFE assigned to a global `const`, ending in `if (typeof module !== 'undefined' && module.exports) module.exports = VinylPlaces;`.
- Every JS test file gets a pytest wrapper so `python -m pytest` stays the single command.
- `tests/test_boot.py` times out on this machine even when every test passes — run the node file directly (`node --test tests/test_places.js`) when checking JS work.

---

### Task 1: `static/places.js` — the pure rules

**Files:**
- Create: `static/places.js`
- Create: `tests/test_places.js`
- Create: `tests/test_places_js.py`

**Interfaces:**
- Consumes: nothing.
- Produces: global `VinylPlaces` with `normalizeUrl(raw) -> string|null`, `validName(raw) -> boolean`, `sortPlaces(places) -> Array`, `mergeTarget(name, places, editingId) -> place|null`, `placeUrl(name, places) -> string`. A place object is `{id: number, name: string, url: string}`. `normalizeUrl` returns `''` for an empty input, the normalized URL string, or `null` when the value must be rejected.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_places.js`:

```js
// Tests for the place rules — the URL normalization is a security boundary:
// a stored javascript: URL becomes an href in the drawer, so the rejecting
// branch is pinned here rather than trusted to the caller.

const test = require('node:test');
const assert = require('node:assert');

const { normalizeUrl, validName, sortPlaces, mergeTarget, placeUrl } =
  require('../static/places.js');

// ── normalizeUrl ────────────────────────────────────────────────────────────

test('an empty link stays empty — a place without one is normal', () => {
  assert.strictEqual(normalizeUrl(''), '');
  assert.strictEqual(normalizeUrl('   '), '');
  assert.strictEqual(normalizeUrl(null), '');
  assert.strictEqual(normalizeUrl(undefined), '');
});

test('a scheme-less host gets https://', () => {
  assert.strictEqual(normalizeUrl('tracksrio.com'), 'https://tracksrio.com');
  assert.strictEqual(normalizeUrl('  tracksrio.com/loja  '), 'https://tracksrio.com/loja');
});

test('a protocol-relative link gets https:// without doubling the slashes', () => {
  assert.strictEqual(normalizeUrl('//tracksrio.com'), 'https://tracksrio.com');
});

test('http and https are kept as typed', () => {
  assert.strictEqual(normalizeUrl('http://x.com'), 'http://x.com');
  assert.strictEqual(normalizeUrl('https://x.com/a?b=c#d'), 'https://x.com/a?b=c#d');
});

test('a javascript: link is rejected', () => {
  assert.strictEqual(normalizeUrl('javascript:alert(1)'), null);
  assert.strictEqual(normalizeUrl('JavaScript:alert(1)'), null);
});

test('any other scheme is rejected', () => {
  assert.strictEqual(normalizeUrl('ftp://x.com'), null);
  assert.strictEqual(normalizeUrl('data:text/html,hi'), null);
});

test('a scheme with no host is rejected', () => {
  assert.strictEqual(normalizeUrl('https://'), null);
});

// ── validName ───────────────────────────────────────────────────────────────

test('a name needs at least one non-space character', () => {
  assert.strictEqual(validName('Tracks Rio'), true);
  assert.strictEqual(validName('  x  '), true);
  assert.strictEqual(validName('   '), false);
  assert.strictEqual(validName(''), false);
  assert.strictEqual(validName(null), false);
});

// ── sortPlaces ──────────────────────────────────────────────────────────────

test('places sort by name, ignoring case, without mutating the input', () => {
  const input = [
    { id: 1, name: 'tracks', url: '' },
    { id: 2, name: 'Feira da Glória', url: '' },
    { id: 3, name: 'Amoeba', url: '' },
  ];
  const out = sortPlaces(input);
  assert.deepStrictEqual(out.map(p => p.id), [3, 2, 1]);
  assert.deepStrictEqual(input.map(p => p.id), [1, 2, 3]);
});

// ── mergeTarget ─────────────────────────────────────────────────────────────

test('a rename onto another place names that place as the merge target', () => {
  const places = [{ id: 1, name: 'Tracks', url: '' }, { id: 2, name: 'Amoeba', url: '' }];
  assert.strictEqual(mergeTarget('amoeba', places, 1).id, 2);
});

test('a rename that only changes case on the place being edited is not a merge', () => {
  const places = [{ id: 1, name: 'Tracks', url: '' }, { id: 2, name: 'Amoeba', url: '' }];
  assert.strictEqual(mergeTarget('TRACKS', places, 1), null);
});

test('a brand new name is not a merge', () => {
  const places = [{ id: 1, name: 'Tracks', url: '' }];
  assert.strictEqual(mergeTarget('Feira da Glória', places, 1), null);
});

// ── placeUrl ────────────────────────────────────────────────────────────────

test('a place with a link resolves to it', () => {
  const places = [{ id: 1, name: 'Tracks Rio', url: 'https://tracksrio.com' }];
  assert.strictEqual(placeUrl('Tracks Rio', places), 'https://tracksrio.com');
  assert.strictEqual(placeUrl('  Tracks Rio  ', places), 'https://tracksrio.com');
});

test('a place with no link, an unknown name and no name all resolve to empty', () => {
  const places = [{ id: 1, name: 'Tracks Rio', url: '' }];
  assert.strictEqual(placeUrl('Tracks Rio', places), '');
  assert.strictEqual(placeUrl('Nowhere', places), '');
  assert.strictEqual(placeUrl('', places), '');
  assert.strictEqual(placeUrl(null, places), '');
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test tests/test_places.js`
Expected: FAIL — `Cannot find module '../static/places.js'`

- [ ] **Step 3: Write the module**

Create `static/places.js`:

```js
/* A place a record was bought at, and the link that place carries.
 *
 * The rules live here because one of them is a security boundary: the drawer
 * renders a place's url as an href, so anything that is not http(s) has to be
 * refused before it is ever stored. Both ends enforce it — app.py mirrors
 * normalizeUrl so a hand-rolled POST cannot get past the browser's copy.
 *
 * Loaded as a plain script in the browser, where `const VinylPlaces` lands in
 * the global lexical scope for the inline script below it; required as a
 * module by the tests. */

const VinylPlaces = (function () {

  const HAS_SCHEME = /^[a-zA-Z][a-zA-Z0-9+.\-]*:/;
  const HTTP_URL = /^https?:\/\/[^\s]+$/i;

  const str = v => String(v === undefined || v === null ? '' : v);

  /* '' for no link, the normalized url, or null when the value must be
   * refused. A bare host is assumed https; leading slashes are dropped first
   * so '//host' does not become 'https:////host'. */
  function normalizeUrl(raw) {
    let s = str(raw).trim();
    if (!s) return '';
    if (!HAS_SCHEME.test(s)) s = 'https://' + s.replace(/^\/+/, '');
    return HTTP_URL.test(s) ? s : null;
  }

  function validName(raw) {
    return str(raw).trim().length > 0;
  }

  function sortPlaces(places) {
    return (places || []).slice().sort((a, b) =>
      str(a.name).toLowerCase().localeCompare(str(b.name).toLowerCase()));
  }

  /* The place this rename would collapse into, or null. The place being
   * edited is excluded, so re-casing its own name is a rename and not a
   * merge onto itself. */
  function mergeTarget(name, places, editingId) {
    const key = str(name).trim().toLowerCase();
    if (!key) return null;
    return (places || []).find(p =>
      p.id !== editingId && str(p.name).trim().toLowerCase() === key) || null;
  }

  /* The link for a bought_where value. An unknown name resolves to '' rather
   * than undefined, so a read surface never builds a broken href. */
  function placeUrl(name, places) {
    const key = str(name).trim();
    if (!key) return '';
    const hit = (places || []).find(p => str(p.name).trim() === key);
    return (hit && hit.url) || '';
  }

  return { normalizeUrl, validName, sortPlaces, mergeTarget, placeUrl };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylPlaces;
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test tests/test_places.js`
Expected: PASS, 14 tests

- [ ] **Step 5: Add the pytest wrapper**

Create `tests/test_places_js.py`:

```python
"""Run the JavaScript place rules under pytest.

Mirrors tests/test_notes.py: the rules are pure functions in static/places.js,
so they need a JS runtime, and shelling out to node's test runner keeps
`pytest` as the one command.
"""

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_places_js():
    result = subprocess.run(
        ["node", "--test", "tests/test_places.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 6: Run the wrapper**

Run: `python -m pytest tests/test_places_js.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add static/places.js tests/test_places.js tests/test_places_js.py
git commit -m "feat: the place rules — url normalization, sort, merge target"
```

---

### Task 2: The `Place` model, its backfill, and `GET /api/places`

**Files:**
- Modify: `app.py` — new model after `class NoteImage`, backfill inside the existing `with app.app_context():` block, new route after `list_records`
- Create: `tests/test_places.py`

**Interfaces:**
- Consumes: nothing from Task 1 (the Python URL rule arrives in Task 3).
- Produces: `class Place` with `id`, `name`, `url` and `to_dict() -> {"id","name","url"}`; `GET /api/places` returning a JSON array sorted by lowercased name.

- [ ] **Step 1: Write the failing test**

Create `tests/test_places.py`:

```python
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
```

These fixtures bind to the session-wide throwaway database `tests/conftest.py`
sets up, and deliberately do not reload `app` the way `tests/test_import.py`
does — so nothing in this file may call `/api/import`, which wipes tables.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_places.py -v`
Expected: FAIL — `ImportError: cannot import name 'Place' from 'app'`

- [ ] **Step 3: Add the model**

In `app.py`, directly after the `class NoteImage(db.Model):` block:

```python
# A place a record was bought at. The NAME is the key, and record.bought_where
# holds it verbatim — so sort, group, filter, search, the scan autofill and the
# CSV all keep reading the column they always read, and this table only adds the
# link. The join is an exact match after trim, which is why every writer of
# bought_where trims.
class Place(db.Model):
    id   = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    url  = db.Column(db.String(500))

    def to_dict(self):
        return {"id": self.id, "name": self.name or "", "url": self.url or ""}
```

- [ ] **Step 4: Add the backfill**

Inside the existing `with app.app_context():` block, after the `added_cover_hash`
backfill loop and **before** `_sweep_note_images()`:

```python
    # One-time backfill: db.create_all() just made the place table, so seed it
    # from the names already in the collection. Links start empty — there is
    # nowhere to get them from. Distinct is case-sensitive on purpose: if the
    # data holds both 'Tracks' and 'tracks' this produces two places and the
    # rename-merge in PUT /api/places/<id> is how they get collapsed. Picking a
    # canonical casing here would silently rewrite records during a deploy.
    if not inspector.has_table("place") or Place.query.first() is None:
        names = {(n or "").strip() for (n,) in
                 db.session.query(Record.bought_where).distinct().all()}
        names.discard("")
        if names:
            db.session.execute(db.insert(Place),
                               [{"name": n, "url": ""} for n in sorted(names)])
            db.session.commit()
```

`inspector` is assigned near the top of this same block, **before**
`db.create_all()` ran, so `has_table("place")` reports whether the table
pre-existed this boot rather than whether it exists now. The
`Place.query.first() is None` half covers the other case: a table that exists
but was never seeded. Step 6 boots the app against a populated database, which
is what proves the branch fires.

- [ ] **Step 5: Add the read route**

In `app.py`, immediately after the `list_records` function:

```python
@app.route("/api/places")
def list_places():
    # Public, like /api/records: the drawer and the crate headers need the link
    # for a visitor too, and a place name is already visible on every record.
    places = Place.query.order_by(func.lower(Place.name)).all()
    return jsonify([p.to_dict() for p in places])
```

`func` is already imported at the top of `app.py`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_places.py -v`
Expected: PASS, 2 tests

Then prove the backfill runs on a database that already has records:

```bash
rm -rf /tmp/places-backfill && mkdir -p /tmp/places-backfill
DATA_DIR=/tmp/places-backfill python - <<'PY'
import app as m
with m.app.app_context():
    m.db.session.add(m.Record(artist="Tim Maia", bought_where="  Tracks Rio  "))
    m.db.session.add(m.Record(artist="Jorge Ben", bought_where="Tracks Rio"))
    m.db.session.commit()
PY
DATA_DIR=/tmp/places-backfill python -c "
import app as m
with m.app.app_context():
    print([(p.name, p.url) for p in m.Place.query.all()])
"
```

Expected: `[('Tracks Rio', '')]` — one place, trimmed, not two.

- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_places.py
git commit -m "feat: a place table, backfilled from the names already in use"
```

---

### Task 3: `POST /api/places`, and the Python URL rule

**Files:**
- Modify: `app.py` — a `_place_url` helper beside the other module-level helpers (near `_size`, around line 204), a new route after `list_places`
- Modify: `tests/test_places.py`

**Interfaces:**
- Consumes: `Place`, the `client`/`authed`/`make_place` fixtures from Task 2.
- Produces: `_place_url(raw) -> str | None` — `''` for empty, the normalized URL, or `None` when it must be refused (mirrors `VinylPlaces.normalizeUrl`). `POST /api/places` accepting `{name, url}`, responding `201` with the place dict.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_places.py`:

```python
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
                                 "data:text/html,hi", "https://"])
def test_create_refuses_a_link_that_is_not_http(authed, bad):
    r = authed.post("/api/places", json={"name": "Somewhere", "url": bad})
    assert r.status_code == 400


def test_create_requires_auth(client):
    r = client.post("/api/places", json={"name": "Tracks Rio"})
    assert r.status_code in (401, 403)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_places.py -v`
Expected: FAIL — `405 METHOD NOT ALLOWED` on the POST

- [ ] **Step 3: Write the helper and the route**

Add `import re` to the top of `app.py` (line 1's import list has no `re` today).

Beside the other small helpers (after `def _size(value):`):

```python
_PLACE_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")
_PLACE_HTTP = re.compile(r"^https?://[^\s]+$", re.I)


def _place_url(raw):
    """A place's link: '' for none, the normalized url, or None to refuse it.

    Mirrors normalizeUrl in static/places.js, and is the enforcing copy — the
    browser's is a courtesy so the form can complain before the round trip.
    The refusal matters: the drawer renders this value as an href, so a stored
    'javascript:' url would be a click target.
    """
    s = (raw or "").strip()
    if not s:
        return ""
    if not _PLACE_SCHEME.match(s):
        s = "https://" + s.lstrip("/")
    return s if _PLACE_HTTP.match(s) else None
```

After `list_places`:

```python
@app.route("/api/places", methods=["POST"])
@require_auth
def create_place():
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    if not name:
        return jsonify({"error": "a place needs a name"}), 400
    url = _place_url(d.get("url"))
    if url is None:
        return jsonify({"error": "a link has to be http:// or https://"}), 400
    clash = Place.query.filter(func.lower(Place.name) == name.lower()).first()
    if clash:
        return jsonify({"error": f"'{clash.name}' is already on the list"}), 409
    p = Place(name=name, url=url)
    db.session.add(p)
    db.session.commit()
    return jsonify(p.to_dict()), 201
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_places.py -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_places.py
git commit -m "feat: create a place, with an http-only link"
```

---

### Task 4: `PUT /api/places/<id>` — rename, merge, and trimmed record writes

**Files:**
- Modify: `app.py` — new route after `create_place`; `create_record` (~line 510), `update_record`'s field loop (~line 539)
- Modify: `tests/test_places.py`

**Interfaces:**
- Consumes: `Place`, `_place_url`, the fixtures.
- Produces: `PUT /api/places/<id>` responding `{"place": {...}, "records_updated": N}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_places.py`:

```python
def make_record(where):
    with app.app_context():
        r = Record(artist="a", album_name="b", bought_where=where)
        db.session.add(r)
        db.session.commit()
        return r.id


def wheres():
    with app.app_context():
        return sorted((r.bought_where or "") for r in Record.query.all())


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
    with app.app_context():
        assert db.session.get(Place, absorbed) is None
        assert db.session.get(Place, keep).name == "Tracks RIO"


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_places.py -v`
Expected: FAIL — `405 METHOD NOT ALLOWED` on the PUT, and the trim test asserting `['  Tracks Rio  ']`

- [ ] **Step 3: Write the route**

After `create_place`:

```python
@app.route("/api/places/<int:pid>", methods=["PUT"])
@require_auth
def update_place(pid):
    place = db.session.get(Place, pid)
    if place is None:
        raise NotFound()
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    if not name:
        return jsonify({"error": "a place needs a name"}), 400
    url = _place_url(d.get("url"))
    if url is None:
        return jsonify({"error": "a link has to be http:// or https://"}), 400

    # Every name this rename has to pull records off: the place's own old name,
    # plus the name of any place it is being merged into. Both move to `name`,
    # so a merge leaves one place and one spelling behind it.
    old_names = [place.name] if place.name != name else []
    absorbed = Place.query.filter(func.lower(Place.name) == name.lower(),
                                  Place.id != place.id).first()
    if absorbed:
        old_names.append(absorbed.name)
        db.session.delete(absorbed)

    updated = 0
    for old in old_names:
        updated += (Record.query.filter(Record.bought_where == old)
                    .update({Record.bought_where: name},
                            synchronize_session=False))
    place.name = name
    place.url = url
    db.session.commit()
    return jsonify({"place": place.to_dict(), "records_updated": updated})
```

- [ ] **Step 4: Trim `bought_where` on the record writes**

In `create_record`, replace the `bought_where` line:

```python
        bought_where= (d.get("bought_where","") or "").strip(),
```

In `update_record`, drop `"bought_where"` from the generic field loop so the
list reads:

```python
    for field in ["artist","album_name","year","genre","bought_date","bought_by","condition"]:
```

and add immediately after that loop:

```python
    # Trimmed, not passed through: the place table joins to this column by
    # exact name, so a stray space would orphan the record from its link.
    if "bought_where" in d: r.bought_where = (d["bought_where"] or "").strip()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_places.py -v`
Expected: PASS, 18 tests

- [ ] **Step 6: Run the whole Python suite for regressions**

Run: `python -m pytest -x -q --ignore=tests/test_boot.py`
Expected: PASS (`test_boot.py` is excluded because it hangs on this machine)

- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_places.py
git commit -m "feat: rename a place, merging it into another and rewriting its records"
```

---

### Task 5: The backup — a `bought_where_url` column out, places upserted back in

**Files:**
- Modify: `app.py` — `export_csv` (~line 988), `_record_mapping` (~line 1051), `import_records_from_csv_rows` (~line 1080)
- Modify: `tests/test_import.py`

**Interfaces:**
- Consumes: `Place`, `_place_url`.
- Produces: a `bought_where_url` column in the export, positioned after `bought_where`; places upserted on import.

- [ ] **Step 1: Write the failing tests**

These belong in `tests/test_import.py` because `/api/import` **wipes the
tables**: that file's `vinyl_app` fixture reloads `app` against its own tmp
database and asserts the resolved URI before anything deletes a row, and its
`client` fixture is already logged in (`tests/test_import.py:20-60`). Use both —
every `app`/`Place` reference goes through the `vinyl_app` module handle rather
than a top-level import. `io` is already imported there; add `csv`.

Append:

```python
def test_export_carries_each_record_s_place_link(client, vinyl_app):
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
    authed = client
    csv_text = "artist,album_name,bought_where\nTim Maia,Racional,Tracks Rio\n"
    r = authed.post("/api/import", data={"file": (io.BytesIO(csv_text.encode()), "c.csv")},
                    content_type="multipart/form-data")

    assert r.status_code == 200
    with vinyl_app.app.app_context():
        assert {p.name: p.url for p in vinyl_app.Place.query.all()} == {"Tracks Rio": ""}


def test_import_leaves_an_existing_link_alone_when_the_csv_has_none(client, vinyl_app):
    authed = client
    authed.post("/api/places", json={"name": "Tracks Rio", "url": "tracksrio.com"})
    csv_text = "artist,album_name,bought_where,bought_where_url\nTim Maia,R,Tracks Rio,\n"
    authed.post("/api/import", data={"file": (io.BytesIO(csv_text.encode()), "c.csv")},
                content_type="multipart/form-data")

    with vinyl_app.app.app_context():
        assert (vinyl_app.Place.query.filter_by(name="Tracks Rio").one().url
                == "https://tracksrio.com")
```

The upload shape above is the one `tests/test_import.py:66-71` already uses:
field name `file`, `content_type="multipart/form-data"`, and `200` with
`{"imported": n}` on success.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_import.py -v`
Expected: FAIL — `ValueError: 'bought_where_url' is not in list` on the header assertion, and empty `Place` tables

- [ ] **Step 3: Add the export column**

In `export_csv`, change the `cols` list so `bought_where_url` follows
`bought_where`:

```python
    cols = ["id","artist","album_name","year","genre","bought_date","bought_where",
            "bought_where_url","bought_by","condition","my_rating","wife_rating","have_it","play_count","play_dates","cleaned_dates","cover_image_base64","notes","country","note_images","tracks","disc_count","size"]
    # One dict for the whole export rather than a lookup per row: there are a
    # few dozen places against hundreds of records, and unlike the note images
    # below these are short strings, so holding them all costs nothing.
    place_urls = dict(db.session.query(Place.name, Place.url).all())
```

and inside `generate()`, next to the other derived columns (after the
`d["cover_image_base64"]` line):

```python
            # The link belongs to the place, but the backup is one flat table,
            # so every row carries its place's link and the importer rebuilds
            # the place table from the pairs it sees.
            d["bought_where_url"] = place_urls.get((r.bought_where or "").strip(), "") or ""
```

- [ ] **Step 4: Carry the column through the import**

In `_record_mapping`, trim the name:

```python
        "bought_where":(row.get("bought_where","") or "").strip(),
```

In `import_records_from_csv_rows`, collect the pairs while looping and upsert
them after the final `flush()`. Add before the loop:

```python
    # name -> url, first non-empty url per name wins. Places are NOT wiped like
    # the records are: a link the CSV does not know about (a place added after
    # the export) is still true, and losing it would make a restore lossy in a
    # way the export cannot see.
    places_seen = {}
```

inside the `for row in rows:` loop, after the `batch.append(...)` line:

```python
        place_name = (row.get("bought_where","") or "").strip()
        if place_name:
            place_url = _place_url(row.get("bought_where_url")) or ""
            if place_url or place_name not in places_seen:
                places_seen.setdefault(place_name, "")
                if place_url:
                    places_seen[place_name] = place_url
```

and after the final `flush()`, before `db.session.commit()`:

```python
    if places_seen:
        existing = {p.name: p for p in
                    Place.query.filter(Place.name.in_(list(places_seen))).all()}
        for name, url in places_seen.items():
            p = existing.get(name)
            if p is None:
                db.session.add(Place(name=name, url=url))
            elif url:
                p.url = url
```

A place already holding a link keeps it when the CSV's cell is empty — that is
the `elif url:` branch, and it is what the fourth test pins.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_import.py -v`
Expected: PASS

- [ ] **Step 6: Run the whole Python suite**

Run: `python -m pytest -x -q --ignore=tests/test_boot.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_import.py
git commit -m "feat: place links ride the CSV backup out and back"
```

---

### Task 6: The picker in the form

**Files:**
- Modify: `templates/index.html` — the `<script src>` list (~line 2850), the `#fWhere` markup (~line 2496), new CSS beside the other form styles, the JS around `populateWhereList` (~line 4662), `applyDraft` (~line 5346), the `openAdd` reset (~line 5386), `editRecord` (~line 5470)

**Interfaces:**
- Consumes: `VinylPlaces.normalizeUrl`, `validName`, `sortPlaces`, `mergeTarget` from Task 1; `GET/POST/PUT /api/places` from Tasks 2–4.
- Produces: globals `places` (the array), `loadPlaces()`, `placeUrlOf(name)`, `setWhere(name)`, `pickWhere(id)`, `renderWherePanel()`; `#fWhere` as a hidden input still readable by `formValues()`.

- [ ] **Step 1: Load the module and the data**

Add after the `notes.js` script tag:

```html
<script src="/static/places.js"></script>
```

Next to the other `VinylPlaces`-free aliases near the top of the inline script
(beside `const avgRating = VinylGrouping.avgRating;`), add:

```js
// The places behind bought_where, fetched once at boot. The rules are in
// static/places.js so they can be tested; this file only does the DOM.
let places = [];
const placeUrlOf = name => VinylPlaces.placeUrl(name, places);

async function loadPlaces(){
  const r = await fetch('/api/places');
  places = VinylPlaces.sortPlaces(await r.json());
}
```

In `loadRecords()`, fetch both so one call refreshes everything a rename
touched — replace its body's fetch line with:

```js
  const [r] = await Promise.all([fetch('/api/records'), loadPlaces()]);
```

- [ ] **Step 2: Replace the field markup**

Replace the `#fWhere` line (currently
`<div class="field"><i class="ti ti-map-pin"></i><input id="fWhere" list="whereList" ...></div>`
and the `<datalist id="whereList"></datalist>` below it) with:

```html
                <div class="where-pick">
                  <button type="button" class="where-btn" id="fWhereBtn" onclick="toggleWherePanel()">
                    <i class="ti ti-map-pin"></i>
                    <span id="fWhereLabel" class="ph">store / city</span>
                    <i class="ti ti-chevron-down where-caret"></i>
                  </button>
                  <!-- Still an input with this id: formValues(), the draft
                       snapshot and editRecord all read #fWhere.value, and
                       keeping it means the save payload is unchanged. -->
                  <input type="hidden" id="fWhere">
                  <div class="where-panel" id="wherePanel" hidden></div>
                </div>
```

- [ ] **Step 3: Add the CSS**

Beside the other form-field styles in the `<style>` block:

```css
.where-pick{position:relative}
.where-btn{display:flex;align-items:center;gap:8px;width:100%;padding:10px 12px;
  background:var(--input-bg,transparent);border:1px solid var(--border);
  border-radius:8px;color:var(--text);font:inherit;text-align:left;cursor:pointer}
.where-btn .ph{color:var(--label)}
.where-btn .where-caret{margin-left:auto;opacity:.6}
.where-panel{margin-top:6px;border:1px solid var(--border);border-radius:8px;
  background:var(--card);max-height:260px;overflow-y:auto}
.where-row{display:flex;align-items:center;gap:4px;
  border-bottom:1px solid var(--border)}
.where-row:hover{background:var(--hover,rgba(127,127,127,.08))}
.where-row.sel{font-weight:600}
/* the row is the container; this button is the choosing half of it, so the ✎
   beside it stays its own target */
.where-pick-btn{display:flex;align-items:center;gap:8px;flex:1;min-width:0;
  padding:9px 12px;background:none;border:0;color:var(--text);font:inherit;
  text-align:left;cursor:pointer}
.where-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.where-has-link{opacity:.5;font-size:12px}
.where-edit{flex:0 0 auto;padding:8px 10px;background:none;border:0;
  color:var(--label);cursor:pointer}
.where-edit:hover{color:var(--text)}
.where-new{border-bottom:0}
.where-new .where-pick-btn{color:var(--accent,#F5C518);font-weight:600}
.where-form{padding:10px 12px;display:flex;flex-direction:column;gap:8px}
.where-form input{padding:8px 10px;border:1px solid var(--border);border-radius:6px;
  background:transparent;color:var(--text);font:inherit}
.where-form-row{display:flex;gap:8px;align-items:center}
.where-err{color:var(--ev-liked,#E05A5A);font-size:12px}
.where-hint{color:var(--label);font-size:12px}
```

Use whatever variable names the surrounding CSS actually uses — check the
`:root` block at the top of the file (`--border`, `--label`, `--card`, `--text`
and `--accent` all exist there; the fallbacks above cover the rest).

- [ ] **Step 4: Replace `populateWhereList` with the panel**

Delete `populateWhereList` and put this in its place (keeping the existing
`// ── bought at ──` comment header):

```js
// The panel is a chooser, not a text field: two thirds of the records were
// bought somewhere already on the list, and a typo in the old free-text input
// silently invented a place that then had no link and its own crate.
let whereEditingId = null;   // the place the inline form is editing, or null for a new one

function setWhere(name){
  const v = (name || '').trim();
  document.getElementById('fWhere').value = v;
  syncWhereLabel();
}

function syncWhereLabel(){
  const v = document.getElementById('fWhere').value.trim();
  const label = document.getElementById('fWhereLabel');
  label.textContent = v || 'store / city';
  label.classList.toggle('ph', !v);
}

function toggleWherePanel(){
  const panel = document.getElementById('wherePanel');
  if (panel.hidden) { whereEditingId = null; renderWherePanel(); panel.hidden = false; }
  else panel.hidden = true;
}

function renderWherePanel(){
  const chosen = document.getElementById('fWhere').value.trim();
  document.getElementById('wherePanel').innerHTML =
    places.map(p => `<div class="where-row${p.name === chosen ? ' sel' : ''}">
      <button type="button" class="where-pick-btn" onclick="pickWhere(${p.id})">
        <span class="where-name">${esc(p.name)}</span>
        ${p.url ? '<span class="where-has-link"><i class="ti ti-link"></i></span>' : ''}
      </button>
      ${authed ? `<button type="button" class="where-edit" title="edit this location"
              onclick="openWhereForm(${p.id})"><i class="ti ti-pencil"></i></button>` : ''}
    </div>`).join('')
    + (authed ? `<div class="where-row where-new">
        <button type="button" class="where-pick-btn" onclick="openWhereForm(null)">
          <i class="ti ti-plus"></i><span class="where-name">add a new location</span>
        </button>
      </div>` : '');
}

// Takes the id, not the name: `esc` does not escape apostrophes, so a place
// called "Pepe's Shop" interpolated into an onclick string would break the
// handler. An id is a number and is always safe there.
function pickWhere(id){
  const p = places.find(x => x.id === id);
  if (!p) return;
  setWhere(p.name);
  document.getElementById('wherePanel').hidden = true;
}

// name + link, for a new place or the one being edited. Rendered into the same
// panel rather than a second overlay: the form is already inside a modal, and
// stacking one on another traps the escape key.
function openWhereForm(id){
  whereEditingId = id;
  const p = id == null ? { name: '', url: '' } : places.find(x => x.id === id) || { name:'', url:'' };
  document.getElementById('wherePanel').innerHTML = `<div class="where-form">
    <input id="fWhereName" placeholder="name" value="${esc(p.name)}" autocomplete="off">
    <input id="fWhereUrl" placeholder="link (optional)" value="${esc(p.url)}" autocomplete="off">
    <div class="where-err" id="fWhereErr" hidden></div>
    <div class="where-hint" id="fWhereHint" hidden></div>
    <div class="where-form-row">
      <button type="button" class="btn btn-sm" onclick="saveWhereForm()">save</button>
      <button type="button" class="btn btn-ghost btn-sm" onclick="renderWherePanel()">cancel</button>
    </div>
  </div>`;
  document.getElementById('fWhereName').focus();
  whereFormHint();
  document.getElementById('fWhereName').addEventListener('input', whereFormHint);
}

// Says up front that this rename will collapse two places into one — the
// server will do it either way, so it must not be a surprise.
function whereFormHint(){
  const hint = document.getElementById('fWhereHint');
  const target = VinylPlaces.mergeTarget(
    document.getElementById('fWhereName').value, places, whereEditingId);
  hint.hidden = !target;
  if (target) hint.textContent = `saves into "${target.name}" — the two become one location`;
}

async function saveWhereForm(){
  const name = document.getElementById('fWhereName').value.trim();
  const rawUrl = document.getElementById('fWhereUrl').value;
  const err = document.getElementById('fWhereErr');
  const show = msg => { err.textContent = msg; err.hidden = !msg; };

  if (!VinylPlaces.validName(name)) return show('a location needs a name');
  const url = VinylPlaces.normalizeUrl(rawUrl);
  if (url === null) return show('a link has to start with http:// or https://');
  show('');

  const editing = whereEditingId != null;
  const was = editing ? (places.find(p => p.id === whereEditingId) || {}).name : '';
  const r = await fetch(editing ? `/api/places/${whereEditingId}` : '/api/places', {
    method: editing ? 'PUT' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, url }),
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    return show(body.error || 'could not save this location');
  }

  await loadPlaces();
  // A rename rewrote records, so the collection on screen is stale. Also move
  // this form's own selection if it was pointing at the old name.
  if (editing) {
    if (document.getElementById('fWhere').value.trim() === (was || '').trim()) setWhere(name);
    await loadRecords();
  } else {
    setWhere(name);
  }
  renderWherePanel();
  document.getElementById('wherePanel').hidden = !editing;
}
```

`esc` (`templates/index.html:7081`) is the file's only escaping helper. It
escapes `&`, `<`, `>` and `"`, which is enough for an attribute value in double
quotes and **not** enough inside a quoted JS string in an `onclick` — which is
why `pickWhere` and `openWhereForm` take ids rather than names.

- [ ] **Step 5: Fix the three call sites**

`applyDraft` (~line 5346) — after the `set(...)` lines that include `'fWhere'`,
add:

```js
  syncWhereLabel();
```

The `openAdd` reset (~line 5386) — drop `'fWhere'` from the list and set it
through the helper so the label clears too:

```js
  ['fArtist','fAlbum','fYear','fCountry'].forEach(id=>document.getElementById(id).value='');
  setWhere('');
```

`editRecord` (~line 5470) — replace the direct assignment and the
`populateWhereList()` call above it:

```js
  setWhere(r.bought_where||'');
```

Then `grep -n "populateWhereList" templates/index.html` and remove every
remaining call (there were two: in `openAdd` and in `editRecord`). The panel
renders from `places`, which `loadRecords()` now refreshes, so there is nothing
left to populate.

- [ ] **Step 6: Verify by hand in the running app**

Run: `python app.py` — **restarted**, not reloaded in the browser: Flask caches
`index.html`, so without a restart you debug a page the browser never got. Open
the app, log in, and check:
1. Add a record → "Bought at" shows the existing places, each with a ✎; `+ add a new location` sits at the bottom.
2. Add a new location with a scheme-less link → it is selected, and re-opening the panel shows it with a link icon.
3. A link of `javascript:alert(1)` → the inline error appears and nothing is saved.
4. Edit an existing location's name to another location's name → the merge hint appears before saving, and after saving the grid's crates show one place, not two.
5. Log out → the panel still chooses, and no ✎ or `+` row is rendered.

- [ ] **Step 7: Run the suites**

Run: `python -m pytest -q --ignore=tests/test_boot.py` and `node --test tests/`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add templates/index.html
git commit -m "feat: pick a bought-at location from the ones you already have"
```

---

### Task 7: The link on the read surfaces

**Files:**
- Modify: `templates/index.html` — `dmInfoTabHTML`'s "Bought at" cell (~line 4164), the crate header (~line 3489)
- Modify: `tests/test_grouping.js`

**Interfaces:**
- Consumes: `placeUrlOf(name)` and `places` from Task 6.
- Produces: `placeLinkHTML(name, fallback)`.

- [ ] **Step 1: Write the failing test**

The crate rules must stay untouched by the header change. Append to
`tests/test_grouping.js` (match its existing import and helper style):

```js
// ── bucketOf: bought at ─────────────────────────────────────────────────────

test('a place crate is keyed by the place, trimmed, whatever link it carries', () => {
  const bucket = bucketOf(rec({ bought_where: '  Tracks Rio ' }), 'bought_where');
  assert.strictEqual(bucket.id, 'tracks rio');
  assert.strictEqual(bucket.label, 'Tracks Rio');
  assert.strictEqual(bucket.unknown, false);
});

test('a record with no place lands in the unknown crate', () => {
  const bucket = bucketOf(rec({ bought_where: '   ' }), 'bought_where');
  assert.strictEqual(bucket.id, 'noplace');
  assert.strictEqual(bucket.unknown, true);
});
```

`bucketOf` is destructured at `tests/test_grouping.js:12` and the `rec()` helper
is defined just below it; the group key is `bucketOf`'s second argument.

- [ ] **Step 2: Run the test**

Run: `node --test tests/test_grouping.js`
Expected: PASS. `bucketOf` already trims (`static/grouping.js:143`), so this is
a regression guard and passing immediately is the right outcome — it is here to
fail if the header work in Step 5 ever reaches into the bucket rules. If it
fails now, the test is wrong; fix the test, not `grouping.js`.

- [ ] **Step 3: Add the link helper**

Next to `placeUrlOf` in the inline script:

```js
// A place name as a link when its place has one, and as plain text when it
// does not — so a place with no link looks exactly as it did before this
// feature. rel=noopener because target=_blank without it hands the opened
// page a handle on this one.
function placeLinkHTML(name, fallback = '—'){
  const v = (name || '').trim();
  if (!v) return fallback;
  const url = placeUrlOf(v);
  return url
    ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(v)} <i class="ti ti-external-link"></i></a>`
    : esc(v);
}
```

- [ ] **Step 4: Use it in the drawer**

In `dmInfoTabHTML`, replace the "Bought at" cell:

```js
      <div class="dm-mcell"><label><i class="ti ti-map-pin"></i>Bought at</label><span>${placeLinkHTML(r.bought_where)}</span></div>
```

- [ ] **Step 5: Add the crate header link**

In the crate-rendering block, after the `.crate-head` button's closing `</button>`
and still inside the `<section>`:

```js
      ${groupBy === 'bought_where' && !crate.unknown && placeUrlOf(crate.label)
        ? `<a class="crate-link" href="${esc(placeUrlOf(crate.label))}"
              target="_blank" rel="noopener noreferrer" title="open ${esc(crate.label)}"
              ><i class="ti ti-external-link"></i></a>` : ''}
```

It is a sibling of the header button, not a child: `.crate-head` is the collapse
target, and an anchor inside it would swallow that click.

With the CSS:

```css
.crate{position:relative}
.crate-link{position:absolute;top:0;right:0;display:flex;align-items:center;
  padding:12px 14px;color:var(--label);text-decoration:none}
.crate-link:hover{color:var(--text)}
```

Check whether `.crate` already sets `position` before adding it, and whether the
existing `.crate-count` sits where this would overlap it — if it does, put the
link before the count inside the section's flow instead of absolutely.

- [ ] **Step 6: Verify by hand**

Run: `python app.py` (restart it — Flask caches the template) and check:
1. A record bought at a place with a link → the drawer's "Bought at" is a link that opens in a new tab; one without a link is plain text; a record with no place still shows `—`.
2. Group by "Bought at" → crates for places with links show the icon, collapsing still works when clicking the header, and the icon opens the link without collapsing.

- [ ] **Step 7: Commit**

```bash
git add templates/index.html tests/test_grouping.js
git commit -m "feat: a place's link opens from the drawer and its crate"
```

---

### Task 8: The manual verification doc

**Files:**
- Create: `docs/places-manual-verification.md`

- [ ] **Step 1: Write it**

Follow the shape of `docs/tracklist-manual-verification.md` (read it first),
covering: the picker's list and `+ add a new location`; a scheme-less link
getting `https://`; a `javascript:` link refused inline; the ✎ hidden when
logged out; a rename rewriting the crates; a rename-merge collapsing two places
with the typed casing winning; the drawer link and the plain-text fallback; the
crate icon not stealing the collapse click; and a CSV export/import round trip
that keeps the links, plus importing a pre-feature CSV.

- [ ] **Step 2: Commit**

```bash
git add docs/places-manual-verification.md
git commit -m "docs: what to check by hand for bought-at places"
```

---

## Notes for the executor

- The user commits to this repo in parallel; `git log` before any checkout or reset, and never rewrite history you did not create in this session.
- `tests/test_boot.py` hangs on this machine after its tests pass. Use `--ignore=tests/test_boot.py` with pytest and run JS files through `node --test` directly.
- Line numbers in this plan are from the tree at `d73199b` and will drift. Locate code by the surrounding text quoted here, not by line number.
- Flask caches `templates/index.html`: restart `python app.py` after every edit to it, or the by-hand checks in Tasks 6 and 7 test a page the browser never received.
- For a scripted UI check rather than a by-hand one, the working Playwright setup on this machine is the Python driver with the three libs unpacked onto `LD_LIBRARY_PATH` — see the project memory note before reinventing it.
