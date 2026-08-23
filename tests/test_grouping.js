// Tests for the pure crate-grouping logic behind the collection's group view.
// Run by tests/test_grouping.py so `pytest` stays the single command.

const test = require('node:test');
const assert = require('node:assert');

const { bucketOf, buildGroups, avgRating, lastPlayed } = require('../static/grouping.js');

// A record only needs the fields the bucket rule reads, so each test builds the
// smallest one that exercises its rule.
function rec(fields) {
  return Object.assign({ id: 1, artist: 'A', album_name: 'A', year: 2000 }, fields);
}

// ── bucketOf: date added ────────────────────────────────────────────────────

test('date added buckets into a named calendar month', () => {
  assert.strictEqual(bucketOf(rec({ bought_date: '2026-08-14' }), 'bought_date').label, 'August 2026');
});

test('two records bought in the same month share a bucket id', () => {
  const a = bucketOf(rec({ bought_date: '2026-08-02' }), 'bought_date');
  const b = bucketOf(rec({ bought_date: '2026-08-30' }), 'bought_date');
  assert.strictEqual(a.id, b.id);
});

test('a record with no bought date falls into the No date bucket', () => {
  assert.strictEqual(bucketOf(rec({ bought_date: '' }), 'bought_date').label, 'No date');
});

// ── bucketOf: artist and album ──────────────────────────────────────────────

test('artist buckets one group per artist', () => {
  assert.strictEqual(bucketOf(rec({ artist: 'Kate Bush' }), 'artist').label, 'Kate Bush');
});

test('artist bucket ids ignore case so casing variants do not split a group', () => {
  const a = bucketOf(rec({ artist: 'The Cure' }), 'artist');
  const b = bucketOf(rec({ artist: 'the cure' }), 'artist');
  assert.strictEqual(a.id, b.id);
});

test('a record with no artist falls into the Unknown artist bucket', () => {
  assert.strictEqual(bucketOf(rec({ artist: '' }), 'artist').label, 'Unknown artist');
});

test('album buckets by its uppercased first letter', () => {
  assert.strictEqual(bucketOf(rec({ album_name: 'aja' }), 'album_name').label, 'A');
});

test('an album starting with a digit or symbol buckets into #', () => {
  assert.strictEqual(bucketOf(rec({ album_name: '1999' }), 'album_name').label, '#');
  assert.strictEqual(bucketOf(rec({ album_name: "(What's the Story)" }), 'album_name').label, '#');
});

// ── bucketOf: year ──────────────────────────────────────────────────────────

test('year buckets into a decade', () => {
  assert.strictEqual(bucketOf(rec({ year: 1997 }), 'year').label, '1990s');
});

test('a record with no year falls into the Year unknown bucket', () => {
  assert.strictEqual(bucketOf(rec({ year: null }), 'year').label, 'Year unknown');
});

// ── bucketOf: ratings ───────────────────────────────────────────────────────

test('total rating buckets by the whole star of the average', () => {
  // 5 and 4 average to 4.5, which belongs to the 4-star crate, not the 5
  assert.strictEqual(bucketOf(rec({ my_rating: 5, wife_rating: 4 }), 'avg_rating').label, '4 ★');
});

test('total rating ignores an unrated half of the pair', () => {
  // Only Pepe rated it, so the average is 5 rather than 2.5
  assert.strictEqual(bucketOf(rec({ my_rating: 5, wife_rating: 0 }), 'avg_rating').label, '5 ★');
});

test('a record neither of them rated falls into the Unrated bucket', () => {
  assert.strictEqual(bucketOf(rec({ my_rating: 0, wife_rating: 0 }), 'avg_rating').label, 'Unrated');
});

test('a personal rating buckets on its exact star', () => {
  assert.strictEqual(bucketOf(rec({ my_rating: 3, wife_rating: 5 }), 'my_rating').label, '3 ★');
  assert.strictEqual(bucketOf(rec({ my_rating: 3, wife_rating: 5 }), 'wife_rating').label, '5 ★');
});

// ── bucketOf: plays ─────────────────────────────────────────────────────────

test('plays bucket into never / 1-4 / 5-9 / 10+ bands', () => {
  const label = plays => bucketOf(rec({ play_count: plays }), 'play_count').label;
  assert.strictEqual(label(0), 'Never played');
  assert.strictEqual(label(1), '1–4 plays');
  assert.strictEqual(label(4), '1–4 plays');
  assert.strictEqual(label(5), '5–9 plays');
  assert.strictEqual(label(9), '5–9 plays');
  assert.strictEqual(label(10), '10+ plays');
});

// ── bucketOf: last played ───────────────────────────────────────────────────

test('last played buckets into the calendar month of the most recent play', () => {
  const r = rec({ play_dates: JSON.stringify(['2026-06-02', '2026-08-14', '2026-07-30']) });
  assert.strictEqual(bucketOf(r, 'last_played').label, 'August 2026');
});

test('two records last played in the same month share a bucket id', () => {
  const a = bucketOf(rec({ play_dates: '["2026-08-02"]' }), 'last_played');
  const b = bucketOf(rec({ play_dates: '["2026-08-30"]' }), 'last_played');
  assert.strictEqual(a.id, b.id);
});

test('a record with no plays falls into the Never played bucket', () => {
  assert.strictEqual(bucketOf(rec({ play_dates: '' }), 'last_played').label, 'Never played');
  assert.strictEqual(bucketOf(rec({ play_dates: '[]' }), 'last_played').label, 'Never played');
});

// ── lastPlayed ──────────────────────────────────────────────────────────────

test('lastPlayed returns the most recent play regardless of stored order', () => {
  assert.strictEqual(lastPlayed({ play_dates: '["2026-08-14","2024-01-09"]' }), '2026-08-14');
  assert.strictEqual(lastPlayed({ play_dates: '["2024-01-09","2026-08-14"]' }), '2026-08-14');
});

test('lastPlayed reads a play count of none as no date at all', () => {
  assert.strictEqual(lastPlayed({}), '');
  assert.strictEqual(lastPlayed({ play_dates: '[]' }), '');
});

test('lastPlayed treats unusable play_dates as never played rather than throwing', () => {
  // A truncated write, or the column holding something that is not an array
  assert.strictEqual(lastPlayed({ play_dates: '["2026-08-1' }), '');
  assert.strictEqual(lastPlayed({ play_dates: '{"when":"2026-08-14"}' }), '');
  assert.strictEqual(lastPlayed({ play_dates: '[null, "2026-08-14"]' }), '2026-08-14');
});

// ── avgRating ───────────────────────────────────────────────────────────────

test('avgRating averages only the ratings that were actually given', () => {
  assert.strictEqual(avgRating({ my_rating: 4, wife_rating: 5 }), 4.5);
  assert.strictEqual(avgRating({ my_rating: 4, wife_rating: 0 }), 4);
  assert.strictEqual(avgRating({ my_rating: 0, wife_rating: 0 }), 0);
});

// ── buildGroups ─────────────────────────────────────────────────────────────

const BY_YEAR_DESC = [
  { id: 1, year: 2016 },
  { id: 2, year: 2015 },
  { id: 3, year: 1997 },
  { id: 4, year: 1991 },
  { id: 5, year: 1977 },
];

test('buildGroups collects records of a decade into one crate', () => {
  const groups = buildGroups(BY_YEAR_DESC, 'year');
  assert.deepStrictEqual(groups.map(g => g.label), ['2010s', '1990s', '1970s']);
  assert.deepStrictEqual(groups.map(g => g.records.length), [2, 2, 1]);
});

test('crates appear in the order their first record appears', () => {
  const ascending = BY_YEAR_DESC.slice().reverse();
  assert.deepStrictEqual(
    buildGroups(ascending, 'year').map(g => g.label),
    ['1970s', '1990s', '2010s']
  );
});

test('flattening the crates reproduces the sorted list', () => {
  // This is what keeps the detail drawer's prev/next, which walks the flat
  // filtered list, in step with the order on screen.
  const flat = buildGroups(BY_YEAR_DESC, 'year').flatMap(g => g.records);
  assert.deepStrictEqual(flat.map(r => r.id), BY_YEAR_DESC.map(r => r.id));
});

test('records that share a bucket but are not adjacent join the same crate', () => {
  // Collation puts "Aja" between "1999" and "(What's the Story)", yet both of
  // those belong to #. One crate, not two.
  const list = [
    { id: 1, album_name: '1999' },
    { id: 2, album_name: 'Aja' },
    { id: 3, album_name: "(What's the Story)" },
  ];
  const groups = buildGroups(list, 'album_name');
  assert.deepStrictEqual(groups.map(g => g.label), ['#', 'A']);
  assert.deepStrictEqual(groups[0].records.map(r => r.id), [1, 3]);
});

test('buildGroups of an empty list is an empty list of crates', () => {
  assert.deepStrictEqual(buildGroups([], 'year'), []);
});

test('last played crates run newest first and end with the never played', () => {
  // The order the page sorts them in: most recent play first, no play last
  const list = [
    { id: 1, play_dates: '["2026-08-20"]' },
    { id: 2, play_dates: '["2026-08-01"]' },
    { id: 3, play_dates: '["2026-07-11"]' },
    { id: 4, play_dates: '' },
  ];
  const groups = buildGroups(list, 'last_played');
  assert.deepStrictEqual(groups.map(g => g.label), ['August 2026', 'July 2026', 'Never played']);
  assert.deepStrictEqual(groups.map(g => g.records.length), [2, 1, 1]);
});
