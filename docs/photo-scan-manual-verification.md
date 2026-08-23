# Photo-scan autofill — manual verification

Everything in this feature that a test can reach is covered by the 90 automated
tests. What follows is what they **cannot** reach: real cameras, real browser
permission prompts, real network calls, and how the layout behaves on a phone.
Work through it once on a desktop browser and once on a real phone.

Tick the ones that pass; anything that fails, tell me what you saw.

---

## Before you start

Set these on Railway (see README):

| Variable | Needed for |
|---|---|
| `ANTHROPIC_API_KEY` | reading the sleeve photo, classifying the genre |
| `MUSICBRAINZ_CONTACT` | the required MusicBrainz `User-Agent` |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | the Spotify paste row |

> **Testing gotcha.** `getUserMedia` only exists in a *secure context*. Over
> HTTPS or on `localhost` the in-page camera works. If you open the app on your
> phone via a plain `http://192.168.x.x` LAN address, `navigator.mediaDevices`
> is `undefined` and the app silently falls back to the OS camera app instead.
> That fallback is correct behaviour, not a bug — but if you want to test the
> **in-page** camera, use the deployed HTTPS URL.

---

## 1. Camera (phone or tablet — this is the part with no test coverage)

1. Open **add record**, tap the cover area → the action sheet opens.
2. **Take photo** → the browser asks for camera permission. Grant it.
3. The in-page camera opens **inline** — it must *not* go fullscreen and must
   *not* cover the whole screen with the native player. (This is what
   `playsinline` buys us on iOS; if it goes fullscreen, that attribute isn't
   taking effect.)
4. It should show the **rear** camera on a phone.
5. Tap **capture** the instant the overlay appears, before the preview has
   painted. You should get the toast *"camera still starting — try again"* and
   nothing should be written to the cover. (Without this guard the app would
   silently save a blank image.)
6. Capture properly → the photo lands in the cover preview and **nothing else
   happens**. No scan starts, no spinner, no API call. A **scan this cover**
   button appears under the photo; that button is now the only way to start a
   scan.
7. **Check the camera indicator light goes dark** once the overlay closes, and
   again after you cancel. A light still on means a stream was leaked.
8. Cancel out of the camera, reopen it, cancel again — a few times. The light
   must go dark every time.

**Orientation:** take a photo holding the phone **portrait**. The cover preview
must appear upright, not rotated 90°. (EXIF orientation is handled via
`createImageBitmap(file, {imageOrientation:'from-image'})`; the older `<img>`
fallback path does not, so if it looks sideways tell me which browser.)

**Deny the permission** once, deliberately. The app should fall back to the OS
camera/photo picker rather than doing nothing.

---

## 2. Photo scan quality — the real point of the feature

Scan **five or six sleeves you already know**, and check the two fields that
are easy to get subtly wrong:

- **Year must be the original release year**, not the year of *your* pressing.
  A 1980s reissue of a 1973 album must come back **1973**.
- **Country must be the artist's home country**, not where the record was
  pressed. A UK-pressed Milton Nascimento record must come back **BR**.

Also try:

- A sleeve with the **genre not printed anywhere** → genre should come back
  empty and you type it yourself. It must **not** invent one.
- A **back cover** or a very dark/stylised sleeve → expect *"nothing readable
  found — type it in by hand"*. Nothing should be filled with garbage.
- An album where the first guess is wrong → the **"not this one? (n)"** link
  should appear and offer alternates with year and country.
- An album you **already own** → the duplicate warning must name the record.
- A file the browser **cannot decode** — a `.heic` straight off an iPhone is the
  easy one, and it sails through the file picker on desktop Chrome. You should
  get *"could not read that image — try a jpg or png"*. A silent no-op here is a
  bug: it just looks like the click didn't register.

---

## 3. The edit path — this is where the worst bug lived

This sequence used to destroy data. Confirm it no longer does:

1. Open an **existing** record for editing — one with artist, album and genre
   all filled in.
2. Attach a **bad** photo (back cover, or something unreadable).
3. The scan returns nothing → **artist, album and genre must still hold the
   record's original values**, and the toast must say *"nothing readable found"*.
4. Save, reopen the record → all three fields still intact.

Then the subtler one:

5. Edit a record, scan a sleeve whose **genre isn't printed** → artist and album
   update, **genre keeps the record's existing value**.
6. On the **add** form, scan album A, then scan album B → none of album A's
   year, country or genre may survive into album B.

And the two that the last round of fixes was about — a scan must never take back
a field **you** touched:

7. Scan a sleeve, then **correct the artist by hand** (the scan reads "Sade",
   you make it "Sade Adu"). Now scan a *second*, unreadable photo. Your
   correction must **still be there** — the second scan may clear what the first
   scan filled, never what you typed over it.
8. Same again with **genre**: let the scan fill it, pick a different genre from
   the dropdown yourself, then run a scan that reads no genre. Your choice stays.
9. Scan a sleeve, tick **multiple artists**, fill in the rows, untick it again
   (which rebuilds the artist field from your rows). A later scan that reads no
   artist must not wipe that rebuilt value.
10. Open a record that **already has a cover you chose** and paste a Spotify
    link just to fill the genre. **The cover must not change.** (On the add
    form the opposite is intended: a photo you just took may be replaced by
    cleaner artwork.)
11. With **multiple artists** ticked, run a scan. The artist rows are what gets
    saved, so the scan must not claim it filled an artist it cannot show you.
12. Scan a record from a country **outside the dropdown list** (the picker has
    75; MusicBrainz knows them all) — Ghana or Iceland, say. The code should
    appear as-is rather than the field coming back empty, and it must still be
    there after you save and reopen.

---

## 4. Spotify paste row

Handing in a link no longer scans on the spot — it arms **analyse** and stops.
See §9 for the gating itself; this section is about the link handling.

1. Paste a normal album link (`https://open.spotify.com/album/...`) → the sheet
   closes and a toast says *"spotify link ready — tap analyse"*. **Nothing is
   sent yet.** Tap **analyse** → fields fill, cover art appears.
2. **Remaster check:** hand in a link to a *remastered* album and analyse it.
   The year must be the **original** release year, not the remaster year.
   (Spotify's own `release_date` is the remaster date and is deliberately
   ignored.)
3. Hand in a **playlist** or **track** link → it looks like a Spotify link, so
   it arms. Tap **analyse** → the server rejects it, and the sheet **reopens**
   with the error next to the input. (It has to reopen: the sheet is closed by
   the time analyse runs, so an error left inside a hidden sheet would never be
   read.)
4. Paste rubbish (`hello`) → inline error straight away, analyse **stays grey**,
   no request made, no crash.
5. Check the **Spotify logo** renders correctly in **both light and dark
   themes**, and that the spacing around it isn't cramped. The 12px gaps are
   Spotify's required clear space — if anything looks tight, say so rather than
   nudging it.

---

## 5. Busy state and races

1. Start a scan. A small spinner and *"scanning… this can take up to a minute"*
   must appear under the cover and **stay** for the whole scan — a scan runs far
   longer than a toast lives, so if it vanishes after a couple of seconds the
   indicator is wrong. While it shows, try **analyse**, **Choose file**, **Take
   photo**, and the Spotify field: all should look visibly greyed out and do
   nothing.
2. Start a scan → **close the form** → open **add record** again. The spinner
   must be **gone** and nothing may be stuck greyed out by the abandoned scan:
   the file inputs and the Spotify row are usable immediately, and **analyse**
   is grey only because the fresh form has nothing in it yet — attach a photo
   and it must light up. Let a scan fail too (see §8) — the spinner must clear
   on the error path as well, not hang there forever.
3. Start a scan on record A → close the form → open a **different** record →
   let the first scan finish. **Nothing** from record A may appear in it.
4. On a slow connection, pick a **large** photo, then close the form and open a
   different record while it's still processing. The first photo must not
   become the second record's cover.

---

## 6. The Google Images fallback

This is the fallback for the scans that read the least — when the app can't pin
the record down, it sends you somewhere you can go look yourself.

1. Scan a sleeve → on the results screen, **none of these fit — search Google
   Images** sits along the bottom.
2. Tap it → a **new tab** opens on Google Images, already searching something
   like *"Bill Withers Live at Carnegie Hall 1973 vinyl cover"*. The app must
   still be sitting there behind it, form intact.
3. Do this on the **phone** too. It is a real link rather than a scripted
   `window.open` precisely so Safari's popup blocker leaves it alone — if
   nothing opens, tell me which browser.
4. Pick an alternate release first, then use the link: the **year in the query
   must be that release's year**, not the first guess's.
5. Scan a **completely unreadable** photo → the link should **not** appear;
   there would be nothing to search for.
6. Check the results screen in **both themes**.

> Note the round trip is manual by design: Google shows you the sleeve, you
> save the image, and you add it as a cover yourself. The app cannot reach into
> a Google tab.

---

## 7. Layout

- Narrow the desktop browser to about **360px** wide. The form must not scroll
  sideways — Year and Genre should stay paired side by side, not knocked out of
  alignment.
- At that width the results screen must drop to **two columns** of covers, and
  its bottom bar must stack so the Google link is a full-width target rather
  than a corner.
- Check the form and the results screen in **both themes**.

---

## 8. Graceful degradation

With `ANTHROPIC_API_KEY` **unset** (easiest to check locally):

- The app still starts and the collection works normally.
- A photo scan gives a clear inline error, the photo still attaches as the
  cover, and you can type the record in by hand.

Same with the Spotify credentials unset: the paste row stays visible (it can't
know the server's credentials) and returns a clear error when used.

---

## 9. Nothing scans until you say so

The whole point of the change: adding a cover or a link is adding a cover or a
link, not spending a vision call and four MusicBrainz lookups. **Analyse** is
the only thing that spends anything, and it is dead until there is something to
spend it on.

1. Open **add record**. **Analyse** is greyed out, and the line under it reads
   *"add a cover or a spotify link first"*.
2. Attach a photo by **file picker**. No scan. Analyse lights up and the line
   becomes *"nothing is sent until you tap analyse"*.
3. Same with the **camera** path, and same with the OS photo picker fallback.
4. Hand in a **Spotify link** instead, on a form with no cover → same thing:
   analyse lights up, nothing sent.
5. Close the form and reopen it → analyse is grey again.
6. Tap **analyse** → the busy state appears and analyse, the file inputs and the
   Spotify row all go disabled until it finishes. Tapping it again mid-scan does
   nothing.
7. Open an **existing record** that already has artwork → analyse is live from
   the start, and it re-reads that artwork. That is intended. A record with
   **no** artwork opens with analyse grey.
8. **Whichever you handed in last wins.** Attach a photo, then paste a link →
   analyse reads the link. Paste a link, then attach a photo → analyse reads the
   photo. (Artwork that arrives from a scan result does *not* count as handing
   in a photo, so picking a candidate after a Spotify scan leaves the link in
   place.)

### The thinking face

It is a 30-frame strip stepped by hand, not an animated GIF — a GIF would twitch
at rest and could never be played on demand.

1. At rest it is **completely still**, both greyed out and live. Any motion
   before you tap is a bug.
2. Tap **analyse** → it runs **one pass, about a second**, then stops. It must
   not loop for the length of the scan; the *"scanning…"* spinner is what tracks
   the actual request, which can take up to a minute.
3. It must be a clean cutout in **both themes** — no dark square or grey halo
   behind the face on the light theme.
4. With **reduced motion** turned on at the OS level, it stays still on tap and
   the scan still runs.

---

## 10. The scan results screen

1. Scan a sleeve → a full screen of **candidate covers** opens, not a collapsed
   *"not this one?"* link. On the phone that is two columns; on the desktop,
   three.
2. The strip at the top shows the photo you took and what was read from it.
3. The first card carries a **best match** badge, and only the first.
4. Tap a card → you land back on the form with artist, album, genre, year and
   country filled, and **that card's artwork as the cover** — your photo is
   replaced. Check this especially with a badly-lit photo: the API artwork
   should win every time.
5. Pick a candidate MusicBrainz has **no artwork** for (the card shows a disc
   and *"no artwork found"*) → your photo must stay put rather than the cover
   going blank.
6. **back to the form** and **skip — I'll type it in** both return you to the
   form with whatever was read still filled in, and no candidate applied.
7. Scan something already in the collection → the matching card carries
   **already in your collection**, and the warning banner is on the form too.
8. Scan a Brazilian pressing MusicBrainz has never heard of → the empty state
   explains itself and offers the Google link.
9. Paste a **Spotify link** instead of a photo → the same screen opens, but the
   heading reads *"read from the Spotify link"* and there is no photo thumbnail.

---

## 11. Wishlist, and the cover at its real size

**Wishlist:**

1. Open **add record** → **Wishlist**. The whole **the purchase** block
   disappears; a purple note explains why. Play count, **played on** and
   **cleaned on** stay on screen but go grey and stop responding — including to
   the keyboard, so tab through them and confirm you cannot land in one.
2. The save button reads **add to wishlist**.
3. Type a shop into **bought at**, switch to Wishlist, switch back → what you
   typed is **still there**. Switching must not destroy anything.
4. Save a wishlist record, then reopen it: **bought on / at / by are empty**.
   This is deliberate — a record you do not own must not carry a purchase, or
   it turns up in the purchase stats. Play history is left alone.
5. Edit an **existing owned** record and flip it to Wishlist → the same thing
   happens, and the button still says **save**, not *add to wishlist*.
6. Flip it back to **In collection** → the purchase fields return.

**The cover:**

1. Attach a **portrait** photo, and a **wide** one. Neither may be cropped —
   the box takes the picture's proportions instead of forcing it into a fixed
   height. Compare against the sleeve in your hand: the top and bottom must
   both be there.
2. Attach a very **tall** photo → it stops growing at 60% of the screen height
   rather than pushing the rest of the form out of reach.
3. Check on the phone as well as the desktop.
