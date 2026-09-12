/* The tracks column's parse/serialize rules.
 *
 * Tracks are stored as JSON: [{side, title, liked_at?}]. The side LETTER
 * carries which disc a song is on, the way a real sleeve carries it — disc 1
 * is A/B, disc 2 is C/D — so there is no disc field on a track and nothing to
 * keep in sync.
 *
 * There is deliberately no position field either. Order within a side is the
 * array's own order and the number shown is derived at render time; storing a
 * position alongside the order gives two sources of truth that drift the first
 * time a row is dragged.
 *
 * liked_at is a stamp in the same format as play_dates — a LOCAL wall clock,
 * never UTC — so momentOf() reads it and the Timeline files it on the right
 * day. Absent means the song is not liked; there is no false to store.
 *
 * Loaded as a plain script in the browser, where `const VinylTracks` lands in
 * the global lexical scope for the inline script below it; required as a
 * module by the tests. */

const VinylTracks = (function () {

  const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

  /* Which sides a record of this many discs has. Two per disc, in order, so
   * the letter alone answers "which disc is this song on". */
  function sideLettersFor(discCount) {
    const n = Math.max(1, Number(discCount) || 1);
    return LETTERS.slice(0, n * 2).split('');
  }

  function discOfSide(letter) {
    const i = LETTERS.indexOf(String(letter || '').toUpperCase().slice(0, 1));
    return i === -1 ? 0 : Math.floor(i / 2) + 1;
  }

  /* Total: this column is read by six consumers straight off /api/records, and
   * a record whose value will not parse — a hand-edited PUT, a CSV from
   * somewhere else — must come back empty rather than take the grid down. */
  function parseTracks(raw) {
    if (!raw) return [];
    let parsed;
    try { parsed = JSON.parse(raw); } catch (e) { return []; }
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(function (t) { return t && typeof t === 'object'; })
      .map(function (t) {
        const out = {
          side: String(t.side || '').toUpperCase().slice(0, 1),
          title: typeof t.title === 'string' ? t.title : '',
        };
        if (t.liked_at) out.liked_at = String(t.liked_at);
        return out;
      });
  }

  /* '' rather than '[]' for an empty list: the column's empty value is the
   * empty string, and every reader treats it that way. */
  function serializeTracks(list) {
    const clean = (list || [])
      .filter(function (t) { return t && typeof t.title === 'string' && t.title.trim(); })
      .map(function (t) {
        const out = {
          side: String(t.side || 'A').toUpperCase().slice(0, 1),
          title: t.title.trim(),
        };
        if (t.liked_at) out.liked_at = String(t.liked_at);
        return out;
      });
    return clean.length ? JSON.stringify(clean) : '';
  }

  /* Every side the record has, in order, each with its songs numbered.
   *
   * `i` is the index in the RAW array and `pos` is the number printed on the
   * sleeve. They are different things: the first two consumers that conflated
   * them would have deleted the wrong song. Every handler addresses a track by
   * `i`; only the eye uses `pos`. */
  function tracksBySide(list, discCount) {
    const all = (list || []).map(function (t, i) { return { t: t, i: i }; });
    return sideLettersFor(discCount).map(function (letter) {
      return {
        disc: discOfSide(letter),
        letter: letter,
        // liked_at is added only when present, matching the stored shape's
        // own "absent, never falsy" rule — every consumer here already tests
        // truthiness, so this view object does not need to invent a false.
        tracks: all
          .filter(function (x) { return x.t.side === letter; })
          .map(function (x, k) {
            const out = { i: x.i, pos: k + 1, title: x.t.title };
            if (x.t.liked_at) out.liked_at = x.t.liked_at;
            return out;
          }),
      };
    });
  }

  function likedTracks(list) {
    return (list || [])
      .map(function (t, i) { return { t: t, i: i }; })
      .filter(function (x) { return x.t.liked_at; })
      .map(function (x) {
        return { i: x.i, title: x.t.title, liked_at: x.t.liked_at };
      });
  }

  /* The sides that actually hold songs, so lowering the disc count can refuse
   * rather than silently delete. Data loss must be an explicit act. */
  function sidesWithTracks(list) {
    const seen = [];
    (list || []).forEach(function (t) {
      if (t && t.side && seen.indexOf(t.side) === -1) seen.push(t.side);
    });
    return seen.sort();
  }

  /* What the card draws: sleeves peeking out behind the cover, and segments in
   * the spine down its left edge. Both are zero for a single disc — a mark on
   * every card in the grid is furniture the eye stops seeing. */
  function discMarks(discCount) {
    const n = Math.max(1, Number(discCount) || 1);
    return n > 1 ? { sleeves: n - 1, segments: n } : { sleeves: 0, segments: 0 };
  }

  /* Turn pasted text into titles — the shapes a tracklist arrives in when it
   * is copied off a sleeve, a wiki or a shop listing. */
  function parsePastedTracklist(text) {
    return String(text || '')
      .split(/\r?\n/)
      .map(function (line) {
        return line
          // 'A1 ', 'A1. ', 'B2 - ' — a side label glued to a number
          .replace(/^\s*[A-F]\s?\d{1,2}\s*[.)\-–]?\s+/i, '')
          // '1. ', '02 - ', '3) ' — a bare number, but ONLY with punctuation
          // after it, so a title like '10 Years Gone' survives
          .replace(/^\s*\d{1,2}\s*[.)\-–]\s*/, '')
          // ' 5:32', ' (4:40)', ' [3:09]'
          .replace(/\s+[\[(]?\d{1,2}:\d{2}[\])]?\s*$/, '')
          .trim();
      })
      .filter(Boolean);
  }

  return { parseTracks, serializeTracks, sideLettersFor, discOfSide,
           tracksBySide, likedTracks, sidesWithTracks, discMarks,
           parsePastedTracklist };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylTracks;
