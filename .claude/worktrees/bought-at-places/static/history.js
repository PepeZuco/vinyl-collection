'use strict';

/* The collection's growth, as frames for the History tab's bar chart race.
 *
 * One frame per day the collection was bought on — days with no purchase get
 * no frame, so the timeline hops between shopping trips rather than crawling
 * through the ~96% of calendar days where nothing changed.
 *
 * Pure functions of the record list, kept out of index.html so they can be
 * tested directly (tests/test_history.js).
 *
 * Loaded as a plain script in the browser AFTER grouping.js, whose momentOf
 * this depends on; required as a module by the tests. */

const VinylHistory = (function (grouping) {

  /* Owned and dated. Every have_it record in the collection carries a
   * bought_date and every undated one is a wishlist item, so this loses
   * nothing owned — and it makes the final frame's counts equal the
   * Statistics tab's genre chart exactly.
   *
   * Anything unparseable is dropped rather than bucketed: momentOf already
   * returns empty for a stamp the calendar could not hold, and one bad row
   * must not take the whole tab down. */
  function inScope(r) {
    return !!r.have_it && !!grouping.momentOf(r.bought_date).day;
  }

  function buildTimeline(records) {
    const scoped = (records || []).filter(inScope);
    if (!scoped.length) return [];

    /* Oldest purchase first, ties broken by id — so a bar's cover strip is in
     * a stable order and never reshuffles between frames. */
    scoped.sort(function (a, b) {
      const at = grouping.momentOf(a.bought_date).at;
      const bt = grouping.momentOf(b.bought_date).at;
      if (at !== bt) return at < bt ? -1 : 1;
      return (Number(a.id) || 0) - (Number(b.id) || 0);
    });

    const byDay = new Map();
    for (const r of scoped) {
      const day = grouping.momentOf(r.bought_date).day;
      if (!byDay.has(day)) byDay.set(day, []);
      byDay.get(day).push(r);
    }

    const cumulative = new Map();   // genre -> records so far, oldest first
    let prevRank = new Map();       // genre -> its row index in the last frame
    const frames = [];
    let total = 0;

    [...byDay.keys()].sort().forEach(function (day, index) {
      const added = new Map();
      for (const r of byDay.get(day)) {
        const g = (r.genre || '').trim();
        if (!cumulative.has(g)) cumulative.set(g, []);
        if (!added.has(g)) added.set(g, []);
        cumulative.get(g).push(r);
        added.get(g).push(r);
        total++;
      }

      /* Only genres that have appeared get a bar — no row sits at zero
       * waiting its turn. */
      const bars = [...cumulative.entries()].map(function (entry) {
        const genre = entry[0], recs = entry[1];
        return {
          genre: genre,
          label: genre || 'unknown',
          count: recs.length,
          records: recs.slice(),
          added: (added.get(genre) || []).slice(),
        };
      });

      /* Ties are broken by who held the higher row last frame, not by name.
       * Genres sit level for long stretches, and an alphabetical tie-break
       * makes them trade rows every time one gains and the other catches up —
       * a swap animation that means nothing. Holding position means a swap on
       * screen is always a real overtake. A genre with no previous rank sorts
       * last among equals, so an entrant slots in below the incumbents. */
      bars.sort(function (a, b) {
        if (a.count !== b.count) return b.count - a.count;
        const ar = prevRank.has(a.genre) ? prevRank.get(a.genre) : Infinity;
        const br = prevRank.has(b.genre) ? prevRank.get(b.genre) : Infinity;
        if (ar !== br) return ar - br;
        return a.label < b.label ? -1 : a.label > b.label ? 1 : 0;
      });

      prevRank = new Map(bars.map(function (bar, i) { return [bar.genre, i]; }));
      frames.push({ day: day, index: index, total: total, bars: bars });
    });

    return frames;
  }

  return { buildTimeline: buildTimeline };
})(typeof module !== 'undefined' && module.exports
     ? require('./grouping.js') : VinylGrouping);

if (typeof module !== 'undefined' && module.exports) module.exports = VinylHistory;
