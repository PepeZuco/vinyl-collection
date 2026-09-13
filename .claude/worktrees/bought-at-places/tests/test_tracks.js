// Tests for the tracks column's parse/serialize rules.
// Run by tests/test_tracks.py so `pytest` stays the single command.
//
// These exist because six consumers read this column straight off
// /api/records. A record whose column holds nonsense — a hand-edited PUT, an
// imported CSV from another tool — must come back as an empty list, not throw
// and take the whole grid down with it.

const test = require('node:test');
const assert = require('node:assert');

const { parseTracks, serializeTracks, sideLettersFor, discOfSide,
        tracksBySide, likedTracks, sidesWithTracks, discMarks,
        parsePastedTracklist } = require('../static/tracks.js');

// ── parse ───────────────────────────────────────────────────────────────────

test('an empty column is an empty list', () => {
  assert.deepStrictEqual(parseTracks(''), []);
  assert.deepStrictEqual(parseTracks(null), []);
  assert.deepStrictEqual(parseTracks(undefined), []);
});

test('nonsense parses to an empty list rather than throwing', () => {
  assert.deepStrictEqual(parseTracks('not json'), []);
  assert.deepStrictEqual(parseTracks('{"side":"A"}'), []);   // object, not array
  assert.deepStrictEqual(parseTracks('42'), []);
});

test('a track keeps side, title and liked_at', () => {
  const raw = JSON.stringify([{ side: 'A', title: 'Umbabarauma', liked_at: '2026-09-09T21:40:00' }]);
  assert.deepStrictEqual(parseTracks(raw),
    [{ side: 'A', title: 'Umbabarauma', liked_at: '2026-09-09T21:40:00' }]);
});

test('an unliked track carries no liked_at key at all', () => {
  const parsed = parseTracks(JSON.stringify([{ side: 'A', title: 'Taj Mahal' }]));
  assert.strictEqual('liked_at' in parsed[0], false);
});

test('side is upper-cased and cut to one letter', () => {
  const parsed = parseTracks(JSON.stringify([{ side: 'bb', title: 'x' }]));
  assert.strictEqual(parsed[0].side, 'B');
});

// ── serialize ───────────────────────────────────────────────────────────────

test('an empty list serializes to the empty string, not "[]"', () => {
  assert.strictEqual(serializeTracks([]), '');
  assert.strictEqual(serializeTracks(null), '');
});

test('a row with no title is dropped', () => {
  assert.strictEqual(serializeTracks([{ side: 'A', title: '   ' }]), '');
});

test('titles are trimmed on the way out', () => {
  assert.strictEqual(serializeTracks([{ side: 'A', title: '  Mother  ' }]),
                     JSON.stringify([{ side: 'A', title: 'Mother' }]));
});

test('a like survives serialize', () => {
  assert.strictEqual(serializeTracks([{ side: 'A', title: 'Hey You', liked_at: '2026-08-02' }]),
                     JSON.stringify([{ side: 'A', title: 'Hey You', liked_at: '2026-08-02' }]));
});

// ── sides and discs ─────────────────────────────────────────────────────────

test('one disc is sides A and B', () => {
  assert.deepStrictEqual(sideLettersFor(1), ['A', 'B']);
});

test('a double is A through D, a triple A through F', () => {
  assert.deepStrictEqual(sideLettersFor(2), ['A', 'B', 'C', 'D']);
  assert.deepStrictEqual(sideLettersFor(3), ['A', 'B', 'C', 'D', 'E', 'F']);
});

test('a missing or nonsense disc count is treated as one disc', () => {
  assert.deepStrictEqual(sideLettersFor(0), ['A', 'B']);
  assert.deepStrictEqual(sideLettersFor(undefined), ['A', 'B']);
});

test('the side letter says which disc it is on', () => {
  assert.strictEqual(discOfSide('A'), 1);
  assert.strictEqual(discOfSide('B'), 1);
  assert.strictEqual(discOfSide('C'), 2);
  assert.strictEqual(discOfSide('F'), 3);
});

// ── grouping ────────────────────────────────────────────────────────────────

test('tracksBySide groups by letter and numbers within the side', () => {
  const list = [
    { side: 'A', title: 'one' },
    { side: 'B', title: 'three' },
    { side: 'A', title: 'two' },
  ];
  const sides = tracksBySide(list, 1);
  assert.deepStrictEqual(sides.map(s => s.letter), ['A', 'B']);
  assert.deepStrictEqual(sides[0].tracks.map(t => [t.pos, t.title]), [[1, 'one'], [2, 'two']]);
  assert.deepStrictEqual(sides[1].tracks.map(t => [t.pos, t.title]), [[1, 'three']]);
});

test('grouping keeps the RAW array index, not the position on the side', () => {
  const list = [
    { side: 'B', title: 'b-one' },
    { side: 'A', title: 'a-one' },
  ];
  const sides = tracksBySide(list, 1);
  assert.strictEqual(sides[0].tracks[0].i, 1);   // side A's song is index 1
  assert.strictEqual(sides[1].tracks[0].i, 0);
});

test('a side with nothing on it is still offered, empty', () => {
  const sides = tracksBySide([{ side: 'A', title: 'only' }], 1);
  assert.deepStrictEqual(sides[1].tracks, []);
});

test('a double offers four sides with their disc numbers', () => {
  const sides = tracksBySide([], 2);
  assert.deepStrictEqual(sides.map(s => s.disc), [1, 1, 2, 2]);
});

// ── likes ───────────────────────────────────────────────────────────────────

test('likedTracks reports only liked songs, with their raw index', () => {
  const list = [
    { side: 'A', title: 'no' },
    { side: 'A', title: 'yes', liked_at: '2026-09-09' },
  ];
  assert.deepStrictEqual(likedTracks(list), [{ i: 1, title: 'yes', liked_at: '2026-09-09' }]);
});

// ── the disc-count guard ────────────────────────────────────────────────────

test('sidesWithTracks names the sides that would lose songs', () => {
  const list = [{ side: 'A', title: 'x' }, { side: 'C', title: 'y' }];
  assert.deepStrictEqual(sidesWithTracks(list), ['A', 'C']);
});

// ── the grid marks ──────────────────────────────────────────────────────────

test('a single disc gets no marks at all', () => {
  assert.deepStrictEqual(discMarks(1), { sleeves: 0, segments: 0 });
  assert.deepStrictEqual(discMarks(undefined), { sleeves: 0, segments: 0 });
});

test('a double gets one sleeve behind and two spine segments', () => {
  assert.deepStrictEqual(discMarks(2), { sleeves: 1, segments: 2 });
});

test('a triple gets two sleeves and three segments', () => {
  assert.deepStrictEqual(discMarks(3), { sleeves: 2, segments: 3 });
});

// ── the paste box ───────────────────────────────────────────────────────────

test('a pasted block becomes one title per line', () => {
  assert.deepStrictEqual(parsePastedTracklist('Mother\nHey You'), ['Mother', 'Hey You']);
});

test('blank lines are dropped', () => {
  assert.deepStrictEqual(parsePastedTracklist('Mother\n\n\nHey You'), ['Mother', 'Hey You']);
});

test('leading track numbers are stripped', () => {
  assert.deepStrictEqual(
    parsePastedTracklist('1. Mother\n02 - Hey You\n3) Comfortably Numb'),
    ['Mother', 'Hey You', 'Comfortably Numb']);
});

test('leading side-and-number labels are stripped', () => {
  assert.deepStrictEqual(parsePastedTracklist('A1 Mother\nA2. Hey You'),
                         ['Mother', 'Hey You']);
});

test('trailing durations are stripped', () => {
  assert.deepStrictEqual(parsePastedTracklist('Mother 5:32\nHey You (4:40)'),
                         ['Mother', 'Hey You']);
});

test('a title that merely starts with a number survives intact', () => {
  assert.deepStrictEqual(parsePastedTracklist('10 Years Gone'), ['10 Years Gone']);
});
