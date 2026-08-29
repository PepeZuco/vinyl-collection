/* The collection's state, for the row that heads the Insights tab.
 *
 * That row used to be two rating averages flanking a record count. The
 * averages said less than the per-genre dumbbell below them already said, and
 * nothing on the page answered the questions you actually have about a
 * collection: how much of it is in rotation, and how much of it is overdue a
 * clean. 53 of 129 owned records had never been cleaned and the app had no way
 * to tell you.
 *
 * Everything here describes the records it is handed, which is whatever the
 * shared query selected — so filtering to Jazz reports on Jazz. The usage
 * figures narrow further to the records you actually own: a wishlist record
 * cannot have been played or cleaned, and counting it as overdue would be a
 * lie about a record nobody has yet.
 *
 * Loaded as a plain script in the browser, where `const VinylHealth` lands in
 * the global lexical scope for the inline script below it; required as a module
 * by the tests. */

const VinylHealth = (function (grouping) {

  const DAY_MS = 86400000;

  /* 'YYYY-MM-DD' -> days since the epoch. Built through Date.UTC from the
   * calendar parts rather than Date.parse, so the arithmetic is timezone-proof
   * — two stamps on the same local day must be the same number of days old
   * wherever the browser happens to be. */
  function dayNumber(day) {
    const [y, m, d] = day.split('-').map(Number);
    return Math.floor(Date.UTC(y, m - 1, d) / DAY_MS);
  }

  function monthKey(day) {
    return day.slice(0, 7);
  }

  /* The `months` month keys ending at `today`'s month, oldest first. Built by
   * walking calendar months rather than subtracting days, so it does not drift
   * across months of different lengths. */
  function monthWindow(today, months) {
    const [y, m] = today.split('-').map(Number);
    const keys = [];
    for (let back = months - 1; back >= 0; back--) {
      const d = new Date(Date.UTC(y, m - 1 - back, 1));
      keys.push(d.getUTCFullYear() + '-' + String(d.getUTCMonth() + 1).padStart(2, '0'));
    }
    return keys;
  }

  function collectionHealth(records, opts) {
    const o = opts || {};
    const today = o.today;
    const withinDays = o.withinDays === undefined ? 30 : o.withinDays;
    const months = o.months === undefined ? 8 : o.months;
    const all = records || [];
    const owned = all.filter(r => !!r.have_it);

    let plays = 0, rotation = 0, cleanedAtLeastOnce = 0;
    const cutoff = today ? dayNumber(today) - withinDays : null;

    owned.forEach(r => {
      plays += Number(r.play_count) || 0;

      const last = grouping.momentOf(grouping.lastPlayed(r)).day;
      if (last && cutoff !== null && dayNumber(last) >= cutoff) rotation++;

      let cleanings = [];
      try {
        const parsed = JSON.parse(r.cleaned_dates || '[]');
        if (Array.isArray(parsed)) cleanings = parsed;
      } catch (e) { /* a malformed column reads as never cleaned */ }
      if (cleanings.some(d => grouping.momentOf(d).day)) cleanedAtLeastOnce++;
    });

    const window = today ? monthWindow(today, months) : [];
    const counts = new Map(window.map(k => [k, 0]));
    owned.forEach(r => {
      const day = grouping.momentOf(r.bought_date).day;
      if (!day) return;                         // undated, or a stamp no calendar holds
      const key = monthKey(day);
      if (counts.has(key)) counts.set(key, counts.get(key) + 1);
    });

    return {
      total: all.length,
      owned: owned.length,
      plays,
      rotation,
      cleanedAtLeastOnce,
      neverCleaned: owned.length - cleanedAtLeastOnce,
      adds: window.map(month => ({ month, n: counts.get(month) })),
    };
  }

  return { collectionHealth };
})(typeof module !== 'undefined' && module.exports
     ? require('./grouping.js') : VinylGrouping);

if (typeof module !== 'undefined' && module.exports) module.exports = VinylHealth;
