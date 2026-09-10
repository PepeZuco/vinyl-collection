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

  // A day number back to 'YYYY-MM-DD' — the inverse of dayNumber, used to
  // build the trailing day window below.
  function dayKey(n) {
    const d = new Date(n * DAY_MS);
    return d.getUTCFullYear() + '-' + String(d.getUTCMonth() + 1).padStart(2, '0') +
      '-' + String(d.getUTCDate()).padStart(2, '0');
  }

  // The `days` calendar days ending at `today`, oldest first.
  function dayWindow(today, days) {
    const end = dayNumber(today);
    const keys = [];
    for (let back = days - 1; back >= 0; back--) keys.push(dayKey(end - back));
    return keys;
  }

  // The Monday-first weekday index of a day number: 0 is Monday, 6 is Sunday.
  // Day 0 of the epoch, 1970-01-01, was a Thursday — index 3.
  function weekdayOf(n) {
    return ((n + 3) % 7 + 7) % 7;
  }

  // How many times weekday `w` falls in the inclusive day-number range a..b.
  // Whole weeks contribute one each; the remainder contributes one more only
  // if `w` is among the days it actually reaches.
  function weekdayCount(w, a, b) {
    if (b < a) return 0;
    const span = b - a + 1;
    const untilFirst = ((w - weekdayOf(a)) % 7 + 7) % 7;
    return Math.floor(span / 7) + (untilFirst < span % 7 ? 1 : 0);
  }

  /* The average number of plays on each weekday, Monday first.
   *
   * This replaced a tracker of the last seven calendar days, which could not
   * answer the question the shape invited: seven days hold one sample of each
   * weekday, so a quiet week and a quiet Tuesday looked identical. Averaging
   * over every week on record makes a weekend habit visible.
   *
   * Each weekday's plays are divided by how many times that weekday has come
   * round since the first play was logged. The window opens at that first play
   * rather than at some fixed span because the silence before there was
   * anything to play is not evidence about when this listener listens. A play
   * dated after today — clock skew across timezones files one a day ahead —
   * extends the window rather than falling outside it.
   */
  function playsByWeekdayOf(owned, today) {
    const totals = [0, 0, 0, 0, 0, 0, 0];
    let earliest = null, latest = null;
    owned.forEach(r => {
      let dates;
      try { dates = JSON.parse(r.play_dates || '[]'); } catch { return; }
      if (!Array.isArray(dates)) return;
      dates.forEach(raw => {
        const day = grouping.momentOf(raw).day;
        if (!day) return;                       // a stamp no calendar holds
        const n = dayNumber(day);
        totals[weekdayOf(n)]++;
        if (earliest === null || n < earliest) earliest = n;
        if (latest === null || n > latest) latest = n;
      });
    });
    if (earliest === null) return totals;       // nothing played: seven zeros
    const end = Math.max(dayNumber(today), latest);
    return totals.map((sum, w) => {
      const occurrences = weekdayCount(w, earliest, end);
      return occurrences ? sum / occurrences : 0;
    });
  }

  // The rotation count as it stood at the end of each day in the window — the
  // same "played within withinDays" rule as today's figure, just asked of a
  // past day instead of today. A play after that day cannot yet have
  // happened, so it is excluded when deciding what was true as of that day.
  function rotationByDayOf(owned, days, withinDays) {
    const lastPlayDayNums = owned.map(r => {
      let dates;
      try { dates = JSON.parse(r.play_dates || '[]'); } catch { return null; }
      if (!Array.isArray(dates)) return null;
      const nums = dates.map(d => grouping.momentOf(d).day).filter(Boolean).map(dayNumber);
      return nums.length ? Math.max(...nums) : null;
    });
    return days.map(day => {
      const dNum = dayNumber(day);
      const cutoff = dNum - withinDays;
      return lastPlayDayNums.filter(n => n !== null && n <= dNum && n >= cutoff).length;
    });
  }

  // The never-cleaned backlog as it stood at the end of each day in the
  // window: a record counts as cleaned by that day only if one of its
  // cleanings is dated on or before it.
  function neverCleanedByDayOf(owned, days) {
    const cleaningDayNums = owned.map(r => {
      let dates;
      try { dates = JSON.parse(r.cleaned_dates || '[]'); } catch { return []; }
      if (!Array.isArray(dates)) return [];
      return dates.map(d => grouping.momentOf(d).day).filter(Boolean).map(dayNumber);
    });
    return days.map(day => {
      const dNum = dayNumber(day);
      return cleaningDayNums.filter(nums => !nums.some(n => n <= dNum)).length;
    });
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
    const trendDays = o.trendDays === undefined ? 7 : o.trendDays;
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
    let addsThisWeek = 0;
    const weekCutoff = today ? dayNumber(today) - trendDays + 1 : null;
    owned.forEach(r => {
      const day = grouping.momentOf(r.bought_date).day;
      if (!day) return;                         // undated, or a stamp no calendar holds
      const key = monthKey(day);
      if (counts.has(key)) counts.set(key, counts.get(key) + 1);
      if (weekCutoff !== null && dayNumber(day) >= weekCutoff) addsThisWeek++;
    });

    const days = today ? dayWindow(today, trendDays) : [];

    return {
      total: all.length,
      owned: owned.length,
      plays,
      rotation,
      cleanedAtLeastOnce,
      neverCleaned: owned.length - cleanedAtLeastOnce,
      adds: window.map(month => ({ month, n: counts.get(month) })),
      addsThisWeek,
      playsByWeekday: today ? playsByWeekdayOf(owned, today) : [],
      rotationByDay: days.length ? rotationByDayOf(owned, days, withinDays) : [],
      neverCleanedByDay: days.length ? neverCleanedByDayOf(owned, days) : [],
    };
  }

  return { collectionHealth };
})(typeof module !== 'undefined' && module.exports
     ? require('./grouping.js') : VinylGrouping);

if (typeof module !== 'undefined' && module.exports) module.exports = VinylHealth;
