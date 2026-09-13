# Search by Name

Mockup: https://claude.ai/code/artifact/0c40b7d5-6ad8-43eb-b42f-25f470efa2f8

Line references are against `main` at `8c3aa7e`. The `addressable-timeline-events`
branch moves `templates/index.html` by ~640 lines; the anchors named below all
exist on both, so read them as names first and numbers second.

## Problem

The form has two ways to fill itself and both need you to be holding something:
photograph the sleeve, or paste a Spotify link. Neither helps when you know a
record exists but have nothing to hand it — you want three more Jorge Ben
albums and that is all you know.

This adds a third: type a name, get that artist's releases, tick the ones you
have, fill the form for each.

## What produces the results

The obvious reading of "AI search" is that Claude lists the discography. It
should not, for the reason `_SLEEVE_SYSTEM` (`scan.py:506`) already gives about
the sleeve: the year and the country are looked up, never recalled. A model
listing releases from memory is the same mistake with a different input.

Measured against the live API, MusicBrainz answers the whole question in two
calls:

```
GET /artist/?query=artist:(Jorge Ben)&limit=3
    → Jorge Ben Jor, 19499124-…, BR, score 100 (next: Ben Webster, 91)

GET /release-group/?query=arid:19499124-… AND primarytype:Album
                          AND -secondarytype:Compilation
                          AND -secondarytype:Live
    → count 30, chronological, real first-release-dates, no comps, no singles
```

Those 30 are the discography: *Samba esquema novo* 1963 through *Recuerdos de
Asunción 443* 2007. For contrast, the iTunes search the cover fallback already
uses returns 53 rows for the same artist, most of them singles, remasters and
"feat." credits.

Two things that matter about the query shape, both established by measurement:

- **`arid:<mbid>`, not `artist:(name)`.** `artist:(Jorge Ben)` returns
  `count: 3655` with every row scoring 100 — the parenthesised fuzzy match that
  `_mb_query` (`scan.py:276`) relies on works because it is *paired* with a
  release-group title. Alone it is worthless. The artist search resolves the
  MBID first, and its own scoring is decisive (100 vs 91).
- **The `secondarytype` exclusions do apply.** `count` drops from 3655 to 30,
  so the filter is doing the work, not the `limit`.

So Claude's job is smaller than it first looked, and that is the point:

| step | who | cost | wall clock |
|---|---|---|---|
| 1. loose query → `{artist, album?}` | Claude, Haiku 4.5 | ~0.05¢ | 1–2s |
| 2. artist → MBID | MusicBrainz | free | ~1s (throttled) |
| 3. MBID → release groups | MusicBrainz | free | ~1s (throttled) |
| 4. artist country | MusicBrainz, cached | free | ~1s (throttled) |
| 5. cover art × N | CAA / iTunes, thread pool | free | ~5s |
| 6. genre, per record you keep | Claude, Haiku 4.5 | ~0.04¢ | 1s |

Claude earns its place at step 1 and nowhere else: typos (`jorje ben`), partial
names, "that Milton album with the bird cover", and deciding whether what you
typed is an artist, an album, or both. Steps 2–5 are the same machinery the
photo scan already runs.

### Why not one MusicBrainz call per result

The first draft of this design assumed twelve results meant twelve lookups.
`_throttle_musicbrainz` (`scan.py:179`) blocks a full second between calls, so
that is twelve seconds before any artwork appears, and `fetch_cover`
(`scan.py:480`) can add four more per row on a CAA miss.

It is three throttled calls total, because step 3 returns year, country, MBID
and primary-type for *every* row at once. This has a consequence worth stating
plainly: **ticking a card needs no second lookup.** Everything the form wants
is already in hand when the grid renders. The only per-pick cost is
`classify_genre`, exactly what the Spotify path already pays.

## Server

### `scan.py`

Three new functions, following the conventions the module already sets.

```python
SEARCH_MODEL = "claude-haiku-4-5"

def parse_search_query(query: str, usage_out: list | None = None) -> dict:
    """A loose query to {"artist": str, "album": str | None}.

    Structured output, same shape as classify_genre: output_config.format with
    a json_schema, no `effort` (it 400s on Haiku 4.5 — see scan.py:645).
    Raises RuntimeError when ANTHROPIC_API_KEY is absent, like _anthropic_client.
    """

def lookup_artist(artist: str) -> dict | None:
    """Top artist match as {"mbid", "name", "country"}, or None if nothing scored.

    Raises MusicBrainzUnavailable, like every other _mb_get caller.
    """

def lookup_discography(mbid: str, album: str | None = None) -> list[dict]:
    """Release groups for an artist, chronological.

    `album` narrows with `AND releasegroup:(…)` via the existing _lucene_escape;
    absent, it lists the studio albums. Rows are the same shape
    lookup_musicbrainz returns — mbid, year, country, artist, album_name, type —
    so the client's card renderer and applyCandidate work unchanged.
    """
```

`lookup_discography` returns `lookup_musicbrainz`'s row shape deliberately. The
scan overlay's card markup, `applyCandidate` (`templates/index.html:5227`) and
`countryLabelFromCode` all consume that shape today. Matching it is what lets
the results grid be the scan grid with checkboxes rather than a parallel
implementation — `applyCandidate` is then reused verbatim, and only the card
renderer is refactored (see The results screen).

`MB_SEARCH_LIMIT = 40` caps the release-group query. Thirty is a full
discography for a prolific artist; forty leaves headroom without turning the
grid into a scroll marathon.

### Cover art

The one part that does not fit the existing serial shape. `fetch_cover` is
already written to take one candidate and never raise, so it goes into a pool
unchanged:

```python
COVER_WORKERS = 8
COVER_FETCH_LIMIT = 24   # rows beyond this render with no artwork
```

`concurrent.futures.ThreadPoolExecutor`, results written back by index. Two
reasons for the cap: `fetch_cover`'s iTunes fallback (`scan.py:461`) is one HTTP
call per miss and forty of them in eight seconds is the kind of thing that gets
an IP throttled; and a row nobody scrolls to does not need its bytes paid for.

The pool touches no MusicBrainz endpoint, so it does not contend with
`_mb_lock` — CAA is `coverartarchive.org` and `_download_image` (`scan.py:445`)
does not throttle.

### `POST /api/search`

A new route rather than a third arm of `/api/scan`. `scan_record`
(`app.py:518`) branches on "exactly one of image or spotify_url" and returns
one record's fields; this returns a list of releases. Folding them together
would mean a response shape that is one thing or the other depending on the
input.

Request: `{"query": "jorge ben"}`.

Response:

```json
{
  "query": "jorge ben",
  "artist": "Jorge Ben Jor",
  "album": null,
  "results": [
    {"mbid": "…", "artist": "Jorge Ben Jor", "album_name": "Força bruta",
     "year": "1970", "country": "BR", "type": "Album",
     "cover_data": "data:image/jpeg;base64,…",
     "duplicate_of": null},
    {"mbid": "…", "album_name": "África Brasil", "year": "1976",
     "duplicate_of": {"id": 141, "artist": "Jorge Ben",
                      "album_name": "África Brasil"}}
  ]
}
```

`duplicate_of` is per row, unlike the scan's single top-level one, because
every row is a candidate for the collection rather than an alternate reading of
one sleeve. It comes from the existing pure `find_duplicate` (`scan.py:108`)
against the same four-column row set `scan_record` already loads
(`app.py:528`) — no query cost, no new code.

`genre` is deliberately absent from the rows. Classifying forty releases would
be forty Haiku calls for a grid where you keep three.

### `POST /api/search/genres`

The picks, classified in one round trip:

```json
{"releases": [{"artist": "Jorge Ben Jor", "album_name": "Força bruta"},
              {"artist": "Jorge Ben Jor", "album_name": "Negro é lindo"}]}
→ {"genres": ["MPB & Samba", "MPB & Samba"]}
```

Called once when you hit *add N records*, not once per record: `classify_genre`
(`scan.py:630`) already takes the collection's own genre vocabulary and already
returns `None` when nothing fits, so this is a loop around an existing function.
One request means one `scan_id` in the ledger, so the genre work for a whole
queue is priced as the single act it is. `genres[i]` pairs with `releases[i]`;
a `None` leaves the form's genre select untouched, exactly as an unclassifiable
scan does today.

Capped at the same `MB_SEARCH_LIMIT`, so a caller cannot turn one request into
an unbounded fan-out of billed calls.

### Errors

Three failures, three different words, following the split `scan_record`
already makes by catching `MusicBrainzUnavailable` separately so a dead lookup
does not discard a paid-for vision call:

| condition | status | what the user sees |
|---|---|---|
| `ANTHROPIC_API_KEY` unset | 503 | same wording as the scan's |
| Claude answered, MusicBrainz did not | 502 | "couldn't reach MusicBrainz" |
| everything reachable, no such artist | 200, `results: []` | "no artist matched" |

The last two must stay distinguishable all the way to the screen — that is the
whole reason `MusicBrainzUnavailable` exists (`scan.py:165`), and the scan
overlay already renders exactly this pair of empty states
(`templates/index.html:5186`).

Spend is banked in a `finally`, like `scan_record`'s: the Claude call was
billed the moment it returned, whatever happened afterwards.

### Spend ledger

`ScanSpend` needs no schema change — `source` is already a free string. Three
touch points:

- `SEED_ESTIMATE_USD` (`app.py:614`) gains `"search": 0.0005`.
- `/api/scan/usage`'s `estimate` block (`app.py:688`) gains
  `"search": _scan_estimate("search")`.
- `VinylSpend.scanHintText` (`static/spend.js`) takes `source: 'search'`
  unchanged; it already reads `usage.estimate[source]`.

`_scan_estimate` groups by `scan_id`, and a search produces two of them: one
for the query parse, one for the batch of genre calls. That is the honest
grouping — they are two separate acts, minutes apart, and the second only
happens if you keep something. The hint quotes the first, which is the only
one it can know about before you have picked anything.

## Client

### Entry point

A third button in `.scan-actions` (`templates/index.html:2074`), beside Analyse
and Spotify:

```html
<button type="button" class="scan-find" id="searchNameBtn" onclick="openSearchOverlay()">
  <i class="ti ti-list-search"></i> Search
</button>
```

Three buttons in the 330px `.form-cover-col` is 106px each at `flex:1`, which
holds a 15px icon, a 6px gap and one word at 12px/600. Verified in the mockup's
Entry artboard against the real CSS.

`.scan-find` takes the default `.scan-actions button` styling — neutral border,
`--text`. Analyse keeps the accent and Spotify keeps the green; a third
coloured button would make the row a stripe.

Unlike Analyse, it is never disabled: it needs nothing handed in. That is the
whole point of it, and it is why the `scanHint` line under the row —
"add a cover or a spotify link first" — must stop being the only thing on
screen explaining a dead button. The hint text is unchanged; it already speaks
only about Analyse.

### The query popup

`#searchOverlay`, modelled on `#spotifyOverlay` (`templates/index.html:2288`)
because it does the same job: one field, hand it in, the results screen takes
over. `max-width:460px`. The hint line under the field is
`VinylSpend.scanHintText({armed: true, source: 'search', usage: scanUsage})`,
so it says what has not been sent yet and what this one costs, in the same
words and the same place as the Analyse hint.

Enter submits. `searchInFlight` guards double-submit the way `scanInFlight`
does in `runScan` (`templates/index.html:5016`) — for the same reason, that
every call costs real credits.

### The results screen

`#scanOverlay` gains a mode rather than acquiring a twin. It already is a
full-screen grid of releases with covers, years, countries, types and a
duplicate badge; the differences are:

- **Checkboxes.** Cards toggle instead of picking-and-closing. `renderScanCandidates`
  (`templates/index.html:5177`) splits into a shared card renderer and two
  callers, one binding `pickCandidate`, one binding a toggle.
- **Four columns, not three.** `.scan-grid` (`templates/index.html:773`) is `repeat(3,1fr)` for the four or
  five alternates a scan returns. A discography is twelve to thirty; a
  `.scan-grid.wide` modifier makes it `repeat(4,1fr)`, which is 242px per sleeve
  in the 1060px modal — still legible, verified in the mockup.
- **The footer counts.** "3 selected" and "add 3 records", the primary disabled
  at zero.
- **Duplicates badged, never hidden.** The same red `.scan-badge-dup` bar. You
  may be holding a different pressing, and that is your call, not the app's.

### The queue

State outside everything `openAdd` resets (`templates/index.html:4320`):

```js
let addQueue = [];      // releases still to fill in, in grid order
let addQueueTotal = 0;  // for the "2 of 3" counter
```

Advancing is the only genuinely fiddly part, because `submitForm`
(`templates/index.html:4585`) ends in `closeForm(true)`. It gains one branch:
on success with a non-empty `addQueue`, call `advanceQueue()` instead of
closing. `advanceQueue` clears the draft for the record just saved, calls
`openAdd()`, applies the next release's fields, and re-baselines.

Four collisions with existing behaviour, each of which will bite if unhandled:

1. **`openAdd` calls `offerDraft()`** (`templates/index.html:4369`). Advancing
   the queue would offer the *previous* record's draft. `advanceQueue` must
   clear the draft before calling `openAdd`, not after.
2. **`formSaveBtn.textContent` is owned by `renderOwnSwitch`**
   (`templates/index.html:3906`), which sets it to `save` or `add to wishlist`.
   The queue's `save & next` has to be applied there too, or the first toggle
   of the ownership switch reverts the label.
3. **`closeForm` is the cancel path** (`templates/index.html:4500`). It must
   clear `addQueue`, which is why the button reads *cancel the rest*. Its
   existing confirm already asks about losing a paid-for scan; with a queue
   pending it should say how many records go with it.
4. **`openAdd` clears `scanCandidates`**, so the reopen-results button dies on
   advance. The queue keeps the result list separately and rebinds it, because
   reopening costs nothing — the search was paid for once and covers every
   record in the queue.

The cover column loses `Choose file` / `Take photo` while a queue is running:
there is already a cover, from the release you picked. It keeps the reopen
button.

## What is not in this

- **A shared purchase panel.** Three records bought together share a bought
  date, a shop and a payer, and this design makes you type them three times.
  It was offered and turned down in favour of the full form per record; noted
  here so the next person does not re-derive it as an oversight.
- **A header entry point.** The form is the only way in. The mobile tab bar's
  "Search" already means the collection filter (`templates/index.html:1996`)
  and a second one would be a coin flip every time.
- **Searching for a specific pressing.** Release *groups*, not releases — the
  same level the scan works at. Which pressing you own is the year and country
  on the record, edited by hand as now.

## Testing

Server, matching the existing `tests/test_scan_*.py` split:

- `test_search_query.py` — `parse_search_query` against a stubbed client:
  artist-only, artist+album, and the RuntimeError with no key.
- `test_search_musicbrainz.py` — `lookup_artist` and `lookup_discography`
  against fixtures, including the `arid:` query string being built correctly
  and the `secondarytype` exclusions present. A `MusicBrainzUnavailable`
  propagating rather than being swallowed.
- `test_search_endpoint.py` — the three error rows in the table above, the
  per-row `duplicate_of` against a seeded collection, spend banked in the
  `finally` when MusicBrainz dies after Claude answered, and the cover pool
  returning rows in input order.
- `test_search_genres.py` — `/api/search/genres` pairing `genres[i]` with
  `releases[i]`, a `None` for an unclassifiable record, one `scan_id` for the
  whole batch, and the `MB_SEARCH_LIMIT` cap refusing an oversized list.

Client, matching `tests/test_*.js`:

- `test_search.js` — the card renderer shared with the scan, the selection
  count and the add-button label, and `advanceQueue`'s four collisions above,
  each as its own case.

Fixtures go in `tests/fixtures/`, named like the existing
`mb_artist_withers.json`: `mb_artist_jorge_ben.json`,
`mb_discography_jorge_ben.json`.

## Manual verification

`docs/search-by-name-manual-verification.md`, following the existing
`photo-scan-manual-verification.md`: the things only a real API can show —
that a real search costs what the hint says, that thirty covers arrive in a
tolerable time, and that a genuinely unreachable MusicBrainz words itself as
"couldn't reach" rather than "nothing matched".
