// Tests for the pure model behind the History tab's activity chart.
// Run by tests/test_activity.py so `pytest` stays the single command.

// Pinned before anything constructs a Date: momentOf moves stamps onto the
// local clock, which says nothing without an offset to move them by. Sao Paulo
// is UTC-3 and the collection's own timezone.
process.env.TZ = 'America/Sao_Paulo';

const test = require('node:test');
const assert = require('node:assert');

const { buildActivity, dayAt, buildClock } = require('../static/activity.js');

// A record only needs the fields the model reads, so each test builds the
// smallest one that exercises its rule.
let nextId = 1;
function rec(fields) {
  return Object.assign(
    { id: nextId++, artist: 'A', album_name: 'B', have_it: true, cover_data: '' },
    fields);
}
const plays = (...d) => JSON.stringify(d);

// ── scope ───────────────────────────────────────────────────────────────────

test('a collection with nothing in it has no model', () => {
  assert.strictEqual(buildActivity([]), null);
  assert.strictEqual(buildActivity(null), null);
});

test('wishlist records are excluded even when they carry events', () => {
  assert.strictEqual(buildActivity([
    rec({ have_it: false, bought_date: '2026-01-05', play_dates: plays('2026-02-01') }),
  ]), null);
});

test('owned records with no bought date are excluded', () => {
  assert.strictEqual(buildActivity([rec({ bought_date: '' })]), null);
});

test('an unparseable bought date drops the whole record', () => {
  assert.strictEqual(buildActivity([rec({ bought_date: '2026-02-30' })]), null);
});

// ── the day axis ────────────────────────────────────────────────────────────

test('day 0 is the first purchase when nothing predates it', () => {
  const a = buildActivity([
    rec({ bought_date: '2026-01-10' }),
    rec({ bought_date: '2026-01-02' }),
  ]);
  assert.strictEqual(a.d0, '2026-01-02');
  assert.strictEqual(a.span, 9);          // 02 Jan .. 10 Jan inclusive
});

test('day 0 is the earliest event of any kind, not the earliest purchase', () => {
  const a = buildActivity([
    rec({ bought_date: '2026-03-01', play_dates: plays('2026-02-20') }),
  ]);
  assert.strictEqual(a.d0, '2026-02-20');
  assert.strictEqual(a.span, 10);         // 20 Feb .. 01 Mar inclusive
});

test('the span reaches the last event day inclusive', () => {
  const a = buildActivity([
    rec({ bought_date: '2026-01-01', cleaned_dates: plays('2026-01-05') }),
  ]);
  assert.strictEqual(a.span, 5);
});

test('a one-day collection has a span of one and does not throw', () => {
  const a = buildActivity([rec({ bought_date: '2026-01-01' })]);
  assert.strictEqual(a.span, 1);
  assert.strictEqual(a.d0, '2026-01-01');
});

test('a stamp carrying a clock files under its calendar day', () => {
  const a = buildActivity([rec({ bought_date: '2026-01-01T23:30:00' })]);
  assert.strictEqual(a.d0, '2026-01-01');
});

// ── dayAt ───────────────────────────────────────────────────────────────────

test('dayAt walks forward from day zero', () => {
  assert.strictEqual(dayAt('2026-01-01', 0), '2026-01-01');
  assert.strictEqual(dayAt('2026-01-01', 31), '2026-02-01');
  assert.strictEqual(dayAt('2024-02-28', 1), '2024-02-29');   // a leap day
  assert.strictEqual(dayAt('2025-12-31', 1), '2026-01-01');   // a year boundary
});

test('a zone-bearing stamp resolves onto the local day, not the UTC one', () => {
  // 02:00 UTC is still the previous evening in Sao Paulo (UTC-3), so this
  // record files under 31 Dec — the TZ pin at the top of this file is what
  // makes that assertion mean something.
  const a = buildActivity([rec({ bought_date: '2026-01-01T02:00:00.000Z' })]);
  assert.strictEqual(a.d0, '2025-12-31');
});

// ── lanes ───────────────────────────────────────────────────────────────────

test('a lane carries its events as day indices from d0', () => {
  const a = buildActivity([rec({
    id: 7, artist: 'Tim Maia', album_name: 'Racional',
    bought_date: '2026-01-01',
    play_dates: plays('2026-01-03', '2026-01-02'),
    cleaned_dates: plays('2026-01-05'),
    notes: JSON.stringify([{ date: '2026-01-04', text: 'first spin' }]),
  })]);
  assert.strictEqual(a.lanes.length, 1);
  const lane = a.lanes[0];
  assert.strictEqual(lane.id, 7);
  assert.strictEqual(lane.artist, 'Tim Maia');
  assert.strictEqual(lane.album, 'Racional');
  assert.strictEqual(lane.bought, 0);
  assert.deepStrictEqual(lane.plays, [1, 2]);      // sorted, not input order
  assert.deepStrictEqual(lane.cleans, [4]);
  assert.deepStrictEqual(lane.notes, [3]);
});

test('lastPlay is the final play, or the purchase when never played', () => {
  const a = buildActivity([
    rec({ id: 1, bought_date: '2026-01-01', play_dates: plays('2026-01-04') }),
    rec({ id: 2, bought_date: '2026-01-01' }),
  ]);
  const by = Object.fromEntries(a.lanes.map(l => [l.id, l]));
  assert.strictEqual(by[1].lastPlay, 3);
  assert.strictEqual(by[2].lastPlay, 0);
});

test('an unparseable play date drops only that play, not the record', () => {
  const a = buildActivity([rec({
    bought_date: '2026-01-01',
    play_dates: plays('2026-02-30', '2026-01-03'),
  })]);
  assert.deepStrictEqual(a.lanes[0].plays, [2]);
});

test('a play dated before the purchase is kept where it was recorded', () => {
  const a = buildActivity([rec({
    bought_date: '2026-01-10', play_dates: plays('2026-01-05'),
  })]);
  assert.strictEqual(a.d0, '2026-01-05');
  assert.strictEqual(a.lanes[0].bought, 5);
  assert.deepStrictEqual(a.lanes[0].plays, [0]);
});

test('a malformed events column is empty, not fatal', () => {
  const a = buildActivity([rec({
    bought_date: '2026-01-01', play_dates: 'not json', cleaned_dates: '{}',
  })]);
  assert.deepStrictEqual(a.lanes[0].plays, []);
  assert.deepStrictEqual(a.lanes[0].cleans, []);
});

test('lanes are ordered by play count desc, ties by purchase then id', () => {
  const a = buildActivity([
    rec({ id: 1, bought_date: '2026-01-02', play_dates: plays('2026-01-03') }),
    rec({ id: 2, bought_date: '2026-01-01',
          play_dates: plays('2026-01-03', '2026-01-04') }),
    rec({ id: 3, bought_date: '2026-01-01', play_dates: plays('2026-01-05') }),
  ]);
  assert.deepStrictEqual(a.lanes.map(l => l.id), [2, 3, 1]);
});

// ── notes ───────────────────────────────────────────────────────────────────

test('a note with no text is not an event', () => {
  const a = buildActivity([rec({
    bought_date: '2026-01-01',
    notes: JSON.stringify([{ date: '2026-01-02', text: '   ' },
                           { date: '2026-01-03', text: 'real' }]),
  })]);
  assert.deepStrictEqual(a.lanes[0].notes, [2]);
  assert.strictEqual(a.notes.length, 1);
  assert.strictEqual(a.notes[0].text, 'real');
});

test('a legacy string notes column migrates onto the bought date', () => {
  const a = buildActivity([rec({
    bought_date: '2026-01-01', notes: 'bought at the fair',
  })]);
  assert.deepStrictEqual(a.lanes[0].notes, [0]);
  assert.strictEqual(a.notes[0].text, 'bought at the fair');
});

test('notes come back ascending and name their record', () => {
  const a = buildActivity([
    rec({ id: 4, artist: 'X', album_name: 'Y', bought_date: '2026-01-01',
          notes: JSON.stringify([{ date: '2026-01-09', text: 'later' }]) }),
    rec({ id: 5, bought_date: '2026-01-01',
          notes: JSON.stringify([{ date: '2026-01-03', text: 'earlier' }]) }),
  ]);
  assert.deepStrictEqual(a.notes.map(n => n.text), ['earlier', 'later']);
  assert.deepStrictEqual(a.notes[1], { day: 8, text: 'later', id: 4,
                                       artist: 'X', album: 'Y' });
});

// ── playedOn ────────────────────────────────────────────────────────────────

test('playedOn indexes every play by day and holds nothing else', () => {
  const a = buildActivity([
    rec({ id: 1, bought_date: '2026-01-01', play_dates: plays('2026-01-03') }),
    rec({ id: 2, bought_date: '2026-01-01', play_dates: plays('2026-01-03') }),
  ]);
  assert.deepStrictEqual(a.playedOn[2], [1, 2]);
  assert.strictEqual(a.playedOn[0], undefined);
  assert.strictEqual(a.playedOn[1], undefined);
});

// ── weeks ───────────────────────────────────────────────────────────────────

test('a week holds seven days, day 6 in the first and day 7 in the second', () => {
  const a = buildActivity([rec({
    bought_date: '2026-01-01',
    play_dates: plays('2026-01-07', '2026-01-08'),   // day 6 and day 7
  })]);
  assert.strictEqual(a.weeks.length, 2);
  assert.strictEqual(a.weeks[0].p, 1);
  assert.strictEqual(a.weeks[1].p, 1);
});

test('a week total is the sum of its four series', () => {
  const a = buildActivity([rec({
    bought_date: '2026-01-01',
    play_dates: plays('2026-01-02'),
    cleaned_dates: plays('2026-01-03'),
    notes: JSON.stringify([{ date: '2026-01-04', text: 'n' }]),
  })]);
  assert.deepStrictEqual(a.weeks[0], { b: 1, p: 1, c: 1, n: 1, total: 4 });
});

// ── cumulative counts ───────────────────────────────────────────────────────

test('cum runs the length of the axis and never decreases', () => {
  const a = buildActivity([rec({
    bought_date: '2026-01-01', play_dates: plays('2026-01-03', '2026-01-05'),
  })]);
  assert.strictEqual(a.cum.p.length, a.span);
  assert.deepStrictEqual(a.cum.p, [0, 0, 1, 1, 2]);
  assert.deepStrictEqual(a.cum.b, [1, 1, 1, 1, 1]);
});

test('the last cumulative value equals the total for every series', () => {
  const a = buildActivity([
    rec({ bought_date: '2026-01-01', play_dates: plays('2026-01-02', '2026-01-03') }),
    rec({ bought_date: '2026-01-04', cleaned_dates: plays('2026-01-05') }),
  ]);
  ['b', 'p', 'c', 'n'].forEach(k => {
    assert.strictEqual(a.cum[k][a.span - 1], a.totals[k], 'series ' + k);
  });
  assert.deepStrictEqual(a.totals, { b: 2, p: 2, c: 1, n: 0 });
});

test('every play in the model is counted exactly once', () => {
  const a = buildActivity([rec({
    bought_date: '2026-01-01', play_dates: plays('2026-01-02', '2026-01-02'),
  })]);
  assert.strictEqual(a.totals.p, 2);
  assert.strictEqual(a.lanes[0].plays.length, 2);
  assert.deepStrictEqual(a.playedOn[1].length, 2);
});

// ── the clock ───────────────────────────────────────────────────────────────

// CLOCK_W_EMPTY is 0.04, which binary floats cannot hold exactly, so weights
// are compared with a tolerance rather than strictEqual.
const near = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-9,
  (msg || '') + ' expected ' + b + ', got ' + a);
const weightOf = (clock, d) => clock.cum[d + 1] - clock.cum[d];

test('no model means no clock', () => {
  assert.strictEqual(buildClock(null), null);
});

test('the table runs one longer than the axis and starts at zero', () => {
  const a = buildClock(buildActivity([rec({ bought_date: '2026-01-01',
    play_dates: plays('2026-01-05') })]));
  assert.strictEqual(a.cum.length, 6);       // span 5, plus the closing edge
  assert.strictEqual(a.cum[0], 0);
  assert.strictEqual(a.total, a.cum[a.cum.length - 1]);
});

test('the table never decreases', () => {
  const a = buildClock(buildActivity([
    rec({ bought_date: '2026-01-01', play_dates: plays('2026-01-09') }),
  ]));
  for (let i = 1; i < a.cum.length; i++) assert.ok(a.cum[i] >= a.cum[i - 1]);
});

test('a purchase day, an event day and an empty day weigh 6, 1 and 0.04', () => {
  const a = buildClock(buildActivity([rec({
    bought_date: '2026-01-01',                 // day 0 — purchase
    play_dates: plays('2026-01-03'),           // day 2 — event
  })]));                                       // day 1 — empty
  near(weightOf(a, 0), 6,    'purchase day');
  near(weightOf(a, 1), 0.04, 'empty day');
  near(weightOf(a, 2), 1,    'event day');
});

test('a day that is both bought on and played on weighs 6, not 7', () => {
  const a = buildClock(buildActivity([rec({
    bought_date: '2026-01-01', play_dates: plays('2026-01-01'),
  })]));
  near(weightOf(a, 0), 6);
});

test('a cleaning and a note each make a day an event day', () => {
  const a = buildClock(buildActivity([rec({
    bought_date: '2026-01-01',
    cleaned_dates: plays('2026-01-03'),
    notes: JSON.stringify([{ date: '2026-01-05', text: 'n' }]),
  })]));
  near(weightOf(a, 2), 1, 'cleaning day');
  near(weightOf(a, 4), 1, 'note day');
});

test('a one-day collection still yields a usable clock', () => {
  const a = buildClock(buildActivity([rec({ bought_date: '2026-01-01' })]));
  assert.strictEqual(a.cum.length, 2);
  near(a.total, 6);
});

// The whole point of the weighting: quiet stretches must not eat the run.
test('a long empty stretch takes a small share of the clock', () => {
  // bought on day 0, played once 200 days later: 199 empty days between.
  const a = buildClock(buildActivity([rec({
    bought_date: '2026-01-01', play_dates: plays('2026-07-20'),
  })]));
  const empty = a.cum[a.cum.length - 2] - a.cum[1];   // everything between
  /* Unweighted those 199 empty days would be 99% of the run; weighted they are
     about 53%. The thresholds are deliberately loose — they exist to catch a
     weighting that has stopped working, not to pin one exact ratio. */
  assert.ok(empty / a.total < 0.70,
    'empty stretch took ' + (empty / a.total * 100).toFixed(0) + '% of the run');
  const eventful = (6 + 1) / a.total;
  assert.ok(eventful > 0.30,
    'event days took only ' + (eventful * 100).toFixed(0) + '% of the run');
});
