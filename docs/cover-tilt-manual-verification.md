# The full-screen cover and its tilt — what to check by hand

jsdom has no gyroscope, no layout and no paint. The boot suite proves the tap
opens the right cover, that only a new record asks for the sensor, that a
reading moves the numbers the right way and that closing stops listening. It
cannot tell you whether the lean *feels* like a sleeve in your hand. These need
a real phone — ideally one iPhone and one Android, since only iOS asks.

Set up **one new record** (condition ★ New), **one used**, and **one censored**.

---

## Opening and closing

1. Open a record on the phone and tap the big cover in the middle. It fills the
   screen on a dark backdrop, square, nothing else on it.
2. Tap a neighbour peeking in at the edge: nothing opens — the swipe still
   works as before.
3. Tap anywhere on the open cover, or the ✕: it closes and you are back on the
   same record, scrolled where you were.
4. The censored record: tapping the blurred cover does nothing. Press the eye,
   then tap — now it opens.

## The used record stays still

Open the used record's cover and tilt the phone about. Nothing moves, there is
no glare, and on iPhone **no motion prompt appears**.

## The new record leans

1. Open the new record's cover while holding the phone the way you normally
   read it. It opens **flat** — not already leaning back — whatever angle you
   were holding it at.
2. Tilt the phone right and left, then tip the top toward and away from you.
   The cover leans with it, a little behind the hand (smoothed, not jittery),
   and stops leaning at about 12° however far you go.
3. The glare: a soft hotspot and a diagonal streak that slide the **opposite**
   way to the lean, like light on shrink-wrap. On a **light** cover it should
   still read as glare, not wash the art out; on a **dark** one it should be
   visible without looking like a white smear.
4. The shadow under the cover shifts away from where the glare is.
5. Hold the phone still: the cover settles and stays put.
6. Turn the phone to landscape with the cover open: it re-centres flat, and
   tilting left/right still leans it left/right (not up/down).

## iPhone permission

1. First time on a new record: iOS asks for motion access as the cover opens.
   Allow → it leans. (Safari remembers per site; to see the prompt again, clear
   the site's data.)
2. Deny → the cover opens flat with the glare in the middle, no error, nothing
   broken. Closing and reopening does not nag.

## Reduced motion

With *Reduce Motion* on (iOS: Accessibility → Motion; Android: Remove
animations), a new record opens flat, like a used one.
