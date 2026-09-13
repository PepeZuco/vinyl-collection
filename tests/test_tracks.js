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
        tracksBySide, likedTracks, sidesWithTracks, formatTag,
        discGroups, formatSummary, capitalizeName,
        parsePastedTracklist, artistsInUse } = require('../static/tracks.js');

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

// ── the grid card's format tag ──────────────────────────────────────────────
//
// The tag replaced the spine segments and the sleeve stack, which counted the
// discs in marks you had to decode and never said the size at all. It earns
// its place on the artwork only when there is something to say: a plain single
// 12" is what most of the shelf is, and a label on all 250 cards is furniture
// the eye stops seeing — the same trade discMarks used to make.

test('a plain single 12" gets no tag — it is what most of the shelf is', () => {
  assert.strictEqual(formatTag(1, '12'), '');
});

test('an unknown size on a single disc says nothing rather than guessing 12"', () => {
  assert.strictEqual(formatTag(1, ''), '');
  assert.strictEqual(formatTag(1, null), '');
  assert.strictEqual(formatTag(undefined, undefined), '');
});

test('a size that is not 12" is worth saying on its own', () => {
  assert.strictEqual(formatTag(1, '7'), '7"');
  assert.strictEqual(formatTag(1, '10'), '10"');
});

test('more than one disc is worth saying, with the size when it is known', () => {
  assert.strictEqual(formatTag(2, '12'), '2 × 12"');
  assert.strictEqual(formatTag(3, '7'), '3 × 7"');
});

test('a multi-disc record of unknown size counts the discs alone', () => {
  assert.strictEqual(formatTag(2, ''), '2 discs');
});

// ── the tracklist's disc groups ─────────────────────────────────────────────
//
// The tracklist draws a rail down the whole height of a disc, so it needs the
// sides GROUPED by disc rather than the flat run tracksBySide returns: a rail
// has to know where the disc ends, not just where it starts.

test('a single disc is one group holding both its sides', () => {
  const groups = discGroups([{ side: 'A', title: 'x' }], 1);
  assert.strictEqual(groups.length, 1);
  assert.deepStrictEqual(groups[0].letters, ['A', 'B']);
});

test('a double splits A/B from C/D', () => {
  const groups = discGroups([], 2);
  assert.deepStrictEqual(groups.map(g => g.disc), [1, 2]);
  assert.deepStrictEqual(groups.map(g => g.letters), [['A', 'B'], ['C', 'D']]);
});

test('a group counts the songs on both of its sides', () => {
  const list = [
    { side: 'A', title: 'one' }, { side: 'A', title: 'two' },
    { side: 'B', title: 'three' },
    { side: 'C', title: 'four' },
  ];
  assert.deepStrictEqual(discGroups(list, 2).map(g => g.songs), [3, 1]);
});

test('a group carries the same side objects tracksBySide builds', () => {
  const list = [{ side: 'A', title: 'Umbabarauma' }];
  const [first] = discGroups(list, 1);
  assert.deepStrictEqual(first.sides[0], tracksBySide(list, 1)[0]);
});

// ── the tracklist's format summary ──────────────────────────────────────────

test('the summary reports the discs, the size, the sides and the songs', () => {
  const list = [{ side: 'A', title: 'one' }, { side: 'C', title: 'two' }];
  assert.deepStrictEqual(formatSummary(list, 2, '12'),
    { discs: 2, size: 12, sides: 4, songs: 2 });
});

test('an unknown size comes back null, so the drawing can skip it', () => {
  assert.strictEqual(formatSummary([], 1, '').size, null);
  assert.strictEqual(formatSummary([], 1, undefined).size, null);
});

test('a nonsense size is rejected rather than drawn at some absurd width', () => {
  assert.strictEqual(formatSummary([], 1, '33').size, null);
  assert.strictEqual(formatSummary([], 1, 'twelve').size, null);
});

test('sides are the ones the record physically has, not the ones with songs', () => {
  assert.strictEqual(formatSummary([], 2, '12').sides, 4);
});

test('a missing disc count is one disc, the way it is everywhere else', () => {
  assert.strictEqual(formatSummary([], undefined, '12').discs, 1);
  assert.strictEqual(formatSummary([], 0, '12').discs, 1);
});

// ── a name as it is written on a sleeve ──────────────────────────
// Only the FIRST letter of each word is touched. Lowercasing the rest would
// rewrite the names that are meant to be read the way they are typed — an
// acronym, an initialled band, a stylised stage name — and a tracklist full of
// "Dna" is worse than one full of "dna".

test('each word of a name starts capital', () => {
  assert.strictEqual(capitalizeName('the boy in the bubble'), 'The Boy In The Bubble');
});

test('a name already capitalised is left as it is', () => {
  assert.strictEqual(capitalizeName('Hey You'), 'Hey You');
});

test('letters after the first are never touched', () => {
  assert.strictEqual(capitalizeName('DNA'), 'DNA');
  assert.strictEqual(capitalizeName('R.E.M.'), 'R.E.M.');
  assert.strictEqual(capitalizeName('MOTHER'), 'MOTHER');
  assert.strictEqual(capitalizeName('will.i.am'), 'Will.i.am');
});

test('a word that opens with a non-letter keeps its shape', () => {
  assert.strictEqual(capitalizeName('10 years gone'), '10 Years Gone');
  assert.strictEqual(capitalizeName('(reprise)'), '(reprise)');
  assert.strictEqual(capitalizeName('\u00e9lan vital'), '\u00c9lan Vital');
});

test('the spacing between words survives exactly', () => {
  assert.strictEqual(capitalizeName('hey  you'), 'Hey  You');
  assert.strictEqual(capitalizeName('side a\nside b'), 'Side A\nSide B');
  assert.strictEqual(capitalizeName('  leading space'), '  Leading Space');
  assert.strictEqual(capitalizeName('trailing space  '), 'Trailing Space  ');
});

test('an empty or missing name is the empty string, never a throw', () => {
  assert.strictEqual(capitalizeName(''), '');
  assert.strictEqual(capitalizeName(null), '');
  assert.strictEqual(capitalizeName(undefined), '');
  assert.strictEqual(capitalizeName('   '), '   ');
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

// ── the per-song artist ─────────────────────────────────────────────────────
// Only a compilation carries these: the name says WHICH of the record's
// semicolon-separated artists played this song. Absent means unassigned, the
// same "absent, never falsy" shape liked_at already uses.

test('a track keeps the artist it was assigned', () => {
  const raw = JSON.stringify([{ side: 'A', title: 'Aquarela do Brasil', artist: 'Gal Costa' }]);
  assert.deepStrictEqual(parseTracks(raw),
    [{ side: 'A', title: 'Aquarela do Brasil', artist: 'Gal Costa' }]);
});

test('an unassigned track carries no artist key at all', () => {
  const parsed = parseTracks(JSON.stringify([{ side: 'A', title: 'Taj Mahal' }]));
  assert.strictEqual('artist' in parsed[0], false);
});

test('a blank artist parses as unassigned rather than an empty name', () => {
  const parsed = parseTracks(JSON.stringify([{ side: 'A', title: 'x', artist: '   ' }]));
  assert.strictEqual('artist' in parsed[0], false);
});

test('an artist survives serialize, trimmed', () => {
  assert.strictEqual(serializeTracks([{ side: 'A', title: 'Ponteio', artist: '  Edu Lobo  ' }]),
                     JSON.stringify([{ side: 'A', title: 'Ponteio', artist: 'Edu Lobo' }]));
});

test('clearing the picker drops the artist key instead of storing an empty one', () => {
  assert.strictEqual(serializeTracks([{ side: 'A', title: 'Ponteio', artist: '' }]),
                     JSON.stringify([{ side: 'A', title: 'Ponteio' }]));
});

test('the side view carries the artist through to the renderers', () => {
  const sides = tracksBySide([{ side: 'A', title: 'Ponteio', artist: 'Edu Lobo' },
                              { side: 'A', title: 'Upa Neguinho' }], 1);
  assert.strictEqual(sides[0].tracks[0].artist, 'Edu Lobo');
  assert.strictEqual('artist' in sides[0].tracks[1], false);
});

test('artistsInUse counts the songs assigned to a name', () => {
  const list = [{ side: 'A', title: 'one', artist: 'Gal Costa' },
                { side: 'A', title: 'two' },
                { side: 'B', title: 'three', artist: 'Gal Costa' },
                { side: 'B', title: 'four', artist: 'Edu Lobo' }];
  assert.strictEqual(artistsInUse(list, 'Gal Costa'), 2);
  assert.strictEqual(artistsInUse(list, 'Edu Lobo'), 1);
  assert.strictEqual(artistsInUse(list, 'Nobody'), 0);
});

test('artistsInUse matches the name exactly, ignoring only surrounding space', () => {
  const list = [{ side: 'A', title: 'one', artist: 'Gal Costa' }];
  assert.strictEqual(artistsInUse(list, '  Gal Costa  '), 1);
  assert.strictEqual(artistsInUse(list, 'gal costa'), 0);
});
