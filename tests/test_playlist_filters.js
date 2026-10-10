// The browser copy of playlist_filters.py, held to the same shared cases.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const F = require('../static/playlist_filters.js');
const CASES = JSON.parse(fs.readFileSync(
  path.join(__dirname, 'fixtures', 'playlist_filter_cases.json'), 'utf8'));

for (const c of CASES.match) {
  test('match: ' + c.why, () => {
    assert.strictEqual(F.matches(c.record, F.normalize(c.filters)), c.match);
  });
}

for (const c of CASES.names) {
  test('name: ' + c.name, () => {
    assert.strictEqual(F.suggestName(F.normalize(c.filters)), c.name);
  });
}

test('form strings become numbers and blanks disappear', () => {
  assert.deepStrictEqual(
    F.normalize({ liked: true, year_from: '1970', year_to: '', genres: [], places: [' '],
                  pepe_min: '4', jenni_min: '', bought_from: '', bought_to: '' }),
    { liked: true, year_from: 1970, pepe_min: 4 });
});

test('decades become sorted unique years', () => {
  assert.deepStrictEqual(F.normalize({ decades: ['1980', 1960, 1960, 1975, 'x'] }),
    { liked: true, decades: [1960, 1980] });
  assert.deepStrictEqual(F.normalize({ decades: [] }), { liked: true });
});

test('a bad value is dropped, not thrown', () => {
  assert.deepStrictEqual(F.normalize({ year_from: 'abc', bought_to: '2024-1-1' }), { liked: true });
});

const REC = (o) => Object.assign({ have_it: true, spotify_url: 'https://open.spotify.com/album/x',
  tracks: JSON.stringify([{ side: 'A', title: 's', liked_at: '2026-01-01' }]) }, o);

test('the count is owned records with a link that pass the filters', () => {
  const records = [
    REC({ genre: 'Rock' }),
    REC({ genre: 'Rock', have_it: false }),
    REC({ genre: 'Rock', spotify_url: '' }),
    REC({ genre: 'Jazz' }),
  ];
  assert.strictEqual(F.countMatching(records, F.normalize({ liked: false, genres: ['rock'] })), 1);
});

test('the owned filter picks owned, wishlist or both', () => {
  const records = [REC({}), REC({ have_it: false }), REC({ have_it: false, spotify_url: '' })];
  assert.strictEqual(F.countMatching(records, F.normalize({ liked: false })), 1);
  assert.strictEqual(F.countMatching(records, F.normalize({ liked: false, owned: 'wishlist' })), 1);
  assert.strictEqual(F.countMatching(records, F.normalize({ liked: false, owned: 'all' })), 2);
  assert.deepStrictEqual(F.normalize({ owned: 'owned' }), { liked: true });
});

test('liked also needs a hearted song', () => {
  const records = [REC({}), REC({ tracks: JSON.stringify([{ side: 'A', title: 's' }]) }),
                   REC({ tracks: '' }), REC({ tracks: 'not json' })];
  assert.strictEqual(F.countMatching(records, F.normalize({ liked: true })), 1);
  assert.strictEqual(F.countMatching(records, F.normalize({ liked: false })), 4);
});

test('calendar-invalid dates are rejected', () => {
  assert.deepStrictEqual(
    F.normalize({ bought_from: '2023-02-29', bought_to: '2024-04-31' }),
    { liked: true });
});

test('leap day in a leap year is valid', () => {
  assert.deepStrictEqual(
    F.normalize({ bought_from: '2024-02-29' }),
    { liked: true, bought_from: '2024-02-29' });
});

test('sort and order: defaults stay out, and neither shows in the name', () => {
  assert.deepStrictEqual(F.normalize({ sort: 'artist', order: 'asc' }), { liked: true });
  const f = F.normalize({ sort: 'year', order: 'desc' });
  assert.deepStrictEqual(f, { liked: true, sort: 'year', order: 'desc' });
  assert.strictEqual(F.suggestName(f), F.suggestName({ liked: true }));
});

test('arrange mirrors the server: artist, year (yearless last) and liked songs', () => {
  const rec = (artist, album_name, year, n) => ({
    artist, album_name, year,
    tracks: Array.from({ length: n }, (_, i) => ({ title: String(i), liked_at: 'x' })) });
  const rs = [rec('Beta', 'B', '1980', 1), rec('alpha', 'A', '', 3),
              rec('Gamma', 'G', '1970', 2), rec('Alpha', 'Z', '1970', 3)];
  const order = o => F.arrange(rs, F.normalize(o)).map(r => r.album_name).join('');
  assert.strictEqual(order({}), 'AZBG');
  assert.strictEqual(order({ order: 'desc' }), 'GBAZ');
  assert.strictEqual(order({ sort: 'year' }), 'ZGBA');
  assert.strictEqual(order({ sort: 'year', order: 'desc' }), 'BZGA');
  assert.strictEqual(order({ sort: 'liked', order: 'desc' }), 'AZGB');
  assert.strictEqual(order({ sort: 'liked' }), 'BGAZ');
});
