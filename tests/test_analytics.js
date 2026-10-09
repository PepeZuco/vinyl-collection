// tests/test_analytics.js
// Tests for the custom-event wrapper around Umami's tracker.
// Run by tests/test_analytics.py so `pytest` stays the single command.

const test = require('node:test');
const assert = require('node:assert');

const VinylAnalytics = require('../static/analytics.js');

function fakeUmami() {
  const calls = [];
  return { calls, track(name, data) { calls.push([name, data]); } };
}

test('an event reaches the tracker with its data', () => {
  const u = fakeUmami();
  assert.strictEqual(VinylAnalytics.track('tab', { tab: 'stats' }, u), true);
  assert.deepStrictEqual(u.calls, [['tab', { tab: 'stats' }]]);
});

test('an event with no data is sent without a data object', () => {
  const u = fakeUmami();
  VinylAnalytics.track('random-record', undefined, u);
  assert.deepStrictEqual(u.calls, [['random-record', undefined]]);
});

test('no tracker on the page is a quiet no-op', () => {
  assert.strictEqual(VinylAnalytics.track('tab', { tab: 'stats' }, undefined), false);
  assert.strictEqual(VinylAnalytics.track('tab', { tab: 'stats' }, {}), false);
});

test('a tracker that throws never reaches the caller', () => {
  const broken = { track() { throw new Error('blocked'); } };
  assert.strictEqual(VinylAnalytics.track('tab', { tab: 'stats' }, broken), false);
});

test('names and string values are cut to what Umami stores', () => {
  const u = fakeUmami();
  VinylAnalytics.track('x'.repeat(80), { query: 'y'.repeat(900) }, u);
  const [name, data] = u.calls[0];
  assert.strictEqual(name.length, 50);
  assert.strictEqual(data.query.length, 500);
});

test('empty values are dropped, numbers and booleans kept', () => {
  const u = fakeUmami();
  VinylAnalytics.track('record-save', { mode: 'add', wishlist: false, step: 3, gone: null, none: undefined, blank: '' }, u);
  assert.deepStrictEqual(u.calls[0][1], { mode: 'add', wishlist: false, step: 3 });
});

test('the data object handed in is not changed', () => {
  const u = fakeUmami();
  const data = { query: 'z'.repeat(600), gone: null };
  VinylAnalytics.track('search', data, u);
  assert.strictEqual(data.query.length, 600);
  assert.ok('gone' in data);
});

test('an empty event name is not sent', () => {
  const u = fakeUmami();
  assert.strictEqual(VinylAnalytics.track('', {}, u), false);
  assert.strictEqual(u.calls.length, 0);
});

test('recordLabel names a record the way the shelf does', () => {
  assert.strictEqual(VinylAnalytics.recordLabel({ artist: 'Tim Maia', album_name: 'Racional' }), 'Tim Maia — Racional');
  assert.strictEqual(VinylAnalytics.recordLabel({ album_name: 'Racional' }), 'Racional');
  assert.strictEqual(VinylAnalytics.recordLabel(null), '');
});
