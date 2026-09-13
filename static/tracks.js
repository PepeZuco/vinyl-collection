/* The tracks column's parse/serialize rules.
 *
 * Tracks are stored as JSON: [{side, title, artist?, liked_at?}]. The side LETTER
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
 * artist is only ever set on a compilation: it names WHICH of the record's
 * semicolon-separated artists played this song. The NAME is stored, not an
 * index into the artist field — an index silently points at the wrong person
 * the first time the artist list is reordered. Absent means unassigned, the
 * same "absent, never falsy" shape liked_at uses. Nothing here checks the name
 * against the record's artist list: the picker in the form is what keeps the
 * two in step, and a PUT that sends tracks alone must not be rejected because
 * the artist column moved in some other request.
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

  /* How a side is named wherever it is named away from the tracklist — the
   * drawer's history, the calendar's day card. A single LP says only the side,
   * the way the tracklist tab draws no disc chrome for one disc; past that the
   * disc leads, because side C alone does not say which record to pull out.
   * A track with no side letter has no label: the callers then print the song
   * on its own rather than a header naming nothing. */
  function sideLabel(letter, discCount) {
    const side = String(letter || '').toUpperCase().slice(0, 1);
    if (!side || LETTERS.indexOf(side) === -1) return '';
    const n = Math.max(1, Number(discCount) || 1);
    return n < 2 ? 'Side ' + side
                 : 'Disc ' + discOfSide(side) + ' \u00b7 Side ' + side;
  }

  /* Total: this column is read by six consumers straight off /api/records, and
   * a record whose value will not parse — a hand-edited PUT, a CSV from
   * somewhere else — must come back empty rather than take the grid down.
   *
   * Names are capitalised HERE, on the way out, rather than only where a title
   * is typed. The column holds tracklists that predate that rule and ones no
   * field ever saw — written by a scan, an import, a PUT — and a sleeve should
   * read the same whichever wrote it. One place to do it also means the
   * tracklist tab, the timeline, the drawer and search cannot disagree about a
   * song's name, and the edit form (which loads through here) shows the
   * capitals, so the next save persists what was already on screen. */
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
          title: typeof t.title === 'string' ? capitalizeName(t.title) : '',
        };
        const artist = capitalizeName(String(t.artist || '').trim());
        if (artist) out.artist = artist;
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
        const artist = String(t.artist || '').trim();
        if (artist) out.artist = artist;
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
            if (x.t.artist) out.artist = x.t.artist;
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

  /* How many songs are credited to this name, so removing an artist row can
   * refuse rather than silently unassign them — the same trade sidesWithTracks
   * makes for the disc count. Matched exactly apart from surrounding space:
   * two artists on one sleeve can differ only by case ("will.i.am"), and
   * folding them together here would reassign somebody else's song. */
  function artistsInUse(list, name) {
    const want = String(name || '').trim();
    if (!want) return 0;
    return (list || []).filter(function (t) {
      return t && String(t.artist || '').trim() === want;
    }).length;
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

  /* The only sizes a sleeve is cut to, in inches. A value from outside this
   * list is not a size we can draw — see sizeInches(). */
  const SIZES = [7, 10, 12];

  function sizeInches(size) {
    const n = Number(size);
    return SIZES.indexOf(n) === -1 ? null : n;
  }

  /* What the card says about the object itself: how many discs, how many
   * inches. The plain single 12" used to be left blank on the grounds that it
   * is what most of the shelf is — but then a bare corner had to be read as
   * "one 12-inch disc", which is a thing you have to know rather than a thing
   * the card says, and it looked the same as a record whose size nobody had
   * filled in. So every known size is spelled out. An unknown size is still
   * silent rather than guessing 12", the same trade the Info tab's Format cell
   * already makes. */
  function formatTag(discCount, size) {
    const n = Math.max(1, Number(discCount) || 1);
    const inches = sizeInches(size);
    if (n > 1 && inches) return n + ' \u00d7 ' + inches + '"';
    if (n > 1)           return n + ' discs';
    if (inches)          return inches + '"';
    return '';
  }

  /* The sides grouped by the disc they are on.
   *
   * tracksBySide returns a flat run of sides because that is how a tracklist
   * is read; this is the same sides nested, because the tracklist DRAWS a rail
   * down the full height of a disc and a rail has to know where the disc ends,
   * not just where it starts. The side objects are passed through untouched —
   * there is one place that decides what a side looks like, and it is up
   * there. */
  function discGroups(list, discCount) {
    const groups = [];
    tracksBySide(list, discCount).forEach(function (side) {
      let g = groups[groups.length - 1];
      if (!g || g.disc !== side.disc) {
        g = { disc: side.disc, letters: [], sides: [], songs: 0 };
        groups.push(g);
      }
      g.letters.push(side.letter);
      g.sides.push(side);
      g.songs += side.tracks.length;
    });
    return groups;
  }

  /* The numbers behind the discs drawn at the top of the Tracks tab.
   *
   * `sides` is what the record physically HAS (two per disc), not the sides
   * that happen to hold songs: a half-entered tracklist is still a double LP,
   * and counting only the filled sides would redraw the record as you typed.
   * `size` is null rather than 12 when unknown — the drawing needs a real
   * measurement to scale a circle by, and an invented one would print a 7"
   * single at the width of an LP. */
  function formatSummary(list, discCount, size) {
    const discs = Math.max(1, Number(discCount) || 1);
    return {
      discs: discs,
      size: sizeInches(size),
      sides: discs * 2,
      songs: (list || []).length,
    };
  }

  /* Where a needle sits IN THE STORED TITLE, or null.
   *
   * The range is measured against the title as written, never against a folded
   * copy of it, because the folding is not one character for one character:
   * relax() DELETES apostrophes, so 'greatest' in "Bill Withers’ Greatest Hits"
   * starts at 13 folded and at 14 stored. Highlighting with the folded index
   * would mark one letter short of the match on every title carrying one.
   *
   * So the title is folded a character at a time, remembering where each
   * surviving character came from. That is only valid because relax() has no
   * rule that spans characters — NFD decomposes one character, the marks and
   * apostrophes it drops are single characters — and it is why the folding
   * comes in as an argument rather than being done to the whole string here.
   *
   * The needle is expected lower-cased and already folded, which is the shape
   * the filter model has in hand by the time it asks. */
  function titleHit(title, needle, relax) {
    const fold = relax || function (s) { return s; };
    let folded = '';
    const from = [];                 // folded position -> position in title
    for (let i = 0; i < title.length; i++) {
      const piece = fold(title.charAt(i).toLowerCase());
      for (let k = 0; k < piece.length; k++) { folded += piece.charAt(k); from.push(i); }
    }
    const at = folded.indexOf(needle);
    if (at === -1) return null;
    return [from[at], from[at + needle.length - 1] + 1];
  }

  /* The tracklist a card draws over its cover while the search box is looking
   * at songs, with the matches marked.
   *
   * Whole sides come back, not just the songs that matched: the overlay's job
   * is to say WHERE on the record the song is, and a bare list of hits with no
   * record around them answers a different question. Each side counts its own
   * hits so the card can drop the ones that have none when the artwork is
   * uncovered, without counting them again in the template.
   *
   * A side the record has but has no songs on is left out — there is nothing
   * to draw under its header. That is the one place this differs from
   * tracksBySide, which reports the sides the OBJECT has because a half-typed
   * tracklist is still a double LP. */
  function matchingTracks(list, needle, discCount, relax) {
    const want = String(needle == null ? '' : needle).toLowerCase();
    const sides = tracksBySide(list, discCount)
      .filter(function (side) { return side.tracks.length; })
      .map(function (side) {
        let hits = 0;
        const tracks = side.tracks.map(function (t) {
          const out = Object.assign({}, t);
          const hit = want ? titleHit(t.title, want, relax) : null;
          // absent, never null — the same shape liked_at and artist use, so
          // every reader can test truthiness and be right
          if (hit) { out.hit = hit; hits++; }
          return out;
        });
        return { letter: side.letter, label: sideLabel(side.letter, discCount),
                 hits: hits, tracks: tracks };
      });
    return {
      sides: sides,
      hits: sides.reduce(function (n, s) { return n + s.hits; }, 0),
    };
  }

  /* A name the way it is written on a sleeve: every word starts capital.
   *
   * Only the FIRST letter of each word is touched. Lowercasing the rest would
   * rewrite the names that are meant to be read exactly as they are typed — an
   * acronym (DNA), an initialled band (R.E.M.), a stylised stage name
   * (will.i.am) — and a tracklist full of "Dna" is worse than one full of
   * "dna". A word opening on a digit or a bracket is left alone by the same
   * rule: there is no first letter to raise.
   *
   * The gap is captured and put back rather than joined over, so the spacing a
   * title was typed with survives — a double space, a newline — and this
   * cannot quietly re-flow text on its way through. Trimming belongs to
   * serializeTracks, which already does it.
   *
   * Applied where a human ENTERS a title (the song-title field, the paste box)
   * and again in parseTracks, which is what covers the tracklists no field
   * ever saw — a Spotify scan, an imported CSV, a hand-written PUT. Still not
   * in serializeTracks: everything reaching it has come through one of those
   * two, so a save has nothing left to rewrite. */
  function capitalizeName(name) {
    return String(name == null ? '' : name)
      .replace(/(^|\s)(\S)/g, function (m, gap, first) { return gap + first.toUpperCase(); });
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

  return { parseTracks, serializeTracks, sideLettersFor, discOfSide, sideLabel,
           tracksBySide, likedTracks, sidesWithTracks, formatTag, matchingTracks,
           discGroups, formatSummary, capitalizeName,
           parsePastedTracklist, artistsInUse };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylTracks;
