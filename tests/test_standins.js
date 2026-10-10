// The stand-in section's rules: which candidates a search keeps, which rows a
// pill shows, how a hit reads, and which songs go on the playlist. Pure, so
// they are pinned here rather than through the DOM.

const test = require('node:test');
const assert = require('node:assert');

const { filterCandidates, tracksKeeps, pillKeeps, hitLabel, sidesFor, discCountFor, pickedUris, songState } =
  require('../static/standins.js');

const rec = (artist, album_name) => ({ artist, album_name });

test('the candidate search matches artist or album, ignoring case and accents', () => {
  const list = [rec('Elis Regina', 'Elis'), rec('Caetano Veloso', 'Transa'), rec('Gal Costa', 'Água Viva')];
  assert.deepStrictEqual(filterCandidates(list, 'ELIS').map(r => r.artist), ['Elis Regina']);
  assert.deepStrictEqual(filterCandidates(list, 'agua').map(r => r.artist), ['Gal Costa']);
  assert.deepStrictEqual(filterCandidates(list, 'veloso transa').map(r => r.artist), ['Caetano Veloso']);
});

test('an empty search keeps every candidate', () => {
  const list = [rec('A', 'B'), rec('C', 'D')];
  assert.strictEqual(filterCandidates(list, '  ').length, 2);
});

test('pills split matched from not matched, and none shows all', () => {
  assert.strictEqual(pillKeeps({ matched: true }, 'matched'), true);
  assert.strictEqual(pillKeeps({ matched: true }, 'unmatched'), false);
  assert.strictEqual(pillKeeps({ matched: false }, 'unmatched'), true);
  assert.strictEqual(pillKeeps({ matched: false }, ''), true);
});

test('the tracks filter splits records with a tracklist from those without', () => {
  assert.strictEqual(tracksKeeps({ has_tracks: true }, 'with'), true);
  assert.strictEqual(tracksKeeps({ has_tracks: false }, 'with'), false);
  assert.strictEqual(tracksKeeps({ has_tracks: false }, 'without'), true);
  assert.strictEqual(tracksKeeps({ has_tracks: true }, 'without'), false);
  assert.strictEqual(tracksKeeps({ has_tracks: false }, ''), true);
});

test('a hit reads as track, album and year; a miss says so', () => {
  assert.strictEqual(hitLabel({ name: 'Song', album: 'Best Of', year: '1999' }), 'Song · Best Of · 1999');
  assert.strictEqual(hitLabel({ name: 'Song', album: '', year: '' }), 'Song');
  assert.strictEqual(hitLabel(null), 'not found on Spotify');
});

test('sides follow the disc count, and the disc count follows the sides', () => {
  assert.deepStrictEqual(sidesFor(1), ['A', 'B']);
  assert.deepStrictEqual(sidesFor(2), ['A', 'B', 'C', 'D']);
  assert.deepStrictEqual(sidesFor(0), ['A', 'B']);
  assert.strictEqual(discCountFor([{ side: 'A' }, { side: 'D' }]), 2);
  assert.strictEqual(discCountFor([]), 1);
});

test('only ticked songs with a hit go on the playlist, in tracklist order, once each', () => {
  const songs = [{ hit: { uri: 'u1' } }, { hit: null }, { hit: { uri: 'u2' } }, { hit: { uri: 'u1' } }];
  assert.deepStrictEqual(pickedUris(songs, new Set([0, 1, 2, 3])), ['u1', 'u2']);
  assert.deepStrictEqual(pickedUris(songs, new Set([2])), ['u2']);
});

test('a suggestion reads as a question and only goes on the playlist once ticked', () => {
  const sug = { uri: 'u9', name: 'Chiquitita', album: 'Voulez-Vous', year: '1979' };
  assert.strictEqual(hitLabel(null, sug), 'did you mean Chiquitita · Voulez-Vous · 1979?');
  const songs = [{ hit: null, suggestion: sug }];
  assert.deepStrictEqual(pickedUris(songs, new Set()), []);
  assert.deepStrictEqual(pickedUris(songs, new Set([0])), ['u9']);
});

test('a song is a hit, a suggestion or a miss', () => {
  assert.strictEqual(songState({ hit: { uri: 'u' } }), 'hit');
  assert.strictEqual(songState({ hit: null, suggestion: { uri: 'u' } }), 'suggestion');
  assert.strictEqual(songState({ hit: null }), 'miss');
});
