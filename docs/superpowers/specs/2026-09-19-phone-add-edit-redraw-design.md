# The add/edit form, redrawn for the phone — design

> **Status:** approved design, not yet implemented
> **Date:** 2026-09-19
> **Scope:** the add/edit form below 760px is redrawn for one thumb in
> standalone Safari; editing drops the wizard for a section list; the app gains
> a real home-screen icon. Desktop is untouched and no field id changes.
>
> **Mockup:** https://claude.ai/artifact/K8uuzh8EMS8VGzsFq8KatL

---

## 1. What this changes, and what it does not

The form already has a mobile pass — `@media(max-width:760px)` at
`templates/index.html:2320` made it full-screen, pinned the footer and forced
inputs to 16px so iOS stops zooming on focus. That pass fixed the fatal problem
(Save was below the fold). It did not redraw anything: every control is still
the desktop control at a smaller size.

Three complaints, and only three:

| | |
|---|---|
| **Desktop-shaped** | the cover well, the three-across scan buttons, the four-across step spine and the 2-up `.form-grid` are all sized for a cursor |
| **The keyboard fights it** | the footer is `position:sticky;bottom:0` inside a `height:100%` flex column — iOS shrinks nothing, so the keyboard covers Back/Next/Save entirely |
| **It does not feel installed** | no `viewport-fit=cover`, no safe-area padding, no standalone meta, and the home-screen icon is a letter Z |

**The step count is not one of them.** Steps 1–4 stay, in the same order, with
the same fields and the same ids. `formValues()`, `applyDraft()`, the scan
autofill, the queue and every test that reaches into the form keep working
untouched.

### Decisions taken, and why

| Decision | Chosen | Rejected, because |
|---|---|---|
| Step 1's opening | three 66px lookup rows (camera / search / Spotify); fields appear after a match | every add starts with a lookup, never with typing, so opening on an empty artist field with the three lookups wedged into a 42px `.scan-actions` triplet leads with the thing that is never used first |
| Lookup rows after a match | they disappear; `Pick a different match` in the identity strip is the way back | keeping them pinned costs ~200px, which is exactly the space the redraw exists to reclaim. The re-pick button already reopens the scan results without paying for a new call |
| Cover, once filled | collapses to an 84px thumb in an identity strip | the 180px `.cover-drop` well earns its size while it is a drop target and nothing after that |
| Editing | no wizard — a list of four sections plus three one-tap log actions | walking 1→2→3→4 to change one field is the actual complaint; and "log a play" is today *edit → step 3 → scroll → add play date → picker → save* |
| Quick actions | write today's date immediately, toast with **Undo** | a date picker in front of the common case pays for the rare one. Silent writes give nothing to trust and nothing to reverse |
| Save in the nav bar | live from step 1, exactly as today | the form was built so a record you just bought can be on the shelf before you have decided anything else about it; gating on artist+album breaks that |
| Keyboard handling | size the overlay from `visualViewport.height` | `interactive-widget=resizes-content` in the viewport meta is one line, but Safari ignores it — it is a Chromium feature. `env(keyboard-inset-height)` is not in Safari either |
| Icon | the existing mark on `#0c0c0c`, flat 180×180 PNG | full-bleed purple crops the label and stops reading as a record. SVG is ignored by iOS for `apple-touch-icon`, and any alpha is composited onto black |
| Phone detection | one `isPhone()` helper reading the same 760px breakpoint via `matchMedia` | duplicating the number in JS and CSS is how the two drift; a `body.phone` class set at boot misses an orientation change on an iPad |

### Out of scope

The detail drawer (`#detailOverlay`) already has its own mobile layout from
`templates/index.html:876` and is not touched. The scan overlay's mobile rules
at `:1386` are not touched. No API route changes except one new endpoint-free
write path reusing `PUT /api/records/<id>`.

---

## 2. The home-screen icon

### 2.1 Why it is a Z

`templates/index.html:7` declares one icon:

```html
<link rel="icon" type="image/png" href="/static/vinyl-icon.png">
```

There is no `apple-touch-icon` and no manifest. When iOS adds a page to the home
screen with no touch icon it generates a tile from the page — in practice, the
first letter of `<title>`, which is the Z of *Zucoloto's Vinyl Collection*.

### 2.2 What ships

The mark already exists as `static/vinyl-icon.svg` — purple `#9B7FD4` ring,
gold `#F5C518` field, pink `#D4608A` label, black spindle. It is rendered onto
the app's own ground rather than shipped transparent, because iOS composites
alpha onto black and masks the tile into a squircle itself.

| File | Size | Notes |
|---|---|---|
| `static/icon-180.png` | 180×180 | `apple-touch-icon`. Mark at 86% of the tile, centred, on `#0c0c0c`. No alpha, **no pre-rounded corners** — iOS applies the mask |
| `static/icon-192.png` | 192×192 | manifest, Android |
| `static/icon-512.png` | 512×512 | manifest, splash screen |
| `static/manifest.json` | — | see below |

Generated from the SVG with a one-off script committed as
`tools/make_icons.py` (Pillow + `cairosvg`, or `rsvg-convert` if available),
so the mark can be changed once and re-rendered rather than hand-edited three
times. The script is not part of the app's runtime or its requirements.

`static/manifest.json`:

```json
{
  "name": "Zucoloto's Vinyl Collection",
  "short_name": "Vinyl",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#0c0c0c",
  "theme_color": "#0c0c0c",
  "icons": [
    {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"}
  ]
}
```

### 2.3 Head changes

Replacing line 5 and adding after line 7:

```html
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
...
<link rel="apple-touch-icon" href="/static/icon-180.png">
<link rel="manifest" href="/static/manifest.json">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Vinyl">
```

`apple-mobile-web-app-title` is **Vinyl**, not the full title: the home-screen
caption truncates at roughly 12 characters and "Zucoloto's Vin…" is worse than
a short true name.

`black-translucent` puts the status bar over the page, which is why
`viewport-fit=cover` and the safe-area work in §3.1 have to land in the same
change — without them the header slides under the clock.

**Anyone who already added the app to their home screen keeps the Z.** iOS
caches the tile at install time. The icon is picked up by removing the shortcut
and re-adding it; this goes in the manual verification doc rather than being
worked around.

---

## 3. Shared phone mechanics

### 3.1 Safe areas

`viewport-fit=cover` lets the page paint edge to edge, which means the page is
now responsible for keeping content out from under the notch and the home
indicator.

```css
@media(max-width:760px){
  #formOverlay .modal.modal-wide{ padding-top:env(safe-area-inset-top,0px); }
  #formOverlay .modal-foot{ padding-bottom:calc(11px + env(safe-area-inset-bottom,0px)); }
}
```

The overlay is `position:fixed;inset:0`, so it is the overlay's own children
that take the insets, not `body`.

### 3.2 The keyboard

The footer is pinned to the bottom of a `height:100%` container. iOS does not
resize the layout viewport when the keyboard opens, so the bottom of that
container is under the keyboard and the action bar is gone until the field is
dismissed.

The fix drives the overlay's height from the **visual** viewport:

```js
/* iOS leaves the layout viewport at full height when the keyboard opens, so a
 * bottom-pinned bar ends up behind it. visualViewport reports what is actually
 * on screen; writing it to a custom property lets the CSS stay declarative. */
function syncViewportHeight(){
  const vv = window.visualViewport;
  if (!vv) return;                                  // desktop, and older Safari
  document.documentElement.style.setProperty('--vvh', vv.height + 'px');
}
if (window.visualViewport){
  ['resize','scroll'].forEach(e => window.visualViewport.addEventListener(e, syncViewportHeight));
  syncViewportHeight();
}
```

```css
@media(max-width:760px){
  #formOverlay .modal.modal-wide{ height:var(--vvh,100%); }
}
```

`scroll` is listened to as well as `resize` because iOS scrolls the visual
viewport when a focused field would otherwise sit under the keyboard, and the
overlay has to follow.

Focus then scrolls the field clear of the bar:

```js
document.addEventListener('focusin', e => {
  const f = e.target.closest('#formOverlay input,#formOverlay textarea,#formOverlay select');
  if (!f || !isPhone()) return;
  // after the keyboard animation, not during it — a scroll issued mid-animation
  // lands against the pre-keyboard viewport and undoes itself
  setTimeout(() => f.scrollIntoView({block:'center', behavior:'smooth'}), 300);
});
```

The 300ms is the keyboard animation, not a guess at layout: a `scrollIntoView`
issued before it finishes is measured against the old viewport and snaps back.

### 3.3 `isPhone()`

```js
/* One source for the breakpoint. 760px matches the media query the form's
 * mobile rules already use; reading it through matchMedia means an iPad
 * rotating into range gets the phone layout without a reload. */
const phoneMQ = window.matchMedia('(max-width:760px)');
function isPhone(){ return !!(phoneMQ && phoneMQ.matches); }
/* addEventListener on a MediaQueryList is Safari 14+; addListener is the
 * deprecated spelling every older engine has. Feature-detected rather than
 * assumed, because the jsdom harness provides only the old one. */
if (phoneMQ.addEventListener) phoneMQ.addEventListener('change', onBreakpointChange);
else if (phoneMQ.addListener) phoneMQ.addListener(onBreakpointChange);

function onBreakpointChange(){
  if (!document.getElementById('formOverlay').classList.contains('hidden')) rebuildFormChrome();
}
```

`rebuildFormChrome()` re-renders the nav bar, the rail and the footer for the
current mode. It is the same function `setFormStep` calls, so a rotation is
handled by the code that already exists rather than by a reload.

### 3.4 The nav bar and the rail

On the phone, `.modal-head` becomes a nav bar and `.form-spine` becomes a rail.
Both are rendered by `rebuildFormChrome()`; on desktop it renders exactly what
`setFormStep` renders today, so there is one code path with a branch rather
than two layouts to keep in step.

```
┌──────────────────────────────┐
│           ▭ grabber           │
│ Cancel     ADD RECORD    Save │   ← Save live from step 1
│ ▬▬▬▬ ▭▭▭▭ ▭▭▭▭ ▭▭▭▭           │   ← 4-segment rail, 3px
│ The record              1 / 4 │
└──────────────────────────────┘
```

`FORM_STEPS` at `templates/index.html:6935` gains one key per entry, leaving
`label` and `sub` — which the desktop spine renders — alone:

```js
const FORM_STEPS = [
  { n:1, label:'Identify',  sub:'what record is this',  phone:'The record'   },
  { n:2, label:'Acquire',   sub:'how you got it',       phone:'The purchase' },
  { n:3, label:'Log',       sub:'what happens to it',   phone:'The log'      },
  { n:4, label:'Tracklist', sub:'what is on it',        phone:'The object'   },
];
```

The phone names are the section headers the form already uses inside the steps
("The record", "The purchase"), so the rail label and the content agree. The
desktop spine's verbs are unchanged.

Rail segment states, reusing the spine's existing semantics: `done` is
`#5FBF7A`, `now` is `var(--accent)`, ahead is `#2a2a26`. Segments are **not**
tappable — the spine's jump-to-step is a cursor affordance; a 3px strip is not
a touch target. Back and the rail label carry navigation instead.

The draft flag moves out of the footer and onto the rail line, right-aligned
under `n / 4`, where it stays legible without competing with the thumb.

### 3.5 The footer

Today: four equal buttons — cancel, back, next, save. Cancel duplicates the
nav bar's Cancel and Save duplicates the nav bar's Save, which leaves the two
that matter sharing half the width.

```
step 1        [        Next  →        ]
steps 2–3     [←] [    Next  →        ]
step 4        [←] [  ✓ Save record    ]
```

`#formSaveBtn` keeps its id and its `onclick`; on the phone it is **moved** into
the nav bar rather than duplicated, so `syncSaveLabel()` and the wishlist label
logic at `templates/index.html:5915` keep addressing one element.

The footer's primary on step 4 is `#formNextBtn` relabelled, calling
`submitForm` instead of advancing. That is not a second Save competing with the
nav bar's: today `formNextBtn.disabled = formStep === FORM_STEPS.length` leaves
a dead button occupying the footer's main slot on the last step. The footer's
job through steps 1–3 is traversal, and on step 4 there is nowhere left to go —
so the traversal button becomes the wizard's terminal action rather than greying
out. The nav bar's Save remains the one that is live from step 1.

> The queue's "save & next" label is longer than "save". In the nav bar it is
> allowed to wrap to two lines at 11px rather than truncate — a queue of ten
> records is exactly when you need to know which button ends this one.

`#queueStrip` stays where it is, directly under the rail.

### 3.6 The grabber

The handle is functional: dragging down anywhere on the nav bar or the grabber
dismisses the sheet, routed through `closeForm()` so the discard confirmation
still fires on a dirty form.

The listener is bound to the nav area only, never to `.modal-body`, so it can
never fight the body's scroll. Threshold is 80px or a downward velocity over
0.5px/ms; below that the sheet springs back. `Cancel` stays for anyone who
reaches for it, and the whole gesture is skipped under
`prefers-reduced-motion`.

---

## 4. Adding a record

### 4.1 Step 1 — the lookup

Step 1 currently opens on `.form-layout`: the cover well, the picker row, the
sensitive-cover checkbox, the re-pick button, the three `.scan-actions` buttons,
then the artist/album fields. On a phone that is a full screen of controls before
the first field.

It opens instead on the three routes that actually start an add:

```
How do you want to find it?
Whatever you pick fills the fields below. Nothing costs
a credit until you tap Analyse.

┌───────────────────────────────────┐
│ 📷  Shoot the sleeve            › │  66px, accent border
│     Camera, then Analyse          │
├───────────────────────────────────┤
│ 🔍  Search by name              › │
│     Artist or album title         │
├───────────────────────────────────┤
│ ♫   Paste a Spotify link        › │
│     From the share sheet          │
└───────────────────────────────────┘
─────────────── or ───────────────
      ✎  Fill it in myself
```

Each row calls the function the corresponding button calls today, unchanged:
`openCamera()` (`:7194`), `openSearchOverlay()` (`:7926`),
`openSpotifyOverlay()` (`:7133`). *Fill it in myself* sets a
`lookupDismissed` flag and reveals the fields. `Choose file` is not promoted to
a row — on a phone the camera is the file picker's interesting half, and
`pickCoverFile()` stays reachable from the cover thumb once one exists.

The **Analyse** button does not appear here. It is dead until there is something
to analyse, which today is expressed by a disabled button taking up a third of a
row. On the phone it appears inside the identity strip the moment a cover lands,
and nowhere before.

### 4.2 Step 1 — after a match

The lookup rows are replaced by the identity strip:

```
┌──────┬────────────────────────────┐
│      │ Tim Maia                   │
│ 84px │ Racional Vol. 1            │
│cover │ 1975 · BRAZIL · SOUL       │
│      │ [ Pick a different match ] │
└──────┴────────────────────────────┘
ARTIST    [🎤 Tim Maia            ]
ALBUM     [💿 Racional Vol. 1     ]
YEAR [1975]      GENRE [Soul     ]
COUNTRY   [🌍 Brazil             ]
SPOTIFY   [♫ open.spotify.com/…  ]
```

The strip is a presentation of `#coverPreview`, `#fArtist`, `#fAlbum`, `#fYear`,
`#fCountry` and `#fGenre` — it holds no state of its own and re-reads those
fields on every `formChanged()`, so typing in a field updates the strip and the
draft/scan paths need no knowledge of it.

`Pick a different match` is the existing `#scanRepickBtn` →
`reopenScanOverlay()`, moved. It shows on the same condition as today (scan
candidates exist). When the cover came from a file or camera with no scan yet,
the strip shows **Analyse** in its place.

`#fCensored` (mark cover as sensitive) keeps its checkbox row but renders only
once a cover exists, inside the identity strip. It is meaningless without a
cover and costs a full row in exactly the state where space is tightest. The
element is not moved in the DOM on desktop.

Fields are 50px tall at 16px. Only Year/Genre share a row; Artist, Album,
Country and Spotify are full width. `#fMultiArtist` and the `#fArtistsBlock`
editor keep their current behaviour and sit below Spotify.

### 4.3 Step 2 — the purchase

The one substantive change is *Bought at*. `populateWhereList()`
(`templates/index.html:5922`) fills a `<datalist>`, which Safari renders as a
thin strip underneath the keyboard — unusable one-handed.

```
BOUGHT AT
[📍 Tracks, São Paulo                ]
(Tracks) (Baratos Afins) (Discoteca) (Mercado Livre)
```

The chips are the four most frequent `bought_where` values across `records`,
ranked by count rather than the alphabetical order the datalist uses, with the
record's current value pinned first and shown active if it is not already in the
top four. Tapping a chip writes `#fWhere.value` and fires `formChanged()`. The
input still accepts anything typed, and the `<datalist>` stays in the markup for
desktop.

> When the places feature's `Place` table is populated, the chips should rank by
> place usage from `loadPlaces()` (`:3798`) instead of by scanning `records`.
> Deriving from `records` is what `populateWhereList` does today and keeps this
> change independent of that one.

Status and Condition become full-width 52px segmented controls. The wishlist
behaviour is unchanged: `setHaveIt(false)` still marks the purchase section
`sec-off` and `inert`, and still relabels save to *add to wishlist*.

### 4.4 Step 3 — the log

Ratings stay visible — they are two rows and they are the thing most likely to
be set at add time. The segment buttons go from 14px to 22px tall, which is the
difference between hitting a 6 and a 7 with a thumb; the row keeps its 10
segments and its per-person colour.

Plays, cleanings and notes collapse to one 56px row each:

```
▶  Played on              none  [+]
✨ Cleaned on             none  [+]
📝 Notes                     1  [+]
```

`[+]` expands that one section inline — it does not navigate. Expanded, the
section is what it is today (`#fPlayDatesList` + `addPlayDate()`, and so on);
collapsed, it renders a count. A section with entries already in it — which is
every edit of a played record — **opens expanded**, so the collapse only ever
hides what is empty.

This is the largest single scroll reduction in the change: today all three are
open `.form-section` cards with headers, date rows and add buttons, on a step
whose own lead text says it is almost always empty.

### 4.5 Step 4 — the object

`#fSizePick` and `#fDiscPick` come out of the 2-up `.form-grid` and become
full-width segmented controls — `.seg-pick` (`:2276`) already renders as a flex
row of equal buttons, so this is a width and a height, not a rewrite.

Paint moves from a 26px swatch + 76px hex side by side to one row per colour:
a 24px well, the label, and the hex right-aligned in `--font-mono`. The 34px
preview disc grows to 44px.

The tracklist sides collapse the same way as §4.4, one row per side with its
track count, expanding in place.

---

## 5. Editing a record

`openEdit(id)` (`templates/index.html:6847`) currently ends the same way
`openAdd()` does — `setFormStep(1)` and show the overlay. On a phone it opens a
root screen instead.

```
 Done            EDIT            Save
┌──────┬───────────────────────────┐
│ 66px │ Tim Maia                  │
│cover │ Racional Vol. 1           │
│      │ 1975 · 12″ · SOUL         │
└──────┴───────────────────────────┘
┌────────────────────────────────┬──┐
│ 💿 The record                  │ ›│
│    Tim Maia · 1975 · Brazil    │  │
│ 🛍 The purchase                │ ›│
│    Tracks, São Paulo · 12 Sep… │  │
│ ⭐ The log                     │ ›│
│    Pepe 5 · Jenni 7 · 3 plays  │  │
│ 📀 The object                  │ ›│
│    1 disc · 11 tracks          │  │
└────────────────────────────────┴──┘
ONE TAP
[ ▶ Log a play ][ ✨ Log a clean ][ 📝 Add a note ]

           🗑 Delete record
```

### 5.1 The section rows

Four rows, one per existing step, in the same order. Each previews what it
holds, read from the same fields the step edits, so you can see whether the
thing you came to change is already right without opening anything.

| Row | Preview, built from |
|---|---|
| The record | `#fArtist` · `#fYear` · country label |
| The purchase | `#fWhere` · `#fDate` · condition — or **Wishlist** when `#fHaveIt` is off |
| The log | `Pepe n · Jenni n · n plays · n notes`, omitting the zero parts; **"nothing logged"** when all are zero |
| The object | size · disc count · track count · paint, when paint is not the default |

`refreshEditRootPreviews()` rebuilds all four preview lines from the current
field values. It is called on `formChanged()` and after every quick action, so
a row can never describe a record that has already moved on.

A module-level `formEditRoot` flag tracks whether the root screen is showing;
`openEdit` sets it `true` on a phone and `false` everywhere else, and it is the
only thing §3.4's `rebuildFormChrome()` needs to know to render the root
chrome instead of the rail.

Tapping a row is `setFormStep(n)` with `formEditRoot = false`. The step renders
exactly as it does in the add flow, with one difference: the nav bar's left
button is `‹ Edit` (back to the root) instead of `Cancel`, and the footer is
`Cancel` + `Save` rather than Back/Next. There is no next-step traversal from a
section — you came for one thing.

`Done` closes via `closeForm()`, which keeps the dirty-form confirmation.

### 5.2 Quick actions

Three buttons that write today's date straight in:

```js
/* The common case by a wide margin, and today it costs six taps: edit, step 3,
 * scroll, add play date, pick today in the native picker, save. Writing the
 * date and saving immediately makes it one — and the toast's Undo is what
 * makes that safe, since a mis-tap here is otherwise silent and permanent.
 *
 * Routed through addPlayDate/addCleanedDate rather than pushing onto the
 * arrays directly: addPlayDate also calls bumpPlayCount(1) and re-renders, and
 * a quick action that skipped the count bump would silently disagree with the
 * card's own + button. */
async function quickLog(kind){                       // 'play' | 'clean'
  const list = kind === 'play' ? formPlayDates : formCleanedDates;
  const before = [...list];
  (kind === 'play' ? addPlayDate : addCleanedDate)();
  if (!await saveQuiet()) { restoreDates(kind, before); return; }
  toastUndo(kind === 'play' ? 'Play logged' : 'Cleaning logged', async () => {
    restoreDates(kind, before);
    if (await saveQuiet()) toast('Undone');
  });
}

/* Whole-array restore, not a splice by index: addPlayDate appends a nowStamp()
 * and bumpPlayCount moves a separate field, so putting both back from the
 * snapshot is the only version that cannot drift. */
function restoreDates(kind, before){
  if (kind === 'play') { formPlayDates = before; setPlayCount(before.length); renderPlayDatesForm(); }
  else                 { formCleanedDates = before; renderCleanedDatesForm(); }
  refreshEditRootPreviews();
}
```

`saveQuiet()` is `submitForm()`'s network half — `PUT /api/records/<id>`, splice
the response into `records`, `render()` — returning `true` on success and, on
failure, toasting the error and returning `false` without touching form state.
Restoring is the caller's job, because only the caller knows what to restore.
`submitForm` is refactored to call it, so there is one save path rather than two
that can drift.

`setPlayCount(n)` is a small addition beside the existing `bumpPlayCount(d)` —
an absolute set, which is what restoring a snapshot needs.

The form stays open on the root screen and the affected section row's preview
updates in place, which is the confirmation the toast is only reinforcing.

*Add a note* is different: a note has a body, so it cannot be written blind. It
expands the note composer on the root screen — the `#fNoteText` /
`#fNoteDate` / `#fNotePrivate` group from step 3, moved, not copied — with the
date pre-set to today. `Add` runs the existing `addNote()` and then
`saveQuiet()`.

### 5.3 `toastUndo`

`toast()` (`:9167`) is a 2500ms text-only banner. Undo needs a button and longer:

```js
/* 2500ms is right for "changes saved" and much too short to notice, read and
 * act on an undo. 6s is the shortest window that survives looking away. */
function toastUndo(msg, onUndo){
  const el = document.getElementById('toast');
  el.innerHTML = `<span></span><button type="button" class="toast-undo">Undo</button>`;
  el.querySelector('span').textContent = msg;
  el.querySelector('.toast-undo').onclick = () => { hideToast(); onUndo(); };
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, 6000);
}
```

`hideToast()` is extracted from the timeout body `toast()` already has
(`el.classList.remove('show')`), so both toasts and the Undo button share one
dismissal. `toast()` is adjusted to clear `innerHTML` before writing its text,
so a plain toast after an undo toast does not inherit the button. On the phone
the toast sits above the safe-area inset, not at `bottom:0`.

### 5.4 Delete

`🗑 Delete record` sits at the bottom of the root screen, outside the section
list, in `--danger` on a transparent ground rather than as a filled red button —
it should be findable, not inviting. It routes to the existing delete path with
its existing confirmation.

---

## 6. What the desktop sees

Nothing. Every change in §3–§5 is inside `@media(max-width:760px)` or behind
`isPhone()`. The specific desktop guarantees:

- `#formSpine` renders the same four `.fstep` buttons with the same labels,
  captions, `on`/`done` states and jump-to-step behaviour
- `.modal-head` keeps its title + `×`; `.modal-foot` keeps cancel/back/next/save
- Step 1 opens on the cover well and the fields, with no lookup rows
- `openEdit` goes straight to step 1 — no root screen
- The `<datalist>` for *Bought at* is unchanged; the chips are phone-only
- Plays, cleanings, notes and tracklist sides render expanded

Field ids, `formValues()`, `applyDraft()`, `formBaseline`, the scan writers and
the queue are untouched, so `tests/test_draft.js`, `tests/test_queue.js`,
`tests/test_cover_form.js` and the scan tests should pass without edits. Any
that break are telling us something and get read, not amended.

---

## 7. Testing

### 7.1 New JS tests

The suite splits along the line the repo already draws. `test_carousel.js` and
`test_grouping.js` are **pure-function** tests over a `static/*.js` module with
no DOM at all; only `test_boot.js` uses jsdom, and jsdom is not a dependency —
`test_boot.py` installs it into a scratch directory and skips when it cannot.

So the decidable logic is extracted rather than tested through the DOM:

- **`static/phoneform.js`** — a `VinylPhoneForm` module holding the rules: rail
  segment states, which log sections start collapsed, place-chip ranking, the
  four edit-root preview strings, and the drag-dismiss threshold. Dual-exported
  the way `static/draft.js` is. Tested by `tests/test_phoneform.js` under
  `node --test`, run from `tests/test_phoneform.py` so `pytest` stays the one
  command.
- **`tests/test_boot.js`** — gains a phone-mode boot that proves the wiring:
  the chrome renders, the rows call the right functions, the quick actions
  issue the right `PUT`.

The boot harness needs two fixes to host this, both of them harness gaps rather
than application bugs:

| Gap | Today | Needed |
|---|---|---|
| `matchMedia` | stubbed as `{matches:false, addListener, removeListener}` | must answer `addEventListener` too, and let a test set `matches: true` — `isPhone()` is built on it |
| `fetch` PUT | returns `{ok:true}` | `saveQuiet` splices the response into `records`, so a PUT must return a record for the quick-action tests to mean anything |

`visualViewport` stays unstubbed — jsdom does not implement it, and
`syncViewportHeight` already returns early without it, which is the desktop
path and is worth having covered.

| Test | Asserts |
|---|---|
| lookup rows render on step 1 when phone and empty | three rows, wired to `openCamera` / `openSearchOverlay` / `openSpotifyOverlay` |
| lookup rows hidden once artist+album filled | identity strip present, rows gone |
| `Fill it in myself` reveals fields | rows gone, `#fArtist` visible, no match required |
| identity strip re-reads fields | typing into `#fArtist` updates the strip text |
| rail renders 4 segments with correct states | step 3 → two `done`, one `now`, one ahead |
| rail segments are not buttons | no click handler, not focusable |
| save button is one element | `#formSaveBtn` appears exactly once in the DOM in both modes |
| collapsed log rows show counts | 0 plays → "none"; 3 plays → "3" |
| a section with entries opens expanded | `formPlayDates` non-empty → play section not collapsed |
| place chips rank by frequency | most-used first; current value pinned and active |
| chip tap writes the field | `#fWhere.value` set, `formChanged` fired |
| edit root lists four sections with previews | preview strings match the field values |
| wishlist record's purchase preview | reads "Wishlist", not a date |
| tapping a section goes to that step | `formStep` set, nav left button is `‹ Edit` |
| `quickLog('play')` appends today and saves | one `PUT`, `play_dates` contains today |
| `quickLog('play')` bumps the play count | `plays` is one higher, matching the card's `+` button |
| undo restores the prior array and re-saves | two `PUT`s, final `play_dates` **and** `plays` equal the originals |
| a failed quick save restores state | `formPlayDates` and `plays` unchanged, error toast shown |
| an edit-root preview follows a quick action | the log row's text gains the new play without a reopen |
| desktop renders the spine, not the rail | `.fstep` × 4, no rail |

### 7.2 Python side — `tests/test_icons.py`

| Test | Asserts |
|---|---|
| `/static/icon-180.png` serves 200, `image/png`, 180×180 | |
| `/static/manifest.json` serves 200 and parses | `display` is `standalone`, both icon paths resolve 200 |
| the page head declares the icon and manifest | `apple-touch-icon`, `manifest`, `apple-mobile-web-app-title` = `Vinyl` |
| the viewport meta carries `viewport-fit=cover` | guards the safe-area work from a silent revert |

### 7.3 Manual verification

`docs/phone-form-manual-verification.md`, following the pattern of the existing
manual docs, covering what a headless DOM cannot: the keyboard actually staying
clear of the action bar, the drag-to-dismiss threshold, the safe-area insets in
standalone mode on a notched device, and the home-screen icon after a remove
and re-add.

---

## 8. Build order

Each step leaves the app working and is independently verifiable.

1. **Icon and standalone meta** (§2). Self-contained, no JS, immediately
   visible. `tests/test_icons.py`.
2. **Safe areas and the keyboard** (§3.1–3.2). The biggest felt improvement for
   the least structural change, and independent of everything below.
3. **`isPhone()` and `rebuildFormChrome()`** (§3.3–3.5) — nav bar, rail, footer.
   The first change that touches `setFormStep`; desktop parity is the thing to
   watch.
4. **Step 1's lookup rows and identity strip** (§4.1–4.2).
5. **Steps 2–4** (§4.3–4.5) — chips, collapsed log rows, segmented pickers.
6. **`saveQuiet()` refactor and `toastUndo`** (§5.3) — no UI yet, so
   `submitForm`'s existing tests are the check.
7. **The edit root screen and quick actions** (§5.1–5.2).
8. **The grabber** (§3.6). Last because it is the only piece that can fight
   scrolling, and the only one worth dropping if it does not feel right.
