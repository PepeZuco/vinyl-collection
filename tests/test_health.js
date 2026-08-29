// Tests for the collection-health figures on the Insights tab.
// Run by tests/test_health.py so `pytest` stays the single command.
//
// These replace the rating scoreboard that used to head the page. Two big
// averages said less than the per-genre dumbbell below them already did; what
// was missing was the state of the collection — how much of it is in rotation,
// and how much of it is overdue a clean. None of that was visible anywhere.

process.env.TZ = 'America/Sao_Paulo';

const test = require('node:test');
const assert = require('node:assert');

const { collectionHealth } = require('../static/health.js');

let nextId = 1;
function rec(fields) {
  return Object.assign(
    { id: nextId++, artist: 'Tim Maia', album_name: 'Uma Onda', have_it: true,
      bought_date: '', play_dates: '', cleaned_dates: '', play_count: 0 },
    fields);
}
const json = (...v) => JSON.stringify(v);

const TODAY = '2026-08-29';
const health = (records, opts) =>
  collectionHealth(records, Object.assign({ today: TODAY, withinDays: 30, months: 8 }, opts));

// ── the set being described ─────────────────────────────────────────────────

test('an empty collection reports zeros rather than throwing', () => {
  const h = health([]);
  assert.strictEqual(h.total, 0);
  assert.strictEqual(h.owned, 0);
  assert.strictEqual(h.plays, 0);
});

test('total counts every record handed in, owned or not', () => {
  assert.strictEqual(health([rec({}), rec({ have_it: false })]).total, 2);
});

test('owned counts only the records in the collection', () => {
  assert.strictEqual(health([rec({}), rec({ have_it: false }), rec({})]).owned, 2);
});

// ── plays ───────────────────────────────────────────────────────────────────

test('plays sums the play count across owned records', () => {
  assert.strictEqual(health([rec({ play_count: 12 }), rec({ play_count: 7 })]).plays, 19);
});

test('a wishlist record contributes no plays', () => {
  // It cannot have been played, so a stray count on one must not inflate the number.
  assert.strictEqual(health([rec({ have_it: false, play_count: 9 })]).plays, 0);
});

// ── rotation ────────────────────────────────────────────────────────────────

test('a record played inside the window is in rotation', () => {
  assert.strictEqual(health([rec({ play_dates: json('2026-08-20T21:00:00') })]).rotation, 1);
});

test('a record played before the window is not in rotation', () => {
  assert.strictEqual(health([rec({ play_dates: json('2026-05-01') })]).rotation, 0);
});

test('the window is inclusive of its oldest day', () => {
  // 30 days before 2026-08-29 is 2026-07-30; that day still counts as rotation.
  assert.strictEqual(health([rec({ play_dates: json('2026-07-30') })]).rotation, 1);
  assert.strictEqual(health([rec({ play_dates: json('2026-07-29') })]).rotation, 0);
});

test('only the most recent play decides rotation', () => {
  const r = rec({ play_dates: json('2024-01-01', '2026-08-20', '2025-06-06') });
  assert.strictEqual(health([r]).rotation, 1);
});

test('a record never played is not in rotation', () => {
  assert.strictEqual(health([rec({})]).rotation, 0);
});

test('a wishlist record is never in rotation', () => {
  assert.strictEqual(health([rec({ have_it: false, play_dates: json('2026-08-20') })]).rotation, 0);
});

// ── cleaning ────────────────────────────────────────────────────────────────

test('never cleaned counts owned records with no cleaning recorded', () => {
  const h = health([rec({}), rec({ cleaned_dates: json('2026-08-02') }), rec({})]);
  assert.strictEqual(h.neverCleaned, 2);
  assert.strictEqual(h.cleanedAtLeastOnce, 1);
});

test('an empty cleaning array counts as never cleaned', () => {
  assert.strictEqual(health([rec({ cleaned_dates: '[]' })]).neverCleaned, 1);
});

test('a wishlist record is not counted as overdue a clean', () => {
  const h = health([rec({ have_it: false })]);
  assert.strictEqual(h.neverCleaned, 0);
  assert.strictEqual(h.cleanedAtLeastOnce, 0);
});

// ── what arrived when ───────────────────────────────────────────────────────

test('adds buckets purchases by month, oldest first', () => {
  const h = health([
    rec({ bought_date: '2026-08-03' }),
    rec({ bought_date: '2026-08-21' }),
    rec({ bought_date: '2026-07-11' }),
  ], { months: 2 });
  assert.deepStrictEqual(h.adds, [{ month: '2026-07', n: 1 }, { month: '2026-08', n: 2 }]);
});

test('adds includes months where nothing was bought', () => {
  const h = health([rec({ bought_date: '2026-08-03' })], { months: 3 });
  assert.deepStrictEqual(h.adds.map(a => a.month), ['2026-06', '2026-07', '2026-08']);
  assert.deepStrictEqual(h.adds.map(a => a.n), [0, 0, 1]);
});

test('adds ignores purchases older than the window', () => {
  const h = health([rec({ bought_date: '2020-01-01' }), rec({ bought_date: '2026-08-03' })],
                   { months: 2 });
  assert.strictEqual(h.adds.reduce((a, b) => a + b.n, 0), 1);
});

test('adds counts the current month even when it is the only one', () => {
  const h = health([rec({ bought_date: '2026-08-29' })], { months: 1 });
  assert.deepStrictEqual(h.adds, [{ month: '2026-08', n: 1 }]);
});

test('a wishlist record has no purchase, so it never lands in a month', () => {
  assert.strictEqual(
    health([rec({ have_it: false, bought_date: '2026-08-03' })], { months: 2 })
      .adds.reduce((a, b) => a + b.n, 0), 0);
});

// ── dates that do not hold ──────────────────────────────────────────────────

test('an unparseable bought date is dropped rather than thrown on', () => {
  const h = health([rec({ bought_date: '2026-02-30' }), rec({ bought_date: '2026-08-03' })],
                   { months: 8 });
  assert.strictEqual(h.adds.reduce((a, b) => a + b.n, 0), 1);
});

test('play dates that are not valid JSON leave the record out of rotation', () => {
  assert.strictEqual(health([rec({ play_dates: 'not json' })]).rotation, 0);
});
