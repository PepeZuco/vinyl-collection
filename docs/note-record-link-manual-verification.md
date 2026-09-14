# Linking a record from a note — manual verification

Notes are markdown, and a note has always been able to link anywhere —
Discogs, a shop, a review. Getting a link to something already **in the
collection** meant leaving the note, opening that record, copying its address
bar, and coming back. There is now a picker for that, inside the note
markdown modal.

Covered by tests: 4 in the jsdom boot suite (insert with existing text,
insert into an empty note, the empty/no-match search states, Escape closing
the picker before the modal). What follows is the part those cannot reach —
how it actually feels to use, and whether the inserted link really opens the
right record.

Tick the ones that pass; anything that fails, tell me what you saw.

---

## 1. Finding the picker

1. Open any record for editing, start typing a note (or open one already
   written), and tap the **expand** icon on the textarea to open the
   markdown modal.
2. Next to the close button there is now a **vinyl icon** — "link a record".
   Click it. A search box drops in above the split view, with a hint that
   says *type to search your collection…*.
3. Click it again. The search box closes without touching the note.

## 2. Searching and inserting

1. With the picker open, type part of an artist name. Matching records
   appear live, each showing artist and album. Type part of an album name
   instead — same thing.
2. Type something that matches nothing. It says so (*no records found*)
   rather than sitting empty.
3. Click a result. The picker closes, and a markdown link for that record
   appears in the text — right where your cursor was, not just tacked onto
   the end.
4. If the note already had words in it, the link lands **space-separated**
   from what came before, not glued onto the last letter. Into a blank note,
   the link starts clean with no leading space.
5. The **preview pane** (right side of the split) shows a real link, not
   literal brackets.
6. Close the modal (✕) — the note in the add/edit row itself now holds the
   link. Save the record, reopen it for editing: the link is still there.

## 3. The link actually works

1. Save a note carrying a record link, viewing the record's history (or the
   markdown preview) so the rendered link is visible.
2. Copy that link's address (right-click → copy link, or click it — it opens
   in a **new tab**, same as any other link in a note) and open it in a
   fresh tab.
3. It lands directly on the linked record's detail view, not on a search
   result or the collection's default screen.

## 4. Escape and outside clicks

1. Open the picker, then press **Esc**. Only the picker closes — the
   markdown modal stays open with whatever you'd typed intact.
2. Press **Esc** again. Now the modal itself closes.
3. Open the picker, then click outside the modal entirely (on the dimmed
   backdrop). The whole modal closes, same as before this feature existed.

## 5. Phone layout

1. On a narrow screen, the search box and result rows stay full width and
   readable — no row's album name should force the row wider than the
   screen (it truncates with an ellipsis instead).
2. The vinyl icon stays reachable next to the close button rather than
   wrapping onto its own line.

---

## Known limits

- The picker only searches by **artist** and **album name** — not year,
  genre, or note text.
- It does not distinguish owned records from wishlist ones; either can be
  linked.
- There is no keyboard-only way to pick a result yet (arrow keys / Enter) —
  it is click-to-insert only.
