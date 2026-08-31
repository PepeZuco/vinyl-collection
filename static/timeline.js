/* The event model behind the Timeline tab.
 *
 * Calendar and History were two tabs over the same four events — bought,
 * cleaned, played, noted — at different zooms. They also disagreed about the
 * collection: the calendar read every record while the growth chart read only
 * owned, dated ones, so the same data answered differently depending on which
 * tab you were standing in.
 *
 * This model does no filtering of its own. The caller hands it the records the
 * shared query selected, which is what lets Month, Week, Day and Replay all
 * describe the same collection.
 *
 * Loaded as a plain script in the browser, where `const VinylTimeline` lands in
 * the global lexical scope for the inline script below it; required as a module
 * by the tests. */

const VinylTimeline = (function (grouping) {

  const ALL_TYPES = { bought: true, cleaned: true, played: true, note: true };

  /* Ordering for events that share a day and carry no clock. A record is
   * bought before it is cleaned, cleaned before it is played, and any note
   * about it comes after the thing it describes. */
  const TYPE_ORDER = { bought: 0, cleaned: 1, played: 2, note: 3 };

  /* An event's name.
   *
   * nowStamp() keeps seconds, so anything logged through the app is already
   * unique on its stamp alone — but rows written before times were kept carry
   * a bare 'YYYY-MM-DD', and two clockless cleanings on one day would collide.
   * Indexing every list-backed type is uniform and costs nothing.
   *
   * bought takes no index: bought_date is one column and cannot hold two.
   *
   * `at` is the RAW stored string, not a normalised moment. The drawer builds
   * its own history from the same parsers and must arrive at the same keys, so
   * both sides pass what the parser handed them and nothing in between. */
  function keyOf(type, at, i) {
    return type === 'bought' ? 'bought:' + at : type + ':' + at + ':' + i;
  }

  /* Map of 'YYYY-MM-DD' -> the day's events, each in the order it reads.
   *
   * Every event files under the day of its LOCAL clock. The stamps are local
   * wall clocks with no zone precisely so that a 23:30 play stays on its own
   * evening instead of sliding onto tomorrow. */
  function eventsByDay(records, types, deps) {
    const map = new Map();
    const on = types || ALL_TYPES;
    const parsePlays = (deps && deps.parsePlayDates) || (() => []);
    const parseCleans = (deps && deps.parseCleanedDates) || parsePlays;
    const parseNotes = (deps && deps.parseNotes) || (() => []);

    const add = (date, event) => {
      const moment = grouping.momentOf(date);
      if (!moment.day) return;            // undated, or a stamp no calendar holds
      if (!map.has(moment.day)) map.set(moment.day, []);
      map.get(moment.day).push(Object.assign(
        { time: moment.time, day: moment.day, at: String(date),
          key: keyOf(event.type, String(date), event.i) },
        event));
    };

    (records || []).forEach(r => {
      if (on.bought) add(r.bought_date, { type: 'bought', r });
      if (on.cleaned) parseCleans(r.cleaned_dates).forEach((d, i) => add(d, { type: 'cleaned', r, i }));
      if (on.played) parsePlays(r.play_dates).forEach((d, i) => add(d, { type: 'played', r, i }));
      if (on.note) parseNotes(r.notes, r.bought_date).forEach((n, i) => {
        // The index is the position in the RAW array: an empty note still holds
        // its slot, so filtering first would renumber everything after it.
        if (n && n.text && n.text.trim()) add(n.date, { type: 'note', r, i, text: n.text });
      });
    });

    // A day reads as an agenda: chronological, with anything clockless counting
    // as midnight and so leading the day in its own order.
    map.forEach(list => list.sort((a, b) =>
      (a.time || '').localeCompare(b.time || '') ||
      TYPE_ORDER[a.type] - TYPE_ORDER[b.type] ||
      String(a.r.album_name).localeCompare(String(b.r.album_name))));

    return map;
  }

  return { ALL_TYPES, TYPE_ORDER, keyOf, eventsByDay };
})(typeof module !== 'undefined' && module.exports
     ? require('./grouping.js') : VinylGrouping);

if (typeof module !== 'undefined' && module.exports) module.exports = VinylTimeline;
