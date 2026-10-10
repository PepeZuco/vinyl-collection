/* The admin page's stand-in playlists: which records a search keeps, which
 * rows a pill shows, how a Spotify hit reads, and which songs the playlist
 * gets.
 *
 * Loaded as a plain script in the browser, where `const VinylStandins` lands
 * in the global lexical scope for the inline script below it; required as a
 * module by tests/test_standins.js. */

const VinylStandins = (function () {

  function fold(s) {
    return String(s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase();
  }

  /* Every word typed must appear in the record's artist or album. */
  function filterCandidates(list, query) {
    const words = fold(query).split(/\s+/).filter(Boolean);
    if (!words.length) return (list || []).slice();
    return (list || []).filter(r => {
      const hay = fold(`${r.artist} ${r.album_name}`);
      return words.every(w => hay.includes(w));
    });
  }

  /* 'with' keeps records that already have a tracklist, 'without' those that
   * have none; anything else keeps all. */
  function tracksKeeps(record, which) {
    if (which === 'with') return !!record.has_tracks;
    if (which === 'without') return !record.has_tracks;
    return true;
  }

  function pillKeeps(standIn, pill) {
    if (pill === 'matched') return !!standIn.matched;
    if (pill === 'unmatched') return !standIn.matched;
    return true;
  }

  function hitLabel(hit, suggestion) {
    const label = h => [h.name, h.album, h.year].filter(Boolean).join(' · ');
    if (hit) return label(hit);
    if (suggestion) return `did you mean ${label(suggestion)}?`;
    return 'not found on Spotify';
  }

  /* 'hit' goes on the playlist ticked; 'suggestion' is a near-spelt song the
   * owner may tick; 'miss' has nothing. */
  function songState(song) {
    if (song && song.hit) return 'hit';
    if (song && song.suggestion) return 'suggestion';
    return 'miss';
  }

  /* A/B are disc 1, C/D disc 2 — the same rule static/tracks.js uses. */
  function sidesFor(discCount) {
    const n = Math.max(1, Number(discCount) || 1) * 2;
    return Array.from({ length: n }, (_, i) => String.fromCharCode(65 + i));
  }

  function discCountFor(tracks) {
    const last = Math.max(0, ...(tracks || []).map(t => String(t.side || 'A').toUpperCase().charCodeAt(0) - 65));
    return Math.floor(last / 2) + 1;
  }

  /* The ticked songs that Spotify has (a hit, or a suggestion the owner
   * ticked), in tracklist order, each track once. */
  function pickedUris(songs, ticked) {
    const out = [];
    (songs || []).forEach((s, i) => {
      const h = s.hit || s.suggestion;
      if (ticked.has(i) && h && h.uri && !out.includes(h.uri)) out.push(h.uri);
    });
    return out;
  }

  return { filterCandidates, tracksKeeps, pillKeeps, hitLabel, songState, sidesFor, discCountFor, pickedUris };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylStandins;
