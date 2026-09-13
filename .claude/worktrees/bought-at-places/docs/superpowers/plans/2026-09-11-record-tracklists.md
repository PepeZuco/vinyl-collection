# Record Tracklists Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every record its songs — grouped by side, with a dated heart on the ones worth remembering — plus the record's format, and surface all of it in the grid, the drawer, the Timeline and search.

**Architecture:** Three new columns on `Record` (`tracks` as JSON-in-text, `disc_count`, `size`), mirroring how `notes` and `play_dates` already work. All parse/serialize rules live in one new pure module, `static/tracks.js`, tested under node — nothing in `templates/index.html` parses the column itself. A like is an event, not a flag: `liked_at` is a stamp in the same format as `play_dates`, so it flows into the existing Timeline machinery as a fifth type.

**Tech Stack:** Flask + SQLAlchemy (SQLite), vanilla JS in one template plus plain-script modules under `static/`, pytest with node `--test` shims for the JS modules, Tabler icons (`ti ti-*`).

**Spec:** `docs/superpowers/specs/2026-09-11-record-tracklists-design.md`

## Global Constraints

- **Stamp format** — `liked_at` is `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS`, a **local** wall clock with no zone suffix. Never UTC. See the comment block above `class Record` in `app.py:195`.
- **Side letters carry the disc.** Disc *n* owns letters at index `2n-2` and `2n-1`: disc 1 = `A`/`B`, disc 2 = `C`/`D`, disc 3 = `E`/`F`. There is no disc field on a track.
- **No `pos` field.** Track order is the array's order within a side; the displayed number is derived at render time.
- **Track identity is its index in the raw array** — never an index into a filtered list. Same rule `notes` lives under (`app.py:_note_image_ids`, `dmHistoryEvents`).
- **Empty column value is `''`, not `'[]'`.** `serializeTracks` returns `''` for an empty list, matching `serializeNotes` in `static/notes.js`.
- **`size`** is one of `''`, `'7'`, `'10'`, `'12'` — inches, as a bare code. The UI owns the `"` suffix.
- **`disc_count`** is an integer `>= 1`, defaulting to `1`.
- **New module style:** `static/tracks.js` follows `static/notes.js` exactly — an IIFE assigned to a `const Vinyl<Name>`, with `if (typeof module !== 'undefined' && module.exports) module.exports = Vinyl<Name>;` at the bottom, loaded as a plain `<script>` in the template.
- **Icon vocabulary:** liked = `ti-heart-filled` / `ti-heart`, colour `--ev-liked`. Do not reuse stars (ratings), headphones (plays) or droplet (cleaning).
- **Machine note:** `tests/test_boot.py` times out on this machine after its tests pass. Run node suites directly (`node --test tests/test_tracks.js`) when iterating; run full `pytest` only at the checkpoints this plan names.

---

### Task 1: The rules module — `static/tracks.js`

Pure functions with no DOM and no network. Everything downstream reads the column through this module.

**Files:**
- Create: `static/tracks.js`
- Create: `tests/test_tracks.js`
- Create: `tests/test_tracks.py`

**Interfaces:**
- Consumes: nothing.
- Produces: global `VinylTracks` with
  `parseTracks(raw) -> Array<{side, title, liked_at?}>`,
  `serializeTracks(list) -> string`,
  `sideLettersFor(discCount) -> string[]`,
  `discOfSide(letter) -> number`,
  `tracksBySide(list, discCount) -> Array<{disc, letter, tracks: Array<{i, pos, title, liked_at}>}>`,
  `likedTracks(list) -> Array<{i, title, liked_at}>`,
  `sidesWithTracks(list) -> string[]`,
  `discMarks(discCount) -> {sleeves, segments}`,
  `parsePastedTracklist(text) -> string[]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tracks.js`:

```js
// Tests for the tracks column's parse/serialize rules.
// Run by tests/test_tracks.py so `pytest` stays the single command.
//
// These exist because six consumers read this column straight off
// /api/records. A record whose column holds nonsense — a hand-edited PUT, an
// imported CSV from another tool — must come back as an empty list, not throw
// and take the whole grid down with it.

const test = require('node:test');
const assert = require('node:assert');

const { parseTracks, serializeTracks, sideLettersFor, discOfSide,
        tracksBySide, likedTracks, sidesWithTracks, discMarks,
        parsePastedTracklist } = require('../static/tracks.js');

// ── parse ───────────────────────────────────────────────────────────────────

test('an empty column is an empty list', () => {
  assert.deepStrictEqual(parseTracks(''), []);
  assert.deepStrictEqual(parseTracks(null), []);
  assert.deepStrictEqual(parseTracks(undefined), []);
});

test('nonsense parses to an empty list rather than throwing', () => {
  assert.deepStrictEqual(parseTracks('not json'), []);
  assert.deepStrictEqual(parseTracks('{"side":"A"}'), []);   // object, not array
  assert.deepStrictEqual(parseTracks('42'), []);
});

test('a track keeps side, title and liked_at', () => {
  const raw = JSON.stringify([{ side: 'A', title: 'Umbabarauma', liked_at: '2026-09-09T21:40:00' }]);
  assert.deepStrictEqual(parseTracks(raw),
    [{ side: 'A', title: 'Umbabarauma', liked_at: '2026-09-09T21:40:00' }]);
});

test('an unliked track carries no liked_at key at all', () => {
  const parsed = parseTracks(JSON.stringify([{ side: 'A', title: 'Taj Mahal' }]));
  assert.strictEqual('liked_at' in parsed[0], false);
});

test('side is upper-cased and cut to one letter', () => {
  const parsed = parseTracks(JSON.stringify([{ side: 'bb', title: 'x' }]));
  assert.strictEqual(parsed[0].side, 'B');
});

// ── serialize ───────────────────────────────────────────────────────────────

test('an empty list serializes to the empty string, not "[]"', () => {
  assert.strictEqual(serializeTracks([]), '');
  assert.strictEqual(serializeTracks(null), '');
});

test('a row with no title is dropped', () => {
  assert.strictEqual(serializeTracks([{ side: 'A', title: '   ' }]), '');
});

test('titles are trimmed on the way out', () => {
  assert.strictEqual(serializeTracks([{ side: 'A', title: '  Mother  ' }]),
                     JSON.stringify([{ side: 'A', title: 'Mother' }]));
});

test('a like survives serialize', () => {
  assert.strictEqual(serializeTracks([{ side: 'A', title: 'Hey You', liked_at: '2026-08-02' }]),
                     JSON.stringify([{ side: 'A', title: 'Hey You', liked_at: '2026-08-02' }]));
});

// ── sides and discs ─────────────────────────────────────────────────────────

test('one disc is sides A and B', () => {
  assert.deepStrictEqual(sideLettersFor(1), ['A', 'B']);
});

test('a double is A through D, a triple A through F', () => {
  assert.deepStrictEqual(sideLettersFor(2), ['A', 'B', 'C', 'D']);
  assert.deepStrictEqual(sideLettersFor(3), ['A', 'B', 'C', 'D', 'E', 'F']);
});

test('a missing or nonsense disc count is treated as one disc', () => {
  assert.deepStrictEqual(sideLettersFor(0), ['A', 'B']);
  assert.deepStrictEqual(sideLettersFor(undefined), ['A', 'B']);
});

test('the side letter says which disc it is on', () => {
  assert.strictEqual(discOfSide('A'), 1);
  assert.strictEqual(discOfSide('B'), 1);
  assert.strictEqual(discOfSide('C'), 2);
  assert.strictEqual(discOfSide('F'), 3);
});

// ── grouping ────────────────────────────────────────────────────────────────

test('tracksBySide groups by letter and numbers within the side', () => {
  const list = [
    { side: 'A', title: 'one' },
    { side: 'B', title: 'three' },
    { side: 'A', title: 'two' },
  ];
  const sides = tracksBySide(list, 1);
  assert.deepStrictEqual(sides.map(s => s.letter), ['A', 'B']);
  assert.deepStrictEqual(sides[0].tracks.map(t => [t.pos, t.title]), [[1, 'one'], [2, 'two']]);
  assert.deepStrictEqual(sides[1].tracks.map(t => [t.pos, t.title]), [[1, 'three']]);
});

test('grouping keeps the RAW array index, not the position on the side', () => {
  const list = [
    { side: 'B', title: 'b-one' },
    { side: 'A', title: 'a-one' },
  ];
  const sides = tracksBySide(list, 1);
  assert.strictEqual(sides[0].tracks[0].i, 1);   // side A's song is index 1
  assert.strictEqual(sides[1].tracks[0].i, 0);
});

test('a side with nothing on it is still offered, empty', () => {
  const sides = tracksBySide([{ side: 'A', title: 'only' }], 1);
  assert.deepStrictEqual(sides[1].tracks, []);
});

test('a double offers four sides with their disc numbers', () => {
  const sides = tracksBySide([], 2);
  assert.deepStrictEqual(sides.map(s => s.disc), [1, 1, 2, 2]);
});

// ── likes ───────────────────────────────────────────────────────────────────

test('likedTracks reports only liked songs, with their raw index', () => {
  const list = [
    { side: 'A', title: 'no' },
    { side: 'A', title: 'yes', liked_at: '2026-09-09' },
  ];
  assert.deepStrictEqual(likedTracks(list), [{ i: 1, title: 'yes', liked_at: '2026-09-09' }]);
});

// ── the disc-count guard ────────────────────────────────────────────────────

test('sidesWithTracks names the sides that would lose songs', () => {
  const list = [{ side: 'A', title: 'x' }, { side: 'C', title: 'y' }];
  assert.deepStrictEqual(sidesWithTracks(list), ['A', 'C']);
});

// ── the grid marks ──────────────────────────────────────────────────────────

test('a single disc gets no marks at all', () => {
  assert.deepStrictEqual(discMarks(1), { sleeves: 0, segments: 0 });
  assert.deepStrictEqual(discMarks(undefined), { sleeves: 0, segments: 0 });
});

test('a double gets one sleeve behind and two spine segments', () => {
  assert.deepStrictEqual(discMarks(2), { sleeves: 1, segments: 2 });
});

test('a triple gets two sleeves and three segments', () => {
  assert.deepStrictEqual(discMarks(3), { sleeves: 2, segments: 3 });
});

// ── the paste box ───────────────────────────────────────────────────────────

test('a pasted block becomes one title per line', () => {
  assert.deepStrictEqual(parsePastedTracklist('Mother\nHey You'), ['Mother', 'Hey You']);
});

test('blank lines are dropped', () => {
  assert.deepStrictEqual(parsePastedTracklist('Mother\n\n\nHey You'), ['Mother', 'Hey You']);
});

test('leading track numbers are stripped', () => {
  assert.deepStrictEqual(
    parsePastedTracklist('1. Mother\n02 - Hey You\n3) Comfortably Numb'),
    ['Mother', 'Hey You', 'Comfortably Numb']);
});

test('leading side-and-number labels are stripped', () => {
  assert.deepStrictEqual(parsePastedTracklist('A1 Mother\nA2. Hey You'),
                         ['Mother', 'Hey You']);
});

test('trailing durations are stripped', () => {
  assert.deepStrictEqual(parsePastedTracklist('Mother 5:32\nHey You (4:40)'),
                         ['Mother', 'Hey You']);
});

test('a title that merely starts with a number survives intact', () => {
  assert.deepStrictEqual(parsePastedTracklist('10 Years Gone'), ['10 Years Gone']);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node --test tests/test_tracks.js`
Expected: FAIL — `Cannot find module '../static/tracks.js'`

- [ ] **Step 3: Write the implementation**

Create `static/tracks.js`:

```js
/* The tracks column's parse/serialize rules.
 *
 * Tracks are stored as JSON: [{side, title, liked_at?}]. The side LETTER
 * carries which disc a song is on, the way a real sleeve carries it — disc 1
 * is A/B, disc 2 is C/D — so there is no disc field on a track and nothing to
 * keep in sync.
 *
 * There is deliberately no position field either. Order within a side is the
 * array's own order and the number shown is derived at render time; storing a
 * position alongside the order gives two sources of truth that drift the first
 * time a row is dragged.
 *
 * liked_at is a stamp in the same format as play_dates — a LOCAL wall clock,
 * never UTC — so momentOf() reads it and the Timeline files it on the right
 * day. Absent means the song is not liked; there is no false to store.
 *
 * Loaded as a plain script in the browser, where `const VinylTracks` lands in
 * the global lexical scope for the inline script below it; required as a
 * module by the tests. */

const VinylTracks = (function () {

  const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

  /* Which sides a record of this many discs has. Two per disc, in order, so
   * the letter alone answers "which disc is this song on". */
  function sideLettersFor(discCount) {
    const n = Math.max(1, Number(discCount) || 1);
    return LETTERS.slice(0, n * 2).split('');
  }

  function discOfSide(letter) {
    const i = LETTERS.indexOf(String(letter || '').toUpperCase().slice(0, 1));
    return i === -1 ? 0 : Math.floor(i / 2) + 1;
  }

  /* Total: this column is read by six consumers straight off /api/records, and
   * a record whose value will not parse — a hand-edited PUT, a CSV from
   * somewhere else — must come back empty rather than take the grid down. */
  function parseTracks(raw) {
    if (!raw) return [];
    let parsed;
    try { parsed = JSON.parse(raw); } catch (e) { return []; }
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(function (t) { return t && typeof t === 'object'; })
      .map(function (t) {
        const out = {
          side: String(t.side || '').toUpperCase().slice(0, 1),
          title: typeof t.title === 'string' ? t.title : '',
        };
        if (t.liked_at) out.liked_at = String(t.liked_at);
        return out;
      });
  }

  /* '' rather than '[]' for an empty list: the column's empty value is the
   * empty string, and every reader treats it that way. */
  function serializeTracks(list) {
    const clean = (list || [])
      .filter(function (t) { return t && typeof t.title === 'string' && t.title.trim(); })
      .map(function (t) {
        const out = {
          side: String(t.side || 'A').toUpperCase().slice(0, 1),
          title: t.title.trim(),
        };
        if (t.liked_at) out.liked_at = String(t.liked_at);
        return out;
      });
    return clean.length ? JSON.stringify(clean) : '';
  }

  /* Every side the record has, in order, each with its songs numbered.
   *
   * `i` is the index in the RAW array and `pos` is the number printed on the
   * sleeve. They are different things: the first two consumers that conflated
   * them would have deleted the wrong song. Every handler addresses a track by
   * `i`; only the eye uses `pos`. */
  function tracksBySide(list, discCount) {
    const all = (list || []).map(function (t, i) { return { t: t, i: i }; });
    return sideLettersFor(discCount).map(function (letter) {
      return {
        disc: discOfSide(letter),
        letter: letter,
        tracks: all
          .filter(function (x) { return x.t.side === letter; })
          .map(function (x, k) {
            return { i: x.i, pos: k + 1, title: x.t.title,
                     liked_at: x.t.liked_at || '' };
          }),
      };
    });
  }

  function likedTracks(list) {
    return (list || [])
      .map(function (t, i) { return { t: t, i: i }; })
      .filter(function (x) { return x.t.liked_at; })
      .map(function (x) {
        return { i: x.i, title: x.t.title, liked_at: x.t.liked_at };
      });
  }

  /* The sides that actually hold songs, so lowering the disc count can refuse
   * rather than silently delete. Data loss must be an explicit act. */
  function sidesWithTracks(list) {
    const seen = [];
    (list || []).forEach(function (t) {
      if (t && t.side && seen.indexOf(t.side) === -1) seen.push(t.side);
    });
    return seen.sort();
  }

  /* What the card draws: sleeves peeking out behind the cover, and segments in
   * the spine down its left edge. Both are zero for a single disc — a mark on
   * every card in the grid is furniture the eye stops seeing. */
  function discMarks(discCount) {
    const n = Math.max(1, Number(discCount) || 1);
    return n > 1 ? { sleeves: n - 1, segments: n } : { sleeves: 0, segments: 0 };
  }

  /* Turn pasted text into titles — the shapes a tracklist arrives in when it
   * is copied off a sleeve, a wiki or a shop listing. */
  function parsePastedTracklist(text) {
    return String(text || '')
      .split(/\r?\n/)
      .map(function (line) {
        return line
          // 'A1 ', 'A1. ', 'B2 - ' — a side label glued to a number
          .replace(/^\s*[A-F]\s?\d{1,2}\s*[.)\-–]?\s+/i, '')
          // '1. ', '02 - ', '3) ' — a bare number, but ONLY with punctuation
          // after it, so a title like '10 Years Gone' survives
          .replace(/^\s*\d{1,2}\s*[.)\-–]\s*/, '')
          // ' 5:32', ' (4:40)', ' [3:09]'
          .replace(/\s+[\[(]?\d{1,2}:\d{2}[\])]?\s*$/, '')
          .trim();
      })
      .filter(Boolean);
  }

  return { parseTracks, serializeTracks, sideLettersFor, discOfSide,
           tracksBySide, likedTracks, sidesWithTracks, discMarks,
           parsePastedTracklist };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylTracks;
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node --test tests/test_tracks.js`
Expected: PASS, 26 tests

- [ ] **Step 5: Add the pytest shim**

Create `tests/test_tracks.py`:

```python
"""Run the JavaScript tracks rules under pytest.

Mirrors tests/test_notes.py: the rules are pure functions in static/tracks.js,
so they need a JS runtime, and shelling out to node's test runner keeps
`pytest` as the one command.
"""

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_tracks_js():
    result = subprocess.run(
        ["node", "--test", "tests/test_tracks.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 6: Run the shim**

Run: `python -m pytest tests/test_tracks.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add static/tracks.js tests/test_tracks.js tests/test_tracks.py
git commit -m "feat: the tracks column's parse and grouping rules"
```

---

### Task 2: Backend — columns, API, migration, CSV

**Files:**
- Modify: `app.py` — `Record` model (~`app.py:206`), `to_dict` (~`app.py:233`), `create_record` (~`app.py:410`), `update_record` (~`app.py:438`), the auto-migration block (~`app.py:288`), `export_csv` (~`app.py:862`), `_record_mapping` (~`app.py:918`)
- Create: `tests/test_tracks_endpoint.py`

**Interfaces:**
- Consumes: nothing from Task 1 (Python has its own small copy of the side-letter rule — the JS module cannot be imported here).
- Produces: `/api/records` responses carrying `tracks` (raw JSON string), `disc_count` (int), `size` (str); `_clean_tracks(raw, disc_count) -> str` raising `ValueError`; CSV columns `tracks`, `disc_count`, `size`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tracks_endpoint.py`:

```python
"""The tracks, disc_count and size fields across the record API and the CSV backup.

The validation tested here is the reason the endpoint has any: a side letter
that does not exist on a record with this many discs is a song nothing will
ever render, and accepting it quietly would hide the bug in the data rather
than at the request that caused it.
"""

import io
import json

import pytest

from app import app, db, Record


@pytest.fixture
def client(tmp_path):
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path}/test.db"
    app.config["TESTING"] = True
    with app.app_context():
        db.drop_all()
        db.create_all()
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["authed"] = True
        yield c
    with app.app_context():
        db.drop_all()


def test_a_new_record_defaults_to_one_disc_and_unknown_size(client):
    r = client.post("/api/records", json={"album_name": "Transa"})
    assert r.status_code == 201
    assert r.get_json()["disc_count"] == 1
    assert r.get_json()["size"] == ""
    assert r.get_json()["tracks"] == ""


def test_tracks_round_trip(client):
    tracks = json.dumps([
        {"side": "A", "title": "Ponta de Lanca", "liked_at": "2026-09-09T21:40:00"},
        {"side": "B", "title": "Taj Mahal"},
    ])
    r = client.post("/api/records", json={"album_name": "Africa Brasil",
                                          "tracks": tracks, "size": "12"})
    assert r.status_code == 201
    got = json.loads(r.get_json()["tracks"])
    assert got[0]["title"] == "Ponta de Lanca"
    assert got[0]["liked_at"] == "2026-09-09T21:40:00"
    assert "liked_at" not in got[1]


def test_a_side_that_does_not_exist_is_refused(client):
    tracks = json.dumps([{"side": "C", "title": "nowhere"}])
    r = client.post("/api/records", json={"album_name": "x", "tracks": tracks})
    assert r.status_code == 400
    assert "C" in r.get_json()["error"]


def test_the_same_side_is_fine_on_a_double(client):
    tracks = json.dumps([{"side": "C", "title": "Hey You"}])
    r = client.post("/api/records", json={"album_name": "The Wall",
                                          "disc_count": 2, "tracks": tracks})
    assert r.status_code == 201


def test_an_empty_title_is_dropped_not_stored(client):
    tracks = json.dumps([{"side": "A", "title": "  "}, {"side": "A", "title": "real"}])
    r = client.post("/api/records", json={"album_name": "x", "tracks": tracks})
    stored = json.loads(r.get_json()["tracks"])
    assert [t["title"] for t in stored] == ["real"]


def test_an_unknown_size_becomes_unknown(client):
    r = client.post("/api/records", json={"album_name": "x", "size": "14"})
    assert r.get_json()["size"] == ""


def test_disc_count_is_floored_at_one(client):
    r = client.post("/api/records", json={"album_name": "x", "disc_count": 0})
    assert r.get_json()["disc_count"] == 1


def test_put_validates_against_the_stored_disc_count(client):
    """A PUT that sends tracks but not disc_count is checked against what the
    record already is — otherwise the default of 1 would reject a double's
    C-side on every partial update."""
    made = client.post("/api/records", json={"album_name": "The Wall", "disc_count": 2})
    rid = made.get_json()["id"]
    r = client.put(f"/api/records/{rid}",
                   json={"tracks": json.dumps([{"side": "D", "title": "The Trial"}])})
    assert r.status_code == 200


def test_a_like_can_be_added_by_patching_tracks_alone(client):
    made = client.post("/api/records", json={
        "album_name": "x",
        "tracks": json.dumps([{"side": "A", "title": "Mother"}])})
    rid = made.get_json()["id"]
    r = client.put(f"/api/records/{rid}", json={"tracks": json.dumps(
        [{"side": "A", "title": "Mother", "liked_at": "2026-08-02"}])})
    assert json.loads(r.get_json()["tracks"])[0]["liked_at"] == "2026-08-02"


def test_export_carries_the_new_columns(client):
    client.post("/api/records", json={
        "album_name": "The Wall", "disc_count": 2, "size": "12",
        "tracks": json.dumps([{"side": "A", "title": "Mother"}])})
    csv_text = client.get("/api/export").get_data(as_text=True)
    header = csv_text.splitlines()[0]
    assert "tracks" in header and "disc_count" in header and "size" in header
    assert "Mother" in csv_text


def test_import_restores_the_new_columns(client):
    client.post("/api/records", json={
        "album_name": "The Wall", "disc_count": 2, "size": "12",
        "tracks": json.dumps([{"side": "C", "title": "Hey You"}])})
    csv_text = client.get("/api/export").get_data(as_text=True)

    r = client.post("/api/import", data={
        "file": (io.BytesIO(csv_text.encode()), "backup.csv")},
        content_type="multipart/form-data")
    assert r.status_code == 200

    with app.app_context():
        rec = Record.query.filter_by(album_name="The Wall").one()
        assert rec.disc_count == 2
        assert rec.size == "12"
        assert json.loads(rec.tracks)[0]["title"] == "Hey You"


def test_a_csv_without_the_columns_still_imports(client):
    """Every backup taken before this feature has no such columns. That is not
    an error — the same rule _row_note_images already follows."""
    csv_text = "artist,album_name\r\nJorge Ben,Africa Brasil\n"
    r = client.post("/api/import", data={
        "file": (io.BytesIO(csv_text.encode()), "old.csv")},
        content_type="multipart/form-data")
    assert r.status_code == 200
    with app.app_context():
        rec = Record.query.filter_by(album_name="Africa Brasil").one()
        assert rec.disc_count == 1
        assert rec.tracks in ("", None)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_tracks_endpoint.py -v`
Expected: FAIL — `KeyError: 'disc_count'` on the first test

- [ ] **Step 3: Add the columns to the model**

In `app.py`, inside `class Record`, after the `country` column (~`app.py:231`):

```python
    country     = db.Column(db.String(2)) # ISO 3166-1 alpha-2 country code, e.g. "BR", "US"
    # The songs, as JSON: [{side, title, liked_at?}]. The side LETTER carries
    # which disc a song is on — disc 1 is A/B, disc 2 is C/D — so a double
    # needs no nesting and no disc field per track. Small enough to ride in the
    # record list (a 26-song double is about 1KB), unlike the covers that had
    # to become a URL.
    tracks      = db.Column(db.Text)
    disc_count  = db.Column(db.Integer, default=1)
    size        = db.Column(db.String(5))   # '' | '7' | '10' | '12', in inches
```

- [ ] **Step 4: Add the validators**

In `app.py`, above `class Record` (after `_sweep_note_images`, ~`app.py:193`):

```python
_SIDE_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_SIZES = {"", "7", "10", "12"}


def _disc_count(value, fallback=1):
    """A disc count is a whole number of discs, and there is always at least one."""
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return max(1, int(fallback or 1))


def _size(value):
    """An unknown size is '' — the collection genuinely does not know, and
    guessing 12" would put a fact in the database nobody checked."""
    v = str(value or "").strip()
    return v if v in _SIZES else ""


def _clean_tracks(raw, disc_count):
    """Validated tracks JSON, or ValueError naming what was wrong.

    A side letter outside the record's discs is refused rather than dropped: it
    is a song no surface would ever render, and swallowing it would hide the
    bug in the data instead of at the request that wrote it. An empty title is
    different — that is an unfilled row, and dropping it is what the form
    expects.
    """
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        raise ValueError("tracks is not valid JSON")
    if not isinstance(parsed, list):
        raise ValueError("tracks must be a list")

    allowed = set(_SIDE_LETTERS[: _disc_count(disc_count) * 2])
    out = []
    for t in parsed:
        if not isinstance(t, dict):
            continue
        title = str(t.get("title") or "").strip()
        if not title:
            continue
        side = str(t.get("side") or "").strip().upper()[:1]
        if side not in allowed:
            raise ValueError(
                f"side {side!r} is not on a record with {_disc_count(disc_count)} disc(s)")
        row = {"side": side, "title": title}
        liked = str(t.get("liked_at") or "").strip()
        if liked:
            row["liked_at"] = liked
        out.append(row)
    return json.dumps(out) if out else ""
```

- [ ] **Step 5: Extend `to_dict`**

In `app.py`, in `Record.to_dict()`, after the `country` entry:

```python
            "country": self.country or "",
            "tracks": self.tracks or "",
            "disc_count": self.disc_count or 1,
            "size": self.size or "",
```

- [ ] **Step 6: Extend the write endpoints**

In `create_record` (~`app.py:410`), replace the `Record(...)` construction's tail and wrap it:

```python
def create_record():
    d = request.get_json(silent=True) or {}
    disc_count = _disc_count(d.get("disc_count"))
    try:
        tracks = _clean_tracks(d.get("tracks", ""), disc_count)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    r = Record(
        ...                                   # every existing field, unchanged
        country     = (d.get("country") or "").strip().upper()[:2],
        tracks      = tracks,
        disc_count  = disc_count,
        size        = _size(d.get("size")),
    )
```

In `update_record` (~`app.py:438`), after the `country` line and before `db.session.commit()`:

```python
    if "country"     in d: r.country      = (d["country"] or "").strip().upper()[:2]
    # disc_count first: the tracks it is about to validate are checked against
    # it. A PUT that sends tracks alone is checked against what the record
    # already is, or every partial update to a double would reject its C side.
    if "disc_count"  in d: r.disc_count   = _disc_count(d["disc_count"], r.disc_count)
    if "size"        in d: r.size         = _size(d["size"])
    if "tracks"      in d:
        try:
            r.tracks = _clean_tracks(d["tracks"], r.disc_count)
        except ValueError as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 400
    db.session.commit()
```

- [ ] **Step 7: Add the migration and the CSV columns**

In the auto-migration block (~`app.py:296`), extend `missing_cols`:

```python
    missing_cols = {
        "country": "VARCHAR(2)",
        "play_dates": "TEXT",
        "cleaned_dates": "TEXT",
        "condition": "VARCHAR(10)",
        "cover_hash": "VARCHAR(64)",
        "tracks": "TEXT",
        "disc_count": "INTEGER",
        "size": "VARCHAR(5)",
    }
```

No backfill: every existing record genuinely has no tracklist, one disc by default and an unknown size.

In `export_csv` (~`app.py:867`), extend `cols`:

```python
    cols = ["id","artist","album_name","year","genre","bought_date","bought_where",
            "bought_by","condition","my_rating","wife_rating","have_it","play_count","play_dates","cleaned_dates","cover_image_base64","notes","country","note_images","tracks","disc_count","size"]
```

In `_record_mapping` (~`app.py:945`), after the `country` entry:

```python
        "country":     (row.get("country","") or "").strip().upper()[:2],
        # A CSV written before this feature simply has no such column, which is
        # not an error — the same rule _row_note_images already follows.
        "tracks":      row.get("tracks",""),
        "disc_count":  _disc_count(row.get("disc_count")),
        "size":        _size(row.get("size")),
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `python -m pytest tests/test_tracks_endpoint.py -v`
Expected: PASS, 12 tests

- [ ] **Step 9: Check nothing else broke**

Run: `python -m pytest tests/test_import.py tests/test_search_endpoint.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add app.py tests/test_tracks_endpoint.py
git commit -m "feat: tracks, disc_count and size on a record"
```

---

### Task 3: The grid — a double record announces itself

**Files:**
- Modify: `templates/index.html` — the `<script src>` block (~`templates/index.html:2586`), `cardHTML()` (~`templates/index.html:2760`), the card CSS

**Interfaces:**
- Consumes: `VinylTracks.discMarks(discCount)` from Task 1; `record.disc_count` from Task 2.
- Produces: `.vcard-sleeve` and `.vcard-spine` elements inside `.vcard-cover`.

- [ ] **Step 1: Load the module**

In `templates/index.html`, after the `notes.js` script tag (~line 2586):

```html
<script src="/static/notes.js"></script>
<script src="/static/tracks.js"></script>
```

Then, next to the other module aliases in the inline script (near `FILTER_DEPS`, ~line 2866), add:

```js
const { parseTracks, serializeTracks, sideLettersFor, discOfSide,
        tracksBySide, likedTracks, sidesWithTracks, discMarks,
        parsePastedTracklist } = VinylTracks;
```

- [ ] **Step 2: Add the CSS**

In `templates/index.html`, next to the other `.vcard-*` rules:

```css
/* A double record is two records. The stack changes the card's silhouette so
 * it reads from across the grid; the spine says HOW many. Both are drawn only
 * when there is more than one disc — a mark on all 250 cards is furniture the
 * eye stops seeing. */
.vcard-cover{padding-left:9px}
.vcard-sleeve{position:absolute;left:9px;right:0;top:0;bottom:0;border-radius:6px;
  background:var(--card-hover);box-shadow:0 3px 10px rgba(0,0,0,.4);pointer-events:none}
.vcard-sleeve.s1{transform:translate(5px,5px);z-index:0;filter:brightness(.6)}
.vcard-sleeve.s2{transform:translate(9px,9px);z-index:-1;filter:brightness(.4)}
.vcard-spine{position:absolute;left:0;top:0;bottom:0;width:5px;z-index:3;
  display:flex;flex-direction:column;gap:3px;pointer-events:none}
.vcard-spine i{flex:1;border-radius:3px;background:var(--accent);display:block}
```

- [ ] **Step 3: Draw the marks**

In `cardHTML()`, immediately after the `const cover = …` assignment:

```js
  // A double record is two records: sleeves peek out behind the cover and the
  // spine down its left edge carries one segment per disc. discMarks returns
  // zeroes for a single, so this whole block vanishes for most of the grid.
  const marks = discMarks(r.disc_count);
  const sleeves = Array.from({length: marks.sleeves},
    (_, k) => `<div class="vcard-sleeve s${k+1}"></div>`).join('');
  const spine = marks.segments
    ? `<div class="vcard-spine" title="${marks.segments} discs">` +
      Array.from({length: marks.segments}, () => '<i></i>').join('') + '</div>'
    : '';
```

Then in the returned template, inside `.vcard-cover`, put `${sleeves}` **before** `${cover}` and `${spine}` after it:

```js
    <div class="vcard-cover">
      ${sleeves}
      ${cover}
      ${spine}
      <div class="vcard-hover-info">
```

- [ ] **Step 4: Verify by eye**

Run the app (`python app.py`), open the grid, and set one record to two discs and one to three via the API:

```bash
curl -X PUT localhost:5000/api/records/1 -H 'Content-Type: application/json' -d '{"disc_count":2}'
```

Expected: that card grows one offset sleeve behind it and a two-segment gold bar on its left edge; every single-disc card is unchanged, with no bar at all.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html
git commit -m "feat: a double record shows its stack and spine in the grid"
```

---

### Task 4: The drawer — tabs, the Tracks tab, Format and the liked chip

**Files:**
- Modify: `templates/index.html` — `dmInfoHTML()` (~`templates/index.html:3290`), `dmSetCurrent()`, `openDetail()`, `closeDetail()`, the drawer CSS

**Interfaces:**
- Consumes: `parseTracks`, `tracksBySide`, `likedTracks` from Task 1; `r.tracks`, `r.disc_count`, `r.size` from Task 2.
- Produces: `detailTab` (module-level `'info' | 'tracks' | 'timeline'`), `setDetailTab(tab)`, `activeDetailTab(r)`, `dmTracksTabHTML(r)`, `formatLabel(r)`.

- [ ] **Step 1: Add the tab state and the fallback rule**

Near `let dmList = [], dmIdx = 0;` in `templates/index.html`:

```js
/* Which tab the drawer is showing. Sticky while the drawer is open, so paging
 * through records with the arrows does not throw you back to Info every time.
 *
 * Tracks is the default because it is what you open a record to see — but the
 * collection starts with no tracklists at all, so a record with none falls
 * back to Info rather than opening on an empty tab. */
let detailTab = 'tracks';

function activeDetailTab(r) {
  if (detailTab === 'tracks' && !parseTracks(r.tracks).length) return 'info';
  return detailTab;
}

function setDetailTab(tab) {
  detailTab = tab;
  const rec = records.find(x => x.id === currentDetailId);
  if (!rec) return;
  const info = document.getElementById('dmInfo');
  if (info) info.innerHTML = dmInfoHTML(rec);
  const ddInfo = document.getElementById('ddInfo');
  if (ddInfo) ddInfo.innerHTML = dmInfoHTML(rec);
}
```

- [ ] **Step 2: Add the CSS**

```css
.dm-tabs{display:flex;gap:2px;margin-top:12px;border-bottom:1px solid var(--border)}
.dm-tab{padding:7px 12px;font-size:10.5px;font-weight:700;letter-spacing:.06em;
  text-transform:uppercase;color:var(--muted);background:none;border:none;cursor:pointer;
  border-bottom:2px solid transparent;margin-bottom:-1px;font-family:var(--font)}
.dm-tab.on{color:var(--accent);border-bottom-color:var(--accent)}
.dm-tab:hover{color:var(--text)}

.tl-disc{font-size:9px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;
  color:var(--muted);margin:12px 0 4px}
.tl-side{display:flex;align-items:center;gap:8px;margin:10px 0 4px}
.tl-letter{width:18px;height:18px;border-radius:50%;background:var(--accent);color:var(--bg);
  font-size:10px;font-weight:800;display:flex;align-items:center;justify-content:center;flex:0 0 18px}
.tl-side .lbl{font-size:9.5px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.tl-side .rule{flex:1;height:1px;background:var(--border)}
.tl-row{display:flex;align-items:center;gap:9px;padding:4px 3px;border-radius:5px}
.tl-row:hover{background:var(--card-hover)}
.tl-row .num{width:14px;text-align:right;font-size:10.5px;color:var(--muted);
  font-variant-numeric:tabular-nums;flex:0 0 14px}
.tl-row .ttl{flex:1;font-size:12.5px;min-width:0}
.tl-row.liked .ttl{color:var(--text);font-weight:600}
.tl-row .when{font-size:9.5px;color:var(--muted);flex:0 0 auto}
.tl-empty{font-size:11px;color:var(--muted);padding:4px 3px 4px 26px;font-style:italic}
.tl-none{text-align:center;padding:26px 12px;color:var(--muted);font-size:12px}
```

- [ ] **Step 3: Split `dmInfoHTML` into a header plus the three tabs**

Replace the body of `dmInfoHTML(r)` (~`templates/index.html:3290`). The album line, artist line and rating bars stay exactly as they are and become the pinned header; everything below the bars moves into a tab.

```js
function dmInfoHTML(r) {
  const tab = activeDetailTab(r);
  const tabBtn = (id, label) =>
    `<button class="dm-tab${tab === id ? ' on' : ''}" onclick="setDetailTab('${id}')">${label}</button>`;
  return dmHeaderHTML(r) + `
    <div class="dm-tabs">
      ${tabBtn('info', 'Info')}${tabBtn('tracks', 'Tracks')}${tabBtn('timeline', 'Timeline')}
    </div>` +
    (tab === 'tracks'   ? dmTracksTabHTML(r)
   : tab === 'timeline' ? dmTimelineTabHTML(r)
   :                      dmInfoTabHTML(r));
}
```

`dmHeaderHTML(r)` is a straight lift of the top of the old function — the
`myR`/`herR`/`tot`/`totalStr` constants, the `bars` helper, and the `.dm-album`,
`.dm-artist` and `.dm-rates` markup — with nothing changed:

```js
function dmHeaderHTML(r) {
  const myR = Number(r.my_rating) || 0;
  const herR = Number(r.wife_rating) || 0;
  const tot = myR + herR;
  const totalStr = tot > 0 ? (tot % 1 === 0 ? tot : tot.toFixed(1)) : '—';
  // The bars ARE the control when you can edit. Changing a rating used to
  // cost four steps — open, edit, scroll past cover and purchase, save — while
  // the play count next to it had been one tap on the card all along.
  const bars = (v, who) => `<div class="dm-bars${authed ? ' live' : ''}">` +
    Array.from({length:5}, (_,i) => authed
      ? `<button class="${i < Math.round(v) ? 'f' : ''}" data-rate="${who}" data-rid="${r.id}" data-val="${i+1}" aria-label="${who} ${i+1} of 5"></button>`
      : `<i class="${i < Math.round(v) ? 'f' : ''}"></i>`).join('') + `</div>`;
  return `
    <div class="dm-album">${esc(r.album_name)||'untitled'}<span class="dm-year">${esc(r.year)||''}</span></div>
    <div class="dm-artist">${dmArtistHTML(r)}${isMultiArtist(r) ? multiArtistBadgeHTML() : ''}</div>
    <div class="dm-rates">
      <div class="dm-rate pepe"><div class="who">Pepe</div>${(myR>0||authed)?bars(myR,'my_rating'):'<span style="font-size:11px;color:var(--muted)">—</span>'}<div class="rv">${myR>0?myR+'/5':''}</div></div>
      <div class="dm-rate jenni"><div class="who">Jenni</div>${(herR>0||authed)?bars(herR,'wife_rating'):'<span style="font-size:11px;color:var(--muted)">—</span>'}<div class="rv">${herR>0?herR+'/5':''}</div></div>
      <div class="dm-total"><div class="who">Total</div><div class="tv">${totalStr}<small>/10</small></div></div>
    </div>`;
}
```

`dmInfoTabHTML(r)` is the rest of the old function — chips, metadata grid and
quick buttons — minus the history, plus a **liked** chip and a **Format** cell:

```js
function dmInfoTabHTML(r) {
  const countryStr = r.country
    ? `${flagImgHTML(r.country, 15)} ${countryLabelFromCode(r.country).replace(/\s*\([A-Z]{2}\)$/,'')}` : '—';
  const liked = likedTracks(parseTracks(r.tracks)).length;
  // Played and cleaned are offered only for a record that is actually here. A
  // wishlist entry is one nobody has yet, so logging either would be a claim
  // about a copy that does not exist.
  const canLog = authed && r.have_it;
  return `
    <div class="dm-chips">
      <span class="dm-chip plays"><span class="dm-dot"></span><b>${r.play_count||0}</b>&nbsp;plays</span>
      ${r.genre ? `<span class="dm-chip genre"><span class="dm-dot"></span>${esc(r.genre)}</span>` : ''}
      ${liked ? `<span class="dm-chip liked"><span class="dm-dot"></span><b>${liked}</b>&nbsp;liked</span>` : ''}
      ${r.have_it ? '' : '<span class="dm-chip wish"><span class="dm-dot"></span>wishlist</span>'}
    </div>
    <div class="dm-mgrid">
      <div class="dm-mcell"><label><i class="ti ti-calendar"></i>Bought</label><span>${boughtLabel(r)}</span></div>
      <div class="dm-mcell"><label><i class="ti ti-map-pin"></i>Bought at</label><span>${esc(r.bought_where||'—')}</span></div>
      <div class="dm-mcell"><label><i class="ti ti-certificate"></i>Condition</label><span>${conditionBadgeHTML(r)}</span></div>
      <div class="dm-mcell"><label><i class="ti ti-stack-2"></i>Format</label><span>${formatLabel(r)}</span></div>
      <div class="dm-mcell"><label><i class="ti ti-world"></i>Country</label><span>${countryStr}</span></div>
      <div class="dm-mcell"><label><i class="ti ti-droplet"></i>Last cleaned</label><span>${lastCleanedLabel(r)}</span></div>
    </div>
    ${canLog ? `<div class="dm-quick">
      <button class="dm-qbtn play" onclick="logPlayed(${r.id})">
        <i class="ti ti-headphones"></i>Played today
      </button>
      <button class="dm-qbtn clean" onclick="logCleaned(${r.id})">
        <i class="ti ti-droplet"></i>Cleaned today
      </button>
    </div>` : ''}`;
}
```

with, next to the other label helpers:

```js
/* Size and disc count in one cell rather than two: on a shelf they are one
 * fact. An unknown size says so instead of guessing 12". */
function formatLabel(r) {
  const discs = Math.max(1, Number(r.disc_count) || 1);
  const size = r.size ? `${r.size}"` : '';
  if (discs > 1 && size) return `${discs} × ${size}`;
  if (discs > 1)         return `${discs} discs`;
  return size || '—';
}
```

and the chip's dot colour:

```css
.dm-chip.liked .dm-dot{background:var(--ev-liked)}
```

`dmTimelineTabHTML(r)` is the existing history block, with its `<h4>History</h4>` heading dropped — the tab is the heading now:

```js
function dmTimelineTabHTML(r) {
  const groups = dmHistoryGroups(dmHistoryEvents(r));
  if (!groups.length) return '<div class="tl-none">nothing logged yet</div>';
  return `<div class="dm-history">${groups.map(dmHistoryGroupHTML).join('')}</div>`;
}
```

- [ ] **Step 4: Write the Tracks tab**

```js
function dmTracksTabHTML(r) {
  const list = parseTracks(r.tracks);
  if (!list.length) {
    return `<div class="tl-none">no tracklist yet
      ${authed ? `<div style="margin-top:10px">
        <button class="btn btn-sm" onclick="openEdit(${r.id});setFormStep(4)">
          <i class="ti ti-plus"></i> add the songs</button></div>` : ''}
    </div>`;
  }
  const discs = Math.max(1, Number(r.disc_count) || 1);
  const sides = tracksBySide(list, discs);
  let out = '';
  let lastDisc = 0;
  sides.forEach(side => {
    // Disc headers appear only on a record that has more than one. A single LP
    // shows sides A and B with no disc chrome at all.
    if (discs > 1 && side.disc !== lastDisc) {
      out += `<div class="tl-disc">Disc ${side.disc}</div>`;
      lastDisc = side.disc;
    }
    out += `<div class="tl-side"><span class="tl-letter">${side.letter}</span>
      <span class="lbl">Side ${side.letter}</span><span class="rule"></span></div>`;
    out += side.tracks.length
      ? side.tracks.map(t => dmTrackRowHTML(r, t)).join('')
      : '<div class="tl-empty">nothing on this side</div>';
  });
  return out;
}

function dmTrackRowHTML(r, t) {
  const on = !!t.liked_at;
  // The heart is the control when you can edit — the same call the rating bars
  // above it already make. Task 5 wires the handler; until then it renders.
  const heart = authed
    ? `<button class="tl-heart${on ? ' on' : ''}" onclick="toggleLike(${r.id}, ${t.i})"
         title="${on ? 'remove this like' : 'liked this one'}"
         aria-label="${on ? 'liked' : 'not liked'}"><i class="ti ti-heart${on ? '-filled' : ''}"></i></button>`
    : `<i class="ti ti-heart${on ? '-filled' : ''} tl-heart-static${on ? ' on' : ''}"></i>`;
  return `<div class="tl-row${on ? ' liked' : ''}">
    <span class="num">${t.pos}</span>
    <span class="ttl">${esc(t.title)}</span>
    ${on ? `<span class="when">${esc(dmFormatLikeDate(t.liked_at))}</span>` : ''}
    ${heart}
  </div>`;
}

/* '9 Sep' — short, because it sits at the end of a song title and the year is
 * almost always this one. The full stamp is in the Timeline tab. */
function dmFormatLikeDate(stamp) {
  const m = momentOf(stamp);
  if (!m.day) return '';
  const [y, mo, d] = m.day.split('-');
  return `${Number(d)} ${DM_MONTHS_PT[Number(mo)-1].slice(0,3)}`;
}
```

with the heart CSS:

```css
.tl-heart,.tl-heart-static{background:none;border:none;padding:2px;cursor:pointer;
  font-size:14px;color:var(--muted);opacity:.35;flex:0 0 auto;line-height:1}
.tl-heart:hover{opacity:1;color:var(--ev-liked)}
.tl-heart.on,.tl-heart-static.on{opacity:1;color:var(--ev-liked)}
.tl-heart-static{cursor:default}
```

`--ev-liked` is defined in Task 6; add it now in both theme blocks so this task renders correctly on its own:

```css
/* dark (~line 31) */  --ev-liked:#E05A5A;
/* light (~line 39) */ --ev-liked:#b33b3b;
```

- [ ] **Step 5: Reset the tab when the drawer closes**

In `closeDetail()`, alongside the other resets:

```js
  detailTab = 'tracks';
```

Opening a record should start on Tracks again; the stickiness is for paging within one session at the drawer, not across openings.

- [ ] **Step 6: Verify by eye**

Run the app. Expected:
- A record with no tracks opens on **Info**, and its Tracks tab shows *no tracklist yet* with an **add the songs** button when unlocked.
- Give a record tracks via `curl` and it opens on **Tracks**, sides labelled, disc headers absent on a single LP.
- The **Format** cell reads `—` for an untouched record, `12"` when a size is set, `2 × 12"` for a double.
- The **Timeline** tab holds what the History section used to.

- [ ] **Step 7: Commit**

```bash
git add templates/index.html
git commit -m "feat: the drawer gets Info, Tracks and Timeline tabs"
```

---

### Task 5: Liking a song from the drawer

**Files:**
- Modify: `templates/index.html` — a new `toggleLike()` and `editLikeDate()` next to `logPlayed()` (~`templates/index.html:6297`)

**Interfaces:**
- Consumes: `parseTracks`, `serializeTracks` from Task 1; `patchRecord(id, changes)` and `nowStamp()`, both existing.
- Produces: `toggleLike(id, i)`, `editLikeDate(id, i)`.

- [ ] **Step 1: Write the handler**

Next to `logPlayed()` and `logCleaned()` in `templates/index.html`:

```js
/* A heart is one tap, with no edit mode and no save — the same call the rating
 * bars in this drawer already make. Liking a song happens while the record is
 * spinning, and routing it through open-edit-scroll-tick-save is the four-step
 * problem those bars were introduced to kill.
 *
 * `i` is the index in the RAW track array, which is what every consumer
 * addresses a track by. */
function toggleLike(id, i) {
  const record = records.find(r => r.id === id);
  if (!record) return;
  const list = parseTracks(record.tracks);
  const t = list[i];
  if (!t) return;
  if (t.liked_at) delete t.liked_at; else t.liked_at = nowStamp();
  patchRecord(id, { tracks: serializeTracks(list) });
  toast(t.liked_at ? `Liked ${t.title}` : `Unliked ${t.title}`);
}

/* You already know which songs you love; the day you got round to marking one
 * is not the day you fell for it. */
function editLikeDate(id, i) {
  const record = records.find(r => r.id === id);
  if (!record) return;
  const list = parseTracks(record.tracks);
  const t = list[i];
  if (!t || !t.liked_at) return;
  const next = prompt(`When did you like ${t.title}?`, stampDay(t.liked_at));
  if (next === null) return;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(next.trim())) { toast('use YYYY-MM-DD'); return; }
  t.liked_at = next.trim();
  patchRecord(id, { tracks: serializeTracks(list) });
}
```

- [ ] **Step 2: Make the date clickable**

In `dmTrackRowHTML` from Task 4, replace the `when` span with an editable one when authed:

```js
    ${on ? (authed
      ? `<button class="when when-btn" onclick="editLikeDate(${r.id}, ${t.i})"
           title="change the date">${esc(dmFormatLikeDate(t.liked_at))} <i class="ti ti-pencil"></i></button>`
      : `<span class="when">${esc(dmFormatLikeDate(t.liked_at))}</span>`) : ''}
```

```css
.when-btn{background:none;border:none;cursor:pointer;font-family:var(--font);padding:0}
.when-btn:hover{color:var(--accent)}
.when-btn i{font-size:10px;opacity:.6}
```

- [ ] **Step 3: Verify by eye**

Run the app, unlock edit mode, open a record with tracks. Expected:
- Tapping an outline heart fills it, shows today's date, and toasts `Liked <title>`.
- Reloading the page keeps it — the write reached the server.
- Tapping a filled heart clears both.
- Clicking the date and entering `2026-08-02` moves it; entering nonsense toasts `use YYYY-MM-DD` and changes nothing.
- With edit mode locked, hearts render but are not buttons.

- [ ] **Step 4: Check the optimistic rollback**

Stop the Flask server, then tap a heart. Expected: the heart fills, then reverts, and a toast reads `Could not save — …`. This is `patchRecord`'s existing rollback; the test is that `tracks` is included in the `before` snapshot it takes, which it is, because `patchRecord` snapshots by the keys of `changes`.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html
git commit -m "feat: like a song with one tap from the drawer"
```

---

### Task 6: Likes in the Timeline, the Calendar and the drawer's history

**Files:**
- Modify: `static/timeline.js` — `ALL_TYPES`, `TYPE_ORDER`, `eventsByDay()`
- Modify: `tests/test_timeline.js`
- Modify: `templates/index.html` — `TIMELINE_DEPS` (~`templates/index.html:8013`), `calTypes` (~`templates/index.html:7966`), the calendar type buttons (~`templates/index.html:1890`), `dmHistoryEvents()` (~`templates/index.html:3470`), `DM_HIST_LABEL` / `DM_HIST_ICON`, the `--ev-*` CSS

**Interfaces:**
- Consumes: `parseTracks` from Task 1.
- Produces: events of `type: 'liked'` carrying `{ r, i, title }`, keyed `liked:<stamp>:<i>`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_timeline.js`:

```js
// ── likes ───────────────────────────────────────────────────────────────────

const { parseTracks } = require('../static/tracks.js');
const LIKE_DEPS = { parseTracks };

test('a liked song is an event on the day it was liked', () => {
  const r = { id: 1, tracks: JSON.stringify([
    { side: 'A', title: 'Mother', liked_at: '2026-08-02T21:40:00' }]) };
  const days = VinylTimeline.eventsByDay([r], null, LIKE_DEPS);
  const evs = days.get('2026-08-02').filter(e => e.type === 'liked');
  assert.strictEqual(evs.length, 1);
  assert.strictEqual(evs[0].title, 'Mother');
  assert.strictEqual(evs[0].i, 0);
});

test('an unliked song produces no event', () => {
  const r = { id: 1, tracks: JSON.stringify([{ side: 'A', title: 'Mother' }]) };
  const days = VinylTimeline.eventsByDay([r], null, LIKE_DEPS);
  assert.strictEqual(days.size, 0);
});

test('a like key is the type, the stamp and the RAW track index', () => {
  assert.strictEqual(VinylTimeline.keyOf('liked', '2026-08-02', 3), 'liked:2026-08-02:3');
});

test('likes can be switched off like any other type', () => {
  const r = { id: 1, tracks: JSON.stringify([
    { side: 'A', title: 'Mother', liked_at: '2026-08-02' }]) };
  const days = VinylTimeline.eventsByDay([r], { bought: true }, LIKE_DEPS);
  assert.strictEqual(days.size, 0);
});

test('a record with no tracks column never throws', () => {
  const days = VinylTimeline.eventsByDay([{ id: 1 }], null, LIKE_DEPS);
  assert.strictEqual(days.size, 0);
});

test('a like ranks between a play and a note', () => {
  // You hear the song, you like it, then you write about it.
  const o = VinylTimeline.TYPE_ORDER;
  assert.ok(o.played < o.liked && o.liked < o.note);
});

test('within a day the order reads played, then liked, then noted', () => {
  const r = {
    id: 1,
    play_dates: JSON.stringify(['2026-08-02T20:00:00']),
    notes: JSON.stringify([{ date: '2026-08-02', text: 'what a side' }]),
    tracks: JSON.stringify([{ side: 'A', title: 'Mother', liked_at: '2026-08-02T20:30:00' }]),
  };
  const deps = Object.assign({
    parsePlayDates: (raw) => JSON.parse(raw || '[]'),
    parseNotes: (raw) => JSON.parse(raw || '[]'),
  }, LIKE_DEPS);
  const evs = VinylTimeline.eventsByDay([r], null, deps).get('2026-08-02');
  assert.deepStrictEqual(evs.map(e => e.type), ['played', 'liked', 'note']);
});
```

> **Existing assertions:** the last test changes `note`'s rank from 3 to 4. Any
> existing assertion in `tests/test_timeline.js` that pins same-day ordering
> must be **read and updated deliberately**, not patched until green — the new
> expected order is bought, cleaned, played, liked, note.

- [ ] **Step 2: Run the test to verify it fails**

Run: `node --test tests/test_timeline.js`
Expected: FAIL — the `liked` events are missing

- [ ] **Step 3: Add the type**

In `static/timeline.js`:

```js
  const ALL_TYPES = { bought: true, cleaned: true, played: true, liked: true, note: true };

  /* bought before it is cleaned, cleaned before it is played, and any note
   * last. A like sits between the play and the note: you hear the song, you
   * like it, then you write about it. */
  const TYPE_ORDER = { bought: 0, cleaned: 1, played: 2, liked: 3, note: 4 };
```

In `eventsByDay()`, with the other dep unpacking:

```js
    const parseTracks = (deps && deps.parseTracks) || (() => []);
```

and inside the per-record loop, after the `played` line:

```js
      // The raw index again, exactly as for notes: a track with an empty title
      // still holds its slot, so filtering before indexing would renumber
      // every song after it and break keys already handed out.
      if (on.liked) parseTracks(r.tracks).forEach((t, i) => {
        if (t.liked_at) add(t.liked_at, { type: 'liked', r, i, title: t.title });
      });
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node --test tests/test_timeline.js`
Expected: PASS

- [ ] **Step 5: Hand the dep in, and switch the type on**

In `templates/index.html`, `TIMELINE_DEPS` (~line 8013):

```js
const TIMELINE_DEPS = {
  parsePlayDates: (raw) => parsePlayDates(raw),
  parseCleanedDates: (raw) => parseCleanedDates(raw),
  parseNotes: (raw, fallback) => parseNotes(raw, fallback),
  parseTracks: (raw) => parseTracks(raw),
};
```

`calTypes` (~line 7966):

```js
let calTypes = { bought: true, cleaned: true, played: true, liked: true, note: true };
```

The type buttons (~line 1890), after the `played` button:

```html
<button class="cal-type-btn active" data-type="liked" onclick="toggleCalType('liked')" title="liked songs" aria-label="liked songs"><i class="ti ti-heart"></i></button>
```

and its colour rule next to the others (~line 1625):

```css
.cal-type-btn.active[data-type="liked"] i{color:var(--ev-liked)}
```

- [ ] **Step 6: Add likes to the drawer's own history**

In `dmHistoryEvents(r)` (~line 3470), after the play-dates line:

```js
  parseTracks(r.tracks).forEach((t, i) => {
    if (t.liked_at) add('liked', t.liked_at, { i, title: t.title });
  });
```

and the label, icon and dot colour:

```js
const DM_HIST_LABEL = { bought:'Added to the collection', played:'Played',
                        cleaned:'Cleaned', liked:'Liked', note:'Note' };
const DM_HIST_ICON  = { bought:'ti-shopping-bag', played:'ti-headphones',
                        cleaned:'ti-droplet', liked:'ti-heart-filled', note:'ti-note' };
```

```css
.dm-hist-entry.liked .dot{background:var(--ev-liked)}
.dm-hist-entry.liked.hit{--hc:var(--ev-liked)}
```

A `liked` entry must name its song, which the existing non-note branch of
`dmHistoryEntryHTML` cannot do — it renders an icon and a clock and nothing
else. Add a branch between the two that are there:

```js
  const body = ev.type === 'note'
    ? /* …the existing note branch, unchanged… */
    : ev.type === 'liked'
    ? `<div class="ht"><i class="ti ${DM_HIST_ICON.liked} dm-hist-icon" title="${DM_HIST_LABEL.liked}"></i>` +
      `<span class="dm-hist-song">${esc(ev.title || '')}</span>${clock}</div>`
    : `<div class="ht"><i class="ti ${DM_HIST_ICON[ev.type]} dm-hist-icon" title="${DM_HIST_LABEL[ev.type]}"></i>${clock}</div>`;
```

```css
.dm-hist-song{font-size:12px;font-weight:600;color:var(--text);margin-left:6px}
```

- [ ] **Step 7: Verify by eye**

Run the app. Expected: liking a song puts a heart entry on today in the **Calendar**, in the **History** tab and in the record's own **Timeline** tab, reading *Liked **Mother***; the calendar's heart button switches them off and on.

- [ ] **Step 8: Commit**

```bash
git add static/timeline.js tests/test_timeline.js templates/index.html
git commit -m "feat: a like is an event in the calendar, the history and the drawer"
```

---

### Task 7: Searching by song

**Files:**
- Modify: `static/filters.js` — `DEFAULT_FIELDS`, `haystack()`
- Modify: `tests/test_filters.js`
- Modify: `templates/index.html` — `searchFields` (~`templates/index.html:2595`), the search-fields panel (~`templates/index.html:1818`), `FILTER_DEPS` (~`templates/index.html:2866`)

**Interfaces:**
- Consumes: `parseTracks` from Task 1.
- Produces: a `song` key in the query's `fields`, default `false`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_filters.js`:

```js
// ── searching by song ───────────────────────────────────────────────────────

const { parseTracks } = require('../static/tracks.js');
const SONG_DEPS = { parseTracks };

const withSongs = {
  artist: 'Pink Floyd', album_name: 'The Wall',
  tracks: JSON.stringify([{ side: 'A', title: 'Mother' }]),
};

test('song search is off by default', () => {
  assert.strictEqual(VinylFilters.DEFAULT_FIELDS.song, false);
});

test('with song off, a song title does not match', () => {
  const q = Object.assign(VinylFilters.defaultQuery(), { text: 'mother' });
  assert.strictEqual(VinylFilters.matches(withSongs, q, SONG_DEPS), false);
});

test('with song on, a song title matches its record', () => {
  const q = Object.assign(VinylFilters.defaultQuery(), { text: 'mother' });
  q.fields.song = true;
  assert.strictEqual(VinylFilters.matches(withSongs, q, SONG_DEPS), true);
});

test('song search is case-insensitive and matches a fragment', () => {
  const q = Object.assign(VinylFilters.defaultQuery(), { text: 'OTHE' });
  q.fields.song = true;
  assert.strictEqual(VinylFilters.matches(withSongs, q, SONG_DEPS), true);
});

test('a record with no tracks never throws when song search is on', () => {
  const q = Object.assign(VinylFilters.defaultQuery(), { text: 'mother' });
  q.fields.song = true;
  assert.strictEqual(VinylFilters.matches({ artist: 'x', album_name: 'y' }, q, SONG_DEPS), false);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node --test tests/test_filters.js`
Expected: FAIL — `DEFAULT_FIELDS.song` is `undefined`

- [ ] **Step 3: Add the field**

In `static/filters.js`:

```js
  const DEFAULT_FIELDS = {
    artist: true, album: true, genre: false, notes: false, bought_at: false,
    song: false,
  };
```

and in `haystack()`, after the notes branch:

```js
    if (fields.song) {
      const parse = (deps && deps.parseTracks) || (() => []);
      parts.push(parse(record.tracks).map(t => (t && t.title) || '').join(' '));
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node --test tests/test_filters.js`
Expected: PASS

- [ ] **Step 5: Wire the UI**

`templates/index.html` — `searchFields` (~line 2595):

```js
let searchFields = { artist: true, album: true, genre: false, notes: false,
                     bought_at: false, song: false };
```

the panel (~line 1818), after the Notes checkbox:

```html
<label class="search-field-check"><input type="checkbox" id="searchField_song" onchange="toggleSearchField('song')"><span>Song</span></label>
```

`FILTER_DEPS` (~line 2866):

```js
const FILTER_DEPS = {
  parseNotes: (raw) => parseNotes(raw),
  parseTracks: (raw) => parseTracks(raw),
  get today() { return today(); },
};
```

- [ ] **Step 6: Verify by eye**

Run the app. Expected: the search panel's sixth checkbox, **Song**, is unticked
on load; typing a song title finds nothing until it is ticked, then the record
holding that song appears in the grid.

- [ ] **Step 7: Commit**

```bash
git add static/filters.js tests/test_filters.js templates/index.html
git commit -m "feat: search can read song titles, off by default"
```

---

### Task 8: The form — step 4, Tracklist

**Files:**
- Modify: `templates/index.html` — `FORM_STEPS` (~`templates/index.html:4637`), a new `.form-step[data-step="4"]` block (after ~line 4636 in the markup, following step 3), `formValues()` (~`templates/index.html:4589`), `applyDraft()` (~`templates/index.html:4479`), `openEdit()` (~`templates/index.html:4560`), `openForm()`/`closeForm()` resets

**Interfaces:**
- Consumes: `parseTracks`, `serializeTracks`, `sideLettersFor`, `tracksBySide`, `sidesWithTracks`, `parsePastedTracklist` from Task 1.
- Produces: `formTracks` (array), `formDiscCount` (number), `formSize` (string), `renderTracksForm()`, `setFormSize(v)`, `setFormDiscCount(n)`, `addTrack(letter)`, `updateTrackTitle(i, v)`, `deleteTrack(i)`, `moveTrack(i, delta)`, `toggleFormLike(i)`, `applyPastedTracks(letter)`.

- [ ] **Step 1: Add the step**

`FORM_STEPS` (~line 4637):

```js
const FORM_STEPS = [
  { n: 1, label: 'Identify', sub: 'what record is this' },
  { n: 2, label: 'Acquire',  sub: 'how you got it' },
  { n: 3, label: 'Log',      sub: 'what happens to it' },
  { n: 4, label: 'Tracklist', sub: 'what is on it' },
];
```

The markup, after the `data-step="3"` block closes:

```html
<div class="form-step" data-step="4" hidden>
  <div class="form-step-lead">What is on it? Sides come from the disc count.</div>
  <div class="form-grid" style="margin-top:16px">
    <div class="form-group">
      <label><i class="ti ti-ruler-measure"></i> Size</label>
      <div class="seg-pick" id="fSizePick"></div>
    </div>
    <div class="form-group">
      <label><i class="ti ti-stack-2"></i> Discs</label>
      <div class="seg-pick" id="fDiscPick"></div>
    </div>
  </div>
  <div id="fTracksSides"></div>
</div>
```

```css
.seg-pick{display:flex;gap:4px}
.seg-pick button{flex:1;padding:6px 0;border:1px solid var(--border);border-radius:var(--radius-sm);
  background:var(--card);color:var(--muted);font-size:12px;font-family:var(--font);cursor:pointer}
.seg-pick button.on{background:var(--accent);border-color:var(--accent);color:var(--bg);font-weight:700}
.track-row{display:flex;align-items:center;gap:6px;margin-bottom:5px}
.track-row .tnum{width:26px;flex:0 0 26px;text-align:center;font-size:11px;color:var(--muted)}
.track-row input{flex:1;background:var(--bg);border:1px solid var(--border);
  border-radius:var(--radius-sm);padding:5px 8px;color:var(--text);font-size:12.5px;font-family:var(--font)}
.track-row button{background:none;border:none;color:var(--muted);cursor:pointer;font-size:14px;padding:2px}
.track-row .tlike.on{color:var(--ev-liked)}
.track-row button:hover{color:var(--accent)}
.track-paste{width:100%;background:var(--bg);border:1px dashed var(--border);
  border-radius:var(--radius-sm);padding:7px 9px;color:var(--text);font-size:12px;
  font-family:var(--font);min-height:56px;resize:vertical}
```

- [ ] **Step 2: Add the state and the renderer**

Next to `formNotes` / `formPlayDates`:

```js
let formTracks = [];
let formDiscCount = 1;
let formSize = '';

const SIZE_OPTIONS = ['7', '10', '12'];
const DISC_OPTIONS = [1, 2, 3];

function renderTracksForm() {
  document.getElementById('fSizePick').innerHTML = SIZE_OPTIONS.map(v =>
    `<button type="button" class="${formSize === v ? 'on' : ''}"
       onclick="setFormSize('${v}')">${v}"</button>`).join('');
  document.getElementById('fDiscPick').innerHTML = DISC_OPTIONS.map(n =>
    `<button type="button" class="${formDiscCount === n ? 'on' : ''}"
       onclick="setFormDiscCount(${n})">${n}</button>`).join('');

  const sides = tracksBySide(formTracks, formDiscCount);
  let html = '';
  let lastDisc = 0;
  sides.forEach(side => {
    if (formDiscCount > 1 && side.disc !== lastDisc) {
      html += `<div class="tl-disc">Disc ${side.disc}</div>`;
      lastDisc = side.disc;
    }
    html += `<div class="form-section"><header><i class="ti ti-disc"></i> Side ${side.letter}
      <span class="count">${side.tracks.length || 'empty'}</span></header><div class="sec-body">`;
    html += side.tracks.map(t => `
      <div class="track-row">
        <button type="button" onclick="moveTrack(${t.i}, -1)" title="move up"><i class="ti ti-chevron-up"></i></button>
        <span class="tnum">${t.pos}</span>
        <input value="${esc(t.title)}" placeholder="song title"
               onchange="updateTrackTitle(${t.i}, this.value)">
        <button type="button" class="tlike${t.liked_at ? ' on' : ''}" onclick="toggleFormLike(${t.i})"
          title="${t.liked_at ? 'liked' : 'mark as liked'}"><i class="ti ti-heart${t.liked_at ? '-filled' : ''}"></i></button>
        <button type="button" onclick="deleteTrack(${t.i})" title="remove"><i class="ti ti-x"></i></button>
      </div>`).join('');
    html += `<button type="button" class="playdate-add" onclick="addTrack('${side.letter}')">
      <i class="ti ti-plus"></i> add song</button>`;
    html += `<textarea class="track-paste" id="fPaste${side.letter}"
      placeholder="or paste a tracklist here — one song per line"></textarea>
      <button type="button" class="btn btn-sm" style="margin-top:5px"
        onclick="applyPastedTracks('${side.letter}')">
        <i class="ti ti-clipboard-text"></i> fill side ${side.letter}</button>`;
    html += `</div></div>`;
  });
  document.getElementById('fTracksSides').innerHTML = html;
  formChanged();
}
```

- [ ] **Step 3: Add the handlers**

```js
function setFormSize(v) {
  formSize = (formSize === v) ? '' : v;   // clicking the current one clears it
  renderTracksForm();
}

/* Lowering the disc count would orphan the songs on the sides that disappear.
 * Refuse, and say which sides to empty first — data loss must be an explicit
 * act, never a side effect of a picker. */
function setFormDiscCount(n) {
  const keeping = sideLettersFor(n);
  const orphaned = sidesWithTracks(formTracks).filter(s => keeping.indexOf(s) === -1);
  if (orphaned.length) {
    toast(`side ${orphaned.join(', ')} still has songs — empty it first`);
    return;
  }
  formDiscCount = n;
  renderTracksForm();
}

function addTrack(letter) {
  formTracks.push({ side: letter, title: '' });
  renderTracksForm();
}

function updateTrackTitle(i, value) {
  if (formTracks[i]) formTracks[i].title = value;
  formChanged();
}

function deleteTrack(i) {
  formTracks.splice(i, 1);
  renderTracksForm();
}

/* Swap with the neighbouring song ON THE SAME SIDE. The raw array interleaves
 * sides freely, so stepping one index can land on another side's song — which
 * would silently move a track across the record. */
function moveTrack(i, delta) {
  const t = formTracks[i];
  if (!t) return;
  const sameSide = formTracks
    .map((x, k) => ({ x, k }))
    .filter(o => o.x.side === t.side)
    .map(o => o.k);
  const at = sameSide.indexOf(i);
  const swapWith = sameSide[at + delta];
  if (swapWith === undefined) return;
  formTracks[i] = formTracks[swapWith];
  formTracks[swapWith] = t;
  renderTracksForm();
}

function toggleFormLike(i) {
  const t = formTracks[i];
  if (!t) return;
  if (t.liked_at) delete t.liked_at; else t.liked_at = nowStamp();
  renderTracksForm();
}

function applyPastedTracks(letter) {
  const box = document.getElementById('fPaste' + letter);
  if (!box) return;
  const titles = parsePastedTracklist(box.value);
  if (!titles.length) { toast('nothing to add'); return; }
  titles.forEach(title => formTracks.push({ side: letter, title }));
  box.value = '';
  renderTracksForm();
  toast(`${titles.length} song${titles.length > 1 ? 's' : ''} added to side ${letter}`);
}
```

- [ ] **Step 4: Wire save, edit and draft**

`formValues()` — add three keys next to `country`:

```js
    country:countryCodeFromInput(document.getElementById('fCountry').value),
    tracks:serializeTracks(formTracks),
    disc_count:formDiscCount,
    size:formSize,
```

`openEdit(id)` — alongside the other field loads:

```js
  formTracks = parseTracks(r.tracks);
  formDiscCount = Math.max(1, Number(r.disc_count) || 1);
  formSize = r.size || '';
  renderTracksForm();
```

`openForm()` (the add path) resets them:

```js
  formTracks = []; formDiscCount = 1; formSize = '';
  renderTracksForm();
```

`applyDraft(d)` — after the cleaned-dates block:

```js
  formTracks = parseTracks(d.tracks);
  formDiscCount = Math.max(1, Number(d.disc_count) || 1);
  formSize = d.size || '';
  renderTracksForm();
```

Because `rememberDraft()` saves `formValues()` wholesale, adding the three keys
there is all drafts need — a half-typed tracklist now survives a lost tab.

- [ ] **Step 5: Verify by eye**

Run the app, unlock edit mode. Expected:
- The wizard shows four steps; step 4 offers Size and Discs and two side blocks.
- Setting Discs to 2 grows sides C and D; setting it back to 1 with a song on C toasts *side C still has songs — empty it first* and leaves the picker at 2.
- Pasting `1. Mother\n02 - Hey You (4:40)` into side B's box and clicking **fill side B** adds two songs titled `Mother` and `Hey You`.
- The up-arrow on side B's second song swaps it with the first and never touches side A.
- Saving, reopening the record and returning to step 4 shows exactly what was saved.
- Typing a title, closing the tab and reopening offers the draft back with the tracklist intact.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests/ -v --ignore=tests/test_boot.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add templates/index.html
git commit -m "feat: build a tracklist in the form's fourth step"
```

---

### Task 9: Manual verification doc and the final run

**Files:**
- Create: `docs/tracklist-manual-verification.md`

- [ ] **Step 1: Write the doc**

Create `docs/tracklist-manual-verification.md`, following the seven existing
`*-manual-verification.md` docs in `docs/`:

```markdown
# Tracklists — what to check by hand

The automated tests cover the rules (`tests/test_tracks.js`), the endpoints
(`tests/test_tracks_endpoint.py`), the events (`tests/test_timeline.js`) and
the search field (`tests/test_filters.js`). What follows is what only an eye
can settle.

## The grid

1. Set one record to `disc_count: 2` and another to `3`.
2. Both grow sleeves behind the cover and a segmented gold bar down the left
   edge — one segment per disc.
3. **Every other card is unchanged, with no bar at all.** A mark on all 250
   cards is the failure this design exists to avoid.
4. At phone width the stack does not push a card into its neighbour.

## The drawer

5. A record with no tracklist opens on **Info**, not on an empty Tracks tab.
6. Its Tracks tab reads *no tracklist yet* and, unlocked, offers **add the
   songs** — which opens the form at step 4.
7. A record with songs opens on **Tracks**.
8. Paging with the arrows keeps you on the tab you chose, except where rule 5
   sends you back to Info.
9. A single LP shows sides A and B with **no** "Disc 1" heading; a double shows
   the disc headings.
10. The **Format** cell reads `—`, `12"` and `2 × 12"` in the three cases.

## Liking

11. Tapping an outline heart fills it and shows today's date. Reload: it is
    still there.
12. Tapping it again clears both.
13. Clicking the date accepts `2026-08-02` and rejects `hello`.
14. Locked (not in edit mode), hearts render but do not respond.
15. Stop the server, tap a heart: it fills, reverts, and says it could not save.

## The timeline

16. A like appears on its day in the **Calendar**, in the **History** tab and in
    the record's own **Timeline** tab, reading *Liked <song>*.
17. The calendar's heart button switches likes off and on.
18. On a day with a play, a like and a note, they read in that order.

## Search

19. The **Song** checkbox is unticked on load.
20. A song title finds nothing until it is ticked, then finds its record.

## The form

21. Discs 2 grows sides C and D.
22. Discs back to 1 with a song on side C refuses, naming side C.
23. Pasting `1. Mother` / `02 - Hey You (4:40)` yields `Mother` and `Hey You`.
24. The up-arrow swaps within a side and never moves a song across sides.
25. A half-typed tracklist survives closing and reopening the tab.

## The backup

26. `/api/export` then `/api/import` of that file preserves tracks, likes,
    disc count and size.
```

- [ ] **Step 2: Walk the doc**

Run the app and work through all 26 checks. Fix anything that fails before
continuing; a check that cannot be made to pass is a finding to report, not a
line to delete.

- [ ] **Step 3: Run everything**

Run: `python -m pytest tests/ -v --ignore=tests/test_boot.py`
Then: `node --test tests/test_tracks.js tests/test_timeline.js tests/test_filters.js`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add docs/tracklist-manual-verification.md
git commit -m "docs: what to check by hand for tracklists"
```

---

## Task dependency order

```
1 (rules) ──┬── 2 (backend) ──┬── 3 (grid)
            │                 ├── 4 (drawer tabs) ── 5 (liking)
            │                 └── 8 (form step 4)
            ├── 6 (timeline)   [needs 1 and 2; 5 to see it working]
            └── 7 (search)     [needs 1 and 2]
9 (verification) — last
```

Tasks 3, 6 and 7 are independent of each other once 1 and 2 land.
