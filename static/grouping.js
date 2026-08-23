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

  /* The average of the ratings actually given — a record only Pepe rated averages
   * to his score, not to half of it. */
  function avgRating(r) {
    const scores = [Number(r.my_rating) || 0, Number(r.wife_rating) || 0].filter(x => x > 0);
    return scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;
  }

  /* One logged play, read onto the local wall clock.
   *
   * Plays are logged so the collection remembers the ORDER they were played in,
   * which means every entry has to reduce to one comparable moment. Three
   * shapes live in the column:
   *
   *   2026-08-14                  logged before times were recorded. Ordered as
   *                               midnight, but reported with no clock — it is
   *                               not a claim the record played at 00:00.
   *   2026-08-14T21:12:44         a local wall clock, what is written now.
   *   2026-08-14T21:12:44.115Z    UTC, what the +/- buttons wrote before this.
   *                               Shifted onto the local clock, which is also
   *                               what stops an evening play filing itself on
   *                               the next day in the calendar.
   *
   * Returns { day, time, at }: `at` is the sortable local stamp, `day` the
   * calendar day to file it under, `time` the clock to show — '' when the entry
   * never carried one. Anything unparseable comes back as all-empty rather than
   * throwing, so one bad row never takes the collection down with it. */
  function playMoment(raw) {
    const none = { day: '', time: '', at: '' };
    const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?$/
      .exec(String(raw == null ? '' : raw).trim());
    if (!m) return none;
    const [, y, mo, d, hh, mm, ss, zone] = m;

    if (hh === undefined) {
      const day = y + '-' + mo + '-' + d;
      return { day, time: '', at: day + 'T00:00:00' };
    }
    if (!zone) return stamp(y, mo, d, hh, mm, ss || '00');

    // Offset-bearing: hand it to Date, then read the local components back.
    // +HHMM is normalized to +HH:MM first — ISO parsing only guarantees the
    // colon form, and Safari rejects the other.
    const at = new Date(y + '-' + mo + '-' + d + 'T' + hh + ':' + mm + ':' + (ss || '00') +
                        (zone === 'Z' ? 'Z' : zone.replace(/^([+-]\d{2})(\d{2})$/, '$1:$2')));
    if (isNaN(at.getTime())) return none;
    const pad = n => String(n).padStart(2, '0');
    return stamp(at.getFullYear(), pad(at.getMonth() + 1), pad(at.getDate()),
                 pad(at.getHours()), pad(at.getMinutes()), pad(at.getSeconds()));
  }

  function stamp(y, mo, d, hh, mm, ss) {
    const day = y + '-' + mo + '-' + d;
    const time = hh + ':' + mm;
    return { day, time, at: day + 'T' + time + ':' + ss };
  }

  /* The most recent play as a local stamp, or '' when the column holds nothing
   * usable. A truncated write or a column holding something that is not an
   * array both read as never played rather than throwing — the collection still
   * renders when one row's JSON is bad. Normalized stamps compare
   * lexicographically, so the max is the latest without parsing any dates. */
  function lastPlayed(r) {
    let dates;
    try { dates = JSON.parse(r.play_dates || '[]'); }
    catch { return ''; }
    if (!Array.isArray(dates)) return '';
    const given = dates.map(d => playMoment(d).at).filter(Boolean);
    return given.length ? given.reduce((a, b) => (a > b ? a : b)) : '';
  }

  /* The crate a record belongs to for a given grouping field.
   *
   *   id       what records are bucketed on
   *   label    what the crate header shows
   *   rank     natural crate order, ascending — dates run oldest first, names
   *            A→Z, stars and play bands low→high. The direction arrow negates
   *            it, so "descending" needs no separate rule per field.
   *   unknown  a catch-all crate (no date, no genre, unrated…). These pin to
   *            the bottom in BOTH directions rather than flipping to the top;
   *            over half the collection has no country recorded, and an Unknown
   *            crate leading the page would bury everything else.
   *   code     country only — the ISO code, so the header can draw the flag
   *            without grouping.js needing to know how flags render.
   *
   * countryName resolves a code to a country name for ranking; the page passes
   * its own countryLabelFromCode. Left out, codes rank as themselves. */
  function bucketOf(r, groupBy, countryName) {
    switch (groupBy) {
      case 'bought_date': {
        if (!r.bought_date) return { id: 'nodate', label: 'No date', rank: '', unknown: true };
        const [year, month] = String(r.bought_date).split('-');
        return { id: year + '-' + month, label: MONTHS[Number(month) - 1] + ' ' + year,
                 rank: year + '-' + month, unknown: false };
      }
      case 'artist': {
        const artist = (r.artist || '').trim();
        if (!artist) return { id: 'noartist', label: 'Unknown artist', rank: '', unknown: true };
        return { id: artist.toLowerCase(), label: artist, rank: artist.toLowerCase(), unknown: false };
      }
      case 'album_name': {
        const first = (r.album_name || '').trim().charAt(0).toUpperCase();
        const letter = /[A-Z]/.test(first) ? first : '#';
        return { id: letter, label: letter, rank: letter, unknown: false };
      }
      case 'year': {
        if (!r.year) return { id: 'noyear', label: 'Year unknown', rank: 0, unknown: true };
        const decade = Math.floor(Number(r.year) / 10) * 10;
        return { id: 'd' + decade, label: decade + 's', rank: decade, unknown: false };
      }
      case 'genre': {
        const genre = (r.genre || '').trim();
        if (!genre) return { id: 'nogenre', label: 'Unknown genre', rank: '', unknown: true };
        return { id: genre.toLowerCase(), label: genre, rank: genre.toLowerCase(), unknown: false };
      }
      case 'country': {
        const code = (r.country || '').trim().toUpperCase();
        if (!code) return { id: 'nocountry', label: 'Unknown country', rank: '', unknown: true };
        const name = countryName ? countryName(code) : code;
        return { id: code, label: name, code, rank: String(name).toLowerCase(), unknown: false };
      }
      case 'avg_rating': {
        const star = Math.floor(avgRating(r));
        return star < 1 ? { id: 'unrated', label: 'Unrated', rank: 0, unknown: true }
                        : { id: 's' + star, label: star + ' ★', rank: star, unknown: false };
      }
      case 'my_rating':
      case 'wife_rating': {
        const star = Math.round(Number(r[groupBy]) || 0);
        return star < 1 ? { id: 'unrated', label: 'Unrated', rank: 0, unknown: true }
                        : { id: 's' + star, label: star + ' ★', rank: star, unknown: false };
      }
      case 'last_played': {
        const when = lastPlayed(r);
        if (!when) return { id: 'never', label: 'Never played', rank: '', unknown: true };
        const [year, month] = when.split('-');
        return { id: year + '-' + month, label: MONTHS[Number(month) - 1] + ' ' + year,
                 rank: year + '-' + month, unknown: false };
      }
      case 'play_count': {
        // "Never played" is a real band here, not a missing value — it flips
        // with the arrow like any other.
        const plays = Number(r.play_count) || 0;
        if (plays === 0)  return { id: 'p0',  label: 'Never played', rank: 0, unknown: false };
        if (plays >= 10)  return { id: 'p10', label: '10+ plays',    rank: 3, unknown: false };
        if (plays >= 5)   return { id: 'p5',  label: '5–9 plays',    rank: 2, unknown: false };
        return { id: 'p1', label: '1–4 plays', rank: 1, unknown: false };
      }
      default:
        return { id: 'all', label: 'All records', rank: 0, unknown: false };
    }
  }

  /* Orders two records by the crate they belong to — the first level of the
   * collection's sort, with the chosen sort field breaking ties inside a crate.
   * Ordering this way rather than sorting the crates after the fact is what
   * keeps crates a pure view of one flat sorted list, which in turn is what lets
   * the detail drawer's prev/next walk that list and stay in step with what is
   * on screen. Records of the same crate compare equal, leaving them to it. */
  function compareByGroup(a, b, groupBy, dir, countryName) {
    if (!groupBy || groupBy === 'none') return 0;
    const ba = bucketOf(a, groupBy, countryName);
    const bb = bucketOf(b, groupBy, countryName);
    if (ba.unknown !== bb.unknown) return ba.unknown ? 1 : -1;
    if (ba.rank === bb.rank) return 0;
    const cmp = ba.rank < bb.rank ? -1 : 1;
    return dir === 'desc' ? -cmp : cmp;
  }

  /* Crates come out in the order their first record appears, so flattening them
   * reproduces the sorted list. That is what lets the detail drawer's prev/next
   * keep walking filtered() while matching the order on screen, and it means the
   * sort direction needs no handling here at all. */
  function buildGroups(sortedRecords, groupBy, countryName) {
    const crates = new Map();
    for (const r of sortedRecords) {
      const bucket = bucketOf(r, groupBy, countryName);
      if (!crates.has(bucket.id)) {
        const crate = { id: bucket.id, label: bucket.label, records: [] };
        if (bucket.code) crate.code = bucket.code;
        crates.set(bucket.id, crate);
      }
      crates.get(bucket.id).records.push(r);
    }
    return [...crates.values()];
  }

  return { avgRating, playMoment, lastPlayed, bucketOf, compareByGroup, buildGroups };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylGrouping;
