# The phone add/edit form — what to check by hand

The redraw touched the home-screen icon, the safe areas, the keyboard, the
whole step 1 lookup flow, the phone chrome (nav bar, progress rail, footer),
place chips and collapsed log sections, a quiet-save Undo toast, an edit root
screen with one-tap actions, and drag-to-dismiss. `static/phoneform.js`'s pure
rules are covered by its own `node --test` suite, and `tests/test_phone_dom.js`
drives the rendered page through jsdom for everything wiring-shaped: which
element got which class, which function got called, what a re-render produced.

None of that is what this document is for. **jsdom evaluates no CSS and
computes no layout.** It cannot tell you whether an element that is
`display:flex` in the stylesheet is actually on screen, whether one element
sits behind another, whether a control is reachable under a real thumb, or
whether the page looks right in either theme. This plan shipped six real bugs
into a fully green suite for exactly that reason — a phone-scoped CSS fix that
broke desktop, three separate instances of `el.hidden = true` doing nothing
because an author `display:` declaration was already sitting on the element
outranking the browser's own `[hidden]{display:none}` rule, and a toast button
that would have been inert under a real finger because its container is
`pointer-events:none`. `tests/test_step1_hidden_guards.py` now checks, by
reading the served CSS as text, that the guard rules those bugs needed are
still present — but by its own docstring it "cannot evaluate the cascade
either," which is the whole reason this document exists. Everything below can
only be confirmed by a person holding a phone, or a person resizing a real
browser window and looking at the result.

Work through this once on a real iPhone with the page added to the home
screen, and once on a desktop browser. Tick what passes; anything that fails,
say what you actually saw.

---

## 1. The home-screen icon

Without an `apple-touch-icon`, iOS invents a tile from the page — in practice
the first letter of the title, a "Z" from "Zucoloto's". `templates/index.html`
now links `/static/icon-180.png`, and the manifest lists 192 and 512px PNGs
for Android/other install paths.

**Fresh install.** On a phone that has never added this app before: Safari →
Share → Add to Home Screen. Expected: the tile is the purple/gold record, not
a letter. Launching from it opens in standalone mode (no Safari chrome).

**Upgrade path — the one that actually matters here.** iOS caches the tile
**at install time**, not on every launch. If your phone already has a
shortcut from before this change, it keeps showing the old "Z" tile
indefinitely, even after the deploy — reopening the same shortcut will not
refresh the icon.

1. Remove the existing shortcut from the home screen.
2. Add it again from Safari.
3. The new tile should be the record icon. Reloading the page in Safari first
   makes no difference; only the remove-and-re-add does.

This is worth stating plainly to anyone who reports "the icon still looks
wrong" after the deploy — it is expected, and the fix is on their phone, not
the server.

---

## 2. Safe areas in standalone mode

The viewport opts into `viewport-fit=cover` and the status bar style is
`black-translucent`, which paints the page under the status bar and the home
indicator. Every piece of fixed or sticky chrome is therefore responsible for
buying its own clearance back with `env(safe-area-inset-*)`.

**This scenario has already caught three real bugs, all of which shipped.**
The metas went in with only the add/edit form's insets; the header, the record
sheet's top bar and the bottom tab bar had none. The tab bar was the worst:
it carried `height:58px` *and* `padding-bottom:env(safe-area-inset-bottom)`,
and because `box-sizing:border-box` is global in this template the inset was
spent **out of** the 58px rather than added to it — leaving roughly 24px of
usable bar. No automated test in this project can see any of it.

Launch the app from the home screen (not in a Safari tab) on a notched device:

1. **The header clears the clock.** "ZUCOLOTO'S VINYL COLLECTION" and the
   record count sit fully below the status bar — the time, signal and battery
   do not overlap the title or the vinyl logo. There is no white strip at the
   very top either.
2. **The bottom tab bar is full height.** COLLECTION / TIMELINE / STATS / MORE
   each show their icon *and* their label, comfortably, with the row sitting
   above the home indicator rather than crushed against it. Compare against a
   desktop browser narrowed below 760px, where there is no inset: the bar
   should look the same height in terms of *content*, just with extra
   clearance underneath on the phone.
3. **You can close a record.** Tap any record to open its sheet. The round
   **×** at the top-left is fully visible and tappable — not behind the clock.
   Tap it; the sheet closes. This is the one that made the app unusable: with
   the close button under the status bar there was no way to dismiss a record
   at all.
4. Open the add/edit form and scroll to the footer (Back / Next / Save, or the
   log-a-play row on the edit root). The buttons sit clear of the home
   indicator — nothing is obscured or needs a fingertip right at the very
   bottom edge of the glass.
5. Repeat step 4 with the record detail drawer's own footer, for the same
   reason.
6. Rotate to landscape and re-check 1-3. The left/right insets change on a
   notched device even though the top one shrinks.

`tests/test_safe_areas.py` statically checks that the three rules behind
steps 1-3 still exist in the served CSS. It cannot evaluate the cascade or lay
anything out — it only fails when a future edit drops one of them, rather than
letting the regression reach a phone silently.

---

## 3. The keyboard clearing the action bar

iOS does not shrink the layout viewport when the keyboard opens — a footer
pinned to the bottom of a 100%-tall box ends up **behind** the keyboard, with
Back/Next/Save simply gone until the field is dismissed. The fix reads
`window.visualViewport`'s height into a `--vvh` custom property and sizes the
sheet against that instead of `100%`; a `focusin` listener also scrolls the
focused field toward the middle of what is actually visible, timed to wait
out the keyboard's own animation.

1. Open **Add**, get to step 2, and tap **Bought at**.
2. Expected: the keyboard opens, the field scrolls up to roughly the middle
   of the space still visible above the keyboard, and the footer's Save
   button stays visible above the keyboard the whole time — never behind it.
3. Dismiss the keyboard (tap Done, or tap elsewhere). The footer returns to
   the true bottom of the screen without a visible jump or a moment where
   the layout looks wrong.

## 4. The same, in landscape

Repeat scenario 3 rotated to landscape. The visible height above the keyboard
is much shorter here, so this is where a fixed-height assumption would show
up first. Expected: the same — Save still visible, the field still scrolled
into the remaining space, no jump on dismiss.

---

## 5. Step 1's three states are mutually exclusive

This is the scenario that guards against the worst of the six bugs. Step 1
on a phone has exactly three states, switched by setting the `hidden` IDL
property on four elements (`renderStep1Phone` in `templates/index.html`):

- **Lookup rows** — "How do you want to find it?" with camera / search /
  Spotify-link options — shown before anything has identified the record.
- **Identity strip** — a compact cover-plus-metadata row — shown once
  something has (a scan, a search pick, or a pasted link).
- **Plain fields** — the ordinary artist/album/year form layout — shown if
  you dismiss the lookup without identifying anything (e.g. by typing
  directly).

All three carry their own `display:` declaration in the phone stylesheet, so
`el.hidden = true` needs an author-origin `[hidden]{display:none}` override
to actually hide anything — the browser's own `[hidden]` rule is user-agent
origin and loses to any author `display:` unconditionally. This exact defect
shipped and passed **24 of 24** jsdom tests, because jsdom never evaluates the
rule that was missing.

1. Open **Add**. Expected: only the lookup rows are visible — no cover well,
   no artist/album fields, no identity strip, all at once underneath it.
2. Identify a record any way (camera, search, or a Spotify link). Expected:
   the lookup rows disappear and **only** the identity strip shows — a small
   cover thumbnail, artist, album, and a *Pick a different match* /
   *Analyse* action. The full field layout must not also be visible below it.
3. Tap into the identity strip's fields (or navigate to see the underlying
   form) and confirm there is exactly one visible presentation of step 1 at
   any moment — never two stacked, never zero.

`tests/test_step1_hidden_guards.py` confirms the guard *rules* exist in the
served CSS as text. It cannot confirm the browser actually applies them the
way this section does.

## 6. The lookup routes themselves

1. Add a record **by camera** — shoot the sleeve, let it analyse. Expected:
   fields fill and the view switches to the identity strip.
2. Add a record **by search** (name lookup). Same expectation.
3. Add a record **by pasting a Spotify link**. Same expectation.
4. From the identity strip, tap **Pick a different match**. Expected: the
   previous scan's candidate list reopens — this must not trigger a new scan
   or a new credit charge. (If nothing was scanned yet, the action reads
   **Analyse** instead, and that one legitimately does cost a credit.)

---

## 7. Drag to dismiss

Bound only to the sheet's grabber and its head, never the scrollable body, so
it can never fight a scroll.

1. Drag the head down **~20px** and release. Expected: it springs back to
   place. (If you script this instead of dragging by hand, note that a
   synthetic drag fired in one tick can race the gesture's own velocity
   check — a real drag, which spans tens of milliseconds, will not.)
2. Drag down **~140px** (past the 80px distance threshold) and release.
   Expected: the sheet dismisses.
3. Drag a short distance but **fast** — a flick. Expected: the sheet
   dismisses even though the distance alone would have sprung back, because
   the gesture also arms on velocity.
4. With text typed into the form, repeat a dismissing drag. Expected: the
   ordinary discard confirmation appears — a drag dismissal goes through the
   same `closeForm()` a tap on × does, so a dirty form still asks before
   anything is lost.
5. Start a drag **on the Save button** itself (which lives in the head on a
   phone). Expected: Save still saves normally — the drag must not steal the
   tap and turn it into a sheet-move. (Guards against a real conflict: Task 4
   moved Save into the head, and Task 9 bound drag listeners to the head.)
6. On step 3 with several notes so the section scrolls, scroll the body up
   and down quickly, including flicking near the top. Expected: **the sheet
   never moves.** The drag handles are only the grabber and the head, so this
   should hold by construction — confirm it does.
7. On the edit root screen (existing record, not the 4-step wizard), drag
   down to dismiss. Expected: it closes the whole sheet, the same as ×  would
   — not a "back to previous screen" — even though the head's own button here
   reads "‹ edit" rather than "×". One gesture, one meaning, matching how an
   iOS sheet behaves regardless of what its own back button says.

---

## 8. Quick actions and Undo

On the edit root screen for a record that currently has **no logged plays**:

1. Tap **Log a play**. Expected: the play-log preview row updates in place
   (no navigation, no full-form save flow) and a toast appears reading
   something like "Play logged" with an **Undo** button.
2. Time the toast. It should stay up for **about six seconds** — long enough
   to look away and back, not the ~2.5s of an ordinary confirmation toast.
3. **Before** tapping Undo, back out to the grid behind the form (or peek at
   it) and confirm the card there already reflects the new play — this
   writes through a real save (`saveQuiet()`), not a local-only UI update.
4. Tap **Undo**. Expected: both the play **list** and the play **count**
   revert — check the record's play count specifically, not just that the
   list entry disappeared, since the two are separate fields that have to be
   restored together.
5. Confirm the card in the grid behind the form also reverts, since Undo
   saves again on the way back.
6. **Tap the Undo button itself and confirm it actually responds.** The
   toast's own container (`.toast`) is `pointer-events:none` so the message
   never blocks clicks on whatever is behind it while it's fading in or out —
   the Undo button inside it carries its own `pointer-events:auto` to opt
   back in. If that declaration were ever missing, every jsdom test would
   still pass (a programmatic `.click()` doesn't care about CSS
   pointer-events), while a real finger would find nothing there. This is
   the fourth of the plan's cascade-blind-spot bugs and the one with no
   automated guard of any kind — it can only be caught here.
7. Repeat with **Log a clean**.

---

## 9. The progress rail absent on the edit root

The four-segment rail and its "N / 4" label belong to the step wizard. The
edit root is a section list with no steps to progress through, so the rail
must not appear there.

1. Open an **existing** record for editing on a phone. Expected: the edit
   root screen (section rows, quick actions, delete) shows with **no**
   progress rail above it.
2. From there, tap into any section (e.g. the identify section) to enter the
   step wizard. Expected: the rail **does** appear now, showing the right
   step highlighted.
3. Tap "‹ edit" to go back to the root. Expected: the rail disappears again.

This guards a bug where `rail.hidden = !phone || root` made the phone-scoped
`.form-rail{display:flex}` newly reachable while `hidden` was still true —
same author-vs-UA trap as scenario 5, on a different element, caught only in
review rather than by a test.

---

## 10. The desktop header's × stays on the right

The phone's nav bar adds a third child to `.modal-head` (a save-button slot,
empty on desktop). The very first fix for this leaked: a compensating CSS
rule was written phone-scoped only, so on **desktop** the base
`justify-content:space-between` rule spread all three items across the row
and moved the × to the wrong side, off-center from the title.

1. On a **desktop** browser, open **Add** (or **Edit** on an existing
   record).
2. Look at the modal head. Expected: the title is between two elements —
   Cancel-or-back on the left, the **×** close button on the **right** — the
   same layout the form always had. Nothing should look pushed, off-center,
   or have a visible gap where a third item's slot is silently taking up
   space.

There is **no automated check for this at all** — jsdom cannot evaluate
`justify-content`, and no test asserts DOM child order here either. This is
the one scenario in this whole document with zero safety net besides a
person looking at the screen.

---

## 11. Resizing a desktop browser across 760px with the form open

The phone/desktop chrome swap is driven by a `matchMedia('(max-width:760px)')`
listener that calls `rebuildFormChrome()` on every breakpoint crossing — this
covers an iPad rotating, or a desktop window being resized.

1. Open a desktop browser **above** 760px wide. Open **Edit** on an existing
   record and step into, say, step 2.
2. Shrink the window to **below** 760px while the form is still open.
   Expected: the chrome switches to the phone layout correctly — nav bar,
   rail, phone-styled step 2 — and the step you were on is still showing its
   fields.
3. Now widen the window back **above** 760px while still on that same step.
   Expected: the chrome switches back to the desktop spine and footer, and —
   this is the specific regression this guards — **the step body is
   visible**, not blank. A prior version of the resize handler only ever set
   each step's `hidden` to `true` and never restored it, so a phone→desktop
   resize mid-edit left every step body hidden with nothing on screen to
   scroll to.
4. Repeat starting from the **edit root** screen (not mid-wizard): shrink
   below 760px, confirm the edit root itself renders; widen back above, and
   confirm the desktop spine reappears normally (the edit root only exists
   on phone).

---

## 12. Delete

The delete control lives on the phone edit root, reusing the detail drawer's
own delete request but with its own close path, since the drawer's version
ends in `closeDetail()` — called from the form, that would leave the sheet
open on a record that no longer exists.

1. Open **Edit** on a record you're happy to lose, scroll to **Delete
   record**. Expected: it reads normally, not pre-armed — tapping once does
   **not** delete.
2. Tap it once. Expected: the label changes to something like "Tap again to
   delete" and it visually arms.
3. Wait a few seconds without tapping again (or tap anywhere that isn't the
   delete button). Expected: it disarms back to its normal state on its own
   (roughly 4 seconds) — a stray scroll-then-mis-tap at the bottom of the
   screen should not turn into a delete.
4. Arm it again and tap a second time within the window. Expected: the
   **form** closes (not the record detail drawer underneath it, if one is
   open) and the record is gone from the grid.
5. Open a **different** record's edit screen afterward. Expected: its delete
   button is unarmed — arming never carries over between records.

---

## 13. Both themes

The light theme's accent is a deep brown, `#7A5A00`, deliberately not the
dark theme's gold (`#f1c23f`) — a direct gold-on-cream reading fails contrast,
and the brown holds the same hue at 4.6:1.

1. Switch to **light mode**. Repeat scenarios 6 (lookup routes / identity
   strip) and 8 (quick actions) in light mode.
2. Confirm every new control from this redraw is legible: the lookup rows,
   the identity strip, the place chips, the progress rail's "now" segment,
   the edit root's quick-action icons, the Undo button.
3. Confirm the accent color used throughout is the **brown**, not gold —
   check the rail's active segment and the quick-action icon colors
   specifically, since those are the newest controls most likely to have
   been eyeballed only in dark mode during development.
4. Switch back to dark mode and spot-check the same controls read correctly
   there too.

---

## 14. A full desktop regression pass

Nothing about the phone redraw should have changed desktop behavior, but the
head fix in scenario 10 shows how easily a phone-scoped change can leak. On a
desktop browser, add a record and then edit it, end to end:

1. The **four-step spine** (Identify / Acquire / Log / Tracklist) shows
   across the top, not the phone's rail.
2. The **×** sits in the head, on the right (scenario 10, repeated here as
   part of the full pass).
3. The footer carries **Cancel, Back, Next, Save** in that order — not the
   phone's Save-in-header arrangement.
4. Step 1 shows the **cover well** (the drop/camera area), not the phone's
   lookup rows or identity strip.
5. Step 2's **Bought at** field is a text input with a `<datalist>` —
   alphabetical suggestions — not the phone's ranked place chips.
6. Step 3's play/cleaning/notes sections are **all expanded** by default, not
   collapsed to a single summary row the way they are on a phone.
7. The notes section's header still reads **"markdown"** next to the note
   count — unchanged text, worth a glance because it sits right next to
   controls this plan did touch.
8. Open an **existing** record for edit. Desktop has no edit-root screen —
   confirm it opens straight into the step wizard, at step 1, not a section
   list.

---

## 15. Step 2's *Bought at* — tappable chips, not the datalist strip

Safari renders a `<datalist>` as a thin suggestion strip pinned under the
keyboard — technically usable, but only with two hands. `renderPlaceChips()`
(`templates/index.html`) swaps it on a phone for a row of tappable chips
above the field, ranked by `VinylPhoneForm.rankPlaces()` with whatever is
already on the record pinned first. The datalist itself never leaves the
DOM — desktop still gets it (scenario 14.5) — so this is purely a question of
which one a phone actually *shows*, something jsdom cannot judge for itself.

1. On a phone, open **Add** or **Edit** and get to step 2 (*Acquire*).
   Expected: **Bought at** shows a row of tappable chips above the input —
   not the thin native suggestion strip a `<datalist>` produces underneath
   the keyboard.
2. Tap a chip. Expected: the field fills with that chip's text immediately,
   no keyboard needed, and the chip gets the "on" (accent) styling.
3. Leave the field and look at the chip row again. Expected: the place you
   just picked has moved to the **front** — `pickPlace()` re-ranks on every
   pick, so the most recently used place stays reachable without scrolling.
4. Type a place that has never been used before, directly into the field
   instead of tapping a chip. Expected: no chip lights up for it, and saving
   the record still works normally — a chip is a shortcut, not the only way
   a place gets in.

---

## 16. Step 3's collapsed log sections and the `+`

Plays, cleanings and notes are three cards that are almost always empty —
step 3's own lead text says so — so on a phone each one collapses to a
single row, expanding only if it already has entries or a person taps its
own `+` (`renderLogCollapse()`, `templates/index.html`). This is bug #3 of
the six the redraw originally shipped into a green suite: `.log-plus`
carries its own unconditional `display:flex`, so the `+` needing to hide
once its section is open needed the same author-vs-UA `[hidden]` guard as
step 1's lookup/identity switch (scenario 5) — `tests/test_step1_hidden_guards.py`
confirms that guard rule survives in the served CSS as text, which used to
be the only coverage this had.

A second, later bug lived in the same code: the `+` used to set its
section's collapsed state directly instead of going through
`renderLogCollapse()`, so opening an empty section by hand did not stick —
the next unrelated re-render (adding an entry to a *different* section, or
deleting a note) recomputed every section's collapsed state from emptiness
again and snapped the one you had just opened by hand back shut.

1. On a phone, open **Add** and get to step 3 (*Log*). Expected: **Played
   on**, **Cleaned on** and **Notes** each show as a single collapsed row —
   a header with a count and a `+`, no date list or note list underneath any
   of them.
2. Tap the `+` on **Played on**. Expected: the section expands to its full
   card (date list, add-date control) and its own `+` disappears — nothing
   left for it to do once the section is already open.
3. With **Played on** still open and still empty, log a **cleaning**
   instead (a different section entirely). Expected: **Played on** stays
   open — it must not snap back shut just because some other section's
   re-render happened to run.
4. Now add a play date, then delete it again, leaving **Played on** empty
   once more. Expected: the section **stays open** through both — adding
   and removing an entry must not be what closes a section you opened by
   hand; only leaving step 3 and coming back (or reopening the form) should
   reset it.
5. Repeat with **Notes**, since it drives the desktop label check in
   scenario 19 below — open it by hand while empty, add a note, delete it,
   confirm it never snaps shut on its own.

---

## 17. No zoom on focus, anywhere in the form

iOS Safari zooms the whole page in when a focused input's font-size is under
16px. The form's phone rules size every field input at 16px specifically to
avoid this (see the comment beside `#formOverlay .field input,#formOverlay
.field select{height:50px}` in `templates/index.html`), but nothing has ever
walked every field on a phone and actually confirmed it holds everywhere.

1. On a phone, open **Add**. Working through **every** step (1 through 4),
   tap into every text field, textarea, and the color hex inputs on the
   paint step. Expected: the page never zooms in on focus, on any of them —
   the keyboard opens and the field scrolls into view (scenario 3), but the
   page's own zoom level never changes.
2. Pay particular attention to the multi-artist rows (step 1, with
   **multiple artists** on), the paint step's color hex fields, and any
   field this redraw added or resized specifically — a field quietly
   inheriting a smaller font from somewhere unexpected is the likely failure
   mode, not the fields that were already 16px before this plan.

---

## 18. No stray strip above the progress rail

`.form-spine` — the desktop step spine (Identify / Acquire / Log /
Tracklist) — carries its own unconditional `display:flex` at the top level
of the stylesheet, not scoped to any width. `rebuildFormChrome()` sets
`spine.hidden = phone` on every render, desktop and phone alike, which
without an author-origin `[hidden]` guard does nothing at all: the same
UA-vs-author trap as scenario 5, except global rather than phone-scoped, so
a guard living only inside the phone media query would not have been enough
to fix it either — this is the seventh cascade bug the redraw shipped.

1. On a phone, open **Add**. Expected: nothing shows above the progress
   rail — no bordered, rounded strip, no stray margin above it, just the
   rail itself at the top of the form.
2. Open **Edit** on an existing record and step into the wizard (not the
   edit root). Expected: same — no strip above the rail.
3. On the phone's **edit root** screen itself (existing record, section
   list, scenario 9). Expected: no strip there either — the edit root
   replaces the rail entirely on that screen, so nothing from the spine
   should be visible above it.
4. On a **desktop** browser, open **Add** or **Edit**. Expected: the spine
   is exactly where it always was, at the top of the form — this guard must
   not have hidden it there too.

---

## 19. The notes header reading "markdown" again after a resize

`playDatesCount` and `cleanedDatesCount` "self-heal" crossing back to
desktop because their own renderers set their count text immediately before
every call to `renderLogCollapse()`; `notesCount` has no such renderer, so
`renderLogCollapse()` itself has to know to restore its static desktop label
rather than passing through whatever a phone-width render last wrote there.
Scenario 11 already covers the wizard body surviving this same resize; this
is the one part of step 3 specifically worth a second look.

1. On a desktop browser **below** 760px wide (or a phone), open **Add** and
   get to step 3. Expected: the **Notes** header shows a count like "none"
   or some number of notes, not the word "markdown".
2. Widen the window back **above** 760px (or, on a phone, rotate/resize past
   the breakpoint if your setup allows it). Expected: the **Notes** header
   goes back to reading **"markdown"** — not stuck on whatever count the
   narrower width last showed.

---

## 20. The Undo toast goes properly inert once it fades

Scenario 8 already checks that the Undo button **responds** while the toast
is up. This is the other half: `.toast` only ever animates opacity and
transform, never `display` or `visibility`, so once `hideToast()` removes
the `.show` class the button is still sitting in the DOM, in the same
bottom-right spot, for as long as nothing replaces it — a stray tap there
used to still fire `onUndo()`.

1. Trigger an Undo toast (**Log a play** from the edit root, same as
   scenario 8). Let it fade out completely — either wait the ~6 seconds or
   watch it finish animating — and do **not** tap Undo while it is visible.
2. Once it has fully faded, tap exactly where the Undo button was. Expected:
   **nothing happens** — no play reverts, no toast reappears, no console
   error. Check the record's play count and play list are unchanged from
   after step 1 of scenario 8's own sequence.
3. Repeat immediately after a **plain** toast (a save confirmation, not an
   Undo one) fades in the same spot, to confirm nothing is tappable there
   even when no Undo button was ever shown.

---

## What this document does not cover

Server-side rules (place ranking math, log counts, the pure functions in
`static/phoneform.js`) are exercised by `node --test` and by
`tests/test_phone_dom.js` against jsdom, and are not repeated here. This
document is deliberately only the things a headless DOM cannot see: real
touch, real layout, real timing, and the CSS cascade actually being applied
by a real rendering engine.
