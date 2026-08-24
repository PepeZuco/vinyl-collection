// Tests for the pure timeline builder behind the History tab's race chart.
// Run by tests/test_history.py so `pytest` stays the single command.

// Pinned before anything constructs a Date: momentOf moves stamps onto the
// local clock, which says nothing without an offset to move them by. Sao Paulo
// is UTC-3 and the collection's own timezone.
process.env.TZ = 'America/Sao_Paulo';

const test = require('node:test');
const assert = require('node:assert');

const { buildTimeline } = require('../static/history.js');

// A record only needs the fields the timeline reads, so each test builds the
// smallest one that exercises its rule.
let nextId = 1;
function rec(fields) {
  return Object.assign(
    { id: nextId++, artist: 'A', album_name: 'A', have_it: true, genre: 'Rock' },
    fields);
}

// ── scope ───────────────────────────────────────────────────────────────────

test('a collection with nothing in it has no timeline', () => {
  assert.deepStrictEqual(buildTimeline([]), []);
});

test('wishlist records are excluded even when they carry a date', () => {
  const frames = buildTimeline([
    rec({ have_it: false, genre: 'Jazz', bought_date: '2026-01-05' }),
  ]);
  assert.deepStrictEqual(frames, []);
});

test('owned records with no date are excluded', () => {
  assert.deepStrictEqual(buildTimeline([rec({ bought_date: '' })]), []);
});

test('an unparseable date is dropped rather than thrown on', () => {
  const frames = buildTimeline([
    rec({ genre: 'Jazz', bought_date: '2026-02-30' }),
    rec({ genre: 'Rock', bought_date: '2026-02-11' }),
  ]);
  assert.strictEqual(frames.length, 1);
  assert.strictEqual(frames[0].total, 1);
  assert.strictEqual(frames[0].bars[0].label, 'Rock');
});

// ── frames ──────────────────────────────────────────────────────────────────

test('one frame per distinct purchase day, ascending', () => {
  const frames = buildTimeline([
    rec({ bought_date: '2026-03-04' }),
    rec({ bought_date: '2026-01-02' }),
    rec({ bought_date: '2026-03-04T18:30:00' }),
  ]);
  assert.deepStrictEqual(frames.map(f => f.day), ['2026-01-02', '2026-03-04']);
  assert.deepStrictEqual(frames.map(f => f.index), [0, 1]);
});

test('days with no purchase get no frame — the timeline hops', () => {
  const frames = buildTimeline([
    rec({ bought_date: '2024-05-31' }),
    rec({ bought_date: '2026-08-01' }),
  ]);
  assert.strictEqual(frames.length, 2);
});

// ── cumulative ──────────────────────────────────────────────────────────────

test('counts are running totals, never per-day counts', () => {
  const frames = buildTimeline([
    rec({ genre: 'Rock', bought_date: '2026-01-01' }),
    rec({ genre: 'Rock', bought_date: '2026-01-02' }),
    rec({ genre: 'Rock', bought_date: '2026-01-03' }),
  ]);
  assert.deepStrictEqual(frames.map(f => f.bars[0].count), [1, 2, 3]);
});

test('frame total counts every genre through that day', () => {
  const frames = buildTimeline([
    rec({ genre: 'Rock', bought_date: '2026-01-01' }),
    rec({ genre: 'Jazz', bought_date: '2026-01-02' }),
    rec({ genre: 'Pop', bought_date: '2026-01-02' }),
  ]);
  assert.deepStrictEqual(frames.map(f => f.total), [1, 3]);
});

test('the final frame matches a plain group-by over the scoped records', () => {
  const frames = buildTimeline([
    rec({ genre: 'Rock', bought_date: '2026-01-01' }),
    rec({ genre: 'Rock', bought_date: '2026-02-01' }),
    rec({ genre: 'Jazz', bought_date: '2026-02-01' }),
  ]);
  const last = frames[frames.length - 1];
  const counts = Object.fromEntries(last.bars.map(b => [b.label, b.count]));
  assert.deepStrictEqual(counts, { Rock: 2, Jazz: 1 });
});

// ── entry ───────────────────────────────────────────────────────────────────

test('a genre is absent until the frame it first has a record', () => {
  const frames = buildTimeline([
    rec({ genre: 'Rock', bought_date: '2026-01-01' }),
    rec({ genre: 'Jazz', bought_date: '2026-02-01' }),
  ]);
  assert.deepStrictEqual(frames[0].bars.map(b => b.label), ['Rock']);
  assert.deepStrictEqual(frames[1].bars.map(b => b.label).sort(), ['Jazz', 'Rock']);
});

// ── added ───────────────────────────────────────────────────────────────────

test('added holds only that day arrivals', () => {
  const frames = buildTimeline([
    rec({ genre: 'Rock', bought_date: '2026-01-01' }),
    rec({ genre: 'Rock', bought_date: '2026-02-01' }),
    rec({ genre: 'Rock', bought_date: '2026-02-01' }),
  ]);
  assert.strictEqual(frames[1].bars[0].count, 3);
  assert.strictEqual(frames[1].bars[0].added.length, 2);
});

test('a genre that gained nothing that day has an empty added list', () => {
  const frames = buildTimeline([
    rec({ genre: 'Rock', bought_date: '2026-01-01' }),
    rec({ genre: 'Jazz', bought_date: '2026-02-01' }),
  ]);
  const rock = frames[1].bars.find(b => b.label === 'Rock');
  assert.deepStrictEqual(rock.added, []);
});

test('records within a bar run oldest purchase first', () => {
  const frames = buildTimeline([
    rec({ id: 9, genre: 'Rock', bought_date: '2026-02-01' }),
    rec({ id: 8, genre: 'Rock', bought_date: '2026-01-01' }),
  ]);
  assert.deepStrictEqual(frames[1].bars[0].records.map(r => r.id), [8, 9]);
});

// ── untagged ────────────────────────────────────────────────────────────────

test('a record with no genre surfaces as unknown', () => {
  const frames = buildTimeline([rec({ genre: '', bought_date: '2026-01-01' })]);
  assert.strictEqual(frames[0].bars[0].genre, '');
  assert.strictEqual(frames[0].bars[0].label, 'unknown');
});
