// Tests for the one filter model shared by every surface.
// Run by tests/test_filters.py so `pytest` stays the single command.
//
// The collection and the statistics table each grew their own copy of this —
// two search boxes, two genre pickers, two condition pickers, two chip rows,
// none of them in sync. These tests define the single model that replaced both.
//
// Genre and condition used to be hardcoded, one branch each. They are entries
// in a registry now, so the bar can offer decade, country, shop and cleaning
// without another branch — and so every active filter can name itself in a
// chip, which is what makes the shelf readable back.

process.env.TZ = 'America/Sao_Paulo';

const test = require('node:test');
const assert = require('node:assert');

const { DEFAULT_FIELDS, FACETS, facetById, defaultQuery, matches, filterRecords,
        facetValues, chipsFor } = require('../static/filters.js');

let nextId = 1;
function rec(fields) {
  return Object.assign(
    { id: nextId++, artist: 'Tim Maia', album_name: 'Uma Onda', genre: 'Soul & Funk',
      condition: 'used', have_it: true, bought_where: '', notes: '',
      year: '1993', country: 'BR', cleaned_dates: '' },
    fields);
}

const deps = { parseNotes: (raw) => { try { const p = JSON.parse(raw || '[]'); return Array.isArray(p) ? p : []; } catch (e) { return []; } } };
const q = (over) => Object.assign(defaultQuery(), over);
const keep = (records, over) => filterRecords(records, q(over), deps);
const withFacet = (id, values, over) => q(Object.assign({ facets: { [id]: values } }, over));

// ── the default is "no constraint" ──────────────────────────────────────────

test('a default query keeps every owned record', () => {
  assert.strictEqual(keep([rec({}), rec({ genre: 'Rock' }), rec({ genre: '' })]).length, 3);
});

test('a record with no genre survives the default query', () => {
  // The bug this model exists to kill: the old code built its genre list with
  // .filter(Boolean), then asked whether the set had (r.genre || ''). '' was
  // never in it, so three wishlist records could not be reached by any
  // combination of controls.
  const genreless = rec({ genre: '', have_it: false });
  assert.deepStrictEqual(
    keep([genreless], { ownership: 'wishlist' }).map(r => r.id), [genreless.id]);
});

// ── ownership ───────────────────────────────────────────────────────────────

test('ownership owned keeps only records in the collection', () => {
  assert.deepStrictEqual(
    keep([rec({ have_it: true }), rec({ have_it: false })], { ownership: 'owned' })
      .map(r => r.have_it), [true]);
});

test('ownership wishlist keeps only records not yet bought', () => {
  assert.deepStrictEqual(
    keep([rec({ have_it: true }), rec({ have_it: false })], { ownership: 'wishlist' })
      .map(r => r.have_it), [false]);
});

/* The toggle only ever sets 'owned' or 'wishlist'; a hash carrying anything
 * else is normalised before it reaches here. Filtering is unconstrained by
 * that, and an unknown value keeping everything is the safe way to be wrong. */
test('an ownership the toggle cannot produce narrows nothing', () => {
  assert.strictEqual(
    keep([rec({ have_it: true }), rec({ have_it: false })], { ownership: 'all' }).length, 2);
});

// ── the facet registry ──────────────────────────────────────────────────────

test('every facet knows its own label and how to read a record', () => {
  FACETS.forEach(f => {
    assert.ok(f.label, `${f.id} has no label`);
    assert.strictEqual(typeof f.valueOf, 'function', `${f.id} cannot read a record`);
  });
});

test('a facet constraint keeps only records carrying one of its values', () => {
  const records = [rec({ genre: 'Rock' }), rec({ genre: 'Jazz' }), rec({ genre: 'Pop' })];
  assert.deepStrictEqual(
    filterRecords(records, withFacet('genre', ['Rock', 'Pop']), deps).map(r => r.genre),
    ['Rock', 'Pop']);
});

test('an empty value list matches nothing, because nothing is ticked', () => {
  const records = [rec({ genre: 'Rock' }), rec({ genre: '' })];
  assert.strictEqual(filterRecords(records, withFacet('genre', []), deps).length, 0);
});

test('"no value" is selectable rather than unreachable, on every facet', () => {
  const blank = { genre: '', condition: '', year: '', country: '', bought_where: '' };
  const r = rec(blank);
  ['genre', 'condition', 'decade', 'country', 'store'].forEach(id => {
    assert.strictEqual(matches(r, withFacet(id, ['']), deps), true, `${id} cannot select ''`);
  });
});

test('decade reads a record by the ten years its release falls in', () => {
  const records = [rec({ year: '1971' }), rec({ year: '1979' }), rec({ year: '1983' })];
  assert.strictEqual(filterRecords(records, withFacet('decade', ['1970s']), deps).length, 2);
});

test('cleaning splits into cleaned at least once and never', () => {
  const records = [
    rec({ cleaned_dates: JSON.stringify(['2026-08-02']) }),
    rec({ cleaned_dates: '' }),
    rec({ cleaned_dates: '[]' }),
  ];
  assert.strictEqual(filterRecords(records, withFacet('cleaning', ['never']), deps).length, 2);
  assert.strictEqual(filterRecords(records, withFacet('cleaning', ['cleaned']), deps).length, 1);
});

test('facets compose, and every one has to pass', () => {
  const records = [
    rec({ genre: 'Rock', condition: 'used', year: '1971' }),
    rec({ genre: 'Rock', condition: 'new',  year: '1971' }),
    rec({ genre: 'Jazz', condition: 'used', year: '1971' }),
    rec({ genre: 'Rock', condition: 'used', year: '1985' }),
  ];
  const got = filterRecords(records, q({
    facets: { genre: ['Rock'], condition: ['used'], decade: ['1970s'] } }), deps);
  assert.strictEqual(got.length, 1);
});

test('facetById finds a facet, and answers null for one that does not exist', () => {
  assert.strictEqual(facetById('genre').label, 'Genre');
  assert.strictEqual(facetById('nonsense'), null);
});

// ── the values a facet offers ───────────────────────────────────────────────

test('facetValues lists what is actually there, commonest first', () => {
  const records = [rec({ genre: 'Rock' }), rec({ genre: 'Jazz' }), rec({ genre: 'Rock' })];
  assert.deepStrictEqual(facetValues(records, defaultQuery(), 'genre', deps),
    [{ value: 'Rock', count: 2 }, { value: 'Jazz', count: 1 }]);
});

test('facetValues offers the empty bucket only when records are in it', () => {
  assert.deepStrictEqual(
    facetValues([rec({ genre: 'Rock' })], defaultQuery(), 'genre', deps).map(v => v.value),
    ['Rock']);
  assert.deepStrictEqual(
    facetValues([rec({ genre: 'Rock' }), rec({ genre: '' })], defaultQuery(), 'genre', deps)
      .map(v => v.value), ['Rock', '']);
});

test('the empty bucket sorts last, however common it is', () => {
  const records = [rec({ genre: '' }), rec({ genre: '' }), rec({ genre: 'Rock' })];
  assert.deepStrictEqual(
    facetValues(records, defaultQuery(), 'genre', deps).map(v => v.value), ['Rock', '']);
});

test('facetValues counts against the other filters, so a count is what you would get', () => {
  const records = [
    rec({ genre: 'Rock', condition: 'used' }),
    rec({ genre: 'Rock', condition: 'new' }),
    rec({ genre: 'Jazz', condition: 'used' }),
  ];
  const query = withFacet('condition', ['used']);
  const counts = Object.fromEntries(
    facetValues(records, query, 'genre', deps).map(v => [v.value, v.count]));
  assert.deepStrictEqual(counts, { Rock: 1, Jazz: 1 });
});

test('a facet does not narrow its own list, or ticking one value would hide the rest', () => {
  const records = [rec({ genre: 'Rock' }), rec({ genre: 'Jazz' })];
  const offered = facetValues(records, withFacet('genre', ['Rock']), 'genre', deps)
    .map(v => v.value).sort();
  assert.deepStrictEqual(offered, ['Jazz', 'Rock']);
});

test('facetValues respects ownership', () => {
  const records = [rec({ genre: 'Rock' }), rec({ genre: 'Jazz', have_it: false })];
  assert.deepStrictEqual(
    facetValues(records, defaultQuery(), 'genre', deps).map(v => v.value), ['Rock']);
});

// ── what the bar shows ──────────────────────────────────────────────────────

test('an unfiltered query produces no chips', () => {
  assert.deepStrictEqual(chipsFor(defaultQuery()), []);
});

test('each constrained facet becomes one chip that names its field and values', () => {
  const chips = chipsFor(q({ facets: { genre: ['Rock'], condition: ['used'] } }));
  assert.deepStrictEqual(chips.map(c => c.id), ['genre', 'condition']);
  assert.strictEqual(chips[0].label, 'Genre');
  assert.deepStrictEqual(chips[0].values, ['Rock']);
});

test('chips follow the registry order, not the order they were added', () => {
  const chips = chipsFor(q({ facets: { cleaning: ['never'], genre: ['Rock'] } }));
  assert.deepStrictEqual(chips.map(c => c.id), ['genre', 'cleaning']);
});

test('a facet ticked to nothing still shows a chip, so the empty shelf is explained', () => {
  const chips = chipsFor(q({ facets: { genre: [] } }));
  assert.deepStrictEqual(chips.map(c => c.id), ['genre']);
  assert.deepStrictEqual(chips[0].values, []);
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
  assert.strictEqual(keep(records, { text: 'samba', fields: { genre: true } }).length, 1);
});

test('search reads where a record was bought when that field is enabled', () => {
  const records = [rec({ bought_where: 'Benedito Calixto' })];
  assert.strictEqual(keep(records, { text: 'benedito' }).length, 0);
  assert.strictEqual(keep(records, { text: 'benedito', fields: { bought_at: true } }).length, 1);
});

test('search reads note text when the notes field is enabled', () => {
  const records = [rec({ notes: JSON.stringify([{ date: '2026-08-23', text: 'clicky side B' }]) })];
  assert.strictEqual(keep(records, { text: 'clicky' }).length, 0);
  assert.strictEqual(keep(records, { text: 'clicky', fields: { notes: true } }).length, 1);
});

test('malformed notes do not throw, and do not break the other fields', () => {
  const records = [rec({ artist: 'Tim Maia', notes: 'not json at all' })];
  assert.strictEqual(keep(records, { text: 'tim', fields: { artist: true, notes: true } }).length, 1);
  assert.strictEqual(keep(records, { text: 'nothing', fields: { artist: true, notes: true } }).length, 0);
});

// ── shape ───────────────────────────────────────────────────────────────────

test('matches() is the single-record form of the same rule', () => {
  const r = rec({ genre: 'Rock' });
  assert.strictEqual(matches(r, withFacet('genre', ['Jazz']), deps), false);
  assert.strictEqual(matches(r, withFacet('genre', ['Rock']), deps), true);
});

test('filterRecords does not mutate the array it is given', () => {
  const records = [rec({ genre: 'Rock' }), rec({ genre: 'Jazz' })];
  const copy = records.slice();
  filterRecords(records, withFacet('genre', ['Rock']), deps);
  assert.deepStrictEqual(records, copy);
});

test('a missing field reads as the empty value rather than throwing', () => {
  const bare = { id: 999, have_it: true };
  assert.strictEqual(matches(bare, withFacet('genre', ['']), deps), true);
  assert.strictEqual(matches(bare, withFacet('decade', ['']), deps), true);
  assert.strictEqual(matches(bare, withFacet('genre', ['Rock']), deps), false);
});

// ── when a record was last played ───────────────────────────────────────────
// The teardown's "gathering dust" view needs this, and unlike the others it is
// relative to a date — so the facet reads one off deps rather than pretending
// it can know today from a record alone.

const playedDeps = Object.assign({ today: '2026-08-29' }, deps);
const played = (records, values) =>
  filterRecords(records, withFacet('played', values), playedDeps);

test('played buckets a record by how long ago it last span', () => {
  const recent = rec({ play_dates: JSON.stringify(['2026-08-20']) });
  const months = rec({ play_dates: JSON.stringify(['2026-06-01']) });
  const stale  = rec({ play_dates: JSON.stringify(['2025-01-01']) });
  const never  = rec({ play_dates: '' });
  const all = [recent, months, stale, never];
  assert.deepStrictEqual(played(all, ['recent']).map(r => r.id), [recent.id]);
  assert.deepStrictEqual(played(all, ['months']).map(r => r.id), [months.id]);
  assert.deepStrictEqual(played(all, ['stale']).map(r => r.id),  [stale.id]);
  assert.deepStrictEqual(played(all, ['never']).map(r => r.id),  [never.id]);
});

test('gathering dust is stale and never together, which is the saved view', () => {
  const all = [
    rec({ play_dates: JSON.stringify(['2026-08-20']) }),
    rec({ play_dates: JSON.stringify(['2025-01-01']) }),
    rec({ play_dates: '' }),
  ];
  assert.strictEqual(played(all, ['stale', 'never']).length, 2);
});

test('the most recent play decides the bucket, not the first', () => {
  const r = rec({ play_dates: JSON.stringify(['2020-01-01', '2026-08-20', '2023-05-05']) });
  assert.deepStrictEqual(played([r], ['recent']).map(x => x.id), [r.id]);
});

test('an unparseable play date does not make a record look recently played', () => {
  const r = rec({ play_dates: JSON.stringify(['2026-02-30']) });
  assert.deepStrictEqual(played([r], ['never']).map(x => x.id), [r.id]);
});

test('without a date to measure against, every record reads as never played', () => {
  // deps carries no today: the facet must not guess one, and must not throw.
  const r = rec({ play_dates: JSON.stringify(['2026-08-20']) });
  assert.strictEqual(matches(r, withFacet('played', ['never']), deps), true);
});

test('played joins the registry, after cleaning', () => {
  assert.deepStrictEqual(FACETS.map(f => f.id),
    ['genre', 'condition', 'decade', 'country', 'store', 'cleaning', 'played']);
});

// ── searching by song ───────────────────────────────────────────────────────

const VinylTracks = require('../static/tracks.js');
const SONG_DEPS = { parseTracks: VinylTracks.parseTracks };

const withSongs = {
  artist: 'Pink Floyd', album_name: 'The Wall', have_it: true,
  tracks: JSON.stringify([{ side: 'A', title: 'Mother' }]),
};

test('song search is off by default', () => {
  assert.strictEqual(DEFAULT_FIELDS.song, false);
});

test('with song off, a song title does not match', () => {
  const qval = Object.assign(defaultQuery(), { text: 'mother' });
  assert.strictEqual(matches(withSongs, qval, SONG_DEPS), false);
});

test('with song on, a song title matches its record', () => {
  const qval = Object.assign(defaultQuery(), { text: 'mother' });
  qval.fields.song = true;
  assert.strictEqual(matches(withSongs, qval, SONG_DEPS), true);
});

test('song search is case-insensitive and matches a fragment', () => {
  const qval = Object.assign(defaultQuery(), { text: 'OTHE' });
  qval.fields.song = true;
  assert.strictEqual(matches(withSongs, qval, SONG_DEPS), true);
});

test('a record with no tracks never throws when song search is on', () => {
  const qval = Object.assign(defaultQuery(), { text: 'mother' });
  qval.fields.song = true;
  assert.strictEqual(matches({ artist: 'x', album_name: 'y' }, qval, SONG_DEPS), false);
});
// ── searching a compilation by the artist of one song ───────────────────────
// The record-level artist column usually lists every performer, so searching a
// name would find the record anyway. Every test here therefore searches for a
// name the column does NOT spell — a guest credited only on the song — which
// is the only way to prove the assignment itself is being read.
//
// The artist field is what reads it, not the song field: to a searcher "who is
// on this record" is one question, and a song artist is an artist.

const guestSong = {
  artist: 'Edu Lobo; Gal Costa', album_name: 'Festival', have_it: true,
  tracks: JSON.stringify([
    { side: 'A', title: 'Ponteio', artist: 'Marilia Medalha' },
    { side: 'B', title: 'Aquarela do Brasil', artist: 'Gal Costa' },
  ]),
};

test('a song artist missing from the artist column is found by default', () => {
  const qval = Object.assign(defaultQuery(), { text: 'medalha' });
  assert.strictEqual(qval.fields.song, false);
  assert.strictEqual(matches(guestSong, qval, SONG_DEPS), true);
});

test('turning the artist field off hides the song artists too', () => {
  const qval = Object.assign(defaultQuery(), { text: 'medalha' });
  qval.fields.artist = false;
  assert.strictEqual(matches(guestSong, qval, SONG_DEPS), false);
});

test('a song artist does not leak into song search, which is about titles', () => {
  const qval = Object.assign(defaultQuery(), { text: 'medalha' });
  qval.fields.artist = false;
  qval.fields.song = true;
  assert.strictEqual(matches(guestSong, qval, SONG_DEPS), false);
});

test('an unassigned song contributes no artist text of its own', () => {
  const unassigned = {
    artist: 'Tim Maia', album_name: 'Racional', have_it: true,
    tracks: JSON.stringify([{ side: 'A', title: 'Que Beleza' }]),
  };
  const qval = Object.assign(defaultQuery(), { text: 'beleza' });
  assert.strictEqual(matches(unassigned, qval, SONG_DEPS), false);
});

test('artist search still works on a record whose tracks will not parse', () => {
  const broken = { artist: 'Tim Maia', album_name: 'Racional', have_it: true,
                   tracks: 'not json at all' };
  const qval = Object.assign(defaultQuery(), { text: 'tim' });
  assert.strictEqual(matches(broken, qval, SONG_DEPS), true);
});

// ── typing without the accents ──────────────────────────────────────────────
// A shelf full of Brazilian and Spanish records is a shelf you cannot search
// on a keyboard you can reach: Milanés, Chitãozinho, Perfídia. And the
// apostrophe in "Bill Withers’ Greatest Hits" is the curly one, so even
// spelling it correctly with the key next to Enter missed the record.
//
// So both sides of the comparison are stripped of accents and apostrophes
// before they meet. On by default; the checkbox turns it off for anyone who
// wants the letters they typed to mean exactly themselves.

const accented = [
  rec({ artist: 'Pablo Milanés', album_name: 'Canta a Nicolás Guillén' }),
  rec({ artist: 'Café Tacvba', album_name: 'Re' }),
  rec({ artist: 'Bill Withers', album_name: 'Bill Withers’ Greatest Hits' }),
  rec({ artist: 'Chitãozinho & Xororó', album_name: 'Tudo por Amor' }),
];

test('loose matching is on by default', () => {
  assert.strictEqual(defaultQuery().loose, true);
});

test('an unaccented query finds the accented artist', () => {
  assert.strictEqual(keep(accented, { text: 'milanes' }).length, 1);
});

test('every accent the shelf uses folds to its bare letter', () => {
  assert.strictEqual(keep(accented, { text: 'cafe tacvba' }).length, 1);
  assert.strictEqual(keep(accented, { text: 'chitaozinho' }).length, 1);
  assert.strictEqual(keep(accented, { text: 'nicolas guillen' }).length, 1);
});

test('the accented spelling still finds its own record', () => {
  assert.strictEqual(keep(accented, { text: 'Milanés' }).length, 1);
});

test('an accented query finds a record spelled without the accent', () => {
  assert.strictEqual(keep([rec({ artist: 'Los Folkloristas' })], { text: 'fölkloristas' }).length, 1);
});

test('a dropped apostrophe still matches the word', () => {
  const records = [rec({ album_name: "Don't Stop" })];
  assert.strictEqual(keep(records, { text: 'dont stop' }).length, 1);
});

test('a typed straight quote reaches a curly one in the data', () => {
  assert.strictEqual(keep(accented, { text: "withers' greatest" }).length, 1);
});

test('loose matching leaves unrelated records out', () => {
  // typos off: these are one edit from a match, which typo tolerance forgives
  assert.strictEqual(keep(accented, { text: 'milanesa', typos: false }).length, 0);
  assert.strictEqual(keep(accented, { text: 'cafes', typos: false }).length, 0);
});

test('turning loose matching off demands the exact letters', () => {
  assert.strictEqual(keep(accented, { text: 'milanes', loose: false, typos: false }).length, 0);
  assert.strictEqual(keep(accented, { text: 'Milanés', loose: false, typos: false }).length, 1);
  assert.strictEqual(keep(accented, { text: "withers' greatest", loose: false, typos: false }).length, 0);
});

test('loose matching reads the opt-in fields too', () => {
  const records = [rec({ genre: 'Forró', bought_where: "O'Reilly Discos" })];
  assert.strictEqual(keep(records, { text: 'forro', fields: { genre: true } }).length, 1);
  assert.strictEqual(keep(records, { text: 'oreilly', fields: { bought_at: true } }).length, 1);
});

test('a song title is matched without its accents', () => {
  const record = { artist: 'Tim Maia', album_name: 'Racional', have_it: true,
                   tracks: JSON.stringify([{ side: 'A', title: 'Que Beleza É Essa' }]) };
  const qval = Object.assign(defaultQuery(), { text: 'beleza e essa' });
  qval.fields.song = true;
  assert.strictEqual(matches(record, qval, SONG_DEPS), true);
});

test('a query of nothing but apostrophes constrains nothing', () => {
  // It relaxes away to the empty string, and an empty needle is inside every
  // haystack — so without a guard one stray key would "match" all 292 records
  // while looking like a typo that found something.
  assert.strictEqual(keep(accented, { text: "'''" }).length, accented.length);
});


// ── typo tolerance ───────────────────────────────────────────────────────────
// "Picture Vook" for "Picture Book" found nothing, because the search is a
// substring test. A word the substring test misses may still be a near miss of
// a word in the record: one edit for a mid-length word, two for a long one,
// none for a short one (where one edit turns any word into any other).

const typoShelf = [
  rec({ artist: 'Simply Red', album_name: 'Picture Book' }),
  rec({ artist: 'Jorge Ben Jor', album_name: 'Samba Esquema Novo' }),
  rec({ artist: 'Tim Maia', album_name: 'Racional' }),
];

test('typo tolerance is on by default', () => {
  assert.strictEqual(defaultQuery().typos, true);
});

test('a substituted letter still finds the record', () => {
  const found = keep(typoShelf, { text: 'Picture Vook' });
  assert.deepStrictEqual(found.map(r => r.album_name), ['Picture Book']);
});

test('a swapped pair, a dropped letter and an added letter each count as one edit', () => {
  assert.strictEqual(keep(typoShelf, { text: 'pictrue book' }).length, 1);
  assert.strictEqual(keep(typoShelf, { text: 'pictue book' }).length, 1);
  assert.strictEqual(keep(typoShelf, { text: 'pictture book' }).length, 1);
});

test('a long word forgives two edits, a mid-length word only one', () => {
  assert.strictEqual(keep(typoShelf, { text: 'racionel' }).length, 1);    // 8 letters, 1 edit
  assert.strictEqual(keep(typoShelf, { text: 'esqeuma' }).length, 1);      // swap = 1 edit
  assert.strictEqual(keep(typoShelf, { text: 'rcioanal' }).length, 1);     // 8 letters, 2 edits
  assert.strictEqual(keep(typoShelf, { text: 'pictxxe' }).length, 0);      // 7 letters, 2 edits
});

test('a short word must be exact', () => {
  assert.strictEqual(keep(typoShelf, { text: 'red' }).length, 1);
  assert.strictEqual(keep(typoShelf, { text: 'rex' }).length, 0);
  assert.strictEqual(keep(typoShelf, { text: 'tom maia' }).length, 0);
});

test('a word still being typed is forgiven against the start of a word', () => {
  // 'esqxe' is 2 edits from the whole word 'esquema' but 1 from its start
  assert.strictEqual(keep(typoShelf, { text: 'esqxe' }).length, 1);
  assert.strictEqual(keep(typoShelf, { text: 'pictuer boo' }).length, 1);
  assert.strictEqual(keep(typoShelf, { text: 'picture vo' }).length, 0);  // 2 letters: exact only
});

test('every word of the query must find a word', () => {
  assert.strictEqual(keep(typoShelf, { text: 'picture vook zzzzzz' }).length, 0);
});

test('typo tolerance leaves unrelated records out', () => {
  assert.strictEqual(keep(typoShelf, { text: 'beatles' }).length, 0);
});

test('turning typo tolerance off demands the substring again', () => {
  assert.strictEqual(keep(typoShelf, { text: 'Picture Vook', typos: false }).length, 0);
  assert.strictEqual(keep(typoShelf, { text: 'Picture Book', typos: false }).length, 1);
});

test('a query with no typos finds what it always found', () => {
  ['Picture Book', 'ben jor', 'esquema', 'maia'].forEach(text => {
    assert.strictEqual(keep(typoShelf, { text, typos: true }).length,
                       keep(typoShelf, { text, typos: false }).length);
  });
});

test('typo tolerance reads only the fields that are ticked', () => {
  const records = [rec({ artist: 'Simply Red', album_name: 'Picture Book', genre: 'Pop' })];
  assert.strictEqual(keep(records, { text: 'pooop', fields: { genre: false, artist: true, album: true } }).length, 0);
  assert.strictEqual(keep(records, { text: 'poop', fields: { genre: true } }).length, 1);
});

test('typo tolerance composes with accent folding', () => {
  assert.strictEqual(keep(accented, { text: 'milaness' }).length, 1);
  assert.strictEqual(keep(accented, { text: 'milaness', typos: false }).length, 0);
});

test('a query of only punctuation is not forgiven into a match', () => {
  assert.strictEqual(keep(typoShelf, { text: '&&' }).length, 0);
});
