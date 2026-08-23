// Tests for the pure crate-grouping logic behind the collection's group view.
// Run by tests/test_grouping.py so `pytest` stays the single command.

// Pinned before anything constructs a Date: half of what momentOf does is
// move a UTC stamp onto the local clock, which says nothing without an offset
// to move it by. Sao Paulo is UTC-3 and the collection's own timezone.
process.env.TZ = 'America/Sao_Paulo';

const test = require('node:test');
const assert = require('node:assert');

const { bucketOf, buildGroups, avgRating, momentOf, lastPlayed, compareByGroup } = require('../static/grouping.js');

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

// ── bucketOf: genre ─────────────────────────────────────────────────────────

test('genre buckets one crate per genre', () => {
  assert.strictEqual(bucketOf(rec({ genre: 'Soul & Funk' }), 'genre').label, 'Soul & Funk');
});

test('genre bucket ids ignore case so casing variants do not split a crate', () => {
  assert.strictEqual(bucketOf(rec({ genre: 'Jazz' }), 'genre').id,
                     bucketOf(rec({ genre: 'jazz' }), 'genre').id);
});

test('a record with no genre falls into the Unknown genre bucket', () => {
  assert.strictEqual(bucketOf(rec({ genre: '' }), 'genre').label, 'Unknown genre');
  assert.strictEqual(bucketOf(rec({ genre: '  ' }), 'genre').label, 'Unknown genre');
});

test('the unknown genre bucket is marked unknown so it can be pinned last', () => {
  assert.strictEqual(bucketOf(rec({ genre: '' }), 'genre').unknown, true);
  assert.strictEqual(bucketOf(rec({ genre: 'Jazz' }), 'genre').unknown, false);
});

// ── bucketOf: country ───────────────────────────────────────────────────────

test('country buckets by ISO code and carries the code so the page can draw a flag', () => {
  const b = bucketOf(rec({ country: 'BR' }), 'country');
  assert.strictEqual(b.id, 'BR');
  assert.strictEqual(b.code, 'BR');
});

test('country bucket ids uppercase the code so casing variants do not split a crate', () => {
  assert.strictEqual(bucketOf(rec({ country: 'br' }), 'country').id,
                     bucketOf(rec({ country: 'BR' }), 'country').id);
});

test('a record with no country falls into the Unknown country bucket', () => {
  const b = bucketOf(rec({ country: '' }), 'country');
  assert.strictEqual(b.label, 'Unknown country');
  assert.strictEqual(b.unknown, true);
  assert.strictEqual(b.code, undefined);
});

test('country crates rank by resolved name, so GB sorts under United Kingdom', () => {
  // The page passes countryLabelFromCode in; ranking on the raw code would put
  // GB between DE and JP instead of last.
  const names = { DE: 'Germany', JP: 'Japan', GB: 'United Kingdom' };
  const rankOf = code => bucketOf(rec({ country: code }), 'country', c => names[c]).rank;
  assert.ok(rankOf('DE') < rankOf('JP'));
  assert.ok(rankOf('JP') < rankOf('GB'));
});

// ── compareByGroup: the order the crates themselves come out in ─────────────

test('genre crates run A to Z ascending', () => {
  const jazz = rec({ genre: 'Jazz' }), rock = rec({ genre: 'Rock' });
  assert.ok(compareByGroup(jazz, rock, 'genre', 'asc') < 0);
});

test('the direction arrow reverses the crates, not just the records in them', () => {
  const jazz = rec({ genre: 'Jazz' }), rock = rec({ genre: 'Rock' });
  assert.ok(compareByGroup(jazz, rock, 'genre', 'desc') > 0);
});

test('records of the same crate compare equal so the sort field can break the tie', () => {
  const a = rec({ genre: 'Jazz', year: 1959 }), b = rec({ genre: 'Jazz', year: 1971 });
  assert.strictEqual(compareByGroup(a, b, 'genre', 'asc'), 0);
});

test('unknown crates pin last ascending', () => {
  const known = rec({ genre: 'Rock' }), unknown = rec({ genre: '' });
  assert.ok(compareByGroup(known, unknown, 'genre', 'asc') < 0);
});

test('unknown crates pin last descending too, rather than flipping to the top', () => {
  // 137 of the collection has no country — an Unknown crate that leads the page
  // whenever the arrow points down would bury everything else.
  const known = rec({ country: 'BR' }), unknown = rec({ country: '' });
  assert.ok(compareByGroup(known, unknown, 'country', 'desc') < 0);
});

test('grouping by none leaves every record in one crate so the sort field alone decides', () => {
  const a = rec({ genre: 'Jazz' }), b = rec({ genre: 'Rock' });
  assert.strictEqual(compareByGroup(a, b, 'none', 'asc'), 0);
});

test('decade crates run oldest first ascending', () => {
  assert.ok(compareByGroup(rec({ year: 1971 }), rec({ year: 1994 }), 'year', 'asc') < 0);
});

test('rating crates run lowest first ascending, so descending leads with 5 stars', () => {
  const three = rec({ my_rating: 3, wife_rating: 3 }), five = rec({ my_rating: 5, wife_rating: 5 });
  assert.ok(compareByGroup(three, five, 'avg_rating', 'asc') < 0);
  assert.ok(compareByGroup(three, five, 'avg_rating', 'desc') > 0);
});

test('sorting a list by compareByGroup makes each crate contiguous', () => {
  // This is the property buildGroups depends on, and through it the detail
  // drawer's prev/next: crates fall out of one flat sort, never a regroup.
  const list = [
    rec({ id: 1, genre: 'Rock' }), rec({ id: 2, genre: 'Jazz' }),
    rec({ id: 3, genre: '' }),     rec({ id: 4, genre: 'Rock' }),
    rec({ id: 5, genre: 'Jazz' }),
  ];
  const sorted = list.slice().sort((a, b) => compareByGroup(a, b, 'genre', 'asc'));
  assert.deepStrictEqual(buildGroups(sorted, 'genre').map(g => g.label),
                         ['Jazz', 'Rock', 'Unknown genre']);
});

// ── momentOf ────────────────────────────────────────────────────────────────

test('a moment recorded with a local time keeps that exact clock', () => {
  assert.deepStrictEqual(momentOf('2026-08-14T21:12:44'),
    { day: '2026-08-14', time: '21:12', at: '2026-08-14T21:12:44' });
});

test('a date recorded before times were kept orders as midnight but shows no clock', () => {
  // "assume 00" for ordering — without claiming the record played at midnight
  assert.deepStrictEqual(momentOf('2026-08-14'),
    { day: '2026-08-14', time: '', at: '2026-08-14T00:00:00' });
});

test('a UTC stamp is read onto the local clock, day included', () => {
  // What the +/- buttons wrote before this: 00:12 UTC is the previous evening
  // here, and filing it under the 24th would put the play on a day it did not
  // happen — the whole reason the calendar slid evening plays forward.
  assert.deepStrictEqual(momentOf('2026-08-24T00:12:44.115Z'),
    { day: '2026-08-23', time: '21:12', at: '2026-08-23T21:12:44' });
});

test('an explicit offset is honored, in either punctuation', () => {
  // +HHMM has to survive too: ISO parsing only guarantees the +HH:MM form
  assert.strictEqual(momentOf('2026-08-14T21:12:44+02:00').at, '2026-08-14T16:12:44');
  assert.strictEqual(momentOf('2026-08-14T21:12:44+0200').at, '2026-08-14T16:12:44');
});

test('a minute-precision stamp fills in seconds so stamps stay comparable', () => {
  assert.strictEqual(momentOf('2026-08-14T21:12').at, '2026-08-14T21:12:00');
});

test('momentOf reads anything unparseable as no moment rather than throwing', () => {
  const none = { day: '', time: '', at: '' };
  [null, undefined, '', 'nonsense', '2026-08-1', '2026-13-40T99:99:99', 42].forEach(bad =>
    assert.deepStrictEqual(momentOf(bad), none, String(bad)));
});

test('normalized stamps sort into the order the records were played', () => {
  // The point of recording the time at all. Mixed shapes and all.
  const logged = ['2026-08-23T21:12:44', '2026-08-23', '2026-08-24T00:40:00.000Z',
                  '2026-08-23T09:05:00'];
  assert.deepStrictEqual(logged.slice().sort((a, b) => momentOf(a).at.localeCompare(momentOf(b).at)),
    ['2026-08-23', '2026-08-23T09:05:00', '2026-08-23T21:12:44', '2026-08-24T00:40:00.000Z']);
});

test('a bought date carrying a time still crates under its own month', () => {
  assert.strictEqual(bucketOf({ bought_date: '2026-08-14T21:12:00' }, 'bought_date').label,
                     'August 2026');
  assert.strictEqual(bucketOf({ bought_date: '' }, 'bought_date').label, 'No date');
});

// ── lastPlayed ──────────────────────────────────────────────────────────────

test('lastPlayed returns the most recent play regardless of stored order', () => {
  assert.strictEqual(lastPlayed({ play_dates: '["2026-08-14","2024-01-09"]' }), '2026-08-14T00:00:00');
  assert.strictEqual(lastPlayed({ play_dates: '["2024-01-09","2026-08-14"]' }), '2026-08-14T00:00:00');
});

test('lastPlayed separates two plays on the same day by their time', () => {
  assert.strictEqual(lastPlayed({ play_dates: '["2026-08-14T21:12:44","2026-08-14T09:05:00"]' }),
                     '2026-08-14T21:12:44');
});

test('lastPlayed reads a play count of none as no date at all', () => {
  assert.strictEqual(lastPlayed({}), '');
  assert.strictEqual(lastPlayed({ play_dates: '[]' }), '');
});

test('lastPlayed treats unusable play_dates as never played rather than throwing', () => {
  // A truncated write, or the column holding something that is not an array
  assert.strictEqual(lastPlayed({ play_dates: '["2026-08-1' }), '');
  assert.strictEqual(lastPlayed({ play_dates: '{"when":"2026-08-14"}' }), '');
  assert.strictEqual(lastPlayed({ play_dates: '[null, "2026-08-14"]' }), '2026-08-14T00:00:00');
});

test('a record last played late in the evening crates under that evening', () => {
  // The UTC stamp says September 1st; locally the record played on August 31st
  assert.strictEqual(bucketOf({ play_dates: '["2026-09-01T01:30:00.000Z"]' }, 'last_played').label,
                     'August 2026');
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

test('buildGroups carries the country code onto the crate so the header can draw a flag', () => {
  const groups = buildGroups([rec({ country: 'BR' })], 'country', c => 'Brazil');
  assert.strictEqual(groups[0].code, 'BR');
  assert.strictEqual(groups[0].label, 'Brazil');
});

test('a crate with no country carries no code, so no flag is drawn for it', () => {
  const groups = buildGroups([rec({ country: '' })], 'country');
  assert.strictEqual(groups[0].code, undefined);
  assert.strictEqual(groups[0].label, 'Unknown country');
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
