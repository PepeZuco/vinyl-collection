/* The one filter model, shared by every surface.
 *
 * The collection and the statistics table each carried their own copy of this
 * — separate search boxes, genre pickers, condition pickers and chip rows,
 * with separate state that never synced. Filtering the collection to Jazz and
 * switching to statistics showed all genres again, silently.
 *
 * Two rules make the model unambiguous, and both come from bugs in what it
 * replaces:
 *
 *   null means "no constraint"; a list means "exactly these".
 *     The old code inferred "unfiltered" from set sizes — `size > 0` for
 *     genres, `size < ALL` for conditions — so the two facets disagreed about
 *     what an empty selection meant, and neither could say "nothing ticked".
 *
 *   '' is a value, not an absence.
 *     The old genre universe was built with .filter(Boolean) and then queried
 *     with `has(r.genre || '')`, so a record with no genre matched nothing and
 *     no combination of controls could reach it. Three wishlist records were
 *     invisible in the deployed app.
 *
 * Sorting deliberately stays out: the shelf sorts within crates and the table
 * sorts by column, and those are genuinely different jobs.
 *
 * Loaded as a plain script in the browser, where `const VinylFilters` lands in
 * the global lexical scope for the inline script below it; required as a module
 * by the tests. */

const VinylFilters = (function () {

  /* Which fields the search box reads. Artist and album are what people
   * actually search; the rest are opt-in because matching on them surprises
   * you more often than it helps. */
  const DEFAULT_FIELDS = {
    artist: true, album: true, genre: false, notes: false, bought_at: false,
  };

  function defaultQuery() {
    return {
      text: '',
      fields: Object.assign({}, DEFAULT_FIELDS),
      genres: null,        // null | array of genre values, '' meaning "no genre"
      conditions: null,    // null | array of '' | 'new' | 'used'
      ownership: 'owned',  // 'owned' | 'wishlist' | 'all'
    };
  }

  /* The text a record offers to the search box, given which fields are on. */
  function haystack(record, fields, deps) {
    const parts = [];
    if (fields.artist)    parts.push(record.artist || '');
    if (fields.album)     parts.push(record.album_name || '');
    if (fields.genre)     parts.push(record.genre || '');
    if (fields.bought_at) parts.push(record.bought_where || '');
    if (fields.notes) {
      const parse = (deps && deps.parseNotes) || (() => []);
      parts.push(parse(record.notes).map(n => (n && n.text) || '').join(' '));
    }
    return parts.join(' ').toLowerCase();
  }

  function matches(record, query, deps) {
    const q = query || defaultQuery();

    if (q.ownership === 'owned' && !record.have_it) return false;
    if (q.ownership === 'wishlist' && record.have_it) return false;

    if (q.genres && q.genres.indexOf(record.genre || '') === -1) return false;
    if (q.conditions && q.conditions.indexOf(record.condition || '') === -1) return false;

    const text = (q.text || '').trim().toLowerCase();
    if (text) {
      const fields = q.fields || DEFAULT_FIELDS;
      if (haystack(record, fields, deps).indexOf(text) === -1) return false;
    }
    return true;
  }

  function filterRecords(records, query, deps) {
    return (records || []).filter(r => matches(r, query, deps));
  }

  /* Every genre a picker should offer for this set of records.
   *
   * '' is included when — and only when — some record actually has no genre,
   * so the picker never shows a bucket that would match nothing, and never
   * omits one that records are hiding in. Building this list with
   * .filter(Boolean), as the old code did, is what made three records
   * unreachable. It sorts last: it is the leftover bucket, not a genre. */
  function genreUniverse(records) {
    const named = new Set();
    let anyBlank = false;
    (records || []).forEach(r => {
      const g = r.genre || '';
      if (g) named.add(g); else anyBlank = true;
    });
    const list = [...named].sort();
    if (anyBlank) list.push('');
    return list;
  }

  return { DEFAULT_FIELDS, defaultQuery, matches, filterRecords, genreUniverse };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylFilters;
