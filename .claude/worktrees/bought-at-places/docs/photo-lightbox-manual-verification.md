# Walking a record's photos — what to check by hand

jsdom has no layout, no paint and no touch, so the boot suite proves the run is
built right and the arrows enable and disable on the correct photos. It cannot
tell you whether you can *reach* them with a thumb, or whether they are legible
sitting on top of a photograph. These are the things only a real browser can.

Set up a record with **at least five photos spread over three notes** — two on
the first, one on the second, two on the third. The boundaries are the
interesting part: the walk is the record's, not the note's.

---

## The arrows are readable on a photo, not just on grey

The buttons sit *on* the image, not beside it, so they have no background of
their own to rely on.

Open a photo that is **light and busy at its left and right edges** — a white
sleeve, an overexposed shot. The chevrons should still be findable. They ride a
translucent dark disc for exactly this reason; if one disappears into the
picture, the disc is too weak.

Then open a **dark** photo and confirm the disc does not read as a hole.

---

## The ends of the run are visibly ends

1. Open the **first** photo on the record. The left arrow is dimmed; pressing it
   does nothing and nothing flickers.
2. Open the **last**. The right arrow is dimmed.
3. A record with exactly **one** photo: both dimmed, and the photo still opens
   normally.

A dimmed arrow must stay in place. If it vanished, the other arrow would shift
and the whole thing would read as a layout glitch — which is why they grey out
rather than disappear.

---

## Crossing a note boundary

Open the **last photo of the first note** and press right. You should land on
the next note's first photo, not stop. Walk all five end to end in both
directions and confirm the order matches what you see in the History list,
top to bottom.

---

## The words under the photo

The note a photo belongs to is printed under it. jsdom proves the right words
arrive and that they change as you walk; it has no layout, so it cannot tell
you whether they fit.

1. Open a photo on a note with a **long** note — a few paragraphs. The photo
   stays whole and the modal scrolls to reach the rest of the words. Nothing is
   cut off with no way to get at it.
2. Open a photo on a note written with **markdown** — a list, a bold word, a
   heading. It renders the same way it does in the History list behind it, not
   as raw asterisks.
3. Step across a note boundary with the arrows. The words change with the
   picture, and the arrows stay centred on the **image** — they must not drift
   down toward the caption.
4. A note that is only a photo shows **no** caption and no empty gap where one
   would be.
5. Clicking the words closes the photo, the same as clicking the photo does.
   That is the overlay behaving as it always has — worth knowing before it
   surprises you mid-sentence.

---

## The phone

At ~400px, on a real device:

- Both arrows are reachable **with one thumb** without covering the photo you
  are trying to look at.
- Tapping an arrow changes the photo and **does not close the lightbox**. The
  overlay closes on any tap that reaches it, so this is the failure to watch
  for — it would look like the photo shutting the instant you navigate.
- Tapping the photo itself still closes it, as it always has.
- A note's words sit under the photo at full width and wrap; they never push
  the picture sideways or off the screen.
- A tall portrait photo and a wide landscape one both keep the arrows vertically
  centred on the image rather than on the empty space around it.

---

## The keys, on desktop

With a photo open:

| Key | Expected |
|---|---|
| ← / → | previous / next **photo** |
| Esc | closes the **photo**, leaving the record drawer open behind it |

With the photo closed, the drawer takes them back:

| Key | Expected |
|---|---|
| ← / → | previous / next **record** |
| Esc | closes the record |

The bug this replaced: the arrows used to walk the collection while you were
looking at a photograph, and Escape threw the record away instead of the photo.

---

## Photos you should not be able to reach

In **edit mode**, a private note's photos appear in the History and belong in
the walk. Log out and open the same record as a visitor: those photos are gone
from the History, and the arrows must skip them — walking the run end to end
should never land on one, and the ends should now be the first and last
*public* photo.

This is the check worth doing properly. The run is read from what is drawn
rather than from the record, so it should be right by construction — but it is
the one way this feature could show something it shouldn't.
