# Generated playlist covers — what to check by hand

The suite covers which rows a cover shows, how long values are cut, that the
picture is a 640×640 JPEG Spotify will take, and that a refused or failed
upload never fails the sync. These are the things only the real Spotify
account and your own eyes can tell you.

---

## Reconnect once, after the deploy

Covers need the `ugc-image-upload` permission, which the saved login was not
granted. Until you reconnect, every sync still works but leaves the cover alone.

1. Open the playlists panel and sync any playlist.
2. The result line ends with **reconnect Spotify to set the cover**.
3. Follow that link and accept on Spotify — the consent screen should now
   mention uploading images.
4. Back in the app, sync again: the hint is gone.

---

## The cover lands on Spotify

1. Sync a playlist with a few filters (a genre, a decade, a rating).
2. Open it on Spotify, on the desktop app and on a phone. The cover is the
   half record on the left with one row per filter, and the footer shows
   liked/every track and the count.
3. The thumbnail in the playlists panel may still show the old mosaic right
   after the sync: Spotify takes a moment to process an upload. The next sync
   (or a reload a minute later) picks it up.

---

## It reads at a glance

Spotify shows covers at about 150 px in lists. Scroll your library: the
playlists made here should be recognisable by the record shape and colours
even where the words are too small to read.

---

## A cover set by hand is replaced

This is by design: every sync redraws the cover so the track count stays true.
If you set one by hand on Spotify, expect it back to the generated one on the
next sync.
