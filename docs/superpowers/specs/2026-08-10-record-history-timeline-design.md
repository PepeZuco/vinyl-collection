# Record History Timeline

## Problem

The record detail view (shared by mobile and desktop through `dmInfoHTML()` in
`templates/index.html`) shows a "Notes across time" list, but individual play
dates and cleaning dates aren't shown there at all — they only exist in the
calendar view. "Last cleaned" is also a single value, not a history, so a
record can't record more than one cleaning. The detail view should show the
full life story of a record — when it was bought, played, cleaned, and
annotated — as one merged, chronological timeline.

## 1. Data model — `cleaned_dates`

`Record.last_cleaned` (single `VARCHAR(50)`) is superseded by a new column:

```python
cleaned_dates = db.Column(db.Text)  # JSON array of ISO date strings, one per cleaning
```

This mirrors the existing `play_dates` column exactly (same JSON-array-of-ISO-
date-strings convention, same helper pattern on the frontend).

**Migration** (in the existing auto-migration block in `app.py`, alongside the
`country`/`play_dates` migration that already runs on startup):

1. Add `cleaned_dates TEXT` if missing (same `ALTER TABLE` pattern already
   used for `country` and `play_dates`).
2. Backfill: for any row where `last_cleaned` is non-empty and `cleaned_dates`
   is null/empty, set `cleaned_dates = json.dumps([last_cleaned])`.

`last_cleaned` stays in the DB schema (SQLite can't cheaply drop columns) but
becomes dead — the app stops reading or writing it after migration. It is not
exposed in any new code path.

**Touch points in `app.py`:**
- `Record.to_dict()` — add `cleaned_dates`, drop `last_cleaned` from the
  returned dict.
- `create_record` — accept `cleaned_dates` the same way `play_dates` is
  accepted.
- `update_record` — `if "cleaned_dates" in d: r.cleaned_dates = d["cleaned_dates"]`,
  same shape as the existing `play_dates` handling.

## 2. Edit form — "Cleaned on" multi-date list

The "Last cleaned" single `<input type=date id=fCleaned>` is replaced with a
"Cleaned on" section structurally identical to the existing "Played on"
section: a list of date rows with per-row remove buttons, plus an "add
cleaning date" button.

New frontend helpers mirror the existing play-date helpers 1:1:
- `parseCleanedDates(raw)` — same shape as `parsePlayDates(raw)`.
- `addCleanedDate()` — same shape as `addPlayDate()`.
- A `formCleanedDates` array (parallel to `formPlayDates`) and an
  `fCleanedDatesList` container (parallel to `fPlayDatesList`).

On open-for-edit, `formCleanedDates = parseCleanedDates(r.cleaned_dates)`
replaces the old `fCleaned.value = r.last_cleaned`. On save, the payload
sends `cleaned_dates: JSON.stringify(formCleanedDates)` instead of
`last_cleaned`.

## 3. Detail view — merged History timeline

`dmInfoHTML(r)` (`templates/index.html`) renders identically for mobile and
desktop already — it's injected into both `.detail-info-col` (desktop) and
`#dmInfo` (mobile) from the same function, so this is a single change that
covers both surfaces.

The current "Notes across time" block (`.dm-notes`) is replaced with a
"History" block that merges four event types into one list:

| type    | source                          | label                        | dot color                  |
|---------|----------------------------------|-------------------------------|-----------------------------|
| bought  | `bought_date` (single, if set)   | "Added to the collection"    | `var(--accent)` (gold)      |
| played  | each date in `play_dates`        | "Played"                     | `#5FBF7A` (green)           |
| cleaned | each date in `cleaned_dates`      | "Cleaned"                    | `#4AA3C4` (teal)            |
| note    | each dated note (`parseNotes`)   | note text, markdown-rendered | `#9B7FD4` (purple)          |

These colors match the calendar view's existing event color coding
(`.cal-dot.bought/.cleaned/.played/.note`), so the visual language is
consistent across the app.

All events are merged into one array and sorted **newest first**. Each row
renders as: colored dot, formatted date (`dmFormatNoteDate`, same as today),
and content (note rows keep today's `marked.parse()` markdown rendering;
bought/played/cleaned rows render their static label). If a record has no
`bought_date` and no play/cleaning/note history, the History section is
omitted entirely (same empty-state behavior as today's notes block).

This view stays **read-only**: adding or editing plays, cleanings, and notes
continues to happen only in the edit form (section 2 and the existing
play-dates/notes sections). No inline quick-add controls are added here.

## 4. Calendar view + CSV — updated for multi-date cleaning

**Calendar** (`templates/index.html`, the month/week/day view logic around
`calValidDate`/the `cleaned` event collection): currently reads
`r.last_cleaned` as a single date. Updated to iterate `cleaned_dates` the same
way it already iterates `play_dates` for the `played` event type — a record
cleaned three times shows three teal dots instead of one. The `cleaned`
filter toggle, its color, and its icon are unchanged.

**CSV export** (`app.py`, `export_csv`): the `last_cleaned` column in the
exported column list is replaced with `cleaned_dates` (JSON array string,
same convention as the existing `play_dates` column).

**CSV import** (`app.py`, `import_records_from_csv_text`): reads
`cleaned_dates` if present. For backward compatibility with older exports
that only have `last_cleaned`, if `cleaned_dates` is absent/empty but
`last_cleaned` is present, seed `cleaned_dates` as a single-element JSON
array from `last_cleaned`.

## Out of scope

- Inline quick-add (logging a play/cleaning/note) from the History view —
  stays in the edit form.
- Editing or deleting individual history entries from the detail view.
- Any change to how ratings, genre, or the meta grid (bought
  date/where/by/country) are displayed — those are unchanged, sitting above
  the new History section as they do today.
