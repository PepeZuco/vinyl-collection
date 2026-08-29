'use strict';

/* How the collection is used, on a calendar clock.
 *
 * The race chart in history.js replays how the collection GREW — one frame per
 * purchase day, genres racing. This is the other half: what happened to each
 * record after it was shelved. Bought, played, cleaned and noted, all indexed
 * by day so the History tab can sweep one playhead across them.
 *
 * Days here are integers counted from d0, never stamps. Everything downstream —
 * column heights, mark positions, the zoom window — is arithmetic on those
 * integers, and the renderer never parses a date.
 *
 * Pure functions of the record list, kept out of index.html so they can be
 * tested directly (tests/test_activity.js).
 *
 * Loaded as a plain script in the browser AFTER grouping.js, whose momentOf
 * this depends on; required as a module by the tests. */

const VinylActivity = (function (grouping) {

  const WEEK = 7;

  /* How much wall clock each day is worth. The axis stays linear in calendar
   * time — every mark keeps its place — but the RATE of travel varies, so a
   * run does not spend 43% of itself on the 352 empty days between this
   * collection's first purchase and its second. A purchase day is a race-chart
   * frame and must be on screen long enough for bars to visibly move; a day
   * carrying only plays or cleanings is worth seeing but cheaper; an empty day
   * passes almost for free. */
  const CLOCK_W_BUY   = 6;
  const CLOCK_W_EVENT = 1;
  const CLOCK_W_EMPTY = 0.04;

  /* Same scope rule as the race chart: owned and dated. Every have_it record
   * in the collection carries a bought_date and every undated one is a
   * wishlist item, so this loses nothing owned. */
  function inScope(r) {
    return !!r.have_it && !!grouping.momentOf(r.bought_date).day;
  }

  /* 'YYYY-MM-DD' -> days since the epoch, and back.
   *
   * Built from the calendar parts through Date.UTC rather than Date.parse, so
   * it is timezone-proof: two stamps on the same local day must land on the
   * same integer no matter where the browser is, and momentOf has already done
   * the work of deciding which local day a stamp belongs to. */
  function dayNumber(iso) {
    const p = String(iso).split('-');
    return Math.round(Date.UTC(+p[0], +p[1] - 1, +p[2]) / 86400000);
  }

  function dayString(n) {
    return new Date(n * 86400000).toISOString().slice(0, 10);
  }

  /* The renderer's only date arithmetic: which calendar day is index i. */
  function dayAt(d0, i) {
    return dayString(dayNumber(d0) + Math.floor(i));
  }

  /* A stamp the calendar could not hold comes back empty from momentOf and is
   * dropped rather than bucketed — one bad row must not take the tab down. */
  function dayOf(stamp) {
    const day = grouping.momentOf(stamp).day;
    return day ? dayNumber(day) : null;
  }

  function isDay(n) { return n !== null && n !== undefined && !isNaN(n); }
  function asc(a, b) { return a - b; }

  /* play_dates and cleaned_dates are JSON arrays of stamps. index.html has its
   * own parsePlayDates, but it lives in the template and cannot be reached
   * from here — so this parses the column itself rather than making the module
   * depend on the page. */
  function parseList(raw) {
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) { return []; }
  }

  /* Notes are [{date, text}], except on legacy rows where the column is a bare
   * string — the same migration parseNotes() does in the template. A note with
   * no text is not an event, matching dmHistoryEvents(). */
  function parseNoteList(raw, fallbackDate) {
    if (!raw) return [];
    let parsed = null;
    try { parsed = JSON.parse(raw); } catch (e) { parsed = null; }
    if (!Array.isArray(parsed)) parsed = [{ date: fallbackDate, text: String(raw) }];
    return parsed.filter(function (n) {
      return n && typeof n.text === 'string' && n.text.trim();
    });
  }

  /* Every event a record carries, as absolute day numbers. */
  function eventsOf(r) {
    return {
      r: r,
      bought: dayOf(r.bought_date),
      plays:  parseList(r.play_dates).map(dayOf).filter(isDay).sort(asc),
      cleans: parseList(r.cleaned_dates).map(dayOf).filter(isDay).sort(asc),
      notes:  parseNoteList(r.notes, r.bought_date)
                .map(function (n) { return { day: dayOf(n.date), text: n.text }; })
                .filter(function (n) { return isDay(n.day); })
                .sort(function (a, b) { return a.day - b.day; }),
    };
  }

  function buildActivity(records) {
    const scoped = (records || []).filter(inScope);
    if (!scoped.length) return null;

    const raw = scoped.map(eventsOf);

    let lo = Infinity, hi = -Infinity;
    for (const e of raw) {
      const days = [e.bought].concat(e.plays, e.cleans,
                                     e.notes.map(function (n) { return n.day; }));
      for (const d of days) { if (d < lo) lo = d; if (d > hi) hi = d; }
    }

    const span = hi - lo + 1;
    const weeks = [];
    for (let i = 0; i < Math.ceil(span / WEEK); i++) {
      weeks.push({ b: 0, p: 0, c: 0, n: 0, total: 0 });
    }
    const perDay = [];
    for (let i = 0; i < span; i++) perDay.push({ b: 0, p: 0, c: 0, n: 0 });

    function count(day, key) {
      perDay[day][key]++;
      weeks[(day / WEEK) | 0][key]++;
    }

    const playedOn = [];
    const noteList = [];

    const lanes = raw.map(function (e) {
      const shift = function (d) { return d - lo; };
      const bought = shift(e.bought);
      const plays  = e.plays.map(shift);
      const cleans = e.cleans.map(shift);

      count(bought, 'b');

      plays.forEach(function (d) {
        if (!playedOn[d]) playedOn[d] = [];
        playedOn[d].push(e.r.id);
        count(d, 'p');
      });

      cleans.forEach(function (d) { count(d, 'c'); });

      const noteDays = e.notes.map(function (n) {
        const day = shift(n.day);
        noteList.push({ day: day, text: n.text, id: e.r.id,
                        artist: e.r.artist || '', album: e.r.album_name || '' });
        count(day, 'n');
        return day;
      });

      return {
        id: e.r.id,
        artist: e.r.artist || '',
        album: e.r.album_name || '',
        // cover_url, not cover_data: covers moved to their own endpoint and the
        // record list stopped carrying bytes at all.
        cover: e.r.cover_url || '',
        bought: bought,
        plays: plays,
        cleans: cleans,
        notes: noteDays,
        /* Falling back to the purchase day rather than -1 means the quiet fade
         * measures silence from the day the record arrived, so one that was
         * never played goes quiet on schedule instead of never. */
        lastPlay: plays.length ? plays[plays.length - 1] : bought,
      };
    });

    const cum = { b: [], p: [], c: [], n: [] };
    const totals = { b: 0, p: 0, c: 0, n: 0 };
    ['b', 'p', 'c', 'n'].forEach(function (k) {
      let running = 0;
      for (let i = 0; i < span; i++) { running += perDay[i][k]; cum[k][i] = running; }
      totals[k] = running;
    });
    weeks.forEach(function (w) { w.total = w.b + w.p + w.c + w.n; });

    noteList.sort(function (a, b) { return a.day - b.day; });

    /* Play count desc, ties by purchase order then id. A defined order means
     * "top N" is meaningful before the user has touched the sort control, and
     * makes the ordering assertable in tests. */
    lanes.sort(function (a, b) {
      if (a.plays.length !== b.plays.length) return b.plays.length - a.plays.length;
      if (a.bought !== b.bought) return a.bought - b.bought;
      return (Number(a.id) || 0) - (Number(b.id) || 0);
    });

    return { d0: dayString(lo), span: span, weeks: weeks, cum: cum,
             lanes: lanes, playedOn: playedOn, notes: noteList, totals: totals };
  }

  /* A running total of weight, one entry per day plus a closing edge. Because
   * it never decreases, both lookups over it are a binary search. */
  function buildClock(act) {
    if (!act) return null;
    const span = act.span;
    const buy = new Array(span).fill(false);
    const ev  = new Array(span).fill(false);
    act.lanes.forEach(function (lane) {
      buy[lane.bought] = true;
      lane.plays.forEach(function (d)  { ev[d] = true; });
      lane.cleans.forEach(function (d) { ev[d] = true; });
      lane.notes.forEach(function (d)  { ev[d] = true; });
    });
    const cum = new Array(span + 1);
    cum[0] = 0;
    for (let d = 0; d < span; d++) {
      /* bought wins outright — a day you bought and played on is still one
       * race frame, and paying for both would give it seven days' worth of
       * screen time for one transition. */
      cum[d + 1] = cum[d] + (buy[d] ? CLOCK_W_BUY
                          : ev[d]  ? CLOCK_W_EVENT
                          :          CLOCK_W_EMPTY);
    }
    return { cum: cum, total: cum[span] };
  }

  /* The largest day whose running total has not yet passed p, plus the
   * fraction of the way through that day — so the playhead glides rather than
   * stepping from day to day. */
  function dayAtProgress(clock, p) {
    if (!clock) return 0;
    const last = clock.cum.length - 2;
    if (!(p > 0)) return 0;                 // also catches NaN
    if (p >= clock.total) return last;
    let lo = 0, hi = last;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (clock.cum[mid] <= p) lo = mid; else hi = mid - 1;
    }
    const w = clock.cum[lo + 1] - clock.cum[lo];
    return lo + (w > 0 ? (p - clock.cum[lo]) / w : 0);
  }

  /* The inverse, so a seek in calendar days lands on the right progress. */
  function progressAtDay(clock, day) {
    if (!clock) return 0;
    const last = clock.cum.length - 2;
    /* Clamp the day FIRST, then split it. Decomposing before clamping gets
     * this wrong whichever order you pick: measure the fraction against the
     * clamped whole and a large day drags it to 1, landing past the last
     * day's start; measure it against the raw whole and -0.3 becomes +0.7 of
     * day zero. Clamping the input once leaves nothing to disagree about. */
    const n = Number(day);
    const at = Math.max(0, Math.min(last, isNaN(n) ? 0 : n));
    const d = Math.floor(at);
    return clock.cum[d] + (clock.cum[d + 1] - clock.cum[d]) * (at - d);
  }

  return { buildActivity: buildActivity, dayAt: dayAt, buildClock: buildClock,
           dayAtProgress: dayAtProgress, progressAtDay: progressAtDay };
})(typeof module !== 'undefined' && module.exports
     ? require('./grouping.js') : VinylGrouping);

if (typeof module !== 'undefined' && module.exports) module.exports = VinylActivity;
