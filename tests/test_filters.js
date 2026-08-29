// Tests for the one filter model shared by every surface.
// Run by tests/test_filters.py so `pytest` stays the single command.
//
// The collection and the statistics table each grew their own copy of this —
// two search boxes, two genre pickers, two condition pickers, two chip rows,
// none of them in sync. These tests define the single model that replaces both.

process.env.TZ = 'America/Sao_Paulo';

const test = require('node:test');
const assert = require('node:assert');

const { defaultQuery, matches, filterRecords, genreUniverse } = require('../static/filters.js');

let nextId = 1;
function rec(fields) {
  return Object.assign(
    { id: nextId++, artist: 'Tim Maia', album_name: 'Uma Onda', genre: 'Soul & Funk',
      condition: 'used', have_it: true, bought_where: '', notes: '' },
    fields);
}

// The notes column is a JSON array of {date, text}; the real parser lives in the
// template, so the model takes it as a dependency rather than importing the DOM.
const deps = { parseNotes: (raw) => { try { return JSON.parse(raw || '[]'); } catch (e) { return []; } } };
const keep = (records, q) => filterRecords(records, Object.assign(defaultQuery(), q), deps);

// ── the default is "no constraint" ──────────────────────────────────────────

test('a default query keeps every owned record', () => {
  const records = [rec({}), rec({ genre: 'Rock' }), rec({ genre: '' })];
  assert.strictEqual(keep(records, {}).length, 3);
});

test('a record with no genre survives the default query', () => {
  // The bug this model exists to kill: the old code built its genre universe
  // with .filter(Boolean), then asked whether selectedGenres.has(r.genre || '').
  // '' was never in the set, so three wishlist records could not be reached by
  // any combination of controls.
  const genreless = rec({ genre: '', have_it: false });
  assert.deepStrictEqual(
    keep([genreless], { ownership: 'wishlist' }).map(r => r.id),
    [genreless.id]);
});

// ── ownership ───────────────────────────────────────────────────────────────

test('ownership owned keeps only records in the collection', () => {
  const records = [rec({ have_it: true }), rec({ have_it: false })];
  assert.deepStrictEqual(keep(records, { ownership: 'owned' }).map(r => r.have_it), [true]);
});

test('ownership wishlist keeps only records not yet bought', () => {
  const records = [rec({ have_it: true }), rec({ have_it: false })];
  assert.deepStrictEqual(keep(records, { ownership: 'wishlist' }).map(r => r.have_it), [false]);
});

test('ownership all keeps both, which the old UI could never do', () => {
  const records = [rec({ have_it: true }), rec({ have_it: false })];
  assert.strictEqual(keep(records, { ownership: 'all' }).length, 2);
});

// ── genre ───────────────────────────────────────────────────────────────────

test('a genre constraint keeps only the named genres', () => {
  const records = [rec({ genre: 'Rock' }), rec({ genre: 'Jazz' }), rec({ genre: 'Pop' })];
  assert.deepStrictEqual(
    keep(records, { genres: ['Rock', 'Pop'] }).map(r => r.genre), ['Rock', 'Pop']);
});

test('"no genre" is a selectable value, not an unreachable state', () => {
  const records = [rec({ genre: 'Rock' }), rec({ genre: '' })];
  assert.deepStrictEqual(keep(records, { genres: [''] }).map(r => r.genre), ['']);
});

test('an empty genre list matches nothing, because nothing is ticked', () => {
  const records = [rec({ genre: 'Rock' }), rec({ genre: '' })];
  assert.strictEqual(keep(records, { genres: [] }).length, 0);
});

// ── condition ───────────────────────────────────────────────────────────────

test('a condition constraint keeps only the named conditions', () => {
  const records = [rec({ condition: 'new' }), rec({ condition: 'used' }), rec({ condition: '' })];
  assert.deepStrictEqual(
    keep(records, { conditions: ['new', ''] }).map(r => r.condition), ['new', '']);
});

// ── search ──────────────────────────────────────────────────────────────────

test('search looks at artist and album by default', () => {
  const records = [rec({ artist: 'Chico Buarque' }), rec({ album_name: 'Chico Vive' }), rec({ artist: 'Elis' })];
  assert.strictEqual(keep(records, { text: 'chico' }).length, 2);
});

test('search is case insensitive', () => {
  assert.strictEqual(keep([rec({ artist: 'Tim Maia' })], { text: 'TIM' }).length, 1);
});

test('search ignores genre unless the genre field is enabled', () => {
  const records = [rec({ artist: 'Elis', genre: 'MPB & Samba' })];
  assert.strictEqual(keep(records, { text: 'samba' }).length, 0);
  assert.strictEqual(
    keep(records, { text: 'samba', fields: { genre: true } }).length, 1);
});

test('search reads where a record was bought when that field is enabled', () => {
  const records = [rec({ bought_where: 'Benedito Calixto' })];
  assert.strictEqual(keep(records, { text: 'benedito' }).length, 0);
  assert.strictEqual(
    keep(records, { text: 'benedito', fields: { bought_at: true } }).length, 1);
});

test('search reads note text when the notes field is enabled', () => {
  const records = [rec({ notes: JSON.stringify([{ date: '2026-08-23', text: 'clicky side B' }]) })];
  assert.strictEqual(keep(records, { text: 'clicky' }).length, 0);
  assert.strictEqual(
    keep(records, { text: 'clicky', fields: { notes: true } }).length, 1);
});

test('malformed notes do not throw, and do not break the other fields', () => {
  const records = [rec({ artist: 'Tim Maia', notes: 'not json at all' })];
  assert.strictEqual(
    keep(records, { text: 'tim', fields: { artist: true, notes: true } }).length, 1);
  assert.strictEqual(
    keep(records, { text: 'nothing', fields: { artist: true, notes: true } }).length, 0);
});

// ── composition ─────────────────────────────────────────────────────────────

test('constraints compose, and every one has to pass', () => {
  const records = [
    rec({ artist: 'Tim Maia', genre: 'Soul & Funk', condition: 'used', have_it: true }),
    rec({ artist: 'Tim Maia', genre: 'Soul & Funk', condition: 'new',  have_it: true }),
    rec({ artist: 'Tim Maia', genre: 'Rock',        condition: 'used', have_it: true }),
    rec({ artist: 'Elis',     genre: 'Soul & Funk', condition: 'used', have_it: true }),
    rec({ artist: 'Tim Maia', genre: 'Soul & Funk', condition: 'used', have_it: false }),
  ];
  const got = keep(records, {
    text: 'tim', genres: ['Soul & Funk'], conditions: ['used'], ownership: 'owned' });
  assert.strictEqual(got.length, 1);
});

test('matches() is the single-record form of the same rule', () => {
  const r = rec({ genre: 'Rock' });
  const q = Object.assign(defaultQuery(), { genres: ['Jazz'] });
  assert.strictEqual(matches(r, q, deps), false);
  assert.strictEqual(matches(r, Object.assign(defaultQuery(), { genres: ['Rock'] }), deps), true);
});

test('filterRecords does not mutate the array it is given', () => {
  const records = [rec({ genre: 'Rock' }), rec({ genre: 'Jazz' })];
  const copy = records.slice();
  keep(records, { genres: ['Rock'] });
  assert.deepStrictEqual(records, copy);
});


test('a missing genre is treated the same as an empty one', () => {
  // Records built client-side before a save can carry no genre key at all.
  const noKey = rec({}); delete noKey.genre;
  assert.strictEqual(matches(noKey, Object.assign(defaultQuery(), { genres: [''] }), deps), true);
  assert.strictEqual(matches(noKey, Object.assign(defaultQuery(), { genres: ['Rock'] }), deps), false);
});

// ── the selectable genres ───────────────────────────────────────────────────
// This is where the invisible-records bug actually lived: the universe was
// built with .filter(Boolean), so "no genre" was never offered as a choice and
// the predicate could never be satisfied for those records.

test('the genre universe lists every genre in use, sorted', () => {
  const records = [rec({ genre: 'Rock' }), rec({ genre: 'Jazz' }), rec({ genre: 'Rock' })];
  assert.deepStrictEqual(genreUniverse(records), ['Jazz', 'Rock']);
});

test('the genre universe offers "no genre" when some record has none', () => {
  const records = [rec({ genre: 'Rock' }), rec({ genre: '' })];
  assert.deepStrictEqual(genreUniverse(records), ['Rock', '']);
});

test('the genre universe omits "no genre" when every record has one', () => {
  assert.deepStrictEqual(genreUniverse([rec({ genre: 'Rock' })]), ['Rock']);
});

test('"no genre" sorts last, so it reads as the leftover bucket', () => {
  const records = [rec({ genre: '' }), rec({ genre: 'Zydeco' }), rec({ genre: 'Afrobeat' })];
  assert.deepStrictEqual(genreUniverse(records), ['Afrobeat', 'Zydeco', '']);
});

test('every record in a collection is reachable by selecting the whole universe', () => {
  const records = [rec({ genre: 'Rock' }), rec({ genre: '' }), rec({ genre: 'Jazz' })];
  const q = Object.assign(defaultQuery(), { genres: genreUniverse(records) });
  assert.strictEqual(filterRecords(records, q, deps).length, records.length);
});
