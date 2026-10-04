/* The admin page's Spotify → wishlist review list: which album rows can be
 * ticked, which start ticked, and the words for the progress line.
 *
 * Loaded as a plain script in the browser, where `const VinylAdmin` lands in
 * the global lexical scope for the inline script below it; required as a
 * module by tests/test_admin.js. */

const VinylAdmin = (function () {

  /* Never an album already on the shelf or the wishlist, never one MusicBrainz
   * and Claude agree was not pressed, and not until its chunk has come back —
   * an unchecked row has no badge to justify the tick. */
  function canTick(album) {
    if (!album || album.duplicate_of) return false;
    if (!album.vinyl) return false;
    return album.vinyl !== 'none';
  }

  /* Only what is both on a known pressing and named by Claude starts ticked:
   * "likely" and the Spotify-fallback rows are offered, not assumed. */
  function defaultTicked(album) {
    return canTick(album) && album.vinyl === 'confirmed' && !album.unverified;
  }

  function chunk(list, size) {
    const out = [];
    for (let i = 0; i < (list || []).length; i += size) out.push(list.slice(i, i + size));
    return out;
  }

  function songsLabel(songs) {
    const s = songs || [];
    const shown = s.slice(0, 3).join(', ') + (s.length > 3 ? ', …' : '');
    return `${s.length} ${s.length === 1 ? 'song' : 'songs'}: ${shown}`;
  }

  function progressText(stage, done, total) {
    if (stage === 'reading') return 'reading songs and naming albums…';
    return `checking vinyl ${done} / ${total}`;
  }

  return { canTick, defaultTicked, chunk, songsLabel, progressText };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylAdmin;
