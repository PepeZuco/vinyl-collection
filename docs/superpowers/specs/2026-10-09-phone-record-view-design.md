# Phone record view redesign — design

Date: 2026-10-09
Scope: the phone (`max-width:760px`) layout of the opened record (`#dmLayout` in `templates/index.html`). The desktop drawer (`.detail-layout`, `#ddInfo`) is unchanged.

## Intent

Remake how a record is explored once opened on a phone. Today it is one long scrolling sheet (cover carousel, crate strip, header, Info/Tracks/Timeline stacked). The gyroscope tilt only exists in a separate full-screen cover view reached by tapping the cover. The new view is a fixed screen built around a cover that tilts by default, with previous/next records at the bottom, the essentials in between, and everything else in a sheet that rises on demand.

## Decisions (agreed)

- Previous/next: two peeking covers at the bottom (previous left, next right), each with a short title. Tap goes there.
- Expand: a bottom sheet that rises over the cover; prev/next stay visible.
- Default: gyroscope tilt is on as soon as the record opens.
- Admin: same screen plus a small, discreet fixed edit button, bottom right.

## Screen, default state (visitor and admin)

Fixed viewport, the page itself does not scroll.

1. **Top bar**: close button, "n / total" count (existing `dm-top`, `dm-count`).
2. **Cover**: square, tilting. Horizontal swipe on the cover goes to the previous/next record (existing slide animation). Tapping the cover still opens the existing full-screen zoom (`openCoverView`).
3. **Details (middle)**: album name + year, artist (multi-artist badge/expand kept), Pepe and Jenni rating bars + total. Below, the tracklist, scrolling inside its own area. A grab handle sits at the top of this area.
4. **Bottom row**: previous cover (left), next cover (right), with short titles. An end of the list leaves its slot empty unless the shelf/random order wraps.

## Expanded state

- Tapping the handle or dragging the details up raises a sheet over most of the cover; the bottom prev/next row stays.
- Sheet content, scrolling inside it: Tracks, then Info (chips, 6-cell grid, Spotify row, Played/Cleaned buttons when `authed && have_it`), then Timeline.
- Tapping the handle or dragging down collapses it. Changing record collapses it.

## Gyroscope by default

- Tilt starts when the record opens and reuses `VinylCoverTilt` (`static/covertilt.js`): `screenTilt`, `tiltFrom`, `smooth`, `requestMotion`. A `new` record keeps the shrink-wrap glare.
- iOS needs motion permission inside a user gesture. It is requested in the tap that opens the record from the grid. Denied or no sensor: the cover stays flat.
- Reduced motion: no tilt.
- The `deviceorientation` listener is removed on close and on leaving the view. The baseline resets on each record change and on orientation change (as `coverOnOrient` does today).
- The existing full-screen cover view keeps its own tilt; the two never run at once.

## Admin mode

- Identical screen plus a small, low-contrast round edit button fixed at the bottom right, above the safe-area inset. The "next" slot shifts to clear it.
- Tap-to-rate bars and like/play/clean actions are unchanged.
- Delete moves into the edit form (bottom of the form), so the record screen stays clean. The current `dm-foot` (delete + edit) goes away on the phone. (To confirm at review: delete placement.)

## Structure

- Reuse: `dmHeaderHTML`, `dmInfoTabHTML`, `dmTracksTabHTML`, `dmTimelineTabHTML`, `detailNavRecords`, rating/like/history handlers, `censorWrap`, the vertical record-slide animation.
- New: `static/phonedetail.js` holds the pure, testable logic (sheet state machine, prev/next selection at list ends/shelf order). Template holds markup, CSS and the glue.
- Retire on the phone: crate strip (`dm-crate*`), carousel peek (`dm-carousel`), tab-row scroll spy, `dmMeasureChrome` / `--dm-sec-min` — only where nothing else (desktop) depends on them. The desktop's `DETAIL_PANES.dd` path stays.

## Testing

- `tests/test_phonedetail.js` (+ pytest wrapper like the existing pairs): sheet toggle, prev/next at ends and in shelf order, edit button only when `authed`, tilt listener removed on close.
- DOM test in the style of `tests/test_phone_dom.js`.
- Phone-size screenshot via the existing no-root chromium setup; restart Flask after template edits.
- Do not rely on `test_boot` (known to hang); run targeted tests.

## Out of scope

Desktop drawer, add/edit form redesign (other than hosting delete), changes to the full-screen cover view.
