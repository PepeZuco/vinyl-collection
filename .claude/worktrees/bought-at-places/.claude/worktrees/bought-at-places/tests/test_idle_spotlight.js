// Tests for the idle-screensaver cycling logic.
// Run by tests/test_idle_spotlight.py so `pytest` stays the single command.
//
// The screensaver itself (timers, DOM, fade) lives in index.html like the
// rest of the UI glue. What's worth testing in isolation is what record it
// shows next: only owned records, in a random order, without repeating the
// one you just saw the moment a lap ends.

const test = require('node:test');
const assert = require('node:assert');

const { ownedPool, shuffle, advance } = require('../static/idle-spotlight.js');

let nextId = 1;
function rec(fields) {
  return Object.assign({ id: nextId++, artist: 'Tim Maia', have_it: true }, fields);
}

// ── ownedPool ────────────────────────────────────────────────────────────

test('ownedPool keeps only records marked as owned', () => {
  const owned = rec({});
  const wishlist = rec({ have_it: false });
  assert.deepStrictEqual(ownedPool([owned, wishlist]), [owned]);
});

test('ownedPool on no records is empty, not a throw', () => {
  assert.deepStrictEqual(ownedPool(undefined), []);
  assert.deepStrictEqual(ownedPool([]), []);
});

// ── shuffle ──────────────────────────────────────────────────────────────

test('shuffle reorders via Fisher-Yates for a given rng', () => {
  const a = rec({}), b = rec({}), c = rec({}), d = rec({});
  const result = shuffle([a, b, c, d], () => 0);
  assert.deepStrictEqual(result, [b, c, d, a]);
});

test('shuffle does not mutate the array it was given', () => {
  const a = rec({}), b = rec({});
  const input = [a, b];
  shuffle(input, () => 0);
  assert.deepStrictEqual(input, [a, b]);
});

// ── advance ──────────────────────────────────────────────────────────────

test('advance steps to the next queued record without reshuffling', () => {
  const a = rec({}), b = rec({}), c = rec({});
  const queue = advance([a, b, c], [a, b, c], () => 0);
  assert.deepStrictEqual(queue, [b, c]);
});

test('advance reshuffles from the pool once the queue runs out', () => {
  const a = rec({}), b = rec({});
  const queue = advance([a], [a, b], () => 0.9);
  assert.strictEqual(queue.length, 2);
});

test('advance never repeats the record that just finished as the next one', () => {
  const a = rec({}), b = rec({});
  // First shuffle attempt (rng=0.9) leaves [a, b] in place -- same head as
  // the one we just showed -- so advance must retry until it gets [b, a].
  const scripted = [0.9, 0.1];
  const rng = () => scripted.shift();
  const queue = advance([a], [a, b], rng);
  assert.strictEqual(queue[0].id, b.id);
});

test('advance with a single owned record just shows it again', () => {
  const a = rec({});
  const queue = advance([a], [a], () => 0);
  assert.deepStrictEqual(queue, [a]);
});
