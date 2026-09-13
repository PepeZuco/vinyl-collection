# Pictures on Notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a note carry photos, added by upload or device camera, reusing the record cover's picker, camera overlay and resize path.

**Architecture:** Image bytes live in a new `NoteImage` table keyed by their own content hash and are served from `/api/note-images/<id>`; the `notes` JSON carries only ids. This is forced by payload size: `notes` is not deferred in the record-list query and six client-side consumers read it straight off `/api/records`, so inlining base64 there would rebuild the 45MB response the cover architecture exists to prevent.

**Tech Stack:** Flask + Flask-SQLAlchemy (SQLite in dev, `DATABASE_URL` in prod), vanilla JS in `templates/index.html` with pure logic extracted to `static/*.js`, pytest, `node --test` invoked from pytest shims.

**Spec:** `docs/superpowers/specs/2026-08-30-note-pictures-design.md`

## Global Constraints

- Image id is `hashlib.sha256(data_uri.encode("utf-8")).hexdigest()[:32]` — 32 hex chars. Never `_cover_hash` (that is `[:16]` and is a cache buster, not a key).
- Stored image `data` is a full base64 data URI, e.g. `data:image/jpeg;base64,…` — the same shape as `Record.cover_data`.
- Upload cap: `2 * 1024 * 1024` bytes measured on the UTF-8 encoded data URI. Over → HTTP 413.
- Boot-sweep grace window: `6 * 3600` seconds.
- Timestamps use the app's existing shape: `datetime.now().strftime("%Y-%m-%dT%H:%M:%S")`.
- A note is valid with text **or** at least one image. Never require text unconditionally.
- A missing `images` key on a note reads as `[]` everywhere. No backfill, no migration.
- Never load `NoteImage.data` in a query that only needs ids — the file is deliberately careful about this (see `defer(Record.cover_data)` at `app.py:236`).
- Run the Python suite with `python -m pytest` from the repo root. Run one JS file with `node --test tests/<file>.js`.

---

### Task 1: `NoteImage` model and its two endpoints

**Files:**
- Modify: `app.py` (imports at `:1`, helpers near `_cover_hash` at `:48`, model after `Record` at `:117`, routes near `record_cover` at `:318`)
- Test: `tests/test_note_images.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `NoteImage` model with columns `id: str(32)`, `data: Text`, `created: str(50)`
  - `_note_image_id(data: str) -> str` — 32-char content hash
  - `_decode_data_uri(value: str) -> tuple[bytes, str] | None` — renamed from `_decode_cover`
  - `_NOTE_IMAGE_MAX_BYTES: int`
  - `POST /api/note-images` → `201 {"id": "<32 hex>"}`
  - `GET /api/note-images/<image_id>` → image bytes

- [ ] **Step 1: Write the failing tests**

Create `tests/test_note_images.py`. The `vinyl_app`/`client` fixtures are copied from `tests/test_cover_endpoint.py:28-70` because that module scopes them to itself; copying is the established pattern in this suite, not duplication to factor out.

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_note_images.py -v`
Expected: FAIL — `AttributeError: module 'app' has no attribute 'NoteImage'`

- [ ] **Step 3: Rename `_decode_cover` to `_decode_data_uri`**

It was never cover-specific — it decodes any stored data URI, and Task 1 gives it a second caller. No test imports it (verified), so this is a safe rename.

In `app.py:299`, change the definition and its docstring:

```python
def _decode_data_uri(value):
    """(bytes, mimetype) for a stored data URI, or None if there is nothing to serve.

    Shared by covers and note images. Anything that is absent, not a data URI,
    or whose base64 payload is malformed is treated as having nothing to serve
    rather than raising: a broken image is an absent image, not a 500.
    """
```

Update its one existing call site in `record_cover` (`app.py:328`):

```python
    decoded = _decode_data_uri(row[0]) if row else None
```

- [ ] **Step 4: Add the id helper next to `_cover_hash`**

After `_cover_hash` (`app.py:54`):

```python
_NOTE_IMAGE_MAX_BYTES = 2 * 1024 * 1024


def _note_image_id(data):
    """A note image's primary key: the image is its own address.

    Deliberately not _cover_hash. A cover's URL is keyed by a record, so it
    changes meaning when the cover does and needs a ?v= buster. An image id is
    keyed by content, so /api/note-images/<id> can never mean anything else —
    which is what lets the response be immutably cached with no buster, and
    what makes two identical photos collapse to one row.
    """
    return hashlib.sha256((data or "").encode("utf-8")).hexdigest()[:32]
```

- [ ] **Step 5: Add the model**

After the `Record` class, before `ScanSpend` (`app.py:117`):

```python
# One row per distinct note image, addressed by its own content hash.
#
# The bytes are here rather than in Record.notes because notes is NOT deferred
# in the record-list query and six client-side consumers read it straight off
# /api/records. Base64 in that column would rebuild the 45MB response the cover
# arrangement above exists to prevent.
class NoteImage(db.Model):
    id      = db.Column(db.String(32), primary_key=True)  # _note_image_id(data)
    data    = db.Column(db.Text)      # base64 data URI, same shape as cover_data
    created = db.Column(db.String(50))  # a stamp — the sweep's grace window reads it
```

No entry in the auto-migration block: `db.create_all()` creates missing *tables* on its own. That block exists only because it will not add missing *columns* (see its comment at `app.py:139`).

- [ ] **Step 6: Add the two routes**

After `record_cover`, before `delete_record` (`app.py:336`):

```python
@app.route("/api/note-images", methods=["POST"])
@require_auth
def create_note_image():
    """Store one note image and return its id.

    Idempotent by construction: the id is the content hash, so re-uploading the
    same photo returns the id that already exists and writes nothing.
    """
    d = request.get_json(silent=True) or {}
    data = d.get("data", "")
    if not isinstance(data, str) or not data.startswith("data:"):
        return jsonify({"error": "Not an image"}), 400
    # Measured encoded, because that is what gets stored.
    if len(data.encode("utf-8")) > _NOTE_IMAGE_MAX_BYTES:
        return jsonify({"error": "Image too large"}), 413
    if _decode_data_uri(data) is None:
        return jsonify({"error": "Not an image"}), 400
    image_id = _note_image_id(data)
    if db.session.get(NoteImage, image_id) is None:
        db.session.add(NoteImage(
            id=image_id, data=data,
            created=datetime.now().strftime("%Y-%m-%dT%H:%M:%S")))
        db.session.commit()
    return jsonify({"id": image_id}), 201


@app.route("/api/note-images/<image_id>")
def note_image(image_id):
    """Serve one note image.

    Immutable with no cache buster, unlike record_cover: the id IS the content
    hash, so this URL's bytes can never change. A different image is a
    different URL.
    """
    row = db.session.query(NoteImage.data).filter(NoteImage.id == image_id).first()
    decoded = _decode_data_uri(row[0]) if row else None
    if decoded is None:
        return jsonify({"error": "No image"}), 404
    data, mime = decoded
    resp = app.response_class(data, mimetype=mime)
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    resp.set_etag(image_id)
    return resp.make_conditional(request)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/test_note_images.py -v`
Expected: PASS, 9 tests

- [ ] **Step 8: Run the whole suite to prove the rename broke nothing**

Run: `python -m pytest`
Expected: PASS — in particular `tests/test_cover_endpoint.py`

- [ ] **Step 9: Commit**

```bash
git add app.py tests/test_note_images.py
git commit -m "feat: store and serve note images by content hash"
```

---

### Task 2: Reaping unreferenced images

**Files:**
- Modify: `app.py` (helpers after `_note_image_id`, `create_record` at `:255`, `update_record` at `:277`, boot block at `:137-190`)
- Test: `tests/test_note_images.py` (extend)

**Interfaces:**
- Consumes: `NoteImage`, `_note_image_id` from Task 1.
- Produces:
  - `_note_image_ids(notes_json: str) -> set[str]`
  - `_reap_note_images(dropped_ids: set[str]) -> int` — deletes ids no note references, returns how many
  - `_sweep_note_images() -> int`
  - `_NOTE_IMAGE_GRACE_SECONDS: int`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_note_images.py`:

```python
def _note(text, images=None):
    import json
    return json.dumps([{"date": "2026-01-01", "text": text, "images": images or []}])


def test_dropping_an_image_from_a_note_deletes_it(client, vinyl_app):
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    rid = client.post("/api/records", json={"artist": "A", "notes": _note("has one", [iid])}).get_json()["id"]

    client.put(f"/api/records/{rid}", json={"notes": _note("now none", [])})

    with vinyl_app.app.app_context():
        assert vinyl_app.NoteImage.query.count() == 0


def test_an_image_another_record_still_uses_survives(client, vinyl_app):
    """Content-hash ids mean two records photographing the same thing share a row.

    Deleting on the first record's say-so would blank the second — this guard is
    load-bearing, not defensive.
    """
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    keeper = client.post("/api/records", json={"artist": "Keeper", "notes": _note("mine too", [iid])}).get_json()["id"]
    dropper = client.post("/api/records", json={"artist": "Dropper", "notes": _note("mine", [iid])}).get_json()["id"]

    client.put(f"/api/records/{dropper}", json={"notes": _note("not any more", [])})

    with vinyl_app.app.app_context():
        assert vinyl_app.NoteImage.query.count() == 1
    assert client.get(f"/api/note-images/{iid}").status_code == 200


def test_deleting_the_whole_note_deletes_its_image(client, vinyl_app):
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    rid = client.post("/api/records", json={"artist": "A", "notes": _note("bye", [iid])}).get_json()["id"]

    client.put(f"/api/records/{rid}", json={"notes": ""})

    with vinyl_app.app.app_context():
        assert vinyl_app.NoteImage.query.count() == 0


def test_a_save_that_does_not_mention_notes_reaps_nothing(client, vinyl_app):
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    rid = client.post("/api/records", json={"artist": "A", "notes": _note("keep", [iid])}).get_json()["id"]

    client.put(f"/api/records/{rid}", json={"my_rating": 5})

    with vinyl_app.app.app_context():
        assert vinyl_app.NoteImage.query.count() == 1


def test_the_sweep_deletes_an_orphan_past_the_grace_window(client, vinyl_app):
    """A photo uploaded into a form the user then abandoned."""
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    with vinyl_app.app.app_context():
        vinyl_app.db.session.get(vinyl_app.NoteImage, iid).created = "2020-01-01T00:00:00"
        vinyl_app.db.session.commit()
        assert vinyl_app._sweep_note_images() == 1
        assert vinyl_app.NoteImage.query.count() == 0


def test_the_sweep_spares_an_orphan_inside_the_grace_window(client, vinyl_app):
    """The window is what stops the sweep eating a form that is open right now."""
    client.post("/api/note-images", json={"data": JPEG_1PX})
    with vinyl_app.app.app_context():
        assert vinyl_app._sweep_note_images() == 0
        assert vinyl_app.NoteImage.query.count() == 1


def test_the_sweep_spares_a_referenced_image_however_old(client, vinyl_app):
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    client.post("/api/records", json={"artist": "A", "notes": _note("keep", [iid])})
    with vinyl_app.app.app_context():
        vinyl_app.db.session.get(vinyl_app.NoteImage, iid).created = "2020-01-01T00:00:00"
        vinyl_app.db.session.commit()
        assert vinyl_app._sweep_note_images() == 0


def test_the_record_list_never_carries_image_bytes(client):
    """The regression guard the whole design exists for."""
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    client.post("/api/records", json={"artist": "A", "notes": _note("look", [iid])})

    body = client.get("/api/records").get_data(as_text=True)
    assert "base64" not in body
    assert iid in body  # the id travels; the bytes do not


def test_ids_are_read_out_of_notes_json_forgivingly(vinyl_app):
    assert vinyl_app._note_image_ids("") == set()
    assert vinyl_app._note_image_ids("not json") == set()
    assert vinyl_app._note_image_ids('"a legacy string note"') == set()
    assert vinyl_app._note_image_ids('[{"date":"d","text":"t"}]') == set()
    assert vinyl_app._note_image_ids('[{"images":["a","b"]},{"images":["b","c"]}]') == {"a", "b", "c"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_note_images.py -v -k "reap or sweep or drop or survive or bytes or forgiv or mention or whole_note"`
Expected: FAIL — `AttributeError: module 'app' has no attribute '_sweep_note_images'`

- [ ] **Step 3: Add the reap helpers**

After `_note_image_id` in `app.py`:

```python
_NOTE_IMAGE_GRACE_SECONDS = 6 * 3600


def _note_image_ids(notes_json):
    """Every image id a notes column refers to.

    Forgiving on purpose: the column also holds legacy plain strings and notes
    written before images existed, and neither is an error.
    """
    try:
        parsed = json.loads(notes_json or "")
    except (TypeError, ValueError):
        return set()
    if not isinstance(parsed, list):
        return set()
    found = set()
    for note in parsed:
        if isinstance(note, dict):
            for image_id in note.get("images") or []:
                if isinstance(image_id, str) and image_id:
                    found.add(image_id)
    return found


def _reap_note_images(dropped_ids):
    """Delete images from `dropped_ids` that no note refers to any more.

    Call AFTER the record's own notes are committed, so the LIKE below sees the
    new truth and the record cannot be its own stale reference.

    The check is per-id rather than a blanket delete because content-hash ids
    dedupe: an image dropped from one record may still be the same photo on
    another, and deleting it would blank that one.
    """
    reaped = 0
    for image_id in dropped_ids:
        still_used = (db.session.query(Record.id)
                      .filter(Record.notes.like(f"%{image_id}%")).first())
        if still_used is None:
            NoteImage.query.filter(NoteImage.id == image_id).delete(
                synchronize_session=False)
            reaped += 1
    if reaped:
        db.session.commit()
    return reaped


def _sweep_note_images():
    """Delete images no note anywhere refers to, past the grace window.

    Catches photos uploaded into a form that was never saved. The window is
    what keeps it from deleting an image belonging to a form open right now.

    Queries ids rather than rows: loading every image's blob to decide what to
    delete would be the same mistake defer(Record.cover_data) exists to avoid.
    """
    referenced = set()
    for (notes,) in db.session.query(Record.notes).all():
        referenced |= _note_image_ids(notes)
    cutoff = (datetime.now() - timedelta(seconds=_NOTE_IMAGE_GRACE_SECONDS)
              ).strftime("%Y-%m-%dT%H:%M:%S")
    candidates = db.session.query(NoteImage.id).filter(NoteImage.created < cutoff).all()
    stale = [image_id for (image_id,) in candidates if image_id not in referenced]
    if stale:
        NoteImage.query.filter(NoteImage.id.in_(stale)).delete(synchronize_session=False)
        db.session.commit()
    return len(stale)
```

Add `timedelta` to the datetime import at `app.py:9`:

```python
from datetime import datetime, timedelta
```

- [ ] **Step 4: Reap on save**

In `update_record` (`app.py:277`), capture the ids before anything is assigned. Add as the first statement after `d = request.get_json(...)`:

```python
    # Read before the assignment below overwrites it: what the record used to
    # point at is the only way to know what it just stopped pointing at.
    images_before = _note_image_ids(r.notes) if "notes" in d else set()
```

Then replace the commit-and-return at the end of `update_record`:

```python
    db.session.commit()
    # After the commit, so the reap's "is anyone still using this" query sees
    # the notes that were just written rather than the ones being replaced.
    if images_before:
        _reap_note_images(images_before - _note_image_ids(r.notes))
    return jsonify(r.to_dict())
```

`create_record` needs no reap — a new record drops nothing.

- [ ] **Step 5: Sweep at boot**

At the end of the `with app.app_context():` block in `app.py` (after the `cover_hash` backfill, around `:190`):

```python
    # Photos uploaded into a form that was then abandoned have nothing pointing
    # at them and nothing that will ever call the save-time reap. This is the
    # only thing that collects them.
    _sweep_note_images()
```

Note this runs *below* the helper definitions in file order only if the helpers are defined above the `with app.app_context():` block — they are, since they sit next to `_note_image_id` near the top.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_note_images.py -v`
Expected: PASS, 18 tests

- [ ] **Step 7: Run the whole suite**

Run: `python -m pytest`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add app.py tests/test_note_images.py
git commit -m "feat: reap note images no note refers to"
```

---

### Task 3: CSV export and import

**Files:**
- Modify: `app.py` (`export_csv` at `:527`, `_record_mapping` at `:556`, `import_records_from_csv_rows` at `:584`)
- Test: `tests/test_note_images.py` (extend)

**Interfaces:**
- Consumes: `NoteImage`, `_note_image_ids`, `_note_image_id` from Tasks 1-2.
- Produces: a `note_images` CSV column holding `{"<id>": "<data uri>"}` JSON.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_note_images.py`:

```python
import csv
import io
import json


def _exported_rows(client):
    body = client.get("/api/export").get_data(as_text=True)
    return list(csv.DictReader(io.StringIO(body)))


def test_export_carries_the_images_a_row_refers_to(client, vinyl_app):
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    client.post("/api/records", json={"artist": "A", "notes": _note("shot", [iid])})

    row = _exported_rows(client)[0]
    assert json.loads(row["note_images"]) == {iid: JPEG_1PX}


def test_export_leaves_the_column_empty_for_a_row_with_no_images(client):
    client.post("/api/records", json={"artist": "A", "notes": _note("words only")})
    assert _exported_rows(client)[0]["note_images"] == ""


def test_a_full_backup_and_restore_keeps_note_images(client, vinyl_app):
    iid = client.post("/api/note-images", json={"data": JPEG_1PX}).get_json()["id"]
    client.post("/api/records", json={"artist": "A", "notes": _note("shot", [iid])})
    backup = client.get("/api/export").get_data(as_text=True)

    with vinyl_app.app.app_context():
        vinyl_app.Record.query.delete()
        vinyl_app.NoteImage.query.delete()
        vinyl_app.db.session.commit()
        vinyl_app.import_records_from_csv_rows(csv.DictReader(io.StringIO(backup)))
        assert vinyl_app.NoteImage.query.count() == 1

    assert client.get(f"/api/note-images/{iid}").status_code == 200


def test_a_restore_drops_images_the_backup_does_not_carry(client, vinyl_app):
    """Import replaces the whole collection; an image whose note is gone must go too."""
    client.post("/api/note-images", json={"data": JPEG_1PX})
    with vinyl_app.app.app_context():
        vinyl_app.import_records_from_csv_rows([{"artist": "Fresh"}])
        assert vinyl_app.NoteImage.query.count() == 0


def test_a_csv_written_before_this_feature_imports_cleanly(vinyl_app):
    with vinyl_app.app.app_context():
        vinyl_app.import_records_from_csv_rows([{"artist": "Old", "notes": "a plain note"}])
        assert vinyl_app.Record.query.count() == 1
        assert vinyl_app.NoteImage.query.count() == 0


def test_a_malformed_note_images_value_imports_as_no_images(vinyl_app):
    with vinyl_app.app.app_context():
        vinyl_app.import_records_from_csv_rows([{"artist": "A", "note_images": "{oops"}])
        assert vinyl_app.Record.query.count() == 1
        assert vinyl_app.NoteImage.query.count() == 0


def test_an_image_shared_by_two_rows_is_inserted_once(vinyl_app):
    """Dedupe means a backup can name the same id on many rows."""
    image_id = vinyl_app._note_image_id(JPEG_1PX)
    payload = json.dumps({image_id: JPEG_1PX})
    notes = json.dumps([{"date": "2026-01-01", "text": "t", "images": [image_id]}])
    with vinyl_app.app.app_context():
        vinyl_app.import_records_from_csv_rows([
            {"artist": "A", "notes": notes, "note_images": payload},
            {"artist": "B", "notes": notes, "note_images": payload},
        ])
        assert vinyl_app.NoteImage.query.count() == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_note_images.py -v -k "export or restore or backup or import or shared_by_two or malformed_note_images"`
Expected: FAIL — `KeyError: 'note_images'`

- [ ] **Step 3: Add the column to the export**

In `export_csv` (`app.py:530`), append to `cols`:

```python
    cols = ["id","artist","album_name","year","genre","bought_date","bought_where",
            "bought_by","condition","my_rating","wife_rating","have_it","play_count","play_dates","cleaned_dates","cover_image_base64","notes","country","note_images"]
```

Inside `generate()`'s loop, after the existing `d["cover_image_base64"] = ...` line:

```python
            # Looked up per row rather than preloaded: this generator streams to
            # keep a whole-collection export off the heap, and a dict of every
            # image would put it straight back.
            image_ids = sorted(_note_image_ids(r.notes))
            images = dict(db.session.query(NoteImage.id, NoteImage.data)
                          .filter(NoteImage.id.in_(image_ids)).all()) if image_ids else {}
            d["note_images"] = json.dumps(images) if images else ""
```

- [ ] **Step 4: Add the import side**

Add a parse helper next to `_record_mapping` (`app.py:556`):

```python
def _row_note_images(row):
    """{id: data uri} for one CSV row, or {} if the column is absent or broken.

    A CSV written before this feature simply has no column, which is not an
    error — and neither is a value that will not parse.
    """
    try:
        parsed = json.loads(row.get("note_images", "") or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {k: v for k, v in parsed.items()
            if isinstance(k, str) and isinstance(v, str) and v.startswith("data:")}
```

Then in `import_records_from_csv_rows`, replace the body's setup and loop. The whole function becomes:

```python
def import_records_from_csv_rows(rows):
    """Replace the whole collection from an iterable of CSV row dicts.

    Inserted in batches to bound memory, but still ONE transaction: the delete
    and every batch commit together at the end. A failure part-way therefore
    rolls back to the existing collection rather than leaving it half-replaced
    — this wipes the table first, so a partial import would be data loss.

    Note images are wiped and restored alongside: they are only reachable
    through a note, so any that survived a restore that removed their note
    would be unreachable rows nothing would ever collect.
    """
    Record.query.delete()
    NoteImage.query.delete()
    count = 0
    batch = []
    image_batch = []
    # Only ids, so this stays small however many rows name the same photo.
    seen_images = set()
    stamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    def flush():
        if batch:
            db.session.execute(db.insert(Record), batch)
            batch.clear()
        if image_batch:
            db.session.execute(db.insert(NoteImage), image_batch)
            image_batch.clear()

    for row in rows:
        batch.append(_record_mapping(row))
        for image_id, data in _row_note_images(row).items():
            if image_id not in seen_images:
                seen_images.add(image_id)
                image_batch.append({"id": image_id, "data": data, "created": stamp})
        count += 1
        if len(batch) >= _IMPORT_BATCH_ROWS:
            flush()
    flush()
    db.session.commit()
    return count
```

Check the tail of the existing function before replacing it — keep whatever it already returns and whatever logging it already does.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_note_images.py -v`
Expected: PASS, 25 tests

- [ ] **Step 6: Run the whole suite, especially the import tests**

Run: `python -m pytest tests/test_import.py tests/test_note_images.py -v && python -m pytest`
Expected: PASS

- [ ] **Step 7: Verify the export against a running app, not only the test client**

The new query runs *inside* `generate()`, which Flask consumes after the view
returns. The existing code already depends on the session being alive there —
`r.cover_data` on the next line is a lazy load — so this is the same
requirement, not a new one. But the test client consumes the response inside
the request context and would hide a failure that production shows.

Start the app, hit `/api/export`, and confirm a real file comes back with the
`note_images` column populated:

```bash
curl -s localhost:5000/api/export | head -1 | tr ',' '\n' | tail -1
```

Expected: `note_images`. If this raises "working outside of application
context", wrap the response in `stream_with_context` (import it from `flask`).

- [ ] **Step 8: Commit**

```bash
git add app.py tests/test_note_images.py
git commit -m "feat: carry note images through CSV export and import"
```

---

### Task 4: Extract `static/notes.js`

**Files:**
- Create: `static/notes.js`
- Create: `tests/test_notes.js`
- Create: `tests/test_notes.py`
- Modify: `templates/index.html` (script tags at `:2334`, `parseNotes`/`serializeNotes` at `:3689-3702`)

**Interfaces:**
- Consumes: nothing.
- Produces, on the global `VinylNotes` and via `module.exports`:
  - `parseNotes(raw: string, fallbackDate: string) -> Array<{date, text, images?}>`
  - `serializeNotes(arr: Array) -> string`
  - `noteImageIds(notes: Array) -> string[]`
  - `hasContent(note: object) -> boolean` — text or at least one image. Task 6 calls this one directly.

- [ ] **Step 1: Write the failing test**

Create `tests/test_notes.js`:

```js
// Tests for the notes column's parse/serialize rules.
// Run by tests/test_notes.py so `pytest` stays the single command.
//
// These exist because a note can now be a photo with no words. Every filter in
// this file used to be `n.text && n.text.trim()`, which silently deletes such a
// note on save — the failure is invisible at the call site and destroys the
// user's photo, so the rules moved here where they can be pinned.

const test = require('node:test');
const assert = require('node:assert');

const { parseNotes, serializeNotes, noteImageIds, hasContent } = require('../static/notes.js');

// ── serialize ───────────────────────────────────────────────────────────────

test('a note with text is kept', () => {
  assert.strictEqual(serializeNotes([{ date: 'd', text: 'hello' }]),
                     JSON.stringify([{ date: 'd', text: 'hello' }]));
});

test('a note with a photo and no words is kept', () => {
  const notes = [{ date: 'd', text: '', images: ['a1'] }];
  assert.strictEqual(serializeNotes(notes), JSON.stringify(notes));
});

test('a note with neither words nor photos is dropped', () => {
  assert.strictEqual(serializeNotes([{ date: 'd', text: '   ', images: [] }]), '');
});

test('an empty list serializes to the empty string, not "[]"', () => {
  assert.strictEqual(serializeNotes([]), '');
});

test('a whitespace-only note is dropped from among real ones', () => {
  const out = JSON.parse(serializeNotes([
    { date: 'a', text: 'real' },
    { date: 'b', text: '  ' },
    { date: 'c', text: '', images: ['x'] },
  ]));
  assert.deepStrictEqual(out.map(n => n.date), ['a', 'c']);
});

// ── parse ───────────────────────────────────────────────────────────────────

test('a note with no images key parses without one', () => {
  const out = parseNotes(JSON.stringify([{ date: 'd', text: 't' }]), '2026-01-01');
  assert.deepStrictEqual(out, [{ date: 'd', text: 't' }]);
});

test('images survive a round trip', () => {
  const notes = [{ date: 'd', text: 't', images: ['a1', 'b2'] }];
  assert.deepStrictEqual(parseNotes(serializeNotes(notes), '2026-01-01'), notes);
});

test('a legacy plain-string note still migrates onto the fallback date', () => {
  assert.deepStrictEqual(parseNotes('bought at the fair', '2026-01-01'),
                         [{ date: '2026-01-01', text: 'bought at the fair' }]);
});

test('an empty column parses to nothing', () => {
  assert.deepStrictEqual(parseNotes('', '2026-01-01'), []);
});

// ── hasContent ──────────────────────────────────────────────────────────────
// Public because the detail history filters on it directly, so it is pinned
// directly rather than only through serializeNotes.

test('a note counts as content when it has words', () => {
  assert.strictEqual(hasContent({ date: 'd', text: 'hello' }), true);
});

test('a note counts as content when it has only a photo', () => {
  assert.strictEqual(hasContent({ date: 'd', text: '', images: ['a1'] }), true);
});

test('a note with neither is not content', () => {
  assert.strictEqual(hasContent({ date: 'd', text: '  ', images: [] }), false);
  assert.strictEqual(hasContent(null), false);
});

// ── ids ─────────────────────────────────────────────────────────────────────

test('every id across every note comes back once', () => {
  assert.deepStrictEqual(
    noteImageIds([{ images: ['a', 'b'] }, { text: 'none' }, { images: ['b', 'c'] }]),
    ['a', 'b', 'c']);
});

test('a note list with no images has no ids', () => {
  assert.deepStrictEqual(noteImageIds([{ date: 'd', text: 't' }]), []);
});
```

Create `tests/test_notes.py`:

```python
"""Run the JavaScript notes rules under pytest.

Mirrors tests/test_cover_form.py: the rules are pure functions in
static/notes.js, so they need a JS runtime, and shelling out to node's test
runner keeps `pytest` as the one command.
"""

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_notes_js():
    result = subprocess.run(
        ["node", "--test", "tests/test_notes.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node --test tests/test_notes.js`
Expected: FAIL — `Cannot find module '../static/notes.js'`

- [ ] **Step 3: Write `static/notes.js`**

```js
/* The notes column's parse/serialize rules.
 *
 * Notes are stored as JSON: [{date, text, images?}]. A note is valid with text
 * OR at least one image — a photo with no words is a note, and the filter that
 * used to demand text would silently delete it on save.
 *
 * `images` holds ids, never bytes. The bytes live in the NoteImage table and
 * are served from /api/note-images/<id>, because this column is not deferred
 * and six consumers read it straight off /api/records.
 *
 * Loaded as a plain script in the browser, where `const VinylNotes` lands in
 * the global lexical scope for the inline script below it; required as a
 * module by the tests. */

const VinylNotes = (function () {

  function hasContent(note) {
    if (!note) return false;
    if (note.text && note.text.trim()) return true;
    return !!(note.images && note.images.length);
  }

  /* Migration: a raw value that is not a JSON array is a legacy single note,
   * dated with the record's purchase day (or today) by the caller. */
  function parseNotes(raw, fallbackDate) {
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed;
    } catch (e) {}
    return [{ date: fallbackDate, text: raw }];
  }

  /* '' rather than '[]' for an empty list: the column's empty value is the
   * empty string, and every reader treats it that way. */
  function serializeNotes(arr) {
    const clean = (arr || []).filter(hasContent);
    return clean.length ? JSON.stringify(clean) : '';
  }

  /* Every image id a note list refers to, deduped and ordered, for the callers
   * that need to know what a record points at without holding any bytes. */
  function noteImageIds(notes) {
    const seen = [];
    (notes || []).forEach(function (n) {
      ((n && n.images) || []).forEach(function (id) {
        if (id && seen.indexOf(id) === -1) seen.push(id);
      });
    });
    return seen;
  }

  return { parseNotes, serializeNotes, noteImageIds, hasContent };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylNotes;
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node --test tests/test_notes.js`
Expected: PASS, 14 tests

- [ ] **Step 5: Load the module in the page**

In `templates/index.html:2334`, after the `cover.js` tag:

```html
<script src="/static/cover.js"></script>
<script src="/static/notes.js"></script>
```

- [ ] **Step 6: Delegate the inline functions to the module**

Replace the bodies at `templates/index.html:3689-3702`. Keeping the wrappers rather than deleting them is deliberate: `FILTER_DEPS` and `TIMELINE_DEPS` inject `parseNotes` by name, and `today()` lives here, not in the module.

```js
// Both delegate to static/notes.js, which is where these are tested. The
// wrappers stay because FILTER_DEPS and TIMELINE_DEPS inject parseNotes by
// name, and because the today() fallback belongs to the page, not the module.
function parseNotes(raw, fallbackDate) {
  return VinylNotes.parseNotes(raw, fallbackDate || today());
}

function serializeNotes(arr) {
  return VinylNotes.serializeNotes(arr);
}
```

- [ ] **Step 7: Run the whole suite**

Run: `python -m pytest`
Expected: PASS, including the new `tests/test_notes.py`

- [ ] **Step 8: Commit**

```bash
git add static/notes.js tests/test_notes.js tests/test_notes.py templates/index.html
git commit -m "refactor: extract notes parse/serialize into static/notes.js"
```

---

### Task 5: Attach photos to a note in the form

**Files:**
- Modify: `templates/index.html` — CSS near `.note-entry` (`:1370`), notes add-row HTML (`:2126-2132`), cover picker JS (`:4241-4290`), `handleCoverFile` (`:4534`), `setScanBusy` (`:4631`), `addNote`/`deleteNote`/`renderNotesForm` (`:3728-3906`), `openEdit`/reset (`:4045`)

**Interfaces:**
- Consumes: `POST /api/note-images` (Task 1), `VinylNotes` (Task 4), existing `resizeImage`, `openCamera`, `toast`, `formChanged`.
- Produces:
  - `photoTarget: 'cover' | 'note'`
  - `applyPhoto(dataUri)`
  - `addNoteImage(dataUri) -> Promise<void>`
  - `noteImageSrc(id) -> string`
  - `formNoteImages: string[]`, `noteImagePreview: {[id]: dataUri}`
  - `removePendingNoteImage(id)`, `removeNoteImage(noteIdx, id)`

- [ ] **Step 1: Add the CSS**

After `.note-delete:hover` (`templates/index.html:1375`):

```css
/* thumbnails on a note, in the form and in the detail history */
.note-shots{display:flex;flex-wrap:wrap;gap:6px;margin-top:7px}
.note-shot{width:52px;height:52px;object-fit:cover;border-radius:var(--radius-sm);
  border:1px solid var(--border);cursor:pointer;display:block}
.note-shot-wrap{position:relative;line-height:0}
.note-shot-drop{position:absolute;top:-5px;right:-5px;width:17px;height:17px;
  border-radius:50%;border:1px solid var(--border);background:var(--card);
  color:var(--muted);cursor:pointer;font-size:10px;line-height:1;padding:0;
  display:flex;align-items:center;justify-content:center}
.note-shot-drop:hover{color:var(--danger)}
.note-photo-row{grid-column:1 / -1;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
```

- [ ] **Step 2: Add the buttons and the pending strip to the add-row**

Replace `templates/index.html:2126-2132`:

```html
            <div class="notes-add-row">
              <div class="field"><i class="ti ti-calendar"></i><input type="date" id="fNoteDate"></div>
              <div class="field"><i class="ti ti-clock"></i><input type="time" id="fNoteTime" title="time of the note — leave blank if it does not matter"></div>
              <textarea id="fNoteText" placeholder="Add a note…"></textarea>
              <button type="button" class="btn btn-primary btn-sm" style="height:34px;align-self:start" onclick="addNote()"><i class="ti ti-plus"></i> add</button>
              <!-- Photos attach to the note being composed and are uploaded as
                   they are picked, so the record save stays small. -->
              <div class="note-photo-row">
                <button type="button" class="btn btn-sm" id="notePickerFile" onclick="pickNotePhoto()">
                  <i class="ti ti-folder"></i> photo
                </button>
                <button type="button" class="btn btn-sm" id="notePickerCamera" onclick="openCamera('note')">
                  <i class="ti ti-camera"></i> take photo
                </button>
                <div class="note-shots" id="fNoteShots"></div>
              </div>
            </div>
```

- [ ] **Step 3: Route the picker and camera by target**

Replace `pickCoverFile` and `fallbackCapture` (`templates/index.html:4241-4242`):

```js
// Which half of the form the next photo belongs to. The picker, the camera
// overlay and the resize path are shared; only the destination differs, and
// captureFrame used to hardcode applyCover so the camera could only ever
// produce a cover.
let photoTarget = 'cover';

function pickCoverFile(){ photoTarget = 'cover'; document.getElementById('coverInput').click(); }
function pickNotePhoto(){ photoTarget = 'note';  document.getElementById('coverInput').click(); }
function fallbackCapture(){ document.getElementById('coverCaptureInput').click(); }

// The one place that knows where a finished data URI goes.
function applyPhoto(dataUri){
  if(photoTarget === 'note') addNoteImage(dataUri); else applyCover(dataUri);
}
```

Change `openCamera` to take a target (`templates/index.html:4244`):

```js
async function openCamera(target){
  photoTarget = target || 'cover';   // the cover button calls openCamera()
  if(camStream) return; // a request is already in flight or live
```

Change the last line of `captureFrame` (`templates/index.html:4280`) from `applyCover(dataUri);` to:

```js
  applyPhoto(dataUri);
```

Change the last line of `handleCoverFile` (`templates/index.html:4553`) from `applyCover(dataUri);` to:

```js
  applyPhoto(dataUri);
```

- [ ] **Step 4: Disable the note buttons during a scan**

In `setScanBusy` (`templates/index.html:4631`), extend the id list — the file inputs are shared, so a scan already blocks the note path, and this only keeps the buttons honest about it:

```js
  ['spotifyUrlInput','spotifySubmitBtn','coverInput','coverCaptureInput',
   'coverPickerFile','coverPickerCamera','notePickerFile','notePickerCamera'].forEach(id=>{
```

- [ ] **Step 5: Add the note-image state and upload**

Next to `formNotes` (`templates/index.html:3684`):

```js
let formNoteImages = [];    // ids attached to the note being composed
// Data URIs for photos uploaded in this session, so a just-added thumbnail
// paints immediately instead of round-tripping through its own URL.
let noteImagePreview = {};
```

After `deleteNote` (`templates/index.html:3906`):

```js
// A photo just picked or captured, on its way to a note. Uploaded now rather
// than at save so the record's own payload stays small: several photos plus a
// dirty cover would otherwise be megabytes of base64 on every save.
async function addNoteImage(dataUri){
  let res;
  try{
    res = await fetch('/api/note-images', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({data: dataUri})});
  }catch(e){ toast('could not save that photo'); return; }
  if(!res.ok){
    toast(res.status === 401 ? 'session expired — unlock and save again'
        : res.status === 413 ? 'that photo is too large'
        : 'could not save that photo');
    return;
  }
  const {id} = await res.json();
  noteImagePreview[id] = dataUri;
  if(formNoteImages.indexOf(id) === -1) formNoteImages.push(id);  // same photo twice
  renderNoteShots();
}

// A photo uploaded in this session paints from the bytes already in hand; a
// stored one comes from its own immutable URL.
function noteImageSrc(id){
  return noteImagePreview[id] || `/api/note-images/${id}`;
}

// One thumbnail, with the × that drops it. `onerror` removes it rather than
// leaving a broken-image icon sitting inside a note.
function noteShotHTML(id, onRemove){
  return `<span class="note-shot-wrap">
    <img class="note-shot" src="${esc(noteImageSrc(id))}" onerror="this.parentNode.remove()">
    <button type="button" class="note-shot-drop" title="remove photo" onclick="${onRemove}"><i class="ti ti-x"></i></button>
  </span>`;
}

// The strip under the add-row: photos on the note not yet added.
function renderNoteShots(){
  document.getElementById('fNoteShots').innerHTML =
    formNoteImages.map(id => noteShotHTML(id, `removePendingNoteImage('${id}')`)).join('');
}

function removePendingNoteImage(id){
  formNoteImages = formNoteImages.filter(x => x !== id);
  renderNoteShots();
}

// Removing a photo from a note already in the list. The image row itself is
// not deleted here — the server reaps it on save, once it knows nothing else
// refers to it.
function removeNoteImage(idx, id){
  const note = formNotes[idx];
  if(!note) return;
  note.images = (note.images || []).filter(x => x !== id);
  renderNotesForm();
}
```

- [ ] **Step 6: Let `addNote` accept a photo-only note**

Replace the text guard and the push in `addNote` (`templates/index.html:3946-3950`):

```js
  // Text OR a photo. A note that is just a picture of the sleeve is a note.
  if (!text && !formNoteImages.length) {
    textEl.focus(); textEl.style.borderColor='var(--danger)'; return;
  }
  dateEl.style.borderColor='';
  textEl.style.borderColor='';
  formNotes.push({ date, text, images: formNoteImages });
  formNoteImages = [];
  renderNoteShots();
  textEl.value = '';
```

- [ ] **Step 7: Render thumbnails on saved notes**

In `renderNotesForm` (`templates/index.html:3735-3741`), add the strip to each entry:

```js
    const shots = (n.images || []).length
      ? `<div class="note-shots">${n.images.map(id =>
           noteShotHTML(id, `removeNoteImage(${origIdx}, '${id}')`)).join('')}</div>`
      : '';
    return `<div class="note-entry">
      <div class="note-entry-date">${noteDateLabel(n.date)}</div>
      <div class="note-entry-body">${typeof marked !== 'undefined' ? marked.parse(n.text || '') : esc(n.text || '')}</div>
      ${shots}
      <button class="note-delete" title="delete note" onclick="deleteNote(${origIdx})"><i class="ti ti-trash"></i></button>
    </div>`;
```

Note `n.text || ''` — `marked.parse(undefined)` throws, and a photo-only note has no text.

- [ ] **Step 8: Clear the pending strip when the form opens**

In the new-record reset (`templates/index.html:4046`, just before `renderNotesForm()`):

```js
  document.getElementById('fNoteText').value='';
  formNoteImages=[];
  renderNoteShots();
  renderNotesForm();
```

Do the same in `openEdit` next to `formNotes=parseNotes(...)` (`templates/index.html:4053`):

```js
  formNotes=parseNotes(r.notes, r.bought_date||today());
  formNoteImages=[];
  renderNoteShots();
```

- [ ] **Step 9: Verify in the browser**

Run the app and check, in one sitting:
1. Add a note with text and one uploaded photo → thumbnail appears in the add strip, then on the note entry after "add".
2. Add a note with **only** a photo → it is accepted, and survives Save + reopen.
3. Remove a photo from a saved note, save, reopen → it is gone.
4. The cover picker and camera still work and still produce a cover, not a note photo.

Use the `run` skill if the project has one, otherwise `python app.py`.

- [ ] **Step 10: Run the whole suite**

Run: `python -m pytest`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add templates/index.html
git commit -m "feat: attach photos to a note by upload or camera"
```

---

### Task 6: Thumbnails and a lightbox in the detail history

**Files:**
- Modify: `templates/index.html` — `dmHistoryEvents` (`:3219-3220`), `dmHistoryEntryHTML` (`:3243-3247`), a new overlay after `cameraOverlay` (`:2176`), CSS

**Interfaces:**
- Consumes: `noteImageSrc` from Task 5, `VinylNotes.hasContent` from Task 4. Not `noteShotHTML` — a detail thumbnail opens a lightbox and has no remove button, so it is its own markup.
- Produces: `openShot(id)`, `closeShot()`.

- [ ] **Step 1: Carry images into the history events**

`dmHistoryEvents` currently drops any note with no text, which would hide a photo-only note entirely. Replace `templates/index.html:3219-3220`:

```js
  // `hasContent`, not `n.text` — a note that is only a photo still happened.
  if (r.notes) parseNotes(r.notes, r.bought_date||today())
    .filter(n => VinylNotes.hasContent(n))
    .forEach(n => {
      add('note', n.date, { text: n.text || '', images: n.images || [] });
    });
```

- [ ] **Step 2: Render the strip**

In `dmHistoryEntryHTML`, replace the note branch (`templates/index.html:3244-3245`):

```js
  const shots = (ev.images || []).length
    ? `<div class="note-shots">${ev.images.map(id =>
         `<img class="note-shot" src="${esc(noteImageSrc(id))}" onclick="openShot('${id}')" onerror="this.remove()">`
       ).join('')}</div>`
    : '';
  const body = ev.type === 'note'
    ? `<div class="ht detail-notes-body">${ev.text ? (typeof marked !== 'undefined' ? marked.parse(ev.text) : esc(ev.text)) : ''}${shots}${clock}</div>`
```

- [ ] **Step 3: Add the lightbox overlay**

After the camera overlay closes (`templates/index.html:2176`):

```html
<!-- One note photo, full size. There was no lightbox before this. -->
<div class="overlay hidden" id="shotOverlay" onclick="closeShot()">
  <div class="modal" style="max-width:min(90vw,720px)">
    <div class="modal-head">
      <span class="modal-title">photo</span>
      <button class="btn btn-ghost btn-sm" onclick="closeShot()"><i class="ti ti-x"></i></button>
    </div>
    <div class="modal-body" style="text-align:center">
      <img id="shotImage" style="max-width:100%;max-height:70vh;border-radius:var(--radius)">
    </div>
  </div>
</div>
```

- [ ] **Step 4: Add the handlers**

Next to `closeCamera` (`templates/index.html:4266`):

```js
function openShot(id){
  document.getElementById('shotImage').src = noteImageSrc(id);
  document.getElementById('shotOverlay').classList.remove('hidden');
}

function closeShot(){
  document.getElementById('shotOverlay').classList.add('hidden');
  // An empty src attribute resolves to the page URL and fetches it again.
  document.getElementById('shotImage').removeAttribute('src');
}
```

- [ ] **Step 5: Verify in the browser**

1. Open a record whose note has photos → thumbnails under the note in History.
2. Click one → the lightbox opens with the full image; clicking the backdrop or × closes it.
3. A note with only a photo appears in History rather than vanishing.

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add templates/index.html
git commit -m "feat: show note photos in the detail history, with a lightbox"
```

---

### Task 7: A thumbnail on the activity strip's note card

**Files:**
- Modify: `static/activity.js` (`parseNoteList` at `:78`, `eventsOf` at `:100`, `noteList` push at `:157`)
- Modify: `templates/index.html` (`actNote` card at `:1795`, `actPaintNote` at `:6345`, CSS near `.act-note` at `:948`)
- Test: `tests/test_activity.js` (extend and fix)

**Interfaces:**
- Consumes: `noteImageSrc` from Task 5.
- Produces: `images: string[]` on every entry of `buildActivity(...).notes`.

- [ ] **Step 1: Write the failing tests**

`tests/test_activity.js:194` asserts a note object exactly, so it must gain the new key. Replace that assertion:

```js
  assert.deepStrictEqual(a.notes[1], { day: 8, text: 'later', id: 4,
                                       artist: 'X', album: 'Y', images: [] });
```

Then append to the notes section of `tests/test_activity.js` (after `:183`):

```js
test('a note carries its image ids, never any bytes', () => {
  const a = buildActivity([
    rec({ id: 7, bought_date: '2026-01-01',
          notes: JSON.stringify([{ date: '2026-01-04', text: 'seam split', images: ['a1', 'b2'] }]) }),
  ]);
  assert.deepStrictEqual(a.notes[0].images, ['a1', 'b2']);
});

test('a note that is only a photo still reaches the strip', () => {
  // parseNoteList used to require text, which would drop this note entirely.
  const a = buildActivity([
    rec({ id: 8, bought_date: '2026-01-01',
          notes: JSON.stringify([{ date: '2026-01-04', text: '', images: ['a1'] }]) }),
  ]);
  assert.strictEqual(a.notes.length, 1);
  assert.deepStrictEqual(a.notes[0].images, ['a1']);
  assert.deepStrictEqual(a.lanes[0].notes, [3]);
});

test('a note with neither text nor photos is still dropped', () => {
  const a = buildActivity([
    rec({ id: 9, bought_date: '2026-01-01',
          notes: JSON.stringify([{ date: '2026-01-04', text: '   ' }]) }),
  ]);
  assert.strictEqual(a.notes.length, 0);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test tests/test_activity.js`
Expected: FAIL — the `images` key is missing, and the photo-only note is dropped

- [ ] **Step 3: Let a photo-only note through**

In `static/activity.js`, replace the filter in `parseNoteList`:

```js
    return parsed.filter(function (n) {
      // Text OR a photo. A note that is only a picture of the sleeve happened
      // on its day like any other, and dropping it hides an event.
      if (!n) return false;
      if (typeof n.text === 'string' && n.text.trim()) return true;
      return !!(n.images && n.images.length);
    });
```

- [ ] **Step 4: Carry the ids through**

In `eventsOf`, replace the notes mapping:

```js
      notes:  parseNoteList(r.notes, r.bought_date)
                .map(function (n) {
                  // Ids only. This runs on the /api/records payload, which is
                  // exactly why the bytes had to leave the notes column.
                  return { day: dayOf(n.date), text: n.text || '', images: n.images || [] };
                })
                .filter(function (n) { return isDay(n.day); })
                .sort(function (a, b) { return a.day - b.day; }),
```

In `buildActivity`'s `noteDays` block, add `images` to the pushed entry:

```js
        noteList.push({ day: day, text: n.text, images: n.images, id: e.r.id,
                        artist: e.r.artist || '', album: e.r.album_name || '' });
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `node --test tests/test_activity.js`
Expected: PASS

- [ ] **Step 6: Put a thumbnail on the card**

Add to the CSS after `.act-note .txt` (`templates/index.html:954`):

```css
.act-note{display:flex;align-items:flex-start;gap:9px}
.act-note .body{flex:1;min-width:0}
.act-note .shot{width:38px;height:38px;object-fit:cover;border-radius:var(--radius-sm);
  border:1px solid var(--border);flex-shrink:0;display:none}
```

Replace the card markup (`templates/index.html:1795`):

```html
          <div class="act-note" id="actNote">
            <span class="body"><span class="who"></span><span class="txt"></span></span>
            <img class="shot" alt="">
          </div>
```

In `actPaintNote` (`templates/index.html:6345`), after the existing `.txt` assignment:

```js
  card.querySelector('.txt').textContent = n.text;
  const shot = card.querySelector('.shot');
  const first = (n.images || [])[0];
  if(first){
    shot.src = noteImageSrc(first);
    shot.style.display = 'block';
  }else{
    shot.removeAttribute('src');   // '' would resolve to the page URL
    shot.style.display = 'none';
  }
  card.classList.add('on');
```

- [ ] **Step 7: Verify in the browser**

Open the History/activity tab and scrub the playhead past a note that has a photo → the hover card shows a thumbnail; past one without → no thumbnail, and no broken-image box.

- [ ] **Step 8: Run the whole suite**

Run: `python -m pytest`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add static/activity.js templates/index.html tests/test_activity.js
git commit -m "feat: show a note's photo on the activity strip"
```

---

## Verification

After Task 7, before calling the feature done:

- [ ] `python -m pytest` — the whole suite, green.
- [ ] `node --test tests/test_notes.js tests/test_activity.js tests/test_cover_form.js` — green.
- [ ] End-to-end in the browser: add a note with two photos, save, reload the page, confirm they render in the form, the detail history and the activity card.
- [ ] Export the collection, wipe it, import the export, confirm the photos come back.
- [ ] `curl -s localhost:5000/api/records | grep -c base64` returns `0` — the regression guard, checked against a real collection rather than only in tests.
