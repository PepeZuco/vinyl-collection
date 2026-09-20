/* The one filter model, shared by every surface.
 *
 * The collection and the statistics table each carried their own copy of this
 * — separate search boxes, genre pickers, condition pickers and chip rows,
 * with separate state that never synced. Filtering the collection to Jazz and
 * switching to statistics silently showed all genres again.
 *
 * Genre and condition were once two hardcoded branches. They are entries in a
 * registry now, which is what lets the bar offer decade, country, shop and
 * cleaning without another branch each, and lets every active filter name
 * itself in a chip — so a shelf can always be read back as a sentence.
 *
 * Two rules make the model unambiguous, and both come from bugs in what it
 * replaced:
 *
 *   An absent facet means "no constraint"; a list means "exactly these".
 *     The old code inferred "unfiltered" from set sizes — `size > 0` for
 *     genres, `size < ALL` for conditions — so the two facets disagreed about
 *     what an empty selection meant, and neither could say "nothing ticked".
 *
 *   '' is a value, not an absence.
 *     The old genre list was built with .filter(Boolean) and then queried with
 *     has(r.genre || ''), so a record with no genre matched nothing and no
 *     combination of controls could reach it. Three wishlist records were
 *     invisible in the deployed app.
 *
 * Sorting deliberately stays out: the shelf sorts within crates and the table
 * sorts by column, and those are genuinely different jobs. So does display —
 * this reports raw values and counts, and the page decides what to call them.
 *
 * Loaded as a plain script in the browser, where `const VinylFilters` lands in
 * the global lexical scope for the inline script below it; required as a module
 * by the tests. */

const VinylFilters = (function (grouping) {

  /* Which fields the search box reads. Artist and album are what people
   * actually search; the rest are opt-in because matching on them surprises
   * you more often than it helps. */
  const DEFAULT_FIELDS = {
    artist: true, album: true, genre: false, notes: false, bought_at: false,
    song: false,
  };

  const DAY_MS = 86400000;
  const RECENT_DAYS = 30;    // still in rotation
  const STALE_DAYS = 180;    // gathering dust

  /* 'YYYY-MM-DD' -> days since the epoch, through Date.UTC from the calendar
   * parts rather than Date.parse, so the arithmetic is timezone-proof. */
  function dayNumber(day) {
    const [y, m, d] = day.split('-').map(Number);
    return Math.floor(Date.UTC(y, m - 1, d) / DAY_MS);
  }

  function hasCleaning(r) {
    try {
      const parsed = JSON.parse(r.cleaned_dates || '[]');
      return Array.isArray(parsed) && parsed.some(Boolean);
    } catch (e) {
      return false;
    }
  }

  /* The dimensions the bar can narrow by, in the order chips appear.
   *
   * `valueOf` returns the single bucket a record falls in — '' for "not set",
   * which is a bucket like any other rather than a record that cannot be
   * reached. Labels live on the page, not here: country needs a name table and
   * condition needs sentence case, and neither is this model's business. */
  const FACETS = [
    { id: 'genre',     label: 'Genre',     valueOf: r => r.genre || '' },
    { id: 'condition', label: 'Condition', valueOf: r => r.condition || '' },
    { id: 'decade',    label: 'Decade',    valueOf: r => (r.year ? String(r.year).slice(0, 3) + '0s' : '') },
    { id: 'country',   label: 'Country',   valueOf: r => r.country || '' },
    { id: 'store',     label: 'Bought at', valueOf: r => r.bought_where || '' },
    { id: 'cleaning',  label: 'Cleaning',  valueOf: r => (hasCleaning(r) ? 'cleaned' : 'never') },
    /* The only facet measured against a date, so it reads one off deps. With
     * no date to measure against every record reads as never played, which is
     * the honest answer rather than a guessed one.
     *
     * The last play comes from VinylGrouping rather than a rule of its own:
     * this used to take the leading YYYY-MM-DD off the raw string, which
     * disagreed with health.js about an offset-bearing stamp near midnight and
     * about a date the calendar cannot hold. One rule, so the filter bar's
     * count and the Insights tile cannot describe the same record differently. */
    { id: 'played',    label: 'Last played',
      valueOf: (r, deps) => {
        const day = grouping.momentOf(grouping.lastPlayed(r)).day;
        const today = deps && deps.today;
        if (!day || !today) return 'never';
        const age = dayNumber(today) - dayNumber(day);
        if (age <= RECENT_DAYS) return 'recent';
        if (age <= STALE_DAYS) return 'months';
        return 'stale';
      } },
  ];

  function facetById(id) {
    return FACETS.find(f => f.id === id) || null;
  }

  /* The search box, minus the keys that are hard to reach.
   *
   * A shelf of Brazilian and Spanish records could not be searched from a
   * keyboard: Milanés, Chitãozinho, Perfídia. And "Bill Withers’ Greatest
   * Hits" carries the curly apostrophe, so even typing the punctuation
   * correctly — the straight one, next to Enter — missed the record.
   *
   * NFD splits an accented letter into its base plus a combining mark, so
   * dropping the marks leaves the bare letter; every apostrophe the world
   * writes goes with them. Applied to BOTH sides, which is what makes it a
   * relaxation rather than a rewrite: 'milanes' reaches Milanés and 'Milanés'
   * still reaches itself.
   *
   * Nothing else is touched. Hyphens, dots and ampersands stay, because
   * folding those makes a query mean something the person did not type. */
  const MARKS = /[\u0300-\u036f]/g;
  const APOSTROPHES = /['\u2018\u2019\u02bc\u0060\u00b4]/g;

  function relax(text) {
    return text.normalize('NFD').replace(MARKS, '').replace(APOSTROPHES, '');
  }

  /* Typo tolerance: a query word the substring test missed may still be a near
   * miss of a word in the record ("Picture Vook" for "Picture Book").
   *
   * Only words the substring test already failed on come here, so a correctly
   * typed query finds exactly what it always did — this can add records, never
   * remove one. The allowance grows with the word: a short word must be exact,
   * because one edit turns almost any 3-letter word into another, and a long
   * one may be two edits off. */
  const WORD = /[\p{L}\p{N}]+/gu;

  function editsAllowed(len) {
    return len < 4 ? 0 : len < 8 ? 1 : 2;
  }

  /* Edit distance where swapping two neighbours costs one edit — the most
   * common slip at a keyboard ("Pcitrue"). Bails out early once every cell in a
   * row is past `max`, since this runs against every word of every record. */
  function editDistance(a, b, max) {
    if (Math.abs(a.length - b.length) > max) return max + 1;
    let prev2 = null;
    let prev = [];
    for (let j = 0; j <= b.length; j++) prev.push(j);
    for (let i = 1; i <= a.length; i++) {
      const cur = [i];
      let best = i;
      for (let j = 1; j <= b.length; j++) {
        const cost = a[i - 1] === b[j - 1] ? 0 : 1;
        let d = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
        if (prev2 && i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
          d = Math.min(d, prev2[j - 2] + 1);
        }
        cur.push(d);
        if (d < best) best = d;
      }
      if (best > max) return max + 1;
      prev2 = prev;
      prev = cur;
    }
    return prev[b.length];
  }

  /* Whether every word of `text` finds a word in `hay` within its allowance.
   * A word may match the start of a longer word, so the search keeps working
   * while the last word is still being typed. */
  function fuzzyMatch(text, hay) {
    const wanted = text.match(WORD) || [];
    if (!wanted.length) return false;
    const have = hay.match(WORD) || [];
    return wanted.every(w => {
      const max = editsAllowed(w.length);
      if (hay.indexOf(w) !== -1) return true;
      if (!max) return false;
      return have.some(h =>
        editDistance(w, h, max) <= max ||
        (h.length > w.length && editDistance(w, h.slice(0, w.length), max) <= max));
    });
  }

  function defaultQuery() {
    return {
      text: '',
      fields: Object.assign({}, DEFAULT_FIELDS),
      ownership: 'owned',  // 'owned' | 'wishlist'
      facets: {},          // id -> array of allowed values; absent = no constraint
      loose: true,         // fold accents and apostrophes away before comparing
      typos: true,         // forgive a slip or two in each word
    };
  }

  /* The text a record offers to the search box, given which fields are on. */
  function haystack(record, fields, deps) {
    const parts = [];
    // Two fields read the tracks column; parse it once, since this runs for
    // every record on every keystroke.
    const tracks = (fields.artist || fields.song)
      ? ((deps && deps.parseTracks) || (() => []))(record.tracks)
      : [];
    if (fields.artist) {
      parts.push(record.artist || '');
      // A compilation credits each song to one of its artists, and a guest who
      // plays on a single track is often missing from the artist column
      // entirely — the song is then the only place their name appears. This
      // sits under the artist field rather than the song field because "who is
      // on this record" is one question to the person typing.
      parts.push(tracks.map(t => (t && t.artist) || '').join(' '));
    }
    if (fields.album)     parts.push(record.album_name || '');
    if (fields.genre)     parts.push(record.genre || '');
    if (fields.bought_at) parts.push(record.bought_where || '');
    if (fields.notes) {
      const parse = (deps && deps.parseNotes) || (() => []);
      parts.push(parse(record.notes).map(n => (n && n.text) || '').join(' '));
    }
    if (fields.song) {
      parts.push(tracks.map(t => (t && t.title) || '').join(' '));
    }
    return parts.join(' ').toLowerCase();
  }

  /* Whether a record passes everything except the named facet. Used both by
   * matches() (skipping nothing) and by facetValues (skipping the facet whose
   * own list is being built). */
  function matchesExcept(record, query, deps, exceptId) {
    const q = query || defaultQuery();

    if (q.ownership === 'owned' && !record.have_it) return false;
    if (q.ownership === 'wishlist' && record.have_it) return false;

    const facets = q.facets || {};
    for (const facet of FACETS) {
      if (facet.id === exceptId) continue;
      const allowed = facets[facet.id];
      if (!allowed) continue;                     // absent means no constraint
      if (allowed.indexOf(facet.valueOf(record, deps)) === -1) return false;
    }

    const loose = q.loose !== false;   // absent reads as on, like the default
    let text = (q.text || '').trim().toLowerCase();
    if (loose) text = relax(text);
    // A query of nothing but apostrophes relaxes away to '', and an empty
    // needle sits inside every haystack — so without this it would silently
    // "match" the whole collection while looking like a typo that found
    // something. An empty query is no constraint, however it got empty.
    if (text) {
      const fields = q.fields || DEFAULT_FIELDS;
      const hay = haystack(record, fields, deps);
      const seen = loose ? relax(hay) : hay;
      if (seen.indexOf(text) === -1) {
        const typos = q.typos !== false;   // absent reads as on, like the default
        if (!typos || !fuzzyMatch(text, seen)) return false;
      }
    }
    return true;
  }

  function matches(record, query, deps) {
    return matchesExcept(record, query, deps, null);
  }

  function filterRecords(records, query, deps) {
    return (records || []).filter(r => matches(r, query, deps));
  }

  /* The values one facet can offer, with the count each would leave on screen.
   *
   * Counted with every OTHER part of the query applied but not this facet's
   * own: narrowing a facet by its own selection would hide the values you have
   * not ticked yet, so the list would shrink as you used it. A value appears
   * only if some record is in it, so the picker never offers a bucket that
   * would match nothing — and never omits one that records are hiding in.
   * '' sorts last: it is the leftover bucket, not a value. */
  function facetValues(records, query, facetId, deps) {
    const facet = facetById(facetId);
    if (!facet) return [];
    const counts = new Map();
    (records || []).forEach(r => {
      if (!matchesExcept(r, query, deps, facetId)) return;
      const v = facet.valueOf(r, deps);
      counts.set(v, (counts.get(v) || 0) + 1);
    });
    return [...counts.entries()]
      .map(([value, count]) => ({ value, count }))
      .sort((a, b) =>
        (a.value === '') - (b.value === '') ||
        b.count - a.count ||
        String(a.value).localeCompare(String(b.value)));
  }

  /* One chip per constrained facet, in registry order. A facet ticked to
   * nothing still gets a chip: an empty shelf must say why it is empty. */
  function chipsFor(query) {
    const facets = (query && query.facets) || {};
    return FACETS
      .filter(f => !!facets[f.id])
      .map(f => ({ id: f.id, label: f.label, values: facets[f.id] }));
  }

  return { DEFAULT_FIELDS, FACETS, facetById, defaultQuery, relax,
           matches, filterRecords, facetValues, chipsFor };
})(typeof module !== 'undefined' && module.exports
     ? require('./grouping.js') : VinylGrouping);

if (typeof module !== 'undefined' && module.exports) module.exports = VinylFilters;
