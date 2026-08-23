'use strict';

/* Crate grouping for the collection's group view.
 *
 * Group view has no field picker of its own — it buckets by whatever "Sort by"
 * is already set to. These rules are pure functions of a record, kept out of
 * index.html so they can be tested directly (tests/test_grouping.js).
 *
 * Loaded as a plain script in the browser, where `const VinylGrouping` lands in
 * the global lexical scope for the inline script below it; required as a module
 * by the tests. */

const VinylGrouping = (function () {

  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
                  'July', 'August', 'September', 'October', 'November', 'December'];

  /* The most recent play, as the ISO string it is stored as, or '' for a record
   * that has never been played. play_dates is a JSON array written by the page;
   * anything unparseable counts as never played rather than throwing mid-render. */
  function lastPlayed(r) {
    let dates;
    try { dates = JSON.parse(r.play_dates || '[]'); }
    catch { return ''; }
    if (!Array.isArray(dates)) return '';
    /* ISO strings sort lexicographically, so max() needs no date parsing. */
    return dates.filter(d => typeof d === 'string' && d).sort().pop() || '';
  }

  /* The average of the ratings actually given — a record only Pepe rated averages
   * to his score, not to half of it. */
  function avgRating(r) {
    const scores = [Number(r.my_rating) || 0, Number(r.wife_rating) || 0].filter(x => x > 0);
    return scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;
  }

  /* The crate a record belongs to for a given sort field: an id to group on and
   * a label to show. Every rule is monotone in the sort key, so once the list is
   * sorted the records of a crate are already adjacent. */
  function bucketOf(r, sortBy) {
    switch (sortBy) {
      case 'bought_date': {
        if (!r.bought_date) return { id: 'nodate', label: 'No date' };
        const [year, month] = String(r.bought_date).split('-');
        return { id: year + '-' + month, label: MONTHS[Number(month) - 1] + ' ' + year };
      }
      case 'last_played': {
        const played = lastPlayed(r);
        if (!played) return { id: 'neverplayed', label: 'Never played' };
        const [year, month] = played.split('-');
        return { id: year + '-' + month, label: MONTHS[Number(month) - 1] + ' ' + year };
      }
      case 'artist': {
        const artist = (r.artist || '').trim();
        if (!artist) return { id: 'noartist', label: 'Unknown artist' };
        return { id: artist.toLowerCase(), label: artist };
      }
      case 'album_name': {
        const first = (r.album_name || '').trim().charAt(0).toUpperCase();
        const letter = /[A-Z]/.test(first) ? first : '#';
        return { id: letter, label: letter };
      }
      case 'year': {
        if (!r.year) return { id: 'noyear', label: 'Year unknown' };
        const decade = Math.floor(Number(r.year) / 10) * 10;
        return { id: 'd' + decade, label: decade + 's' };
      }
      case 'avg_rating': {
        const star = Math.floor(avgRating(r));
        return star < 1 ? { id: 'unrated', label: 'Unrated' }
                        : { id: 's' + star, label: star + ' ★' };
      }
      case 'my_rating':
      case 'wife_rating': {
        const star = Math.round(Number(r[sortBy]) || 0);
        return star < 1 ? { id: 'unrated', label: 'Unrated' }
                        : { id: 's' + star, label: star + ' ★' };
      }
      case 'play_count': {
        const plays = Number(r.play_count) || 0;
        if (plays === 0) return { id: 'p0', label: 'Never played' };
        if (plays >= 10) return { id: 'p10', label: '10+ plays' };
        if (plays >= 5) return { id: 'p5', label: '5–9 plays' };
        return { id: 'p1', label: '1–4 plays' };
      }
      default:
        return { id: 'all', label: 'All records' };
    }
  }

  /* Crates come out in the order their first record appears, so flattening them
   * reproduces the sorted list. That is what lets the detail drawer's prev/next
   * keep walking filtered() while matching the order on screen, and it means the
   * sort direction needs no handling here at all. */
  function buildGroups(sortedRecords, sortBy) {
    const crates = new Map();
    for (const r of sortedRecords) {
      const bucket = bucketOf(r, sortBy);
      if (!crates.has(bucket.id)) crates.set(bucket.id, { id: bucket.id, label: bucket.label, records: [] });
      crates.get(bucket.id).records.push(r);
    }
    return [...crates.values()];
  }

  return { avgRating, lastPlayed, bucketOf, buildGroups };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylGrouping;
