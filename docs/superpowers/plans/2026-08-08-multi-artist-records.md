# Multi-Artist Records Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let records have multiple artists (e.g. compilation albums), stored in the existing `artist` field, shown with an indicator, and sorted to the end when sorting by artist.

**Architecture:** All changes are in `templates/index.html` (vanilla JS + inline CSS, single-file frontend). No backend or schema changes — `app.py` already stores and returns whatever string is in the `artist` column with no validation, so a delimited string round-trips through the existing API, CSV export, and CSV import unchanged.

**Tech Stack:** Flask + Flask-SQLAlchemy backend (`app.py`, untouched by this plan), vanilla JS + Tabler icons webfont frontend (`templates/index.html`).

## Global Constraints

- Multiple artists are stored as one string in the `artist` column, joined with `"; "` (semicolon-space), e.g. `"Artist A; Artist B"`. Semicolon was chosen over comma because artist/band names can legitimately contain commas (e.g. "Earth, Wind & Fire"), which would false-positive as "multiple artists" under a comma delimiter.
- No new files, no new DB columns, no backend changes. Every change lives in `templates/index.html`.
- This project has no automated test suite (confirmed: no test framework, no CI, only manual QA). Every task's verification step is manual: run the app locally and check behavior in the browser. Do not introduce a test framework as part of this plan — out of scope.
- Follow existing code patterns exactly where an equivalent already exists (e.g. the play-dates repeatable-row editor at `formPlayDates`/`renderPlayDatesForm()` is the template for the new artist-rows editor).

---

### Task 1: Artist helpers + read-only display with indicator

**Files:**
- Modify: `templates/index.html` — CSS near line 684 (`.list-artist`), JS near line 1332 (after `avgRating`), and three render sites: list view (~line 1445), card overlay (~line 1582), detail modal (~line 1712).

**Interfaces:**
- Produces (used by later tasks):
  - `artistList(r)` → `string[]`, trimmed non-empty artist names from `r.artist`.
  - `isMultiArtist(r)` → `boolean`, true when `artistList(r).length > 1`.
  - `artistDisplay(r)` → `string`, artist names joined with `" / "` for display.
  - `multiArtistBadgeHTML()` → `string`, HTML for the small indicator icon.

- [ ] **Step 1: Add the badge CSS**

In `templates/index.html`, find this line (around line 684):

```css
.list-artist{font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
```

Add a new rule immediately after it:

```css
.list-artist{font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.multi-artist-badge{font-size:10px;opacity:.6;margin-left:4px}
```

- [ ] **Step 2: Add the artist helper functions**

Find this block (around line 1328):

```js
// avg uses only ratings that exist — if only one person rated, uses that score alone
function avgRating(r) {
  const scores = [Number(r.my_rating)||0, Number(r.wife_rating)||0].filter(x => x > 0);
  return scores.length ? scores.reduce((a,b)=>a+b,0) / scores.length : 0;
}

// ── filtering & sorting ────────────────────────────────────────────────────
```

Insert a new helpers block between the `avgRating` function and the `filtering & sorting` comment:

```js
// avg uses only ratings that exist — if only one person rated, uses that score alone
function avgRating(r) {
  const scores = [Number(r.my_rating)||0, Number(r.wife_rating)||0].filter(x => x > 0);
  return scores.length ? scores.reduce((a,b)=>a+b,0) / scores.length : 0;
}

// ── multi-artist records ────────────────────────────────────────────────────
// artist field stores multiple names as "Name A; Name B" — semicolon was chosen
// over comma because band names can legitimately contain commas (e.g. "Earth,
// Wind & Fire"), which would false-positive as "multiple artists"
function artistList(r) {
  return (r.artist||'').split(';').map(s => s.trim()).filter(Boolean);
}
function isMultiArtist(r) {
  return artistList(r).length > 1;
}
function artistDisplay(r) {
  return artistList(r).join(' / ');
}
function multiArtistBadgeHTML() {
  return '<i class="ti ti-users multi-artist-badge" title="multiple artists"></i>';
}

// ── filtering & sorting ────────────────────────────────────────────────────
```

- [ ] **Step 3: Use the helpers in the list view render**

Find (around line 1445):

```js
      <div class="list-artist">${esc(r.artist)||'unknown'}${r.country ? ' '+flagImgHTML(r.country, 14) : ''}</div>
```

Replace with:

```js
      <div class="list-artist">${esc(artistDisplay(r))||'unknown'}${isMultiArtist(r) ? multiArtistBadgeHTML() : ''}${r.country ? ' '+flagImgHTML(r.country, 14) : ''}</div>
```

- [ ] **Step 4: Use the helpers in the card overlay render**

Find (around line 1582):

```js
      <div class="vcard-artist-overlay">${esc(r.artist)||'unknown'}</div>
```

Replace with:

```js
      <div class="vcard-artist-overlay">${esc(artistDisplay(r))||'unknown'}${isMultiArtist(r) ? multiArtistBadgeHTML() : ''}</div>
```

- [ ] **Step 5: Use the helpers in the detail modal render**

Find (around line 1712):

```js
    <div class="dm-artist">${esc(r.artist)||'unknown'}</div>
```

Replace with:

```js
    <div class="dm-artist">${esc(artistDisplay(r))||'unknown'}${isMultiArtist(r) ? multiArtistBadgeHTML() : ''}</div>
```

- [ ] **Step 6: Manual verification**

Run the app locally (`python app.py` or `flask run`, whatever the project normally uses) and open it in a browser.

1. Open any existing record, click edit, and type `Pixies; The Breeders` into the Artist field (the single input — the multi-row UI doesn't exist yet, this task only tests display). Save.
2. Confirm the list view shows "Pixies / The Breeders" with a small users-icon badge after it.
3. Switch to card/grid view (if the app has one) and confirm the overlay shows the same, with badge.
4. Open the record's detail view and confirm the same joined text + badge.
5. Confirm an unrelated single-artist record still shows just its plain name, with no badge.
6. Edit the test record back to a single artist name (e.g. `Pixies`) to leave the data clean for Task 2/3 testing, or leave it — Task 2 needs a multi-artist record anyway.

- [ ] **Step 7: Commit**

```bash
git add templates/index.html
git commit -m "Add multi-artist display helpers and indicator badge"
```

---

### Task 2: Sorting — multi-artist records always last

**Files:**
- Modify: `templates/index.html` — `filtered()` sort comparator, around line 1384.

**Interfaces:**
- Consumes: `isMultiArtist(r)` from Task 1.

- [ ] **Step 1: Special-case the artist field in the sort comparator**

Find this block (around line 1384):

```js
  }).sort((a, b_) => {
    let cmp;
    if (s === 'bought_date') cmp = (b_.bought_date||'').localeCompare(a.bought_date||'');
    else if (s === 'avg_rating')  cmp = avgRating(b_) - avgRating(a);
    else if (['year','my_rating','wife_rating','play_count'].includes(s)) cmp = (Number(b_[s])||0) - (Number(a[s])||0);
    else cmp = (a[s]||'').localeCompare(b_[s]||'');
    return sortDir === 'asc' ? -cmp : cmp;
  });
```

Replace with:

```js
  }).sort((a, b_) => {
    if (s === 'artist') {
      const aMulti = isMultiArtist(a), bMulti = isMultiArtist(b_);
      if (aMulti !== bMulti) return aMulti ? 1 : -1; // multi-artist records always last, regardless of sortDir
      const cmp = (a.artist||'').localeCompare(b_.artist||'');
      return sortDir === 'asc' ? -cmp : cmp;
    }
    let cmp;
    if (s === 'bought_date') cmp = (b_.bought_date||'').localeCompare(a.bought_date||'');
    else if (s === 'avg_rating')  cmp = avgRating(b_) - avgRating(a);
    else if (['year','my_rating','wife_rating','play_count'].includes(s)) cmp = (Number(b_[s])||0) - (Number(a[s])||0);
    else cmp = (a[s]||'').localeCompare(b_[s]||'');
    return sortDir === 'asc' ? -cmp : cmp;
  });
```

Note: this keeps the exact same within-group alphabetical formula and `sortDir` handling the default (non-artist) branch already used for text fields — only the multi-vs-single grouping is pulled out from under the `sortDir` flip, since that grouping must stay fixed regardless of direction.

- [ ] **Step 2: Manual verification**

1. Make sure at least one record has a multi-artist value (e.g. the `Pixies; The Breeders` record from Task 1, or create one by typing a `;`-separated value into the Artist field directly).
2. In the UI, set sort to "Artist".
3. With the default sort direction, confirm the multi-artist record appears last in the list.
4. Toggle the sort direction button and confirm the multi-artist record still appears last (not first).
5. Confirm single-artist records still reorder alphabetically (forward/reverse) between the two toggle states, same as before this change.

- [ ] **Step 3: Commit**

```bash
git add templates/index.html
git commit -m "Sort multi-artist records to the end when sorting by artist"
```

---

### Task 3: Edit form — checkbox + dynamic artist rows

**Files:**
- Modify: `templates/index.html` — CSS near line 715 (`.playdate-row`), form HTML near line 1123 (Artist form-group), JS state/render functions near line 1917 (`formPlayDates`), `openAdd()` (~line 2013), `openEdit()` (~line 2035), `submitForm()` (~line 2073).

**Interfaces:**
- Consumes: `artistList(r)`, `isMultiArtist(r)` from Task 1.
- Produces: `formArtists` (in-memory `string[]` while the form is open), `renderArtistsForm()`, `addArtistRow()`, `updateArtistRow(idx, value)`, `deleteArtistRow(idx)`, `toggleMultiArtist()`.

- [ ] **Step 1: Add CSS for the artist rows, mirroring the existing play-date rows**

Find (around line 711):

```css
/* ── play-date editor in form ──────────────────────────────────────────────── */
.playdates-section{display:flex;flex-direction:column;gap:8px}
.playdates-list{display:flex;flex-wrap:wrap;gap:8px}
.playdates-list:empty{display:none}
.playdate-row{display:flex;align-items:center;gap:4px;background:var(--card);
  border:1px solid var(--border);border-radius:var(--radius-sm);padding:4px 4px 4px 8px}
.playdate-row input[type=date]{background:transparent;color:var(--text);border:none;
  font-size:13px;outline:none;font-family:var(--font);padding:2px 0;width:130px}
.playdate-delete{background:transparent;border:none;color:var(--muted);cursor:pointer;
  font-size:13px;padding:3px 4px;border-radius:3px;line-height:1;display:flex}
.playdate-delete:hover{color:var(--danger)}
.playdates-empty{font-size:12px;color:var(--muted);padding:2px 0}
```

Add a new block immediately after it:

```css
/* ── multi-artist editor in form ───────────────────────────────────────────── */
.artists-list{display:flex;flex-direction:column;gap:6px}
.artist-row{display:flex;align-items:center;gap:4px;background:var(--card);
  border:1px solid var(--border);border-radius:var(--radius-sm);padding:4px 4px 4px 8px}
.artist-row input[type=text]{background:transparent;color:var(--text);border:none;
  font-size:13px;outline:none;font-family:var(--font);padding:2px 0;flex:1}
.artist-delete{background:transparent;border:none;color:var(--muted);cursor:pointer;
  font-size:13px;padding:3px 4px;border-radius:3px;line-height:1;display:flex}
.artist-delete:hover{color:var(--danger)}
```

- [ ] **Step 2: Add the checkbox and rows container to the form HTML**

Find (around line 1123):

```html
            <div class="form-group"><label>Artist</label><input id="fArtist" placeholder="artist name"></div>
```

Replace with:

```html
            <div class="form-group">
              <label>Artist</label>
              <input id="fArtist" placeholder="artist name">
              <div class="check-row" style="margin-top:6px">
                <input type="checkbox" id="fMultiArtist" onchange="toggleMultiArtist()">
                <label for="fMultiArtist">multiple artists (e.g. compilation)</label>
              </div>
              <div class="artists-list" id="fArtistsList" style="display:none"></div>
              <button type="button" class="btn btn-sm" id="fAddArtist" style="margin-top:6px;display:none" onclick="addArtistRow()"><i class="ti ti-plus"></i> add artist</button>
            </div>
```

- [ ] **Step 3: Add the `formArtists` state and render/edit functions**

Find (around line 1916):

```js
let formNotes = []; // in-memory list while the form is open
let formPlayDates = []; // ditto for the play-date editor
```

Replace with:

```js
let formNotes = []; // in-memory list while the form is open
let formPlayDates = []; // ditto for the play-date editor
let formArtists = []; // ditto for the multi-artist editor
```

Find (around line 1987, right after `deletePlayDate`):

```js
function deletePlayDate(idx) {
  formPlayDates.splice(idx, 1);
  bumpPlayCount(-1);
  renderPlayDatesForm();
}
```

Add a new block immediately after it:

```js
function deletePlayDate(idx) {
  formPlayDates.splice(idx, 1);
  bumpPlayCount(-1);
  renderPlayDatesForm();
}

// ── multi-artist editor in the form ─────────────────────────────────────────
function renderArtistsForm() {
  const list = document.getElementById('fArtistsList');
  list.innerHTML = formArtists.map((name, i) => `
    <div class="artist-row">
      <input type="text" value="${esc(name)}" placeholder="artist name" onchange="updateArtistRow(${i}, this.value)">
      <button type="button" class="artist-delete" title="remove this artist" onclick="deleteArtistRow(${i})"><i class="ti ti-trash"></i></button>
    </div>`).join('');
}

function addArtistRow() {
  formArtists.push('');
  renderArtistsForm();
}

// no re-render here: rebuilding the inputs mid-edit would steal focus
function updateArtistRow(idx, value) {
  formArtists[idx] = value;
}

function deleteArtistRow(idx) {
  formArtists.splice(idx, 1);
  if (!formArtists.length) formArtists.push('');
  renderArtistsForm();
}

function toggleMultiArtist() {
  const multi = document.getElementById('fMultiArtist').checked;
  document.getElementById('fArtist').style.display = multi ? 'none' : '';
  document.getElementById('fArtistsList').style.display = multi ? '' : 'none';
  document.getElementById('fAddArtist').style.display = multi ? '' : 'none';
  if (multi && formArtists.length === 0) {
    const existing = document.getElementById('fArtist').value.trim();
    formArtists = existing ? [existing] : [''];
    renderArtistsForm();
  }
}
```

- [ ] **Step 4: Reset multi-artist state when opening the "add record" form**

Find (around line 2013):

```js
function openAdd(){
  editingId=null;myRating=0;wifeRating=0;coverDataUri='';
  document.getElementById('formTitle').textContent='add record';
  ['fArtist','fAlbum','fYear','fWhere','fBuyer','fCountry'].forEach(id=>document.getElementById(id).value='');
```

Replace with:

```js
function openAdd(){
  editingId=null;myRating=0;wifeRating=0;coverDataUri='';
  document.getElementById('formTitle').textContent='add record';
  ['fArtist','fAlbum','fYear','fWhere','fBuyer','fCountry'].forEach(id=>document.getElementById(id).value='');
  formArtists=[];
  document.getElementById('fMultiArtist').checked=false;
  document.getElementById('fArtist').style.display='';
  document.getElementById('fArtistsList').style.display='none';
  document.getElementById('fAddArtist').style.display='none';
  renderArtistsForm();
```

- [ ] **Step 5: Pre-populate multi-artist state when opening the "edit record" form**

Find (around line 2040):

```js
  document.getElementById('fArtist').value=r.artist||'';
```

Replace with:

```js
  if (isMultiArtist(r)) {
    formArtists = artistList(r);
    document.getElementById('fMultiArtist').checked = true;
    document.getElementById('fArtist').value = '';
    document.getElementById('fArtist').style.display = 'none';
    document.getElementById('fArtistsList').style.display = '';
    document.getElementById('fAddArtist').style.display = '';
  } else {
    formArtists = [];
    document.getElementById('fMultiArtist').checked = false;
    document.getElementById('fArtist').value = r.artist||'';
    document.getElementById('fArtist').style.display = '';
    document.getElementById('fArtistsList').style.display = 'none';
    document.getElementById('fAddArtist').style.display = 'none';
  }
  renderArtistsForm();
```

- [ ] **Step 6: Build the joined artist string on submit**

Find (around line 2075):

```js
    artist:document.getElementById('fArtist').value,
```

Replace with:

```js
    artist: document.getElementById('fMultiArtist').checked
      ? formArtists.map(s => s.trim()).filter(Boolean).join('; ')
      : document.getElementById('fArtist').value,
```

- [ ] **Step 7: Manual verification — full end-to-end flow**

1. Click "add record", check "multiple artists", add two rows (e.g. "Artist A", "Artist B"), fill in the rest of the required fields, save.
   - Confirm the new record shows "Artist A / Artist B" with the badge in list, card, and detail views (Task 1's rendering).
   - Confirm it sorts to the end when sorting by artist, both directions (Task 2's sorting).
2. Open that record for editing again.
   - Confirm the checkbox is pre-checked and the two rows are pre-populated with "Artist A" and "Artist B" (not a single field with raw semicolons).
   - Remove one row, add a different name, save, and confirm the change is reflected everywhere.
3. Uncheck "multiple artists" on a multi-artist record, confirm the single field becomes editable and the rows hide; type a plain name and save; confirm the record now displays as single-artist with no badge.
4. Type one of the artist names from a multi-artist record into the search box; confirm it matches and the record shows up in results.
5. Use the app's CSV export, then re-import the same file; confirm the multi-artist record's artist field round-trips correctly (still shows joined names + badge after re-import).

- [ ] **Step 8: Commit**

```bash
git add templates/index.html
git commit -m "Add multi-artist checkbox and dynamic artist rows to the edit form"
```
