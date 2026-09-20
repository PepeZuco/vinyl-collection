// The phone form's decidable rules, tested without a DOM.
// Run by tests/test_phoneform.py so `pytest` stays the single command.
//
// Everything here is a pure function on purpose. The phone redraw is mostly
// wiring, and wiring is what test_boot.js is for; these are the parts that
// have an answer worth pinning — which rail segment is which, what a section
// row says about a record, and whether a drag was a dismissal or a scroll.

const test = require('node:test');
const assert = require('node:assert');

const {
  STEPS, railStates, rankPlaces, logSectionOpen, logCount,
  recordPreview, purchasePreview, logPreview, objectPreview, dragDismisses,
} = require('../static/phoneform.js');

// ── the rail ────────────────────────────────────────────────────────────────

test('the rail has one segment per step', () => {
  assert.strictEqual(railStates(1).length, 4);
  assert.strictEqual(STEPS.length, 4);
});

test('steps before the current one are done, the current one is now', () => {
  assert.deepStrictEqual(railStates(3), ['done', 'done', 'now', 'ahead']);
});

test('on the first step nothing is done yet', () => {
  assert.deepStrictEqual(railStates(1), ['now', 'ahead', 'ahead', 'ahead']);
});

test('on the last step nothing is ahead', () => {
  assert.deepStrictEqual(railStates(4), ['done', 'done', 'done', 'now']);
});

test('the phone step names match the sections the form already uses', () => {
  assert.deepStrictEqual(STEPS.map(s => s.phone),
    ['The record', 'The purchase', 'The log', 'The object']);
});

// ── place chips ─────────────────────────────────────────────────────────────
// Safari draws a <datalist> as a strip under the keyboard, so the phone offers
// the places you actually use as chips instead. Ranked by how often they were
// used, not alphabetically the way the datalist is.

const recs = n => Array.from({length: n}, () => ({}));
function at(place, n) { return recs(n).map(() => ({bought_where: place})); }

test('places rank by how often they were used', () => {
  const records = [...at('Tracks', 5), ...at('Amazon', 2), ...at('Baratos', 9)];
  assert.deepStrictEqual(rankPlaces(records, ''), ['Baratos', 'Tracks', 'Amazon']);
});

test('the ranking stops at the limit', () => {
  const records = [...at('A', 5), ...at('B', 4), ...at('C', 3), ...at('D', 2), ...at('E', 1)];
  assert.deepStrictEqual(rankPlaces(records, '', 4), ['A', 'B', 'C', 'D']);
});

test('the current value is pinned first even when it is rare', () => {
  const records = [...at('A', 9), ...at('B', 8), ...at('C', 7), ...at('D', 6), ...at('Rare', 1)];
  assert.deepStrictEqual(rankPlaces(records, 'Rare', 4), ['Rare', 'A', 'B', 'C']);
});

test('a current value already in the top four is not duplicated', () => {
  const records = [...at('A', 9), ...at('B', 8)];
  assert.deepStrictEqual(rankPlaces(records, 'B', 4), ['B', 'A']);
});

test('blank places are not offered', () => {
  const records = [...at('', 9), ...at('A', 1), {bought_where: null}];
  assert.deepStrictEqual(rankPlaces(records, ''), ['A']);
});

test('a place is matched after trimming, so a stray space is not a second chip', () => {
  const records = [{bought_where: 'Tracks'}, {bought_where: ' Tracks '}];
  assert.deepStrictEqual(rankPlaces(records, ''), ['Tracks']);
});

// ── collapsed log sections ──────────────────────────────────────────────────

test('an empty section starts collapsed', () => {
  assert.strictEqual(logSectionOpen([]), false);
});

test('a section with entries starts open, so the collapse only ever hides nothing', () => {
  assert.strictEqual(logSectionOpen(['2026-08-20T20:00:00']), true);
});

test('a missing list is treated as empty rather than throwing', () => {
  assert.strictEqual(logSectionOpen(undefined), false);
});

test('an empty section counts as none, not zero', () => {
  assert.strictEqual(logCount([]), 'none');
});

test('a filled section counts its entries', () => {
  assert.strictEqual(logCount(['a', 'b', 'c']), '3');
});

// ── edit-root previews ──────────────────────────────────────────────────────
// Each row says what it already holds, so you can see whether the thing you
// came to change is right without opening anything.

test('the record row reads artist, year and country', () => {
  assert.strictEqual(
    recordPreview({artist: 'Tim Maia', year: '1975', country: 'Brazil'}),
    'Tim Maia · 1975 · Brazil');
});

test('the record row omits the parts that are blank', () => {
  assert.strictEqual(recordPreview({artist: 'Tim Maia', year: '', country: ''}), 'Tim Maia');
});

test('the purchase row reads place, date and condition', () => {
  assert.strictEqual(
    purchasePreview({haveIt: true, where: 'Tracks', date: '2026-09-12', condition: 'used'}),
    'Tracks · 12 Sep 2026 · used');
});

test('a wishlist record says so instead of showing a purchase it never had', () => {
  assert.strictEqual(purchasePreview({haveIt: false, where: '', date: '', condition: ''}),
                     'Wishlist');
});

test('an owned record with nothing filled in says so', () => {
  assert.strictEqual(purchasePreview({haveIt: true, where: '', date: '', condition: ''}),
                     'nothing recorded');
});

test('the log row reads both ratings and both counts', () => {
  assert.strictEqual(
    logPreview({myRating: 5, wifeRating: 7, plays: 3, notes: 1}),
    'Pepe 5 · Jenni 7 · 3 plays · 1 note');
});

test('the log row omits the zero parts', () => {
  assert.strictEqual(logPreview({myRating: 0, wifeRating: 7, plays: 1, notes: 0}),
                     'Jenni 7 · 1 play');
});

test('a wholly unlogged record says nothing is logged', () => {
  assert.strictEqual(logPreview({myRating: 0, wifeRating: 0, plays: 0, notes: 0}),
                     'nothing logged');
});

test('the object row reads size, discs and tracks', () => {
  assert.strictEqual(objectPreview({size: '12"', discs: 1, tracks: 11, painted: false}),
                     '12" · 1 disc · 11 tracks');
});

test('the object row pluralises discs', () => {
  assert.strictEqual(objectPreview({size: '12"', discs: 2, tracks: 20, painted: false}),
                     '12" · 2 discs · 20 tracks');
});

test('a painted record says so, since that is the part you would come back for', () => {
  assert.strictEqual(objectPreview({size: '7"', discs: 1, tracks: 2, painted: true}),
                     '7" · 1 disc · 2 tracks · painted');
});

test('an empty tracklist is left out rather than reported as zero', () => {
  assert.strictEqual(objectPreview({size: '12"', discs: 1, tracks: 0, painted: false}),
                     '12" · 1 disc');
});

// ── drag to dismiss ─────────────────────────────────────────────────────────
// Bound to the nav area only, never the scrolling body — but it still has to
// tell a dismissal from a stray touch.

test('a long drag dismisses', () => {
  assert.strictEqual(dragDismisses(100, 400), true);
});

test('a short slow drag does not', () => {
  assert.strictEqual(dragDismisses(30, 400), false);
});

test('a short fast flick dismisses on velocity alone', () => {
  assert.strictEqual(dragDismisses(40, 50), true);       // 0.8 px/ms
});

test('an upward drag never dismisses', () => {
  assert.strictEqual(dragDismisses(-200, 100), false);
});

test('a zero-duration drag does not divide by zero', () => {
  assert.strictEqual(dragDismisses(10, 0), false);
});
