# Photo-scan autofill — manual verification

Everything in this feature that a test can reach is covered by the 70 automated
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
6. Capture properly → the photo lands in the cover preview and the scan starts.
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

---

## 4. Spotify paste row

1. Paste a normal album link (`https://open.spotify.com/album/...`) → fields
   fill, cover art appears.
2. **Remaster check:** paste a link to a *remastered* album. The year must be
   the **original** release year, not the remaster year. (Spotify's own
   `release_date` is the remaster date and is deliberately ignored.)
3. Paste a **playlist** or **track** link → a clear inline error, form still
   usable.
4. Paste rubbish (`hello`) → inline error, no crash.
5. Check the **Spotify logo** renders correctly in **both light and dark
   themes**, and that the spacing around it isn't cramped. The 12px gaps are
   Spotify's required clear space — if anything looks tight, say so rather than
   nudging it.

---

## 5. Busy state and races

1. Start a scan and, while *"scanning…"* is showing, try **Choose file**,
   **Take photo**, and the Spotify field. All should look visibly greyed out
   and do nothing.
2. Start a scan → **close the form** → open **add record** again. Every scan
   control must be usable immediately, not stuck greyed out.
3. Start a scan on record A → close the form → open a **different** record →
   let the first scan finish. **Nothing** from record A may appear in it.
4. On a slow connection, pick a **large** photo, then close the form and open a
   different record while it's still processing. The first photo must not
   become the second record's cover.

---

## 6. Layout

- Narrow the desktop browser to about **360px** wide. The form must not scroll
  sideways, and the *"not this one?"* link must sit on its **own full-width
  row** — Year and Genre should stay paired side by side, not knocked out of
  alignment.
- Check the form in **both themes**.

---

## 7. Graceful degradation

With `ANTHROPIC_API_KEY` **unset** (easiest to check locally):

- The app still starts and the collection works normally.
- A photo scan gives a clear inline error, the photo still attaches as the
  cover, and you can type the record in by hand.

Same with the Spotify credentials unset: the paste row stays visible (it can't
know the server's credentials) and returns a clear error when used.
