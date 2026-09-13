# Bought-at places — what to check by hand

The suite covers the place rules, the API and the merge arithmetic, and a
Playwright pass covered the popup, the drawer link and the crate header on this
machine. These are the things only your own data and a real phone can tell you.

---

## The backfill read your collection correctly

The `place` table is created and filled on the **first boot after deploy**, one
row per distinct trimmed `bought_where` already in the records.

1. Open ⋯ → **places**.
2. Every store, fair and city you have ever typed into "bought at" should be
   listed, with its record count beside it.
3. The counts should add up to the number of records that have a place at all.

Two rows that differ **only by case** (`Tracks` and `tracks`) are expected, not
a bug: the backfill will not invent a canonical spelling during a deploy,
because that would silently rewrite records. Fix them with a merge, below.

---

## A merge moves every record on both sides

This is the destructive one, and the only way to remove a place.

1. Pick the smaller of two duplicate places and press its pencil.
2. Type the **exact spelling you want to keep** into Name — including its
   casing, which is what wins — and save.
3. The confirm names both places and the total records moving. Read that number
   before accepting: it is the sum of both sides.
4. After saving: one row remains, its count is the sum, and the toast says how
   many records were updated.
5. Filter or group by "Bought at" and confirm the old name is gone from the
   crate list and from the filter facet.

The surviving row keeps **the link you saved in that form**, not the link the
absorbed place had. If the one you were merging away had the better link, paste
it in before saving, not after.

---

## The link actually opens what you meant

`tracksrio.com` is stored as `https://tracksrio.com`. Anything that is not
http(s) is refused by both the form and the server.

1. Give a place a link and open a record bought there → the drawer's "Bought
   at" is a link with an arrow icon; it opens in a **new tab**, leaving the
   collection where it was.
2. A place with no link renders as plain text, exactly as before.
3. Group by "Bought at" → only crates whose place has a link show the arrow at
   the right of the header. Clicking the header still collapses the crate;
   clicking the arrow opens the link and does **not** collapse it.

---

## On a phone

The crate header is a pill at two columns, and the link now sits inside that
pill rather than beside it.

1. Group by "Bought at" on the phone and scroll a long crate. The header pins
   to the top and the arrow pins with it.
2. The arrow and the header are separate tap targets. Tapping near the arrow
   should not collapse the crate, and tapping the name should not open the link.
3. Open ⋯ → places on the phone: the inline edit form should not push the save
   button off the popup, and the keyboard should not cover it.

---

## A shop typed into a record turns up on the list

The record form's "bought at" is still free text. Saving a record with a name
that has no place row now creates one, so it can be given a link — the backfill
only ever runs once, so without this a shop first visited after that boot would
be unreachable.

1. Add or edit a record and type a store you have never used before. Save.
2. Open ⋯ → **places**. The new name is on the list, with no link and one
   record.
3. Give it a link, then reopen the record's drawer — "Bought at" is now a link.

The flip side is that a **typo** in that field also creates a place: save
`Trakcs Rio` and it appears as its own row and its own crate. Fix it in the
places popup by renaming it onto the right spelling, which merges the two and
rewrites the record.

A name differing from an existing place only by case (`tracks rio` against
`Tracks Rio`) does **not** create a second row — but the record still holds the
casing you typed, so it lands in its own crate until you merge it. Group by
"Bought at" after a bulk edit to spot these.
