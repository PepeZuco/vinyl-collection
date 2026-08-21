# Photo Scan Autofill

## Problem

Adding a record today is a three-step manual loop: photograph the sleeve,
paste the photo into Gemini to get back album name / artist / year / genre /
country, then retype all five into the add-record form. The photo is already
being taken, and the form already accepts an image — but nothing connects
them.

This feature closes that loop inside the app. Two ways in, one pipeline:

- **A photo of the sleeve** — taken in-app or imported.
- **A shared Spotify link** — pasted from the Spotify share sheet, for
  records already identified on streaming.

Two facts about the existing 190 records drive the whole design:

- `year` is the **original release year**, not the pressing year (B.B. King
  *Live at the Regal* → 1965; Bill Withers *Greatest Hits* → 1981).
- `country` is the **artist's home country**, not the pressing country
  (Beabadoobee → `PH`, Bob Marley → `JM`, Ariana Grande → `US`).

Neither field is reliably printed on a front sleeve, so neither is a vision
problem. They are lookup problems, and MusicBrainz exposes both directly.
Asking a model to recall them instead would produce confident wrong values,
worst of all on the 38 MPB & Samba records where model recall is thinnest.

## Architecture

Two interchangeable front ends resolve a record to **artist + album**, then a
single shared pipeline enriches it:

```
photo ──▶ resize ──▶ ┐
                     ├─▶ POST /api/scan ──▶ artist + album
spotify link ──────▶ ┘                          │
                                                ├─ 2. MusicBrainz
                                                │     → year, country,
                                                │       candidates
                                                │
                                                └─ 3. cover art +
                                                      duplicate check
```

Stages 2 and 3 are identical for both inputs. Only stage 1 differs, which is
why the Spotify path costs almost nothing to add once the photo path exists.

Scanning is **purely additive**. Every failure mode falls back to the
existing manual form, which is never blocked or altered.

## 1. New module — `scan.py`

`app.py` is ~300 lines and already holds the model, migrations, auth, records
API, and CSV import/export. This feature adds ~150 lines of logic with three
distinct external dependencies, so it lives in a new `scan.py` exposing five
independent functions. `app.py` only wires the route.

```python
def extract_from_image(image_data_uri: str, genres: list[str]) -> dict
def extract_from_spotify(url: str) -> dict
def classify_genre(artist: str, album: str, genres: list[str]) -> str | None
def lookup_musicbrainz(artist: str, album: str) -> list[dict]
def fetch_cover(candidate: dict) -> str | None
```

Each takes plain data and returns plain data — no Flask objects, no DB
session — so each is testable in isolation with a mocked client or a recorded
fixture.

New dependencies in `requirements.txt`: `anthropic`, `requests`.

New environment variables:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key. **Not** the Claude.ai subscription — a separate pay-as-you-go key from the Anthropic Console. |
| `MUSICBRAINZ_CONTACT` | Contact email embedded in the `User-Agent`. MusicBrainz rejects requests without an identifying UA. |
| `SPOTIFY_CLIENT_ID` | From a Spotify app registration. Optional — absent disables only the link path. |
| `SPOTIFY_CLIENT_SECRET` | As above. |

Each input path degrades independently: no Anthropic key disables photo
scanning, no Spotify credentials disables link pasting, and neither blocks
the other or the manual form.

## 2. Stage 1a — sleeve extraction from a photo (`extract_from_image`)

Model: `claude-sonnet-5`. Effort `low` — this is reading text off an image,
not reasoning. Roughly $0.006 per record.

Output is constrained with structured outputs (`output_config.format`), not a
delimiter-separated string. The schema makes malformed output impossible to
represent:

| Field | Type | Note |
|---|---|---|
| `artist` | string \| null | as printed on the sleeve |
| `album_name` | string \| null | as printed on the sleeve |
| `genre` | enum \| null | **enum built at request time** from `SELECT DISTINCT genre` |
| `label` | string \| null | if legible; improves the MusicBrainz query |
| `catalog_number` | string \| null | if legible |

Building the `genre` enum from the database rather than hardcoding the
current 11 values keeps it in lockstep with `populateGenreSelect()`, which
already derives its options from `records`. Add a genre by hand once and the
scanner can use it immediately.

The prompt states two hard rules:

1. Return `null` for anything not legible. Do not guess.
2. Never infer release year or country. Those are looked up downstream.

Rule 2 matters: without it the model will read a `℗ 1978` line off the sleeve
and report a pressing year, contradicting the collection's convention.

## 3. Stage 1b — Spotify link (`extract_from_spotify`)

Auth is the **client credentials flow** — server-to-server, no user login, no
callback URL, public catalog only, which is all this needs:

```
POST https://accounts.spotify.com/api/token
  Authorization: Basic base64(client_id:client_secret)
  Content-Type: application/x-www-form-urlencoded
  grant_type=client_credentials
```

Returns a bearer token valid ~3600s. Cached in-process and refreshed on
expiry or on a 401.

### URL parsing

The Spotify share sheet emits several shapes, and a shared **track** link is
at least as common as an album link. All of these must resolve:

| Input | Handling |
|---|---|
| `open.spotify.com/album/<id>` | direct |
| `open.spotify.com/album/<id>?si=…` | strip query |
| `open.spotify.com/intl-pt/album/<id>` | strip the `intl-xx` segment |
| `spotify:album:<id>` | URI form |
| `open.spotify.com/track/<id>` | `GET /v1/tracks/<id>` → `.album` |
| `spotify.link/<code>` | follow the redirect, then re-parse |

Anything else returns a 400 with a plain message rather than failing
obscurely.

### What Spotify supplies

`GET https://api.spotify.com/v1/albums/<id>`

| Field | Use |
|---|---|
| `name` | → `album_name` |
| `artists[].name` | → `artist` (joined for multi-artist releases) |
| `images[0].url` | 640×640 official art — **preferred cover source** |
| `release_date` | **not used for `year`** — see below |
| `genres` | **unusable** — deprecated, always an empty array |
| `label` | deprecated |

Two fields are deliberately discarded:

**`release_date` is not the original release.** Each Spotify album entry is a
specific release, so a remaster is a separate entry carrying its own date. A
link shared for the 2015 remaster of a 1973 album reports `2015` — directly
contradicting the collection's original-release convention. The year comes
from MusicBrainz for both input paths, with no special-casing.

**`genres` is confirmed deprecated and always empty** on the album object, so
genre for this path comes from `classify_genre()`: a text-only Haiku 4.5 call
given artist and album, constrained to the same DB-derived enum as the photo
path. Roughly $0.0002 — three orders of magnitude below the vision call.

Spotify has no artist-nationality field at all, so `country` likewise comes
from MusicBrainz.

## 4. Stage 2 — MusicBrainz lookup (`lookup_musicbrainz`)

All three endpoints below were verified live against real responses while
writing this spec.

**Release group search** — supplies the year:

```
GET /ws/2/release-group/?query=artist:"<artist>" AND releasegroup:"<album>"
    &fmt=json&limit=5
```

`first-release-date` → `year` (truncated to the 4-digit year). This is the
original-release semantics the collection uses. Verified: Bill Withers *Live
at Carnegie Hall* → `1973`.

**Artist lookup** — supplies the country:

```
GET /ws/2/artist/<artist-mbid>?fmt=json
```

`country` → `country`, already ISO 3166-1 alpha-2, dropping straight into the
existing `VARCHAR(2)` column with no mapping table. Verified: Bill Withers →
`US`, Altamiro Carrilho → `BR`.

Fallback chain when `country` is null: `country` → `area.iso-3166-1-codes`.

**Request rules.** MusicBrainz requires a `User-Agent` identifying the
application and a contact address, and rate-limits to 1 request/second. A
small module-level throttle in `scan.py` serialises calls. A scan makes at
most 2 MusicBrainz calls, so worst case adds ~1s.

**Candidates.** Up to 3 release-groups are returned, each with `year`,
`country`, `label`, `mbid`, and `cover_url`. The highest-scoring one is the
primary; the rest back the "not this one?" affordance.

**Edge cases** (both hit during live verification):

- `first-release-date` absent — observed on Altamiro Carrilho *Para Sempre*.
  Omit `year`, keep the candidate; the field stays empty rather than wrong.
- No release-group match at all — return `[]`. The artist/album/genre from
  stage 1a or 1b still fill in, and year/country stay empty.

## 5. Stage 3 — cover art and duplicate check

**Cover chain**, first hit wins, identical for both input paths:

1. `GET coverartarchive.org/release-group/<mbid>/front-500` — free, no key,
   community scans of real releases, best coverage for older and Brazilian
   pressings. Verified: HTTP 200, ~50KB JPEG.
2. `GET itunes.apple.com/search?term=<artist>+<album>&entity=album` →
   `artworkUrl100`, rewritten `100x100bb` → `600x600bb`. No auth.
3. Spotify `images[0].url` (640×640) — link path only.
4. The user's own photo — photo path only, and always available there.

Spotify's own art is deliberately **third, not first**, despite being the
highest-quality source on the link path. `cover_data` is a permanent base64
copy in the database and gets re-exported through `/api/export`; Cover Art
Archive images are community-contributed and unambiguous to store that way,
while Spotify's developer terms govern reuse of their content more tightly.
For a private collection the practical risk is negligible, but preferring the
license-clean source costs nothing here since both paths already query
MusicBrainz.

The link path has no photo to fall back on, so a total miss leaves
`cover_data` empty and the copy string does the work.

The fetch happens **server-side** — a browser-side fetch would hit CORS and
hotlink protection. The result is base64-encoded into a data URI, matching
how `cover_data` is already stored.

**Copy string.** The response always includes
`"<artist> <album> <year> vinyl cover"`, rendered in the form beside a copy
button. It costs nothing, never breaks, and covers whatever both APIs miss.

**Duplicate check.** The extracted artist + album are compared against every
existing record on a normalised key (casefold, strip punctuation and
leading articles). A hit returns `duplicate_of: {id, artist, album_name}` and
the form shows a warning banner — useful when deciding whether to buy a
record while standing in a shop.

## 6. Endpoint — `POST /api/scan`

Decorated `@require_auth`, exactly like every other write route. Without it,
anyone who finds the deployed app can spend the API key's credits.

Request — exactly one of:

```json
{"image": "data:image/jpeg;base64,..."}
{"spotify_url": "https://open.spotify.com/album/4LH4d3cOWNNsVw41Gqt2kv?si=x"}
```

Both keys present, or neither, is a 400. The response shape is identical
either way, so the frontend has one code path for filling the form.

Response:

```json
{
  "source": "photo",
  "artist": "Bill Withers",
  "album_name": "Live at Carnegie Hall",
  "genre": "Soul & Funk",
  "candidates": [
    {"year": "1973", "country": "US", "label": "Sussex",
     "mbid": "8f1318d9-...", "cover_url": "data:image/jpeg;base64,..."}
  ],
  "duplicate_of": null,
  "search_string": "Bill Withers Live at Carnegie Hall 1973 vinyl cover"
}
```

**Error handling — the manual path always survives:**

| Condition | Response | UI |
|---|---|---|
| `ANTHROPIC_API_KEY` unset | 503 | Photo scan action hidden |
| Spotify credentials unset | 503 | Link paste field hidden |
| Claude API error | 502 | Toast; form stays manual |
| Unrecognised Spotify URL | 400 | Inline message on the paste field |
| Spotify 404 (bad/regional ID) | 404 | Inline message on the paste field |
| MusicBrainz timeout (2s) | 200, `candidates: []` | Artist/album/genre fill; year/country empty |
| No cover found | 200, `cover_url: null` | Photo path keeps the photo; link path leaves it empty |

Image size is capped server-side before the API call.

## 7. UI — image import and camera capture

Clicking the cover drop zone currently opens a file picker directly. It
instead opens a two-choice action sheet:

```
┌─ add cover ──────────────────────────┐
│  📁  Choose file                     │
│  📷  Take photo                      │
│  ──────────────────────────────────  │
│  ◉   Paste Spotify link              │
│      [                        ] [→]  │
└──────────────────────────────────────┘
      ▲ static/spotify-logo.png @ 24px
```

Rows hide individually when their credentials are missing, so a partial
configuration still yields a working sheet.

**Choose file** → the existing `<input type="file" accept="image/*">`,
unchanged. On iOS Safari this input already presents Photo Library / Take
Photo / Choose File, so this path alone remains fully functional if
everything below fails.

**Take photo** → in-page camera via `getUserMedia`, with a live preview and a
shutter button.

`getUserMedia` is the primary camera path, **not** `<input capture>`. MDN
classifies the `capture` attribute as *not Baseline*, with limited support on
Safari iOS and desktop; `getUserMedia` has been Baseline widely available
since September 2017. `capture="environment"` is kept only as the fallback
rung below.

### Browser policy requirements

| Requirement | Handling |
|---|---|
| **Secure context.** In an insecure context `navigator.mediaDevices` is `undefined` — a `TypeError`, not a catchable rejection. | Feature-detect `navigator.mediaDevices?.getUserMedia` before use, never `try`/`catch` alone. Railway serves HTTPS; `localhost` dev is fine; `http://<LAN-IP>:5000` is not, and correctly degrades. |
| **Permissions Policy.** `camera` directive governs access. | Same-origin, no iframe, no restrictive header set — nothing to configure. Documented here so a future CSP or embed doesn't silently break it. |
| **User gesture.** Permission may only be requested from a user action. | The prompt is triggered by the "Take photo" tap, never on page load. |
| **iOS fullscreen takeover.** iOS Safari forces fullscreen playback without `playsinline`. | `<video playsinline autoplay muted>` — all three attributes required. |
| **Rear camera.** `facingMode: {exact: "environment"}` throws `OverconstrainedError` on any desktop without a rear camera. | Use `{ideal: "environment"}`, which degrades to the only available camera. |
| **Camera release.** The indicator light stays on if tracks are left running. | `stream.getTracks().forEach(t => t.stop())` on capture, on cancel, and on modal close. |

### Fallback ladder

Each rung is tried only when the one above is unavailable:

1. `getUserMedia` live preview — the normal path on HTTPS.
2. `<input type="file" accept="image/*" capture="environment">` — on
   `NotAllowedError`, `NotFoundError`, `NotReadableError`, or when
   `mediaDevices` is undefined. Opens the native camera app where `capture`
   is honoured.
3. Plain `<input type="file" accept="image/*">` — always works, and on iOS
   offers the camera through the system action sheet anyway.

### Client-side resize

Before upload, the image is drawn to a canvas at max 1000px on the long edge
and exported as JPEG. This is not cosmetic:

- A raw 12MP photo costs 4784 visual tokens on Sonnet 5's high-resolution
  tier versus 1296 at 1000×1000 — roughly 3× the input cost for no gain on a
  square sleeve.
- It keeps the request well under `MAX_CONTENT_LENGTH` (32MB).

**EXIF orientation** must be handled explicitly. A portrait phone photo
carries an orientation flag, and a sideways sleeve degrades both OCR accuracy
and the stored cover. Use
`createImageBitmap(file, {imageOrientation: 'from-image'})`, falling back to
`<img>` + `drawImage`. Verify during implementation with a real portrait
photo taken on a phone, not a desktop-generated test image.

The resized data URI is used for **both** the scan request and `cover_data`,
so the photo is retained even when every cover lookup misses.

## 8. UI — Spotify link paste

The paste field accepts any of the URL shapes in §3 and submits on Enter or
on the arrow button. On mobile, a `paste` event containing an
`open.spotify.com` or `spotify:` URL submits immediately — pasting a share
link is the whole gesture, and requiring a second tap adds nothing.

While the request is in flight the field shows a spinner and the form is
non-interactive; on error the message renders inline beneath the field
rather than as a toast, so the offending URL stays visible for editing.

### Spotify branding compliance

The official primary logo ships as `static/spotify-logo.png` (939×940, RGB
Green, transparent). Spotify's developer design guidelines impose real
constraints, and the app happens to satisfy them without a variant asset:

| Rule | Compliance |
|---|---|
| Green logo permitted on **black or white backgrounds only** | Dark theme `--surface: #141414`, light theme `#ffffff`. Both qualify — no monochrome swap needed in either theme. |
| Icon-alone minimum **21px** digital | Rendered at 24px. |
| Clear space = **half the icon's height** | ≥12px padding on all sides of the 24px mark. |
| No rotating, stretching, recolouring, or filling the lines | Rendered at native 1:1 aspect, no CSS filters, no `border-radius`, no background plate. |
| Not used inside a sentence or as a decorative element | Appears only as the leading mark of its own action row. |
| Attribution required when displaying Spotify content | The logo on the row that ingests Spotify data serves as the attribution. |

Because the asset is a raster PNG at 939×940, it is rendered with
`width:24px;height:24px` and `image-rendering:auto`; downscaling that far is
safe on high-DPI screens.

The logo marks the **input** affordance only. It is not attached to saved
records — once a record exists, its data came from MusicBrainz, so branding
it as Spotify content would be both inaccurate and a co-branding violation
next to the app's own logo.

## 9. Form behaviour

Per the chosen flow: autofill immediately from the top candidate, with a
correction path.

- Fields populate from the response; `coverDataUri` is set and previewed.
- When `candidates.length > 1`, a small "not this one? (N)" link appears
  under the album field. It opens a popover listing the alternates with year,
  country, and label; picking one re-fills those fields and swaps the cover.
- `duplicate_of` renders a warning banner linking to the existing record.
- Every field stays fully editable. Nothing auto-saves.

## Known limitation — country for expatriate artists

MusicBrainz models artist location as three separate fields, and they can
disagree. Beabadoobee returns `country: null`, `area: England`,
`begin-area: Iloilo City` — while the collection records `PH`, her
birthplace.

The `country → area` chain gets the overwhelming majority right (Bill Withers
`US`, Altamiro Carrilho `BR`) but would put `GB` on that record. Resolving it
properly means mapping `begin-area` city names to countries — a meaningful
amount of complexity for a handful of records.

**Accepted:** take the imperfect prefill and correct the occasional expat by
hand. It is one pre-filled field and one keystroke to change.

## Testing

No test framework exists in the repo today. This feature adds `pytest`.

**`extract_from_image`** — mocked Anthropic client:
- `genre` is always drawn from the enum passed in, never invented.
- Illegible fields come back `null` rather than fabricated.
- The genre enum reflects the DB at call time, not a hardcoded list.

**`extract_from_spotify`** — mocked HTTP:
- Every URL shape in §3 resolves to the same album id: plain, `?si=`,
  `intl-pt`, `spotify:album:`, and a track link resolving via `.album`.
- An unrecognised URL raises rather than silently returning empty fields.
- `release_date` is **never** written to `year` — the regression test that
  protects the original-release convention.
- A cached token is reused; a 401 triggers exactly one refresh and retry.

**`classify_genre`** — mocked Anthropic client: output is always a member of
the enum passed in, and `None` when the model declines.

**`lookup_musicbrainz`** — recorded fixtures from the real responses used to
verify this spec:
- Bill Withers *Live at Carnegie Hall* → `year: "1973"`, `country: "US"`.
- Altamiro Carrilho *Para Sempre* → missing `first-release-date`, candidate
  returned with no `year`.
- A no-match query → `[]`.
- The 1 req/sec throttle actually serialises calls.

**`fetch_cover`** — mocked HTTP: 200 from Cover Art Archive; 404 falling
through to iTunes; both failing, returning `None`; timeout.

**Duplicate detection** — unit tests over a small in-memory record set:
casefold, punctuation, and leading-article differences all match.

**Manual verification** — run the app and scan three real sleeves from the
collection: one US rock record, one MPB record, and one with no MusicBrainz
entry. Then confirm on a physical phone that the camera opens, `playsinline`
holds (no fullscreen takeover), a portrait photo lands right-side up, and the
camera indicator goes dark after capture.

For the link path, share a real album from the Spotify mobile app and paste
it, plus a track link from the same album — both must produce identical
fields. Include one album whose Spotify entry is a remaster and confirm the
year comes back as the original, not the remaster date.

## Out of scope

- **Pressing-level metadata.** Discogs would supply pressing year, pressing
  country, and catalog number. The collection's convention is original
  release plus artist origin, so pressing data would actively contradict the
  existing 190 records.
- **Web search enrichment.** Priced at ~$0.12/record against ~$0.006 for the
  MusicBrainz path, and noisier for these two specific fields. Reconsider
  only if MusicBrainz coverage proves inadequate in practice.
- **Batch scanning.** One record at a time.
- **Amazon cover scraping.** Claude's web search returns text and citations,
  never images, so there is no supported path from search to a stored PNG.
  Scraping image URLs is against Amazon's terms, unstable to hotlink, and
  unnecessary given Cover Art Archive and iTunes.
- **Spotify user login.** Client credentials only — no OAuth, no callback
  URL, no reading the user's saved albums or playlists. Importing a Spotify
  library wholesale is a different feature with a different auth model.
- **Spotify playlist and artist links.** Only album and track links resolve
  to a single record. A playlist link is rejected with the same 400 as any
  other unrecognised URL.
- **Backfilling the 87 records with no country.** Same lookup could do it,
  but that is a separate migration task.
