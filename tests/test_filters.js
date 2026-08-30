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

const { FACETS, facetById, defaultQuery, matches, filterRecords,
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
