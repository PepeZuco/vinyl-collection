# Note pictures — manual verification

A note on a record can now carry photos, added the same two ways a cover can be:
a file from the device, or the camera.

Everything a test can reach is covered — 29 server tests for the image table and
the CSV round trip, 17 for the notes rules, 44 for the activity strip, plus the
jsdom boot suite and four proof scripts that drive the real rendered page. What
follows is what they **cannot** reach: real cameras, real files off a real
phone, and how any of it looks. Work through it once on a desktop browser and
once on a real phone.

Tick the ones that pass; anything that fails, tell me what you saw.

---

## What is stored where, so a surprise reads correctly

A photo is **not** kept in the note. The note holds only a 32-character id, and
the bytes live in their own table, served from `/api/note-images/<id>`.

Two consequences worth knowing before you test:

- **The same photo added twice is stored once.** The id is a hash of the image
  itself, so re-adding a photo you already added is free and yields the same id.
  Seeing one row where you expected two is correct.
- **A photo is deleted when nothing points at it any more** — when you remove it
  from its note and save, or delete the record. A photo you uploaded but never
  saved is swept about six hours later, not immediately.

> **Testing gotcha, same as the cover.** `getUserMedia` only exists in a *secure
> context*. Over HTTPS or on `localhost` the in-page camera works. If you open
> the app on your phone via a plain `http://192.168.x.x` LAN address,
> `navigator.mediaDevices` is `undefined` and the app falls back to the OS camera
> app. That fallback is correct, not a bug — but to test the **in-page** camera,
> use the deployed HTTPS URL.

---

## 1. Adding a photo to a note

1. Open a record for editing, scroll to **notes**. Under the note box there are
   now two buttons: **photo** and **take photo**.
2. **photo** → pick an image. A thumbnail appears under the buttons within a
   second or two of the file dialog closing.
3. Add a second and a third. They sit in a row and wrap rather than overflowing.
4. Each thumbnail has a small **×** at its top-right. Click one — that photo
   goes, the others stay.
5. Type some text, click **add**. The note appears in the list below *with its
   photos under the words*.
6. Save the record, reopen it. The note and its photos are still there.

## 2. A note that is only a photo

This used to be impossible — a note with no text was silently thrown away.

1. Attach one photo, type **nothing**, click **add**.
2. The note is accepted, and shows as an entry with a photo and no words.
3. Save, reopen. It survived.
4. Now remove that photo from the note with its ×. The whole note should
   disappear, because a note with no words and no photo is nothing.

## 3. The camera (phone or tablet — the part with no test coverage)

1. In the notes row, tap **take photo** → grant camera permission.
2. The camera opens **inline**, shows the **rear** camera, and does not go
   fullscreen.
3. **capture** → the shot lands as a note thumbnail, **not** as the album cover.
   This is the one worth checking carefully: the picker, the camera and the
   resize path are shared with the cover, and only the destination differs.
4. Now tap the **cover** area's camera and capture. That one must still become
   the cover. Neither should ever land in the other's place.
5. Slow path, worth trying once: pick a large photo for a note, and while it is
   still processing, tap the cover's camera button. The note photo must still
   become a note photo.

## 4. Where the photos show up

1. **Detail history.** Open the record, look at History. The note shows its
   photos as thumbnails.
2. Click one → it opens full size. Clicking the backdrop or the × closes it.
3. A note that is only a photo appears in History rather than vanishing.
4. **Activity strip.** On the History/activity tab, scrub the playhead past a
   note that has a photo → the hover card shows a small thumbnail. Past one
   without → no thumbnail, and no broken-image box.

## 5. It does not slow the collection down

This is the constraint the whole design exists for, and it is easy to break.

1. With several photo-carrying notes saved, open the app fresh.
2. In the browser devtools Network tab, find the request to **`/api/records`**.
3. Its size must be in **kilobytes**, not megabytes, and must not grow when you
   add more photos. The photos load separately, one request per image, cached
   permanently after the first time.

## 6. Export and import carry the photos

1. **Export** the collection.
2. Delete a record that had photos on a note.
3. **Import** the file you just exported.
4. The record comes back, and its note's photos come back with it and display.

## 7. Phone layout

1. On a narrow screen, the notes row's **photo** and **take photo** buttons sit
   side by side and do not each stretch to the full width of the row. (The
   **add** button below them still does.)
2. The thumbnail rows wrap rather than pushing anything sideways.
3. The full-size photo view fits the screen and does not need scrolling.

---

## Known limits

- A photo is capped at 2MB after resizing. A larger one is refused with a
  message rather than failing silently.
- Photos are resized to 1000px on the long edge before upload, and rotated
  according to the EXIF orientation, so a portrait phone photo is not sideways.
- The activity strip's hover card shows only the **first** photo on a note; it
  is a card, not a gallery. The full set is in the detail history.
