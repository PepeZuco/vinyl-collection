// Tests for putting the app's state in the address bar.
// Run by tests/test_urlstate.py so `pytest` stays the single command.
//
// There was not one pushState, hash or URLSearchParams in the app: you could
// not link to a record or a filter, Back left the app entirely, and a refresh
// lost your place. These rules are what a link has to survive.

process.env.TZ = 'America/Sao_Paulo';

const test = require('node:test');
const assert = require('node:assert');

const { DEFAULTS, FACET_IDS, encode, decode } = require('../static/urlstate.js');

const state = (over) => Object.assign(JSON.parse(JSON.stringify(DEFAULTS)), over);

// ── a clean slate says nothing ──────────────────────────────────────────────

test('the default state encodes to an empty hash', () => {
  // Landing on the app should not immediately dirty the address bar.
  assert.strictEqual(encode(DEFAULTS), '');
});

test('an empty hash decodes to the defaults', () => {
  assert.deepStrictEqual(decode(''), DEFAULTS);
  assert.deepStrictEqual(decode('#'), DEFAULTS);
});

// ── each thing a link can carry ─────────────────────────────────────────────

test('a tab other than the shelf is carried', () => {
  assert.strictEqual(decode(encode(state({ tab: 'timeline' }))).tab, 'timeline');
});

test('search text is carried, spaces and all', () => {
  const got = decode(encode(state({ text: 'chico buarque' })));
  assert.strictEqual(got.text, 'chico buarque');
});

test('ownership is carried when it is not the default', () => {
  assert.strictEqual(decode(encode(state({ ownership: 'wishlist' }))).ownership, 'wishlist');
  assert.strictEqual(encode(state({ ownership: 'owned' })), '');
});

test('an open record is carried', () => {
  assert.strictEqual(decode(encode(state({ recordId: 34 }))).recordId, 34);
});

test('the arrange controls are carried', () => {
  const got = decode(encode(state({ crate: 'genre', sort: 'year', dir: 'asc', view: 'list' })));
  assert.strictEqual(got.crate, 'genre');
  assert.strictEqual(got.sort, 'year');
  assert.strictEqual(got.dir, 'asc');
  assert.strictEqual(got.view, 'list');
});

// ── facets ──────────────────────────────────────────────────────────────────

test('a facet and its values are carried', () => {
  const got = decode(encode(state({ facets: { genre: ['Rock'] } })));
  assert.deepStrictEqual(got.facets, { genre: ['Rock'] });
});

test('several values of one facet are carried, not flattened', () => {
  const got = decode(encode(state({ facets: { genre: ['Rock', 'Jazz'] } })));
  assert.deepStrictEqual(got.facets.genre, ['Rock', 'Jazz']);
});

test('a value carrying a comma or an ampersand survives the round trip', () => {
  // Repeated params rather than a joined string, so no separator can collide
  // with a shop called "Benedito, Calixto & Sons".
  const messy = ['Soul & Funk', 'Benedito, Calixto', 'a=b'];
  const got = decode(encode(state({ facets: { store: messy } })));
  assert.deepStrictEqual(got.facets.store, messy);
});

test('the empty value is a value and survives', () => {
  const got = decode(encode(state({ facets: { genre: [''] } })));
  assert.deepStrictEqual(got.facets.genre, ['']);
});

test('a facet ticked to nothing survives as ticked to nothing', () => {
  // "no values selected" is not the same as "no constraint", and an empty
  // shelf has to stay explained across a reload.
  const got = decode(encode(state({ facets: { genre: [] } })));
  assert.deepStrictEqual(got.facets, { genre: [] });
});

test('several facets are carried together', () => {
  const got = decode(encode(state({ facets: { genre: ['Rock'], cleaning: ['never'] } })));
  assert.deepStrictEqual(got.facets, { genre: ['Rock'], cleaning: ['never'] });
});

// ── what a hash is allowed to do to the app ─────────────────────────────────

test('an unknown parameter is ignored rather than obeyed', () => {
  assert.deepStrictEqual(decode('#nonsense=1&tab=timeline').tab, 'timeline');
});

test('a tab that does not exist falls back to the shelf', () => {
  assert.strictEqual(decode('#tab=admin').tab, DEFAULTS.tab);
});

test('an ownership that does not exist falls back to the default', () => {
  assert.strictEqual(decode('#own=everything').ownership, DEFAULTS.ownership);
});

test('an unknown facet is dropped, so a link cannot invent a filter', () => {
  assert.deepStrictEqual(decode('#f.nonsense=x').facets, {});
});

test('a record id that is not a number is no record', () => {
  assert.strictEqual(decode('#rec=abc').recordId, null);
});

test('a malformed hash decodes to the defaults rather than throwing', () => {
  assert.doesNotThrow(() => decode('#%%%%'));
  assert.deepStrictEqual(decode('#%%%%'), DEFAULTS);
});

// ── round trips ─────────────────────────────────────────────────────────────

test('a fully loaded state survives the round trip intact', () => {
  const full = state({
    tab: 'stats', text: 'tim maia', ownership: 'wishlist',
    facets: { genre: ['Soul & Funk', 'MPB & Samba'], cleaning: ['never'] },
    crate: 'country', sort: 'plays', dir: 'asc', view: 'list', recordId: 7,
  });
  assert.deepStrictEqual(decode(encode(full)), full);
});

test('encoding is stable, so an unchanged view does not churn the history', () => {
  const a = state({ facets: { genre: ['Rock'], cleaning: ['never'] }, text: 'x' });
  assert.strictEqual(encode(a), encode(state({
    facets: { cleaning: ['never'], genre: ['Rock'] }, text: 'x' })));
});

test('encoding refuses to write a facet the bar does not offer', () => {
  // Both directions have to hold: decode drops what it does not know, and
  // encode never puts it there in the first place.
  assert.strictEqual(encode(state({ facets: { nonsense: ['x'] } })), '');
});

test('the facets a link may carry are exactly the facets the bar offers', () => {
  // Two modules each holding a list of ids is how a link silently loses a
  // filter: encode drops what it does not recognise, with no error anywhere.
  const { FACETS } = require('../static/filters.js');
  assert.deepStrictEqual(FACET_IDS.slice().sort(), FACETS.map(f => f.id).sort());
});
