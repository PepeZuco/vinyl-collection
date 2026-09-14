# Analysing progress — showing what the scan is actually doing

## The problem

A scan is a vision call, up to four rate-limited MusicBrainz lookups, up to
three cover fetches and a second Claude call. It runs for twenty to sixty
seconds. All the user sees is a 12px spinner and the words "scanning… this can
take up to a minute" (`templates/index.html:2903`).

Two costs follow from that. A scan that is slow and a scan that has hung look
identical, so the only way to tell them apart is to wait out the worst case.
And the work itself — three different services being consulted on the user's
behalf, each one costing money — is invisible, so the price on the hint line
reads as a charge for a spinner.

## What this builds

The spinner becomes a panel that names each stage as it happens, badges it with
the service being consulted, and shows what that stage found. The thinking face
from the Analyse button grows to 128px and moves into the panel, where the
photo used to be.

The mockup is `static/mockup-analysing.html`, served at
`/static/mockup-analysing.html`. It is throwaway and is deleted when this
lands.

## Decisions taken before the spec

Three questions were open. They are settled here; each follows from code that
already exists rather than from preference.

**Cancel abandons, it does not refund.** `runScan` already discards a result
whose form was closed out from under it, via `scanToken`, and
`refreshScanUsage()` already runs unconditionally because "the money was spent
whatever became of the result". Cancel joins that path: it aborts the stream,
bumps `scanToken`, and closes the panel. The server keeps going to its own
`finally` and banks the spend. The footer must therefore not imply a refund —
it says the credit is spent once a stage starts, not that nothing is charged
until you pick.

**An unreachable MusicBrainz is a third row state, not an error.** The route
already treats it that way: `MusicBrainzUnavailable` is caught separately and
degrades to `lookup_failed`, deliberately, so that an outage costs "the year,
the country and the alternates — not the identification". A row therefore has
four states — `wait`, `run`, `done`, `skip` — and `skip` is styled as
information, not failure.

**Scan first, search second.** This increment streams `/api/scan` only.
`/api/search` has the same thirty-second wait and the same 12px spinner and
reuses the same component, but in a follow-up increment. Doing both at once
doubles the surface before any of it has been used in anger.

## Transport

### Content negotiation, not replacement

`POST /api/scan` keeps returning exactly the JSON it returns today. It streams
only when the caller asks, by sending `Accept: text/event-stream`.

This is not politeness. Twelve test files POST to `/api/scan` and read
`get_json()`. Replacing the response type outright would rewrite all of them to
prove something they are not about. With negotiation they keep passing
untouched, and the streaming path gets its own tests. It also means the
endpoint still works from `curl` and from any client that does not want a
stream.

### Why not EventSource

`EventSource` issues a GET and cannot carry a body. The photo path posts a data
URI of the sleeve, which is megabytes. So the client uses `fetch()` with a
`ReadableStream` reader and parses SSE frames by hand — frames are separated by
a blank line, and each frame is `event:` and `data:` lines. This is a dozen
lines of parsing and is the only reason a hand-rolled reader is needed instead
of the browser's built-in one.

### The event stream

Three event types.

```
event: step
data: {"id":"mb","state":"run","n":1,"of":4}

event: step
data: {"id":"vision","state":"done","detail":"Jorge Ben — África Brasil"}

event: done
data: {…exactly the JSON body the route returns today…}

event: error
data: {"error":"ANTHROPIC_API_KEY not set","status":503}
```

`step.id` is one of `vision`, `spotify`, `genre`, `mb`, `cover`, `vinyl`,
`shelf`. `state` is `run`, `done` or `skip`. `n`/`of` appear only on counted
stages (`mb`, `cover`). `detail` appears on `done` and `skip`.

The stage sequence differs by path, which is the point of showing it at all:

- photo: `vision` → `mb` → `cover` → `vinyl` → `shelf`
- spotify: `spotify` → `genre` → `mb` → `cover` → `vinyl` → `shelf`

### Errors inside a stream

Once the first byte is sent the status is already 200, so an error cannot be a
status code any more. Every error the route can answer with today —
400 `ValueError`, 503/502 `RuntimeError`, 502 catch-all — becomes an `error`
event carrying the status it would have used. The client maps that event onto
the branch it already has for `!res.ok`, so the Spotify popup still reopens
with the message on a rejected link, and everything else still toasts. No error
path changes behaviour; only the channel changes.

### Two Flask details that will bite

`stream_with_context` is required. The generator otherwise runs after the
request context is gone, and the route touches `db.session` (the duplicate
check and `_record_scan_spend`). The codebase already does this for CSV export
at `app.py:1337`, so the pattern is established.

The existing `finally: _record_scan_spend(source, spent)` must move inside the
generator. Generator `finally` blocks run when the generator is closed, which
Flask does on client disconnect, so a cancelled scan still banks its spend —
which is exactly what the cancel decision above depends on.

### Worker occupancy is unchanged

`gunicorn --workers 2` means two concurrent scans occupy both workers. That is
already true today: the blocking POST holds a worker for the same twenty to
sixty seconds. Streaming does not make it worse, and this spec does not fix it.
Noted so the next person does not read the stream as the cause.

## Where progress comes from

Most of it is free, because the loops are already in the route.

The cover loop is already written out in `scan_record`, so it emits per
candidate with no change to `scan.py`:

```python
for i, candidate in enumerate(candidates):
    emit("cover", "run", n=i + 1, of=len(candidates))
    candidate["cover_data"] = scan.fetch_cover(candidate, spotify_image)
```

`lookup_musicbrainz` is the one that needs a seam: its lookups are internal. It
gains an optional `on_progress(n, of)` keyword that defaults to `None`, so
every existing caller and every existing test is unaffected. This is the only
change to `scan.py`.

`vision`, `spotify`, `genre`, `vinyl` and `shelf` are each a single call the
route already makes, so they emit around the call site.

## The panel

One component, two sizes, driven entirely by the event stream. Full markup and
CSS are in the mockup; the shape is:

- **Head** — the 128px face, `analysing n/N`, the current stage name, elapsed
  seconds, and a hairline progress bar. The face is stepped by hand at
  1010ms per pass, positioned in `--face` units exactly as `setAnalyseFrame`
  does, for the reason its comment gives: percentages drift out of step with
  `background-size`.
- **Steps** — one row per stage: service badge, label, detail line, and pips
  for counted stages. Colour identifies who is being consulted — Spotify green,
  MusicBrainz orange, Claude clay, gold for local work. A `wait` row is drained
  of colour; the badge lighting up is the signal that the service is now being
  talked to.
- **Foot** — the honest cost line and cancel.

Desktop takes the whole 920px form (`.analysing.wide`, a `270px 1fr` grid).
Phone keeps the panel in the cover section, where the form is already one
column under 760px. The face is 128px on desktop, 84px on phone.

### A new sprite

`static/analyse-sprite-128.png` is cut from `source.gif` — 2048², 30 frames —
at 128px per frame, black matte keyed to transparent, the same way the 44px
button strip was. It is a new file, not a replacement: the button keeps its
44px strip, because upscaling 44px to 128px is visibly soft and downscaling
128px to 44px costs the button 100KB it does not need.

## Testing

Python, against the streaming path only — the JSON path is already covered:

- a photo scan emits its stages in order and ends with `done` carrying the same
  body the JSON path returns
- a Spotify scan emits `spotify` and `genre` where the photo path emits
  `vision`
- `MusicBrainzUnavailable` emits `mb` as `skip`, not `error`, and the scan
  still completes
- each error class emits an `error` event carrying the status the JSON path
  would have used
- spend is recorded when the generator is closed early, i.e. cancel still bills

JavaScript, against the frame parser and the panel:

- frames split on blank lines, including a frame arriving in two chunks
- each step state renders the right row state
- an `error` event routes to the same place `!res.ok` does today

The boot suite hangs on this machine unless run with `--test-force-exit`; see
the note in memory before running it.

## Out of scope

- `/api/search` and `/api/search/genres` — follow-up increment
- aborting the server-side work on cancel; the calls are billed on return and
  nothing downstream refunds them
- the worker-occupancy limit described above
