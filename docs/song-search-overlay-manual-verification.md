# Song search overlay — what to check by hand

When the search box is looking at songs, a record whose tracklist matches draws
that tracklist over its cover. The boot suite checks the markup — which rows
are marked, which side headers carry `has-hit`, how many songs the badge counts
— but jsdom has no layout, no paint and no hover, so everything below needs a
real browser.

> The dev database has no tracklists. Give one to a record first: open it, edit,
> and paste a few songs into the Tracks step — or, faster, patch the page's own
> `records` array from the console and call `render()`.

---

## The tracklist sits on the artwork, not instead of it

1. Tick **Song** in the search box's field panel (the funnel next to the box).
2. Type a word that appears in a song title.

The matching records dim their covers and show the whole tracklist, grouped by
side. The artwork must still be **readable through** the scrim — dimmed, not
replaced. A record that matched on its artist or album and has no matching song
keeps its cover untouched: no tracklist, no badge.

Check both themes. The scrim is dark in light mode too, deliberately — the
ground here is a photograph, not the page — and the small type must stay
legible over a pale cover and a dark one.

---

## Hovering gives you the cover back without losing the answer

Hover a card with matches. The artwork comes up to near full brightness and the
tracklist drops to **the matches alone** — each on its own dark pill, under its
side header. A side with nothing matching disappears with its songs: on a
double LP with hits only on side C, `Disc 1 · Side A` and `Disc 1 · Side B`
must be gone while you hover.

Move the mouse off. The full tracklist comes back, **scrolled to the first
match again** — not to the top. (Hovering collapses the list shorter than the
box, so the browser clamps the scroll to zero; a `mouseleave` handler puts it
back. If you ever see the list sitting at side A after a hover, that handler
has stopped firing.)

The genre / condition / plays scrim must NOT appear on these cards — it would
cover the artwork the hover just uncovered.

---

## A long tracklist scrolls inside the cover

Search something matching a song late on a double LP. The overlay opens with
the first match already in view, with **its side header above it** — landing
the match at the very top would hide which side it is on.

Scroll inside the overlay with the wheel. The page behind must not scroll with
it. The side headers stick as you pass them, and must never slide up under the
format tag or the match count in the top corners.

---

## The corners keep saying what the object is

While the overlay is up:

- the format tag (`12"`, `2 discs`) stays in the top left,
- the match count (`3 songs`) takes the top right — the **flag is hidden**
  there while you are hunting a song,
- the artist strip stays lit along the bottom, over the scrim rather than under
  it, so you can still see whose tracklist you are reading.

---

## Accents and apostrophes mark the right letters

With **Ignore accents & apostrophes** on (the default):

| Type | Expect marked |
|---|---|
| `perfidia` | **Perfídia** — the whole word, accent included |
| `greatest` | the **Greatest** in `Bill Withers’ Greatest Hits` |

The second one is the case worth doing by hand: folding *deletes* the
apostrophe, so a highlight measured in the folded text lands one letter short.
If the mark ever sits off by one after a punctuation mark, that mapping has
broken.

Untick the option and search `perfidia` again — the record should drop off the
shelf entirely, because now it is only findable as written.

---

## On a phone

There is no hover, so the tracklist simply stays up. That is intended: a tap
already opens the drawer, where the same tracklist has a whole tab of its own.
Check that the rows are not cramped at phone width and that the overlay still
scrolls with a finger without dragging the page.
