# Guided tour — what to check by hand

The suite boots the page in jsdom, which lays nothing out: every element is
given a box so the tour can walk, and nothing is ever measured. These are the
things only a real browser can tell you — where the light lands, where the
card sits, and how it feels on a phone.

Open the app **logged out** (a visitor) unless a step says otherwise.

---

## The offer, once

1. In a private window (or after clearing site data), open `/`.
2. A **"First time here?"** card appears bottom-right; on a phone, above the
   tab bar, not behind it.
3. Press **no thanks**. Reload. It does not come back.
4. Clear site data again and open `/#tab=stats` (any link with a hash). No
   offer: someone who followed a link has somewhere to be.
5. Log in to edit mode on a fresh profile. No offer for the owner.

---

## The walk, desktop

Press the **?** button in the header. Check each step:

| Step | Lit | Check |
|---|---|---|
| Welcome | nothing, card centred | the number matches the owned count in the header |
| Search | the search box | card below it, not covering it |
| Narrow it down | the chips row | |
| Arrange | the Arrange row | |
| Can't decide? | the dice | card clamped inside the window, not cut off on the right |
| Open a record | the first card on the shelf | in list view, the first row instead |
| The shelf, on Spotify | the playlist list | tab switched to Spotify playlists; the light grows when "loading…" is replaced by the list |
| Claude | the Claude card on Readme | |
| Spotify link | the Spotify card | |
| That's the tour | the **?** button | button reads **done**; pressing it closes on Collection |

- **back** on "The shelf, on Spotify" returns to "Open a record" on Collection.
- **back** is hidden on Welcome.
- Scroll the page or resize the window mid-tour: the light and the card
  follow the target.
- Clicking the dimmed page does nothing. The page under the tour is not
  usable until it ends.

## Keyboard

- **→ / ←** step forward and back. **Esc** ends the tour and returns to the
  tab it was started on (start it from Statistics to see this).
- **Tab** cycles skip / back / next and never escapes to the page.
- Esc during the tour does not also close a filter popover or anything else
  behind it.

---

## Phone (≤ 760px)

1. Start the tour from **?** in the header.
2. Steps whose control the phone layout hides are skipped, not lit as an
   empty box.
3. On "The shelf, on Spotify", the playlist list is taller than the screen:
   the light is clipped to the screen and the card sits at the bottom over it,
   readable.
4. The card is never wider than the screen.

---

## Both themes, and reduced motion

- Toggle light/dark mid-tour: the card follows the theme, the dim stays dark.
- With *reduce motion* on in the OS, the light jumps between targets instead
  of sliding, and the offer card appears without its rise.

---

## The screensaver stays out of the way

In edit mode, start the tour and leave it for over two minutes. The idle
screensaver must not appear over it.
