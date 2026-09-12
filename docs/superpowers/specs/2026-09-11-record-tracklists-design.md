# Record tracklists — design

> **Status:** approved design, not yet implemented
> **Date:** 2026-09-11
> **Scope:** songs on a record, a dated "I liked it" mark per song, record format
> (size + disc count), and the surfaces that read them

---

## 1. What this adds

A record currently knows *what it is* and *what happened to it*. It does not know
**what is on it**. This adds the songs.

Four things, in one feature:

| | |
|---|---|
| **Tracklist** | songs grouped by side (`A`, `B`, `C`, …), typed by hand, editable |
| **Format** | record size (7" / 10" / 12") and disc count (1, 2, 3…) |
| **Liked songs** | a dated heart per song — *I heard this one and liked it* |
| **Reach** | a double record is visible in the grid; likes land in the Timeline; songs are searchable |

### Decisions taken, and why

| Decision | Chosen | Rejected, because |
|---|---|---|
| Data shape | flat array of tracks, each carrying its side letter | nested `discs → sides → tracks` makes every reader walk three levels; a separate `Track` table breaks the JSON-in-a-column pattern that `notes`, `play_dates` and `cleaned_dates` all follow, and complicates the CSV backup |
| Filling the list | typed by hand, plus a paste box | auto-fill from MusicBrainz/Spotify is a real win but a separate spec — medium→side assignment is guesswork on a CD-shaped tracklist, so it needs a hand-edit pass anyway, and it does nothing for the ~250 records already here |
| Like marker | `ti-heart` / `ti-heart-filled`, on/off, one per song, **dated** | stars are spent on record ratings, headphones on plays, droplet on cleaning — a heart is the only unambiguous glyph left. Two hearts (Pepe + Jenni) doubles the tap targets for a thing only one person records |
| Double indicator | stacked sleeve **+** split spine, shown only when `disc_count > 1` | a mark on all 250 cards is furniture the eye stops seeing |
| Drawer layout | tabs **Info · Tracks · Timeline**, opening on Tracks | one long scroll buries the History under a four-side tracklist |
| Editing | hearts live in the drawer, structure in the form wizard | see [§7.4](#74-editing-split-by-act) — this repeats a call the codebase already made for rating bars |

---

## 2. Data model

### 2.1 New columns on `Record`

```python
tracks     = db.Column(db.Text)        # JSON array, see below
disc_count = db.Column(db.Integer, default=1)
size       = db.Column(db.String(5))   # '' | '7' | '10' | '12'  (inches)
```

All three follow the existing conventions: `tracks` is JSON-in-a-text-column the
same way `notes` is, and `size` is a short code rather than a display string so
the UI owns the formatting.

### 2.2 The `tracks` JSON

```json
[
  { "side": "A", "title": "Ponta de Lança Africano", "liked_at": "2026-09-09T21:40:00" },
  { "side": "A", "title": "Umbabarauma" },
  { "side": "B", "title": "Charles Jr." },
  { "side": "C", "title": "Taj Mahal", "liked_at": "2026-08-02" }
]
```

**Field by field:**

- **`side`** — a single uppercase letter. Which disc a song is on is *carried by
  the letter*, exactly as a real sleeve carries it: disc 1 is `A`/`B`, disc 2 is
  `C`/`D`, disc 3 is `E`/`F`. No disc field on the track.
- **`title`** — trimmed string. Empty titles are dropped on save.
- **`liked_at`** — **absent when not liked.** When present, a stamp in the exact
  format `play_dates` and `cleaned_dates` use, and read by the same
  `momentOf()`: either `YYYY-MM-DD` (a like backdated to a day, no clock) or
  `YYYY-MM-DDTHH:MM:SS` (a local wall clock, written by a heart tap now).

> **No `pos` field.** Track order is the array's own order within a side; the
> number shown in the UI is derived at render time. Storing a position
> alongside the order gives two sources of truth that drift the first time a row
> is dragged.

### 2.3 Invariants

1. `disc_count >= 1`. `size` is `''` (unknown) or one of `'7'`, `'10'`, `'12'`.
2. A track's `side` must be within range for `disc_count` — disc *n* owns the
   letters at index `2n-2` and `2n-1`. With `disc_count = 2`, `A`–`D` are legal
   and `E` is not.
3. **Lowering `disc_count` never silently deletes songs.** If sides `C`/`D` hold
   tracks, the form refuses the change and says so; the user empties the sides
   first. Data loss must be an explicit act.
4. A side may be empty. A 7" single with one song per side is two sides of one
   track each; a record with no tracklist at all is `tracks = ''`.
5. **Track identity is its index in the raw array** — the same rule notes and
   play dates already live under, and for the same reason: the Timeline hands
   out keys built from it (see [§6](#6-timeline-and-event-plumbing)). Reordering
   in the form renumbers; that is acceptable because reordering happens at a
   desk, between saves, and the keys are only used to focus an event after a
   click.

### 2.4 Parse/serialize rules — `static/tracks.js`

A new module, mirroring `static/notes.js`, so the rules are pure functions with
node tests rather than logic buried in the template:

```js
parseTracks(raw)              // '' | bad JSON | non-array  → []
serializeTracks(list)         // drops empty titles, trims, strips empty liked_at
sideLettersFor(discCount)     // 2 → ['A','B','C','D']
discOfSide(letter)            // 'C' → 2
tracksBySide(list, discCount) // → [{ disc, letter, tracks: [...] }, …]
likedTracks(list)             // → [{ i, title, liked_at }, …]
```

`parseTracks` must be total: a record whose column holds nonsense returns an
empty list rather than throwing, because six client-side consumers read it
straight off `/api/records`.

---

## 3. API

### 3.1 `to_dict()`

```python
"tracks":     self.tracks or "",
"disc_count": self.disc_count or 1,
"size":       self.size or "",
```

`tracks` ships as the **raw JSON string**, like `notes` and `play_dates` — the
client parses it. Consistency matters more than elegance here; every existing
consumer already expects that shape.

> **Payload note.** A tracklist is small text (a 26-song double LP is roughly
> 1 KB), so unlike covers and note images it can ride in the record list without
> reviving the 45 MB-response problem the `cover_url` arrangement exists to
> prevent. Search needs it on the client anyway.

### 3.2 `POST /api/records` and `PUT /api/records/<id>`

Both accept `tracks`, `disc_count`, `size`, validated server-side against
[§2.3](#23-invariants): unknown `size` → `''`, `disc_count` coerced to `int`
and floored at 1, tracks with an out-of-range `side` rejected with `400` rather
than quietly dropped.

The heart tap writes through the existing optimistic helper —
`patchRecord(id, { tracks: JSON.stringify(next) })` — the same path
`logPlayed()` and `logCleaned()` use. No new endpoint.

### 3.3 Migration

Three entries in the existing auto-migration block in `app.py`:

```python
missing_cols = {
    …,
    "tracks":     "TEXT",
    "disc_count": "INTEGER",
    "size":       "VARCHAR(5)",
}
```

**No backfill.** Every existing record starts with no tracklist, `disc_count`
defaulting to 1 and unknown size. That is honest — the collection genuinely does
not know yet — and it is why the drawer needs the empty-state rule in
[§7.2](#72-drawer--tabs).

### 3.4 CSV export / import

Three new columns appended to `cols` in `export_csv()`: `tracks`, `disc_count`,
`size`, and three matching entries in `_record_mapping()`:

```python
"tracks":     row.get("tracks", ""),
"disc_count": int(row.get("disc_count") or 1),
"size":       (row.get("size", "") or "").strip(),
```

A CSV written before this feature simply has no such columns, which is not an
error — `_row_note_images()` already establishes that convention.

---

## 4. The grid — a double record announces itself

Two marks, both driven by `disc_count`, both rendered **only when
`disc_count > 1`**:

- **Stacked sleeve.** `disc_count - 1` sleeve elements behind the cover, offset
  `+5px, +5px` and `+9px, +9px`, at `brightness(.6)` and `brightness(.4)`. The
  card's silhouette changes, so a double is legible from across the grid.
- **Split spine.** A 5px accent bar down the left edge of the cover, cut into
  `disc_count` segments with a 3px gap, in `--accent`. It says *how many*.

Both live in `cardHTML()`. The cover area gains 9px of left padding to make room
for the spine; the stack needs a few px of grid gutter.

Record **size stays off the card entirely** — almost everything is 12", so a
badge on 95% of cards is noise. It shows in the drawer, where there is room for
words.

---

## 5. The drawer

### 5.1 What changes

The info column becomes:

```
album / year
artist
rating bars (Pepe · Jenni · Total)      ← pinned, unchanged
─────────────────────────────────────
[ Info ] [ Tracks ] [ Timeline ]        ← new tabs
─────────────────────────────────────
  …tab content…
```

Everything above the tabs is what the drawer already draws. The tabs swap what
sits underneath.

### 5.2 Drawer — tabs

| Tab | Holds |
|---|---|
| **Info** | the chips and the metadata grid as they are today, plus a new **Format** cell |
| **Tracks** | the tracklist, grouped by disc and side, with a heart per song |
| **Timeline** | today's History section — bought / played / cleaned / noted — **plus likes** |

**The default tab is Tracks when the record has any tracks, Info otherwise.**
Without that fallback, every record in the collection opens on an empty tab on
day one. The empty Tracks tab still exists and is reachable; it says *no
tracklist yet* and, when authed, offers **+ add the songs** (which opens the form
at step 4).

The chosen tab is **sticky while the drawer is open**, so paging through records
with the prev/next arrows keeps you on Tracks — subject to the same fallback
when a record has none.

**New Format cell** in the Info grid, carrying size and disc count together
rather than as two cells:

| `size` | `disc_count` | shows |
|---|---|---|
| `12` | 2 | `2 × 12"` |
| `12` | 1 | `12"` |
| `7` | 1 | `7"` |
| `''` | 1 | `—` |
| `''` | 2 | `2 discs` |

A **liked** chip joins the plays/genre chips when the count is above zero, so
"four songs on this record are ones I love" reads without opening a tab.

### 5.3 Drawer — the Tracks tab

```
Disc 1
─ (A) SIDE A ──────────────────────────
  1  In the Flesh?                9 Sep ♥
  2  The Thin Ice                       ♡
  3  Another Brick in the Wall…   9 Sep ♥
─ (B) SIDE B ──────────────────────────
  1  Mother                       2 Aug ♥
  2  Goodbye Blue Sky                   ♡
Disc 2
─ (C) SIDE C ──────────────────────────
  …
```

- Side letters render in a filled `--accent` circle — the label a real record
  carries.
- Disc headers appear **only when `disc_count > 1`**. A single LP shows sides A
  and B with no disc chrome at all.
- A liked song shows its date inline, formatted the way the drawer already
  formats note dates.
- Unliked hearts are `ti-heart` at `--muted` / 35% opacity, so an unmarked
  tracklist is not a wall of symbols; liked ones are `ti-heart-filled` in
  `--ev-liked`.

---

## 6. Timeline and event plumbing

A like is an **event**, not a flag. It flows through the machinery that already
carries bought / cleaned / played / noted.

### 6.1 `static/timeline.js`

```js
ALL_TYPES  = { bought: true, cleaned: true, played: true, liked: true, note: true };
TYPE_ORDER = { bought: 0, cleaned: 1, played: 2, liked: 3, note: 4 };
```

`keyOf('liked', stamp, trackIndex)` → `liked:<stamp>:<i>`, indexed like every
other list-backed type.

In `eventsByDay()`, with the parser arriving through `deps` exactly as
`parsePlayDates`, `parseCleanedDates` and `parseNotes` already do — the module
does no parsing of its own, and an absent dep degrades to an empty list rather
than throwing:

```js
const parseTracks = (deps && deps.parseTracks) || (() => []);
…
if (on.liked) parseTracks(r.tracks).forEach((t, i) => {
  if (t.liked_at) add(t.liked_at, { type: 'liked', r, i, title: t.title });
});
```

Both call sites must hand the new dep in: the Timeline's own call in
`templates/index.html`, and `FILTER_DEPS`-style wiring wherever the Calendar
builds its events.

The **raw index**, as with notes — a track with an empty title still holds its
slot, so filtering before indexing would renumber everything after it and break
keys the Timeline has already handed out.

> **`note` moves from 3 to 4.** Within a single day the true sequence is
> *played → liked → noted*: you hear the song, you like it, then you write about
> it. This changes same-day ordering for records that have both a note and a
> like, and `tests/test_timeline.js` asserts ordering — those assertions must be
> updated deliberately, not patched until green.

### 6.2 Everything downstream, for free

- **Calendar** gains a fifth type button (`ti-heart`), new CSS var
  `--ev-liked: #E05A5A` dark / `#b33b3b` light, alongside the four existing
  `--ev-*` colours.
- **History** lists likes among the other events.
- **Drawer Timeline tab** — `dmHistoryEvents()` picks up likes once it parses
  tracks, with `DM_HIST_LABEL.liked = 'Liked'` and
  `DM_HIST_ICON.liked = 'ti-heart-filled'`. The entry names the song:
  **Liked *Umbabarauma***.
- **Click-through** works like notes and plays already do — a like in the
  Timeline opens the record and focuses that song.

### 6.3 Deliberately *not* touched

`static/activity.js` — the insight lanes measuring play cadence and shelf-life —
does **not** count likes. It answers "how often does this record get played",
and a like is not a play.

---

## 7. Editing

### 7.1 The two acts

"Edit a tracklist" hides two different jobs:

| | Where | Why there |
|---|---|---|
| **Liking a song** | the drawer, one tap, no edit mode | happens while the record spins, phone in hand |
| **Building the list** | form wizard, new step 4 | 26 titles and side assignment; desk work, done once |

### 7.2 Drawer — the heart

Tapping a heart in the Tracks tab stamps `liked_at` with `nowStamp()` and writes
immediately through `patchRecord`. Tapping a filled heart clears it. No edit
mode, no save button. A small ✎ beside the date opens a date/time input so a like
can be backdated — you already know which songs you love; the date they were
first marked is not the date you fell for them.

This is the same call the codebase made for the rating bars, recorded in the
comment above them: *"Changing a rating used to cost four steps — open, edit,
scroll past cover and purchase, save — while the play count next to it had been
one tap on the card all along."*

### 7.3 Form — step 4, "Tracklist"

The wizard becomes **Record · Purchase · Log · Tracklist**.

```
┌ Size ──────────────┐ ┌ Discs ─────────┐
│  7"   10"  [12"]   │ │ [1]  2   3     │
└────────────────────┘ └────────────────┘

◍ SIDE A                            4 songs
  ⠿  1  [ In the Flesh?          ]  ♥  ✕
  ⠿  2  [ The Thin Ice           ]  ♡  ✕
       + add song

◍ SIDE B                              empty
  ┌ paste a tracklist here ─────────────┐
  │ one song per line                   │
  └──────────────── → fills side B ─────┘
```

- **Size** and **Discs** are segmented pickers. Changing Discs adds or removes
  side blocks; removing a side that holds songs is refused per
  [§2.3](#23-invariants).
- Rows have a drag grip (reorder within a side), an editable title, a heart, and
  a delete.
- **The paste box** is how a tracklist actually gets in: paste a block of text,
  one song per line, and it becomes rows on that side. It strips leading track
  numbers (`1.`, `01 -`, `A1`) and trailing durations (`3:42`) — the shapes
  copied text arrives in.
- The hearts are editable here too. The form is the definitive writer; the
  drawer is the shortcut.
- Draft persistence (`static/draft.js`) must cover the new step, or a
  half-typed tracklist dies with the tab.

---

## 8. Search

The **search-in panel** gains a sixth checkbox, **Song**, **off by default** —
matching genre, notes and bought-at, which are all off.

In `static/filters.js`:

```js
DEFAULT_FIELDS = { artist: true, album: true, genre: false,
                   notes: false, bought_at: false, song: false };

// in haystack()
if (fields.song) parts.push(parseTracks(record.tracks)
                              .map(t => t.title || '').join(' '));
```

`parseTracks` joins `parseNotes` in `FILTER_DEPS`, so the module stays free of
its own parsing. The matched record is what surfaces — the grid shows records,
not songs — and a hit is not highlighted inside the tracklist. Jumping straight
to the matching song is a good idea and a separate one.

---

## 9. Testing

Following the repo's convention — pure rules in a `static/*.js` module, node
tests, a pytest shim so `pytest` stays the single command:

| File | Covers |
|---|---|
| `static/tracks.js` | the rules themselves |
| `tests/test_tracks.js` | parse/serialize totality, empty-title dropping, `sideLettersFor`, `discOfSide`, `tracksBySide` grouping, `likedTracks` |
| `tests/test_tracks.py` | the node shim, mirroring `tests/test_notes.py` |
| `tests/test_timeline.js` | likes appear in `eventsByDay`, `keyOf` shape, the `TYPE_ORDER` change |
| `tests/test_filters.js` | the `song` field off by default; on, it matches a track title; a record with `tracks = ''` never throws |
| `tests/test_tracks_endpoint.py` | `POST`/`PUT` accept the three fields, reject an out-of-range side with `400`, coerce `disc_count`, round-trip through `/api/export` → `/api/import` |

Plus `docs/tracklist-manual-verification.md` for what has to be checked by eye,
matching the seven manual-verification docs already in `docs/`: the stacked
sleeve and spine at real grid density, the tab fallback on a record with no
tracks, a heart tap surviving a reload, and a like appearing in the Calendar.

> **Machine note:** `tests/test_boot.py` times out on this machine after its
> tests pass — run `node --test tests/test_tracks.js` directly when iterating.

---

## 10. Out of scope

Named here so they are decisions, not omissions:

1. **Auto-filling tracklists** from MusicBrainz (`inc=recordings`) or the Spotify
   album endpoint, and a per-record *fetch tracklist* button to backfill the
   ~250 records already in the collection. Wanted, deferred, its own spec.
2. **Flipping the sleeve** — tracklist printed on the back of the cover, reached
   by tapping it in the carousel. The most charming option on the table; it
   reads the same data and can be added later on top of this with no rework.
3. **Per-song ratings, durations, songwriters, guest artists.** A like is a
   binary with a date. Anything richer is a different feature.
4. **A cross-collection "liked songs" view** — every heart in one list. Tempting
   once the data exists; not needed to make the data worth having.
5. **Jenni's own likes.** The heart records one person's reaction. A second
   colour doubles the tap targets on a phone for something only one person logs.
6. **Play cadence counting likes** (`static/activity.js`), per
   [§6.3](#63-deliberately-not-touched).

---

## 11. Files touched

| File | Change |
|---|---|
| `app.py` | 3 columns, `to_dict`, create/update validation, auto-migration, CSV export + `_record_mapping` |
| `static/tracks.js` | **new** — parse/serialize/grouping rules |
| `static/filters.js` | `song` in `DEFAULT_FIELDS`, `haystack`, `FILTER_DEPS` |
| `static/timeline.js` | `liked` in `ALL_TYPES`, `TYPE_ORDER`, `eventsByDay` |
| `static/draft.js` | draft coverage for form step 4 |
| `templates/index.html` | card marks, drawer tabs + Tracks tab, Format cell, liked chip, heart handler, form step 4 + paste box, search checkbox, calendar type button, `--ev-liked`, `DM_HIST_*` |
| `tests/` | five files per [§9](#9-testing) |
| `docs/tracklist-manual-verification.md` | **new** |
