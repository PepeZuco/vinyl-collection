# Bought at, as a place with a link — design

> **Status:** approved design, not yet implemented
> **Date:** 2026-09-12
> **Scope:** the `bought_where` field becomes a pick from a known list of places,
> each place can carry a link, and that link is clickable where the place is read

---

## 1. What this adds

Today `bought_where` is free text on `Record` with a native `<datalist>` of the
distinct values already in the collection (`populateWhereList`). Two things are
missing: nothing stops a typo from inventing a phantom place, and a place cannot
carry the one thing you actually want to reach from it — its link (the store's
site, the Discogs seller, the fair's page).

Three things, in one feature:

| | |
|---|---|
| **A known list** | the form offers the places you already have; a new one is added deliberately, at the bottom of the list |
| **A link per place** | the place owns the URL, not the record — 14 records bought at the same store share one link |
| **Clickable on read** | the drawer's "Bought at" cell and the crate header when grouping by place open the link |

### Decisions taken, and why

| Decision | Chosen | Rejected, because |
|---|---|---|
| Place identity | new `place` table, **name is the key**; `record.bought_where` keeps the name verbatim | a `place_id` FK is a cleaner rename story but rewrites every read path — sort, group, search, filters, CSV export/import, scan autofill — for no user-visible gain. Links-only (a bare name→url map) leaves the typo problem unsolved |
| Picker | dropdown of existing places + a pinned `+ add a new location` row; no free typing into the record field | a type-to-filter combobox is better at 50+ places, and can be added later without changing the data; free text with a link button beside it keeps inventing phantom places |
| Editing a place | name **and** link; renaming rewrites every matching record, renaming onto an existing name merges | link-only can never clean up a typo already in the data. A delete needs a rule for the records left pointing at nothing, and rename-to-merge already covers the cleanup case |
| Link delivery to read surfaces | `GET /api/places` once at boot; the client keeps a name→url map | denormalizing `bought_where_url` onto every record still needs `/api/places` for the picker (a place used by zero records is invisible in the record list), and duplicates a string across ~250 rows |
| Backup | one new `bought_where_url` column on every export row | a separate places export makes a full backup two files and two steps, and the CSV is the one manual backup path the README documents |

---

## 2. Data model

### 2.1 New table

```python
class Place(db.Model):
    id   = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)  # matches record.bought_where verbatim
    url  = db.Column(db.String(500))                               # '' when unset
```

`Record.bought_where` is **unchanged**. Every existing reader — `sortBy`
`bought_where`, `bucketOf`'s `bought_where` case in `static/grouping.js`, the
"Bought at" facet in `static/filters.js`, the `bought_at` search field, the scan
autofill, the CSV mapping — keeps working with no edits.

The join between the two is the name, compared exactly after a trim. To keep that
join sound, `bought_where` is trimmed on every write — `create_record`, `update_record`,
`import_records_from_csv_rows` and the rename in `PUT /api/places/<id>` — so a
stray trailing space can never orphan a record from its place.

### 2.2 Migration and backfill

Follows the pattern already in the `with app.app_context():` block for
`cleaned_dates` and `cover_hash`: `db.create_all()` creates the `place` table on
first boot after deploy; if it was just created, insert one row per distinct
non-empty trimmed `bought_where`, with `url = ''`.

Distinct is case-sensitive here, matching how the datalist behaves today: if the
data holds both `Tracks` and `tracks`, the backfill produces two places and the
rename-merge is how you fix it. Inventing a canonical casing at backfill time
would silently rewrite records during a deploy.

---

## 3. API

All writes behind the existing `@require_auth`, exactly as the record endpoints
are. The read is public, like `/api/records`.

| Route | Body | Does |
|---|---|---|
| `GET /api/places` | — | `[{id, name, url}]`, sorted by name (case-insensitive) |
| `POST /api/places` | `{name, url}` | creates. `409` if the name already exists case-insensitively; `400` on an empty name or a URL that is not http(s) |
| `PUT /api/places/<id>` | `{name, url}` | updates. On a name change, also `UPDATE record SET bought_where=:new WHERE bought_where=:old`, in one transaction. Renaming onto an existing name (matched case-insensitively) **merges**: the other row is deleted and both sets of records land on the name **as typed in this request**. Responds `{place, records_updated}` |

There is no `DELETE`. A place that is no longer wanted is renamed into another.

The merge is also how a casing collision is resolved: `POST` refuses a name that
differs from an existing one only by case, but §2.2's backfill can produce such a
pair from data already in the collection, and `PUT` renaming one onto the other
collapses them — the casing typed into the rename wins, and every record on either
side is rewritten to it.

`/api/records` keeps its bare-array response shape — nothing is added to it.

### 3.1 URL rule

One helper, used by both write endpoints and by the importer:

- trim
- empty stays empty (a place with no link is normal, and renders as plain text)
- no scheme → prepend `https://`
- after that, anything whose scheme is not `http` or `https` is **rejected** with
  `400`

The rejection is load-bearing, not tidiness: the drawer turns this value into an
`href`, so a stored `javascript:` URL would become a click target.

---

## 4. Frontend

### 4.1 `static/places.js` — the pure rules

New module, following `static/notes.js`: exported pure functions, no DOM, tested
under node from a pytest wrapper.

| Function | Rule |
|---|---|
| `normalizeUrl(raw)` | the §3.1 rule, client side, so the form can show the error before the round trip |
| `validName(raw)` | non-empty after trim |
| `mergeTarget(name, places, editingId)` | the place this rename would merge into, or `null` — drives the confirm text |
| `sortPlaces(places)` | case-insensitive by name |
| `placeUrl(name, places)` | the name→url lookup the read surfaces use; unknown name → `''` |

### 4.2 The picker

Replaces `populateWhereList` and the `#fWhere` input + `#whereList` datalist in
`templates/index.html`.

- `#fWhere` becomes a read-only button showing the chosen name, or the
  `store / city` placeholder, plus a caret. The chosen name is held in a hidden
  input that `saveRecord` reads as `bought_where` — **the save payload is
  unchanged**.
- Clicking opens a panel: one row per place, each with a `✎` button, and a pinned
  `+ add a new location` row at the bottom.
- `✎` or `+` swaps the panel for a small form: name, link, save, cancel. Save
  POSTs or PUTs, then refreshes the place list **and** the records — a rename
  changed them.
- A rename that would merge asks first, naming the record count.
- The `✎` affordance renders only when `authed`; unauthed the panel is a plain
  chooser. This mirrors the form's existing auth gating.

### 4.3 Read surfaces

| Surface | Behaviour |
|---|---|
| Drawer Info tab (`dmInfoTabHTML`) | the "Bought at" cell becomes `<a href target="_blank" rel="noopener noreferrer">name <i class="ti ti-external-link"></i></a>` when the place has a URL; plain text otherwise, identical to today |
| Crate header, `groupBy === 'bought_where'` | a small external-link icon **button after** the label, only when the place has a URL |

The crate header link is deliberately a separate element rather than wrapping the
label: the header itself is the collapse target, and an anchor around it would
hijack that click.

Both go through `placeUrl()`, so a name with no matching place renders no link
rather than a broken href.

The "Bought at" filter chips are left alone — a click there means *filter by this
place*, and a link would navigate away from the collection instead.

---

## 5. Backup (CSV export/import)

- `cols` in `export_csv` gains `bought_where_url`, immediately after
  `bought_where`. Values come from one `{name: url}` dict built with a single
  query, so the export stays one pass over the records.
- `_record_mapping` reads `bought_where_url` when the column is present.
- `import_records_from_csv_rows` upserts a place for each distinct non-empty
  name + url pair it sees. A place that already exists **keeps its current url**
  when the CSV's is empty, and takes the CSV's when one is given.
- A CSV exported before this change has no such column and imports exactly as it
  does today; the places are created from the names alone, with empty links.

---

## 6. Testing

TDD throughout — the rule or endpoint test first, then the code.

**`tests/test_places.py`** (new): create; duplicate name → 409 (and
case-insensitively); non-http scheme → 400; scheme-less URL gets `https://`;
empty name → 400; rename rewrites every matching record and leaves others alone;
rename onto an existing name merges and deletes the absorbed row; writes require
auth; `GET` works unauthed.

**`tests/test_places.js`** + **`tests/test_places.py::test_places_js`** wrapper
(the `test_notes.py` shape): every rule in §4.1, including `placeUrl` on an
unknown name and `mergeTarget` ignoring the place being edited.

**`tests/test_import.py`** additions: round-trip a collection with links; import a
CSV with no `bought_where_url` column; an existing place keeps its link when the
CSV's cell is empty.

**`tests/test_grouping.js`**: the `bought_where` buckets are unchanged — the new
header link must not touch bucketing.

**`docs/places-manual-verification.md`**: the by-hand checks for the picker, the
drawer link and the rename-merge, following the repo's existing
`*-manual-verification.md` convention.

---

## 7. Out of scope

- Unifying the picker with the genre select and the country datalist. This form
  will have three dropdown-ish widgets that share no code; making them one
  component is a refactor of its own, not this feature's job.
- Type-to-filter in the picker. Worth it past ~50 places; the data model here does
  not change when it arrives.
- Deleting a place, and any per-place page or stats (spend per store, records per
  store). The link is the whole ask.
