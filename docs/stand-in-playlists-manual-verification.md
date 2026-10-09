# Spotify stand-in playlists — what to check by hand

The suite covers the song search ranking, the description, the cover JPEG,
creating, matching, unmatching and deleting against a fake Spotify, Claude's
tracklist with a mocked API, and the admin section in jsdom. These are the
things only the real Spotify account and your own eyes can tell you.

---

## Build one for a record with a tracklist

1. Admin page → **spotify stand-ins**. The right column lists every record
   without a Spotify link; search narrows it.
2. Pick a record that has a tracklist → **find songs on Spotify**.
3. Every song shows its hit (track · album · year) or *not found on Spotify*.
   Check a few hits are the right recording; untick a live take if a studio
   one exists on Spotify but was not picked.
4. **create playlist**. The new row appears on the left, *not matched*.
5. Open it on Spotify: private, named "Artist — Album", the record's cover,
   and a description with the year, genre, country, shop and "n of m songs found".
   The thumbnail on the row may show Spotify's mosaic until the page is
   reloaded: Spotify takes a moment to process an upload.

## A record with no tracklist

1. Pick one tagged **no tracklist** → **suggest tracklist with Claude**.
2. Compare with the sleeve, fix titles and sides, remove or add rows.
3. **save tracklist**: the search runs straight after. Open the record: the
   tracklist is on it, and its songs can be hearted.
4. The spend line counts the call (source `tracklist`).

## Match feeds the playlists

1. **match** on the row. The chip turns green; the record is gone from the
   candidates; the record's "Open in Spotify" opens the stand-in.
2. Spotify tab → sync a playlist whose filters include that record (default
   "albums" source). Its songs are added. Heart a song on the record and
   sync a liked playlist: that song is added.
3. A playlist with **compilations only** does *not* take it.
4. **unmatch**: the link is cleared; the next sync takes the songs out.

## Delete

1. Delete a matched stand-in. Confirm the prompt.
2. The playlist is gone from your Spotify library, and the record has no link.

## Old login

A login granted before cover uploads were asked for still creates the
playlist; the row says **reconnect Spotify to allow cover uploads**.
