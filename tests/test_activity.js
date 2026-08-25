// Tests for the pure model behind the History tab's activity chart.
// Run by tests/test_activity.py so `pytest` stays the single command.

// Pinned before anything constructs a Date: momentOf moves stamps onto the
// local clock, which says nothing without an offset to move them by. Sao Paulo
// is UTC-3 and the collection's own timezone.
process.env.TZ = 'America/Sao_Paulo';

const test = require('node:test');
const assert = require('node:assert');

const { buildActivity, dayAt } = require('../static/activity.js');

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
