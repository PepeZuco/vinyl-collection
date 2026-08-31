# Pictures on Notes

## Problem

Notes are text only. A note wants to carry photos — the sleeve corner it
describes, the receipt, the shop it was bought in — added the same two ways a
record's cover already can be: an upload, or the device camera.

The constraint that shapes the whole design is payload size. Covers were
deliberately moved out of `/api/records`: `cover_data` is deferred in the list
query (`app.py:236`), the row advertises a `cover_url` computed from a stored
`cover_hash`, and the bytes are served by `/api/records/<id>/cover`. That exists
because inlining base64 covers made the list a 45MB response that blocked the
first paint (`app.py:89-93`).

`notes` is **not** deferred. It loads in full for every record, because six
consumers read it straight off the list payload: the form (`parseNotes`), the
detail history, the calendar, `activity.js`, `filters.js`, and `timeline.js`.
Putting base64 images in the notes JSON would rebuild the exact problem the
cover architecture exists to prevent.

So: image bytes live outside the notes column, and the notes JSON carries only
references.

## Storage

A new table. One row per distinct image, keyed by its own content hash.

```python
class NoteImage(db.Model):
    id      = db.Column(db.String(32), primary_key=True)  # sha256(data)[:32]
    data    = db.Column(db.Text)        # base64 data URI, same shape as cover_data
    created = db.Column(db.String(50))  # stamp — see the reap grace window below
```

**The id is the content hash**, which is not what covers do and is deliberate.
A cover's URL is keyed by a *record*, so the URL's meaning changes when the
cover does, and it needs `?v=<hash>` to bust the cache. An image id is keyed by
*content*, so `/api/note-images/<id>` can never mean anything else: the response
is `Cache-Control: immutable`, there is no cache-buster, and there is no second
hash column to keep in step with the data. Two identical photos collapse to one
row for free, and a CSV round-trip carries ids verbatim with no remapping.

The table is created by `db.create_all()`, which handles missing *tables*
without help. Unlike the `record` column additions, no `ALTER TABLE` entry in
the auto-migration block is needed.

## Notes JSON

One new optional key:

```json
[{"date": "2026-08-30T14:05:00", "text": "sleeve has a seam split", "images": ["a3f19c…"]}]
```

`images` absent reads as `[]` everywhere. Every note written before this feature,
and the legacy plain-string migration in `parseNotes`, keep working with no
backfill.

The list payload grows by 32 bytes per photo, not ~150KB.

## Endpoints

`POST /api/note-images` — auth required, body `{data: "data:image/jpeg;base64,…"}`,
returns `{id}`.

- Rejects anything not starting with `data:`, and anything over a 2MB cap.
  The cap is new — covers have no server-side limit, relying on the client
  resize to bound them — and is here because this is a new write endpoint whose
  body is attacker-controlled.
- Computes the hash; if that id already exists, returns it without a second
  write. Uploading the same photo twice is a no-op.

`GET /api/note-images/<id>` — serves bytes and mimetype via the existing decoder
(`_decode_cover`, renamed `_decode_data_uri` since it was never cover-specific).
An unknown id or a malformed stored payload returns 404 rather than raising,
matching `record_cover`'s stance that a broken image is an absent image.

There is no DELETE. An image is deleted when no note refers to it — see below.

## Reaping

Two paths, because there are two ways an image can stop being referenced.

**On record save** (`POST /api/records`, `PUT /api/records/<id>` when `notes` is
present): diff the ids in the record's stored notes against the ids in the
incoming notes. For each dropped id, delete the row **only after** confirming no
other record's notes mention it — one `LIKE '%<id>%'` query over `notes`, cheap
because notes are small. That guard is load-bearing rather than defensive:
content-hash ids mean two records that photograph the same thing share a row,
and deleting on the first record's say-so would blank the second.

**At boot**: delete images that no note anywhere references and that are older
than a grace window (6 hours). This catches photos uploaded into a form the user
then abandoned. The window is what keeps the sweep from deleting an image
belonging to a form that is open right now.

## CSV import / export

A new trailing column, `note_images`, holding a JSON object of `id → data URI`
containing only the images that row's notes reference.

Export builds it per row. Import wipes `NoteImage` alongside `Record` inside the
existing single transaction — `import_records_from_csv_rows` already replaces the
whole collection and rolls back as a unit, and note images must not survive a
restore that removed the notes pointing at them. Rows are inserted in the same
`_IMPORT_BATCH_ROWS` batches, since note images have the same memory profile as
covers.

A CSV without the column imports cleanly: `row.get("note_images","")` yields no
images. A value that is not valid JSON is treated as no images rather than
raising, consistent with how a malformed cover is handled.

Duplicate ids across rows are expected (dedupe), so the import inserts each
distinct id once.

## New module: `static/notes.js`

`parseNotes` and `serializeNotes` live inline in `templates/index.html` and are
injected into the extracted modules as deps (`FILTER_DEPS`, `TIMELINE_DEPS`).
They move into `static/notes.js`, following the precedent of `static/cover.js` —
a module exists there for exactly this reason, to make form-save logic testable.

The extraction is not cosmetic. `serializeNotes` currently drops any note failing
`n.text && n.text.trim()`. Once a note can be a photo with no words, that filter
silently deletes it on save, and it cannot be tested where it currently sits.

```js
serializeNotes(arr)  // keeps a note with text OR at least one image
parseNotes(raw, fallbackDate)
noteImageIds(notes)  // every id referenced by a note list — used by the reap tests
```

`addNote()`'s "text is required" guard relaxes the same way: a note needs text or
at least one photo, not text unconditionally.

## Form

The notes add-row (`templates/index.html:2126`) gains file and camera buttons
mirroring `coverPickerFile` / `coverPickerCamera` (`:1962-1965`), plus a
thumbnail strip for the note being composed, each thumbnail with an × to drop it
before the note is added. Saved notes in `renderNotesForm()` render their
thumbnails the same way.

A pending photo previews from its local data URI rather than round-tripping
through `GET /api/note-images/<id>`; the id is what gets stored.

## Camera and picker refactor

`captureFrame()` ends in a hardcoded `applyCover(dataUri)`
(`templates/index.html:4279`), so the camera overlay can only ever produce a
cover. A module-level `photoTarget`, set by `openCamera(target)` and by the
file-pick entry points, routes the finished data URI to either `applyCover` or
`addNoteImage`.

Everything else is reused unchanged: the one `cameraOverlay`, the
`getUserMedia` / `capture="environment"` fallback ladder, and `resizeImage()`
(1000px max edge, JPEG quality .85, EXIF-aware). Note photos get identical
treatment to covers, and this feature adds no new image-processing code.

## Detail history

The note branch of `dmHistoryEntryHTML` (`templates/index.html:3244`) appends a
thumbnail strip after the rendered markdown. Clicking one opens a lightbox — a
new overlay following the existing `.overlay` / `.hidden` pattern, since none
exists today.

## Activity strip

`activity.js` carries `images` through `eventsOf` and into the `noteList`
entries, so `actPaintNote` (`templates/index.html:6345`) can put a thumbnail on
the hover card. It holds ids only, never bytes — the strip is computed
client-side from `/api/records`, which is precisely why the bytes had to leave
the notes column.

## Calendar

Unchanged. A day's note event shows its text without thumbnails.

## Error handling

- Upload failure toasts in the existing vocabulary (`'session expired — unlock
  and save again'` on 401) and the photo is not added to the note.
- A thumbnail whose fetch 404s hides itself via `onerror`, rather than showing a
  broken-image icon inside a note.
- A note referencing an id that no longer exists renders as a note with fewer
  photos. It is not an error state and produces no warning.

## Testing

TDD throughout.

**Python** (`tests/test_note_images.py` unless noted):
- `POST` stores and returns an id; the id equals the content hash.
- `POST` of an identical image returns the same id and creates no second row.
- `POST` requires auth; rejects a non-data-URI; rejects over the 2MB cap.
- `GET` serves the right bytes and mimetype; unknown id → 404; malformed stored
  payload → 404, not 500.
- Saving a record that drops an image deletes the row.
- Saving a record that drops an image **still referenced by another record**
  leaves the row alone.
- The boot sweep deletes an unreferenced image past the grace window and spares
  one inside it.
- `tests/test_import.py`: export includes `note_images` and round-trips; a CSV
  without the column imports cleanly; a malformed value imports as no images.
- **The regression guard the design exists for**: `/api/records` contains no
  image bytes for a record whose notes have photos.

**JS**:
- `tests/test_notes.js` (new): `serializeNotes` keeps a photo-only note; drops a
  note that is empty of both; `parseNotes` reads a missing `images` key as `[]`
  and still migrates a legacy string note.
- `tests/test_activity.js`: a note's images reach `act.notes`.
- `tests/test_filters.js`: notes search still matches on text, unaffected by
  images.

## Out of scope

- Calendar thumbnails.
- Reordering photos within a note.
- Captions per photo — the note's text is the caption.
- Scanning/analysing a note photo the way a cover can be scanned.
