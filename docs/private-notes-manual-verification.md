# Private notes — manual verification

A note can now be marked **private**: you see it in edit mode, a visitor never
receives it at all. Every note written before this is public, and stays public.

Covered by tests: 14 server tests for the stripping, the export lock and the
image gate, 10 in the jsdom boot suite for the form switch and the unlock
reload, 2 for the calendar event. What follows is what they **cannot** reach —
what a second person actually sees in a second browser, and how any of it looks.

Tick the ones that pass; anything that fails, tell me what you saw.

---

## What "private" actually means, so a surprise reads correctly

The hiding happens **on the server**. A visitor's `/api/records` response has
the private notes removed from it before it leaves the app — they are not sent
and hidden, they are not sent.

Two consequences worth knowing before you test:

- **There is nothing to find.** No dot on the timeline, no row in the record's
  history, no mark on the calendar, no entry in the activity feed, and the
  counts do not include it. A visitor cannot tell the note exists.
- **The flag is written only when it is on.** A public note carries no
  `private` key at all, which is why every note you have ever written is still
  visible with nothing to migrate.

> **How to be a visitor.** Open the app in a **private/incognito window**, or a
> second browser. Do not just press **lock** in the same tab and trust it —
> that is worth testing too (§4), but a fresh session is the honest check.

---

## 1. Writing one

1. Open a record for editing, scroll to **notes**. Under the note box, beside
   the photo buttons, there is now a **🔒 private** switch.
2. Leave it off, type a note, **add**. It appears in the list looking normal.
3. Turn it **on**, type a second note, **add**. That one appears with a dashed
   warm-purple edge and a small **PRIVATE** tag by its date.
4. The switch **stays on** after adding — deliberate, so writing two private
   notes in a row does not publish the second one. Turn it off by hand.
5. Each note in the list has a **padlock button** next to its bin. Click it on
   the public note → it becomes private. Click again → public again.
6. Save the record, reopen it for editing. Both notes are there, still marked
   the way you left them.
7. Open **add** for a brand-new record. The switch is **off** again — it is
   sticky within one form, not across forms.

## 2. What a visitor sees

Save a record with one public note and one private note, then open the app in a
private window.

1. Open that record. The **history** shows the public note and **no trace** of
   the private one — no extra row, no gap, no lock.
2. **Timeline** tab, on the private note's day: no note event for it. If the
   private note was on its own day, that day has no note mark at all.
3. **Calendar/week view**: the public note's row is there, the private one is
   not.
4. **Search**: turn on the **Notes** search field and search for a word that
   appears **only in the private note**. No match. Search for a word from the
   public note → it matches.
5. **Activity** tab: scrub past the private note's day. Nothing appears for it.

## 3. The proof, in the network tab

This is the check that actually settles it, and it takes ten seconds.

1. In the **private window**, open devtools → **Network**, reload the app.
2. Click the request to **`/api/records`** and look at the response.
3. Search the payload for the private note's text. **It must not be in there.**
   If you can find it, the note is not private, however it looks on screen.

## 4. Unlocking and locking mid-session

This is the one that could have lost data, so it is worth doing exactly.

1. In the private window (as a visitor), press **edit mode** and log in.
2. The collection **reloads** — a brief spinner. That is the point: the page was
   holding notes with the private ones stripped out.
3. Now open the record from §2 and edit it. The **private note is there** in the
   notes list.
4. Change something small and **save**. Reopen. **The private note survived.**
   (Before the reload existed, saving here would have deleted it.)
5. Press **lock**. The collection reloads again and the private note is gone
   from the record's history — it left with you.

## 5. Photos on a private note

A photo lives in its own table, addressed by a 32-character id, so it needs its
own gate.

1. In edit mode, add a note with a **photo** and mark it **private**. Save.
2. Copy the photo's URL — right-click the thumbnail in the record's history →
   copy image address. It looks like `/api/note-images/<32 characters>`.
3. Paste that URL into a **private window**. It must return **404**, not the
   photo.
4. Now do the same with a photo on a **public** note. That one must still load
   in the private window — public notes' photos have to keep working for
   everyone.
5. Back in edit mode, the private note's photo still shows in the form and in
   the history, and still opens full size when clicked.

## 6. Export and import

1. As a **visitor**, open the menu. There is **no export** item — it went behind
   auth along with import, because a backup carries the private notes verbatim.
2. In **edit mode**, export. Open the CSV and find the record's `notes` column:
   the private note is in there, with `"private": true`.
3. Delete that record, then **import** the file you just exported.
4. The record comes back, the note comes back, and it is **still private** — the
   dashed edge and the PRIVATE tag are there when you edit it, and a visitor
   still cannot see it.

## 7. Phone layout

1. On a narrow screen, the **private** switch sits on the photo row with the
   two photo buttons and wraps rather than stretching across the width.
2. A private note's entry in the list still shows both its padlock button and
   its bin, and they do not overlap the text.
3. The **PRIVATE** tag in the record's history does not push the note's date or
   time off the row.

---

## Known limits

- **Private is per note, not per record.** There is no "private record".
- **A private note's photo is unreachable to a visitor but not secret in the
  cryptographic sense** — the id is a hash of the image, so knowing it means
  having the image already. A visitor is never given the id.
- **Nothing is encrypted.** Anyone with the edit password, or with the database
  file or a CSV backup, reads everything. This hides notes from visitors to the
  site; it is not a safe.
- **The timeline rail dots and the activity strip's hover card are not tagged**
  with a lock when you are in edit mode. They show glyphs and one-line previews
  rather than the note itself, and the visitor side is handled on the server, so
  the tag is only missing from your own view in those two places. The form, the
  record's history and the calendar all carry it.
