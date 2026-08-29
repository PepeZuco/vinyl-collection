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

  function defaultQuery() {
    return {
      text: '',
      fields: Object.assign({}, DEFAULT_FIELDS),
      ownership: 'owned',  // 'owned' | 'wishlist' | 'all'
      facets: {},          // id -> array of allowed values; absent = no constraint
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

    const text = (q.text || '').trim().toLowerCase();
    if (text) {
      const fields = q.fields || DEFAULT_FIELDS;
      if (haystack(record, fields, deps).indexOf(text) === -1) return false;
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

  return { DEFAULT_FIELDS, FACETS, facetById, defaultQuery,
           matches, filterRecords, facetValues, chipsFor };
})(typeof module !== 'undefined' && module.exports
     ? require('./grouping.js') : VinylGrouping);

if (typeof module !== 'undefined' && module.exports) module.exports = VinylFilters;
