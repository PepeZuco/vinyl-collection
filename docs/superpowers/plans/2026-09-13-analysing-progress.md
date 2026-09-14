# Analysing Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 12px "scanning…" spinner with a panel that names each stage of a scan as it happens, fed by real progress events streamed from `/api/scan`.

**Architecture:** `POST /api/scan` keeps returning today's JSON, and streams Server-Sent Events only when the caller sends `Accept: text/event-stream`. The route's existing pipeline is wrapped in a generator that emits a `step` event around each call it already makes, then one `done` event carrying the same body as the JSON path. The browser reads the stream with `fetch()` + a `ReadableStream` reader (not `EventSource`, which cannot POST a body), parses frames with a pure helper in `static/scanstream.js`, and paints a `.analysing` panel.

**Tech Stack:** Flask 3.0.3 (`stream_with_context`), SQLAlchemy, vanilla JS (no framework, no build step), `node --test` for JS unit tests run through pytest wrappers.

**Spec:** `docs/superpowers/specs/2026-09-13-analysing-progress-design.md`

## Global Constraints

- **Never break the JSON path.** Twelve test files POST to `/api/scan` and call `get_json()`. A request without `Accept: text/event-stream` must get byte-identical behaviour to today.
- **`stream_with_context` is mandatory** on the streaming response. The generator touches `db.session` (duplicate check, `_record_scan_spend`); without it the request context is gone and it raises.
- **Spend must be banked even when the client disconnects.** `_record_scan_spend(source, spent)` moves *inside* the generator's `finally`, which Flask runs on generator close.
- **Stage ids** are exactly: `vision`, `spotify`, `genre`, `mb`, `cover`, `vinyl`, `shelf`.
- **Row states** are exactly: `wait`, `run`, `done`, `skip`.
- **An unreachable MusicBrainz is `skip`, never `error`.** It is a normal outcome (`lookup_failed`).
- **Sprite positioning uses `--face` units, never percentages** — `calc(var(--face) * -N)`, matching `setAnalyseFrame` in `templates/index.html:7163`.
- **Restart `app.py` after every `templates/index.html` edit.** Flask caches the template; otherwise you debug a page the browser never received.
- **The JS boot suite hangs on this machine** unless run with `--test-force-exit`.
- New JS modules follow the house pattern: an IIFE assigned to a `Vinyl*` const, ending with `if (typeof module !== 'undefined' && module.exports) module.exports = <Name>;`

---

### Task 1: Progress seam in `lookup_musicbrainz`

The only change `scan.py` needs. Its MusicBrainz calls are internal (one search, then up to three artist-country lookups), so the route cannot count them from outside.

**Files:**
- Modify: `scan.py:403-439` (`lookup_musicbrainz`)
- Test: `tests/test_scan_musicbrainz.py`

**Interfaces:**
- Consumes: nothing
- Produces: `lookup_musicbrainz(artist: str, album: str, on_progress=None) -> list[dict]`. `on_progress` is `Callable[[int, int], None] | None`, called as `on_progress(done, total)` where `total` is the number of ranked candidates about to be detailed and `done` counts those finished. Called once with `(0, total)` right after the search returns, then once per candidate.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_scan_musicbrainz.py`:

```python
def test_on_progress_reports_the_search_then_each_candidate(monkeypatch):
    """The callback is the only way the route can count MusicBrainz work:
    the lookups are internal, so progress has to be pushed out."""
    groups = {"release-groups": [
        {"id": f"rg{i}", "title": "Africa Brasil", "first-release-date": "1976-01-01",
         "artist-credit": [{"artist": {"id": f"ar{i}", "name": "Jorge Ben"}}]}
        for i in range(3)]}
    monkeypatch.setattr(scan, "_mb_get", lambda path, params, **kw:
                        groups if path == "/release-group/" else {"country": "BR"})

    seen = []
    scan.lookup_musicbrainz("Jorge Ben", "Africa Brasil",
                            on_progress=lambda done, total: seen.append((done, total)))

    assert seen[0] == (0, 3), "the search finishing is itself progress"
    assert seen[-1] == (3, 3)
    assert [done for done, _ in seen] == [0, 1, 2, 3]


def test_on_progress_is_optional(monkeypatch):
    """Every existing caller passes nothing and must be unaffected."""
    monkeypatch.setattr(scan, "_mb_get", lambda path, params, **kw: {"release-groups": []})
    assert scan.lookup_musicbrainz("Jorge Ben", "Africa Brasil") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_scan_musicbrainz.py -k on_progress -v`
Expected: FAIL — `TypeError: lookup_musicbrainz() got an unexpected keyword argument 'on_progress'`

- [ ] **Step 3: Write minimal implementation**

In `scan.py`, change the signature and add three call sites:

```python
def lookup_musicbrainz(artist: str, album: str, on_progress=None) -> list[dict]:
```

Extend the docstring with:

```
    on_progress, when given, is called as on_progress(done, total) — once when
    the search returns and the candidate count is known, then once per
    candidate detailed. It exists so a streaming caller can show which of the
    four rate-limited lookups is in flight; these calls are internal and
    invisible from outside otherwise.
```

After `groups = ...` / `if not groups: return []`, replace the loop setup:

```python
    candidates = []
    country_cache: dict = {}
    ranked = _rank_candidates(groups, album, artist)[:3]
    # The search is itself one of the rate-limited lookups, so it counts as
    # progress the moment it lands — total is only knowable from here on.
    if on_progress:
        on_progress(0, len(ranked))
    for group in ranked:
```

and at the end of the loop body, after `candidates.append({...})`:

```python
        if on_progress:
            on_progress(len(candidates), len(ranked))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_scan_musicbrainz.py tests/test_scan_musicbrainz_reliability.py -v`
Expected: PASS, including every pre-existing test (they pass no `on_progress`).

- [ ] **Step 5: Commit**

```bash
git add scan.py tests/test_scan_musicbrainz.py
git commit -m "scan: optional on_progress seam in lookup_musicbrainz"
```

---

### Task 2: SSE frame formatting helper

A tiny pure function, separated so the route's generator reads as pipeline steps rather than string plumbing, and so frame syntax is tested once.

**Files:**
- Modify: `app.py` (add near the scan route, above `scan_record`)
- Test: `tests/test_scan_stream.py` (create)

**Interfaces:**
- Consumes: nothing
- Produces: `_sse(event: str, payload: dict) -> str` — returns `"event: <event>\ndata: <compact json>\n\n"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scan_stream.py`:

```python
"""The streaming half of /api/scan. The JSON half is covered by
tests/test_scan_endpoint.py and must keep behaving identically."""

import json

import app as app_module


def test_sse_frame_has_event_data_and_blank_line():
    frame = app_module._sse("step", {"id": "mb", "state": "run"})
    assert frame == 'event: step\ndata: {"id":"mb","state":"run"}\n\n'


def test_sse_payload_is_one_line_even_when_nested():
    """A newline inside the data would end the frame early and split one
    event into two unparseable halves."""
    frame = app_module._sse("done", {"candidates": [{"album_name": "A\nB"}]})
    body = [ln for ln in frame.split("\n") if ln.startswith("data: ")]
    assert len(body) == 1
    assert json.loads(body[0][6:])["candidates"][0]["album_name"] == "A\nB"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_scan_stream.py -v`
Expected: FAIL — `AttributeError: module 'app' has no attribute '_sse'`

- [ ] **Step 3: Write minimal implementation**

In `app.py`, immediately above `@app.route("/api/scan", ...)`:

```python
def _sse(event, payload):
    """One Server-Sent Events frame.

    separators keeps the JSON on a single line: a raw newline inside the data
    would terminate the frame early, and the client would see one event torn
    into two halves it cannot parse.
    """
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"
```

If `json` is not already imported in `app.py`, add `import json` with the other stdlib imports.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_scan_stream.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_scan_stream.py
git commit -m "scan: SSE frame helper"
```

---

### Task 3: Stream the scan route

The substantial task. The existing pipeline body moves into a generator; the JSON path is preserved by running the same generator and keeping only its `done` payload.

**Files:**
- Modify: `app.py:984-1088` (`scan_record`)
- Test: `tests/test_scan_stream.py`

**Interfaces:**
- Consumes: `_sse` (Task 2); `lookup_musicbrainz(..., on_progress=)` (Task 1)
- Produces: `POST /api/scan` with `Accept: text/event-stream` responds `text/event-stream` with a sequence of `step` frames, then exactly one `done` frame (payload identical to the JSON body) or one `error` frame `{"error": str, "status": int}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scan_stream.py`:

```python
import pytest
from unittest.mock import patch


SSE = {"Accept": "text/event-stream"}


def frames(response):
    """Parse an SSE body into [(event, payload), …]."""
    out = []
    for block in response.get_data(as_text=True).split("\n\n"):
        if not block.strip():
            continue
        event = data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        out.append((event, data))
    return out


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        with test_client.session_transaction() as session:
            session["authed"] = True
        yield test_client


@pytest.fixture(autouse=True)
def _pipeline_offline():
    """Every outbound call stubbed; these tests are about the event sequence."""
    with patch.object(app_module.scan, "extract_from_image",
                      return_value={"artist": "Jorge Ben", "album_name": "Africa Brasil",
                                    "genre": "Samba", "label": None, "catalog_number": None}), \
         patch.object(app_module.scan, "lookup_musicbrainz",
                      return_value=[{"mbid": "rg1", "year": "1976", "country": "BR",
                                     "artist": "Jorge Ben", "album_name": "Africa Brasil",
                                     "type": "Album", "label": None}]), \
         patch.object(app_module.scan, "fetch_cover", return_value=None), \
         patch.object(app_module.scan, "flag_vinyl",
                      side_effect=lambda rows, **kw: [r.setdefault("vinyl", "yes") for r in rows]), \
         patch.object(app_module.scan, "find_duplicate", return_value=None):
        yield


def test_photo_scan_streams_its_stages_in_order(client):
    got = frames(client.post("/api/scan", headers=SSE,
                             json={"image": "data:image/jpeg;base64,x"}))
    assert [e for e, _ in got][-1] == "done"
    ids = [p["id"] for e, p in got if e == "step" and p["state"] == "run"]
    assert ids == ["vision", "mb", "cover", "vinyl", "shelf"]


def test_done_payload_matches_the_json_path(client):
    streamed = frames(client.post("/api/scan", headers=SSE,
                                  json={"image": "data:image/jpeg;base64,x"}))[-1][1]
    plain = client.post("/api/scan", json={"image": "data:image/jpeg;base64,x"}).get_json()
    assert streamed == plain


def test_json_path_is_untouched_without_the_accept_header(client):
    response = client.post("/api/scan", json={"image": "data:image/jpeg;base64,x"})
    assert response.status_code == 200
    assert response.mimetype == "application/json"


def test_unreachable_musicbrainz_is_a_skip_not_an_error(client):
    with patch.object(app_module.scan, "lookup_musicbrainz",
                      side_effect=app_module.scan.MusicBrainzUnavailable("down")):
        got = frames(client.post("/api/scan", headers=SSE,
                                 json={"image": "data:image/jpeg;base64,x"}))
    assert not [e for e, _ in got if e == "error"]
    assert ("step", {"id": "mb", "state": "skip",
                     "detail": "MusicBrainz unavailable — no year or alternates"}) in got
    assert got[-1][0] == "done"
    assert got[-1][1]["lookup_failed"] is True


def test_a_bad_input_becomes_an_error_event_carrying_its_status(client):
    with patch.object(app_module.scan, "extract_from_image",
                      side_effect=ValueError("that is not a sleeve")):
        got = frames(client.post("/api/scan", headers=SSE,
                                 json={"image": "data:image/jpeg;base64,x"}))
    assert got[-1] == ("error", {"error": "that is not a sleeve", "status": 400})


def test_spend_is_banked_even_when_the_client_never_reads_the_stream(client):
    """Cancel abandons the result but not the bill — the call was billed the
    moment it returned. The generator's finally is what guarantees this."""
    with patch.object(app_module, "_record_scan_spend") as banked:
        client.post("/api/scan", headers=SSE, json={"image": "data:image/jpeg;base64,x"})
    assert banked.called
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_scan_stream.py -v`
Expected: FAIL — the streaming request returns `application/json`, so `frames()` finds no events.

- [ ] **Step 3: Write the implementation**

Restructure `scan_record` in `app.py`. Keep the 400 guard and the `rows`/`genres`/`source`/`spent` setup exactly as they are, then replace everything from the `try:` down to the final `return jsonify({...})` with a generator plus two exits:

```python
    def run():
        """The whole pipeline, yielding one frame per stage.

        A generator rather than straight-line code so the streaming and JSON
        paths are the same pipeline: there is no second copy to drift.
        """
        try:
            if image:
                yield _sse("step", {"id": "vision", "state": "run"})
                fields = scan.extract_from_image(image, genres, usage_out=spent)
                spotify_image = None
                yield _sse("step", {"id": "vision", "state": "done",
                                    "detail": f"{fields.get('artist') or '?'} — "
                                              f"{fields.get('album_name') or '?'}"})
            else:
                yield _sse("step", {"id": "spotify", "state": "run"})
                resolved = scan.extract_from_spotify(spotify_url)
                spotify_image = resolved.get("image_url")
                yield _sse("step", {"id": "spotify", "state": "done",
                                    "detail": f"{resolved['artist']} — {resolved['album_name']}"})
                yield _sse("step", {"id": "genre", "state": "run"})
                genre = scan.classify_genre(resolved["artist"], resolved["album_name"],
                                            genres, usage_out=spent)
                yield _sse("step", {"id": "genre", "state": "done", "detail": genre or "—"})
                fields = {"artist": resolved["artist"],
                          "album_name": resolved["album_name"],
                          "genre": genre, "label": None, "catalog_number": None}

            artist = fields.get("artist") or ""
            album = fields.get("album_name") or ""

            # Collected by the callback and drained after the call:
            # lookup_musicbrainz is not a generator, so it cannot yield.
            ticks = []
            yield _sse("step", {"id": "mb", "state": "run"})
            try:
                candidates = scan.lookup_musicbrainz(
                    artist, album, on_progress=lambda done, total: ticks.append((done, total)))
                lookup_failed = False
                for done, total in ticks:
                    yield _sse("step", {"id": "mb", "state": "run", "n": done, "of": total})
                yield _sse("step", {"id": "mb", "state": "done",
                                    "detail": f"{len(candidates)} pressing(s) found"
                                              if candidates else "no match on MusicBrainz"})
            except scan.MusicBrainzUnavailable:
                app.logger.warning("MusicBrainz unavailable for %r / %r", artist, album)
                candidates = []
                lookup_failed = True
                yield _sse("step", {"id": "mb", "state": "skip",
                                    "detail": "MusicBrainz unavailable — no year or alternates"})

            yield _sse("step", {"id": "cover", "state": "run"})
            for i, candidate in enumerate(candidates):
                yield _sse("step", {"id": "cover", "state": "run",
                                    "n": i + 1, "of": len(candidates)})
                candidate["cover_data"] = scan.fetch_cover(candidate, spotify_image)
            found = sum(1 for c in candidates if c.get("cover_data"))
            if candidates:
                yield _sse("step", {"id": "cover", "state": "done",
                                    "detail": f"{found} of {len(candidates)} had artwork"})
            else:
                yield _sse("step", {"id": "cover", "state": "skip",
                                    "detail": "nothing to fetch artwork for"})

            album_row = [{"mbid": None, "artist": artist, "album_name": album}]
            yield _sse("step", {"id": "vinyl", "state": "run"})
            scan.flag_vinyl(candidates or album_row, usage_out=spent)
            vinyl = (candidates or album_row)[0]["vinyl"]
            yield _sse("step", {"id": "vinyl", "state": "done", "detail": vinyl})

            yield _sse("step", {"id": "shelf", "state": "run"})
            existing = [{"id": r.id, "artist": r.artist or "",
                         "album_name": r.album_name or ""} for r in rows]
            duplicate = scan.find_duplicate(artist, album, existing)
            yield _sse("step", {"id": "shelf", "state": "done",
                                "detail": "already on your shelf" if duplicate
                                          else "not a duplicate"})

            year = candidates[0]["year"] if candidates else ""
            yield _sse("done", {
                "source": source,
                "artist": artist,
                "album_name": album,
                "genre": fields.get("genre") or "",
                "vinyl": vinyl,
                "candidates": candidates,
                "lookup_failed": lookup_failed,
                "duplicate_of": {"id": duplicate["id"], "artist": duplicate["artist"],
                                 "album_name": duplicate["album_name"]} if duplicate else None,
                "search_string": " ".join(p for p in [artist, album, year, "vinyl cover"] if p),
            })
        except ValueError as e:
            yield _sse("error", {"error": str(e), "status": 400})
        except RuntimeError as e:
            message = str(e)
            yield _sse("error", {"error": message,
                                 "status": 503 if "not set" in message else 502})
        except Exception as e:
            yield _sse("error", {"error": str(e), "status": 502})
        finally:
            # Inside the generator, not the route: Flask closes the generator
            # when the client disconnects, and a cancelled scan was still
            # billed the moment the API answered.
            _record_scan_spend(source, spent)

    if "text/event-stream" in (request.headers.get("Accept") or ""):
        return app.response_class(stream_with_context(run()),
                                  mimetype="text/event-stream",
                                  headers={"Cache-Control": "no-cache",
                                           "X-Accel-Buffering": "no"})

    # The JSON path runs the same generator and keeps only its last frame, so
    # the two can never answer differently.
    last = None
    for frame in run():
        last = frame
    event, _, data = last.partition("\ndata: ")
    payload = json.loads(data.strip())
    if event == "event: error":
        return jsonify({"error": payload["error"]}), payload["status"]
    return jsonify(payload)
```

- [ ] **Step 4: Run the full scan suite**

Run: `.venv/bin/python -m pytest tests/test_scan_stream.py tests/test_scan_endpoint.py tests/test_scan_spend.py tests/test_scan_spotify.py tests/test_scan_duplicates.py tests/test_scan_cover.py -v`
Expected: PASS. The pre-existing files are the regression guard on the JSON path — if any of them fails, the negotiation is wrong, not the test.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_scan_stream.py
git commit -m "scan: stream progress events when the client asks for them"
```

---

### Task 4: SSE frame parser

Pure string handling in its own module, following the `static/spend.js` pattern. Kept separate because chunk-splitting is the one piece of this whose edge cases are worth testing directly.

**Files:**
- Create: `static/scanstream.js`
- Create: `tests/test_scanstream.js`
- Create: `tests/test_scanstream.py`

**Interfaces:**
- Consumes: nothing
- Produces: `VinylScanStream.createParser()` returning `{push(chunk) -> [{event, data}, …]}`. `push` returns only the frames completed by that chunk and buffers any partial tail.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scanstream.js`:

```javascript
// Tests for the SSE frame parser behind the analysing panel.
// Run by tests/test_scanstream.py so `pytest` stays the single command.

const test = require('node:test');
const assert = require('node:assert');

const { createParser } = require('../static/scanstream.js');

test('one whole frame in one chunk', () => {
  const p = createParser();
  assert.deepStrictEqual(p.push('event: step\ndata: {"id":"mb"}\n\n'),
                         [{ event: 'step', data: { id: 'mb' } }]);
});

test('two frames in one chunk come back in order', () => {
  const p = createParser();
  const got = p.push('event: step\ndata: {"id":"a"}\n\nevent: step\ndata: {"id":"b"}\n\n');
  assert.deepStrictEqual(got.map(f => f.data.id), ['a', 'b']);
});

// The network decides where chunks break, not the server — a frame split
// mid-JSON must not be parsed until its blank line arrives.
test('a frame split across two chunks is held until complete', () => {
  const p = createParser();
  assert.deepStrictEqual(p.push('event: step\ndata: {"id":'), []);
  assert.deepStrictEqual(p.push('"mb"}\n\n'), [{ event: 'step', data: { id: 'mb' } }]);
});

test('a frame split exactly on its blank line is held', () => {
  const p = createParser();
  assert.deepStrictEqual(p.push('event: done\ndata: {"ok":true}\n'), []);
  assert.deepStrictEqual(p.push('\n'), [{ event: 'done', data: { ok: true } }]);
});

test('unparseable data is dropped rather than throwing', () => {
  const p = createParser();
  assert.deepStrictEqual(p.push('event: step\ndata: not json\n\n'), []);
});
```

Create `tests/test_scanstream.py`:

```python
"""Run the JavaScript SSE frame-parser tests under pytest.

Same arrangement as tests/test_spend.py: the parsing is pure, so it lives in
static/scanstream.js where a JS runtime can reach it, and pytest shells out.
"""

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_scanstream_js():
    result = subprocess.run(
        ["node", "--test", "tests/test_scanstream.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_scanstream.py -v`
Expected: FAIL — `Cannot find module '../static/scanstream.js'`

- [ ] **Step 3: Write minimal implementation**

Create `static/scanstream.js`:

```javascript
/* Reading the /api/scan progress stream.
 *
 * EventSource would do this for free, but it issues a GET and cannot carry a
 * body — the photo path posts a data URI of the sleeve, which is megabytes.
 * So the fetch body is read by hand and the frames parsed here.
 *
 * Pure string handling, kept out of index.html so it is testable: see
 * tests/test_scanstream.js. */
const VinylScanStream = (function () {

  /* Frames are separated by a blank line. The network decides where chunks
   * break, so anything after the last blank line is an incomplete frame and
   * is held until the rest of it arrives. */
  function createParser() {
    let buffer = '';
    return {
      push(chunk) {
        buffer += chunk;
        const blocks = buffer.split('\n\n');
        buffer = blocks.pop();          // the tail: incomplete until proven otherwise
        const frames = [];
        for (const block of blocks) {
          let event = null, data = null;
          for (const line of block.split('\n')) {
            if (line.startsWith('event: ')) event = line.slice(7);
            else if (line.startsWith('data: ')) data = line.slice(6);
          }
          if (!event || data === null) continue;
          try {
            frames.push({ event, data: JSON.parse(data) });
          } catch (e) {
            /* A frame we cannot read is dropped, not thrown: one malformed
             * event must not kill a scan the user already paid for. */
          }
        }
        return frames;
      },
    };
  }

  return { createParser };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylScanStream;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_scanstream.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add static/scanstream.js tests/test_scanstream.js tests/test_scanstream.py
git commit -m "scan: SSE frame parser for the progress stream"
```

---

### Task 5: Panel markup and CSS

Static structure only — no wiring. Copy from the approved mockup, which is already written against the app's own tokens.

**Files:**
- Modify: `templates/index.html` — CSS after the `.scan-hint` rule (~line 1086); markup replacing `#scanStatus` (lines 2903-2906)
- Reference: `static/mockup-analysing.html` (the approved design)

**Interfaces:**
- Consumes: nothing
- Produces: `#scanPanel` (the `.analysing` container, `hidden` by default), and inside it `.an-face`, `.an-n`, `.an-stage`, `.an-clock`, `.an-bar i`, `.an-steps`, `.an-cost`, `#scanCancelBtn`.

- [ ] **Step 1: Copy the CSS**

From `static/mockup-analysing.html`, copy the whole block between the `THE DESIGN UNDER REVIEW` banner comment and the `@media (prefers-reduced-motion:reduce)` rule — that is `.analysing`, `.an-head`, `.an-face`, `.an-title`, `.an-sub`, `.an-bar`, `.an-steps`, `.an-step`, `.an-badge`, the four `[data-src]` rules, `.an-body`, `.an-label`, `.an-detail`, `.an-pips`, `.an-foot`, `.an-cost`, `.an-cancel`, and the `.analysing.wide` block. Paste it into `templates/index.html` after the `.scan-hint` rule.

Then add the `skip` state, which the mockup does not have (it only ever showed the happy path):

```css
/* MusicBrainz being unreachable is a normal outcome, not a failure — the
   route degrades to lookup_failed on purpose. So a skipped stage reads as
   information: no colour, no alarm, just struck through and explained. */
.an-step.skip .an-badge{--fg:var(--muted);--bdr:var(--border);--bgc:transparent}
.an-step.skip .an-label > span:first-child{text-decoration:line-through;
  text-decoration-color:color-mix(in srgb,var(--muted) 60%,transparent);color:var(--label)}
.an-step.skip .an-detail{color:var(--muted);font-style:italic}
```

Add the reduced-motion rule alongside the app's existing ones:

```css
@media(prefers-reduced-motion:reduce){.an-step.run .an-badge{animation:none}}
```

- [ ] **Step 2: Replace the status markup**

Replace `templates/index.html:2903-2906` (the `#scanStatus` div) with:

```html
          <!-- A scan is a vision call, up to four rate-limited MusicBrainz
               lookups and up to three cover fetches. Rather than a spinner and
               a guess at the worst case, the panel names each stage as it
               happens and says which service is being asked. Painted from the
               event stream by paintScanPanel; see static/scanstream.js. -->
          <div class="analysing" id="scanPanel" hidden>
            <div class="an-head">
              <div class="an-face" id="scanPanelFace"></div>
              <div class="an-head-main">
                <div class="an-title">analysing<em class="an-n"></em></div>
                <div class="an-sub"><span class="an-stage">starting…</span><span class="dot">·</span><span class="an-clock">0.0s</span></div>
                <div class="an-bar"><i></i></div>
              </div>
            </div>
            <div class="an-steps"></div>
            <div class="an-foot">
              <!-- Not "nothing is charged until you pick": the call is billed
                   the moment it returns, and cancel does not refund it. -->
              <span class="an-cost"></span>
              <button type="button" class="an-cancel" id="scanCancelBtn"
                      onclick="cancelScan()"><i class="ti ti-x"></i> cancel</button>
            </div>
          </div>
```

- [ ] **Step 3: Restart Flask and eyeball it**

```bash
pkill -f "python app.py"; .venv/bin/python app.py &
```

Open `http://localhost:5000`, then in the browser console: `document.getElementById('scanPanel').hidden = false`. The panel should appear in the cover section with the face box empty (no stages rendered yet) and no layout break.

- [ ] **Step 4: Commit**

```bash
git add templates/index.html
git commit -m "scan: analysing panel markup and styles"
```

---

### Task 6: Wire the stream to the panel

**Files:**
- Modify: `templates/index.html` — `setScanBusy` (~7284), `runScan` (~7308), script tags (~3399)

**Interfaces:**
- Consumes: `VinylScanStream.createParser()` (Task 4); `#scanPanel` and children (Task 5); the streaming route (Task 3)
- Produces: `cancelScan()`, called by the cancel button's onclick.

- [ ] **Step 1: Load the module**

Add after the `spend.js` script tag in `templates/index.html`:

```html
<script src="/static/scanstream.js"></script>
```

- [ ] **Step 2: Add the stage table and painter**

Insert above `function setScanBusy(busy)`:

```javascript
// ── the analysing panel ─────────────────────────────────────────────────────
// Labels for the stages app.py streams. The order here is display order; the
// server decides which of them actually run, so the spotify-only stages simply
// never arrive on a photo scan.
const SCAN_STAGES = {
  photo:   ['vision', 'mb', 'cover', 'vinyl', 'shelf'],
  spotify: ['spotify', 'genre', 'mb', 'cover', 'vinyl', 'shelf'],
};
const STAGE_META = {
  vision:  {src:'claude',  icon:'ti-sparkles',        label:'reading the sleeve',      sub:'Claude vision'},
  spotify: {src:'spotify', icon:'ti-brand-spotify',   label:'reading the album',       sub:'Spotify API'},
  genre:   {src:'claude',  icon:'ti-tag',             label:'placing it in a genre',   sub:'Claude'},
  mb:      {src:'mb',      icon:'ti-database-search', label:'matching on MusicBrainz', sub:'release groups'},
  cover:   {src:'mb',      icon:'ti-photo-search',    label:'fetching cover art',      sub:'Cover Art Archive'},
  vinyl:   {src:'claude',  icon:'ti-vinyl',           label:'confirming it is vinyl',  sub:'Claude'},
  shelf:   {src:'shelf',   icon:'ti-checklist',       label:'checking your shelf',     sub:'local'},
};

let scanPanelState = {};
let scanPanelStart = 0;
let scanPanelRaf = 0;
let scanAbort = null;

function buildScanPanel(source){
  scanPanelState = {};
  const rows = SCAN_STAGES[source].map(id => {
    const m = STAGE_META[id];
    return `<div class="an-step wait" data-src="${m.src}" data-id="${id}">
      <div class="an-badge"><i class="ti ${m.icon}"></i></div>
      <div class="an-body">
        <div class="an-label"><span>${m.label}</span><span class="tail"></span></div>
        <div class="an-detail">${m.sub}</div>
        <div class="an-pips" hidden></div>
      </div></div>`;
  }).join('');
  document.querySelector('#scanPanel .an-steps').innerHTML = rows;
  document.querySelector('#scanPanel .an-cost').textContent =
    VinylSpend.scanHintText({armed: true, source, usage: scanUsage, verb: 'analyse'});
  document.getElementById('scanPanel').hidden = false;
}

// One step event. The server is the only source of truth for state here — the
// panel never advances a row on its own, so a stage that hangs visibly hangs.
function applyScanStep(p){
  const row = document.querySelector(`#scanPanel .an-step[data-id="${p.id}"]`);
  if(!row) return;
  scanPanelState[p.id] = p.state;
  row.classList.remove('wait','run','done','skip');
  row.classList.add(p.state);
  const tail = row.querySelector('.tail');
  const detail = row.querySelector('.an-detail');
  if(p.detail) detail.textContent = p.detail;
  tail.className = p.state === 'done' ? 'tail tick ti ti-check' : 'tail';
  if(p.of){
    const pips = row.querySelector('.an-pips');
    pips.hidden = false;
    if(pips.children.length !== p.of)
      pips.innerHTML = '<i></i>'.repeat(p.of);
    [...pips.children].forEach((el,i)=>el.classList.toggle('on', i < (p.n||0)));
    if(p.state === 'run' && p.n)
      detail.textContent = `${STAGE_META[p.id].sub} — ${p.n} of ${p.of}`;
  }
  const stages = [...document.querySelectorAll('#scanPanel .an-step')];
  const settled = stages.filter(r => r.classList.contains('done') || r.classList.contains('skip')).length;
  document.querySelector('#scanPanel .an-bar i').style.width =
    (settled / stages.length * 100) + '%';
  document.querySelector('#scanPanel .an-n').textContent = ` ${Math.min(settled+1, stages.length)}/${stages.length}`;
  if(p.state === 'run')
    document.querySelector('#scanPanel .an-stage').textContent = STAGE_META[p.id].sub;
}

// The face and the clock are the only things driven locally — everything else
// waits on the server. Same 30-frame strip and 1010ms cadence as the button's,
// positioned in --face units for the reason setAnalyseFrame gives.
function tickScanPanel(){
  const elapsed = performance.now() - scanPanelStart;
  document.getElementById('scanPanelFace').style.backgroundPositionX =
    `calc(var(--face) * ${-(Math.floor(elapsed / ANALYSE_MS * ANALYSE_FRAMES) % ANALYSE_FRAMES)})`;
  document.querySelector('#scanPanel .an-clock').textContent = (elapsed/1000).toFixed(1)+'s';
  scanPanelRaf = requestAnimationFrame(tickScanPanel);
}

function cancelScan(){
  // Abandons the result, not the bill: the call was billed the moment it
  // returned. Bumping scanToken is the same abandon path closeForm uses.
  scanToken++;
  if(scanAbort) scanAbort.abort();
  setScanBusy(false);
}
```

- [ ] **Step 3: Swap the panel into `setScanBusy`**

In `setScanBusy`, replace the `scanStatus` line:

```javascript
  document.getElementById('scanStatus').style.display = busy ? 'flex' : 'none';
```

with:

```javascript
  if(!busy){
    document.getElementById('scanPanel').hidden = true;
    cancelAnimationFrame(scanPanelRaf);
    scanPanelRaf = 0;
  }
```

The panel is shown by `buildScanPanel` rather than here, because it needs the source to know which stages to draw.

- [ ] **Step 4: Read the stream in `runScan`**

Replace the fetch-and-parse block inside `runScan`'s inner `try` — the four lines from `res = await fetch(...)` through `data = await res.json();` — with:

```javascript
      const source = body.spotify_url ? 'spotify' : 'photo';
      buildScanPanel(source);
      scanPanelStart = performance.now();
      cancelAnimationFrame(scanPanelRaf);
      scanPanelRaf = requestAnimationFrame(tickScanPanel);
      scanAbort = new AbortController();
      res = await fetch('/api/scan', {method:'POST',
        headers:{'Content-Type':'application/json', 'Accept':'text/event-stream'},
        body:JSON.stringify(body), signal: scanAbort.signal});
      const parser = VinylScanStream.createParser();
      const reader = res.body.getReader();
      const decode = new TextDecoder();
      let streamError = null;
      data = null;
      for(;;){
        const {value, done} = await reader.read();
        if(done) break;
        for(const frame of parser.push(decode.decode(value, {stream:true}))){
          if(frame.event === 'step') applyScanStep(frame.data);
          else if(frame.event === 'done') data = frame.data;
          else if(frame.event === 'error') streamError = frame.data;
        }
      }
      // The stream always answers 200, so an error arrives as an event. Shape
      // it back into what the code below already expects from !res.ok.
      if(streamError){
        res = {ok:false};
        data = {error: streamError.error};
      } else if(!data){
        throw new Error('stream ended without a result');
      } else {
        res = {ok:true};
      }
```

Everything after this — the `!res.ok` branch, the `myToken !== scanToken` guard, `applyScanResult(data)`, the `finally` — stays exactly as it is.

Finally, make the abort land in the existing `catch(e)`: an aborted fetch throws `AbortError`, which must not toast "scan failed" since the user asked for it. At the top of that `catch(e)` block add:

```javascript
      if(e.name === 'AbortError') return;   // the user cancelled; not a failure
```

- [ ] **Step 5: Restart Flask and run a real scan**

```bash
pkill -f "python app.py"; .venv/bin/python app.py &
```

Open `http://localhost:5000`, add a record, paste a Spotify album link and hit analyse. Confirm: the panel appears, the face spins at 128px, stages light up one at a time in the order `spotify → genre → mb → cover → vinyl → shelf`, the MusicBrainz row shows pips, and the results overlay opens as before. Then run one more and hit cancel mid-scan — the panel closes, no error toast, and the month's spend in the form's hint line still goes up.

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. If `tests/test_boot.js` hangs, it needs `--test-force-exit`.

- [ ] **Step 7: Commit**

```bash
git add templates/index.html
git commit -m "scan: paint the analysing panel from the progress stream"
```

---

### Task 7: Retire the mockup

**Files:**
- Delete: `static/mockup-analysing.html`
- Modify: `docs/photo-scan-manual-verification.md`

**Interfaces:**
- Consumes: a working panel (Task 6)
- Produces: nothing

- [ ] **Step 1: Delete the mockup**

```bash
git rm static/mockup-analysing.html
```

`static/analyse-sprite-128.png` stays — it is the panel's sprite now, not the mockup's.

- [ ] **Step 2: Add the manual verification steps**

Append to `docs/photo-scan-manual-verification.md`, matching the file's existing style:

```markdown
## Analysing progress panel

1. Open the form, attach a sleeve photo, tap Analyse.
   - The panel replaces the cover area: 128px thinking face on desktop, 84px on phone.
   - Stages light up in order: reading the sleeve → matching on MusicBrainz →
     fetching cover art → confirming it is vinyl → checking your shelf.
   - Each badge takes its service's colour only once that stage starts.
2. Paste a Spotify link instead.
   - The first two stages are "reading the album" (green Spotify badge) and
     "placing it in a genre" — the photo path's vision stage never appears.
3. Hit cancel mid-scan.
   - The panel closes, no error toast appears, and the spend on the hint line
     still increases: the call was billed the moment it returned.
4. With MusicBrainz unreachable (block `musicbrainz.org` in /etc/hosts):
   - The MusicBrainz row goes grey and struck through, reading
     "MusicBrainz unavailable — no year or alternates".
   - The scan still finishes and the form still fills from the sleeve.
```

- [ ] **Step 3: Commit**

```bash
git add -A docs/photo-scan-manual-verification.md static/mockup-analysing.html
git commit -m "scan: retire the analysing mockup, document the panel"
```

---

## Self-Review

**Spec coverage:** Content negotiation → Task 3. Why-not-EventSource → Task 4. Event shape → Tasks 2, 3. Errors-in-stream → Task 3. `stream_with_context` + spend-in-`finally` → Task 3. Progress sources → Tasks 1, 3. Panel (head/steps/foot) → Tasks 5, 6. Sprite → already committed; retained by Task 7. Testing (five Python cases, three JS cases) → Tasks 1-4. Out-of-scope items (`/api/search`, server-side abort, worker occupancy) → no tasks, correctly.

**Placeholder scan:** None. Every code step carries the code.

**Type consistency:** `on_progress(done, total)` defined in Task 1, consumed in Task 3. `_sse(event, payload)` defined in Task 2, consumed in Task 3. `createParser().push(chunk) -> [{event, data}]` defined in Task 4, consumed in Task 6. Stage ids and row states match the Global Constraints across Tasks 3, 5 and 6. `scanToken`, `scanUsage`, `ANALYSE_MS`, `ANALYSE_FRAMES` and `VinylSpend.scanHintText` are pre-existing in `templates/index.html`.

**One gap found and closed:** the spec's `skip` state had no CSS in the mockup (which only drew the happy path), so Task 5 Step 1 now writes those three rules explicitly rather than saying "copy the mockup".
