# Multi-Artist Records

## Problem

Compilation records are currently entered with the artist field set to a literal
string like "Varios Artistas" ("Various Artists"), which loses the actual list of
artists on the record. Records will be updated manually to list real artist names
instead. The app needs to support entering, storing, displaying, and sorting
records that have multiple artists.

## Storage

No schema change. Multiple artists are stored in the existing `artist` column
(`VARCHAR(200)`, SQLite in both dev and prod) as a semicolon-delimited string:

```
Artist A; Artist B; Artist C
```

Semicolon was chosen over comma because band/artist names can legitimately
contain commas (e.g. "Earth, Wind & Fire"), which would produce false positives
when detecting "multiple artists" from the string. A single artist's name is
just the plain string with no delimiter, as today.

## Helper logic

Two pure functions in `templates/index.html`, used everywhere the artist field
is read:

```js
function artistList(r) { return (r.artist||'').split(';').map(s=>s.trim()).filter(Boolean); }
function isMultiArtist(r) { return artistList(r).length > 1; }
```

No backend changes are required — `app.py` already stores and returns whatever
string is in `artist` with no validation, so the delimited format round-trips
through the API and CSV import/export unchanged.

## Edit form

Add a "Multiple artists" checkbox near the existing Artist field (`#fArtist`)
in the add/edit form (`templates/index.html` ~line 1123).

- **Unchecked** (default): today's single text input, unchanged.
- **Checked**: swap in a repeatable list of artist-name inputs with add/remove
  row buttons, following the same pattern already used for the play-dates and
  notes repeatable rows in this form.

On submit (`submitForm()`), if the checkbox is checked, join the non-empty rows
with `"; "` and send that as the `artist` field — same API payload shape as
today, no backend change needed.

On edit (`openEdit()`), detect existing multi-artist records via
`isMultiArtist(r)` and pre-populate either the single field or the row list
accordingly, so editing an already-split record shows the rows, not raw
semicolons in a single input.

## Display indicator

A small icon badge (tabler icon, e.g. `ti-users`, matching the icon set already
used elsewhere in the UI) is shown next to the artist name whenever
`isMultiArtist(r)` is true, in the three main record views:

- List view (`.list-artist`)
- Card overlay (`.vcard-artist-overlay`)
- Detail modal (`.dm-artist`)

Other, more compact/secondary UI that also renders the artist string —
the calendar view (`.cal-ev-artist`), week-chip tooltips, and the stats
tooltip (`chartTooltipHTML`) — intentionally omits the badge to avoid
clutter in those dense views. Those places still use the joined `" / "`
display (via `artistDisplay(r)`) rather than the raw semicolon, they just
don't render the icon.

The visible artist text itself joins the names with `" / "` (e.g.
"Artist A / Artist B") rather than showing the raw semicolon delimiter.

## Sorting

In `filtered()`'s sort comparator (`templates/index.html` ~line 1384), when
`sortBy === 'artist'`: multi-artist records always sort after all single-artist
records, regardless of `sortDir` (asc or desc). Within each group (multi vs.
single), alphabetical comparison applies as today and still respects `sortDir`
for direction.

## Search

No change. Search already does substring matching against `r.artist`, so a
query naturally matches any of the joined names within a multi-artist string.

## Stats ("top artists" ranking)

Out of scope for this change. Multi-artist records group under their full
combined string as a single bucket in the ranking, same as any other artist
value today. Can be revisited later (e.g. splitting credit across each artist)
if it becomes a problem in practice.

## CSV import/export

No change. The delimited string is plain text and round-trips through CSV like
any other field.

## Testing

Manual verification (no automated test suite exists in this project):

1. Create a new record via the "Multiple artists" checkbox flow with 2-3 names;
   confirm it saves and displays with the indicator badge in list, card, and
   detail views.
2. Edit an existing multi-artist record; confirm the row-list UI pre-populates
   correctly (not raw semicolons in one field).
3. Sort by Artist in both ascending and descending order; confirm multi-artist
   records are always last.
4. Search for one of the artist names within a multi-artist record; confirm it
   matches.
5. Export to CSV and re-import; confirm the multi-artist record round-trips
   correctly.
