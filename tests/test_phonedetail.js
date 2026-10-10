// Pure logic for the phone's record screen: which records sit at the bottom,
// and what a drag on the sheet handle decides. Run by tests/test_phonedetail.py.
const test = require('node:test');
const assert = require('node:assert');
const { neighbors, settle } = require('../static/phonedetail.js');

test('neighbours of a middle record are its two sides', () => {
  assert.deepStrictEqual(neighbors(['a', 'b', 'c'], 1), { prev: 'a', next: 'c' });
});
test('the first record has no previous, the last no next', () => {
  assert.deepStrictEqual(neighbors(['a', 'b', 'c'], 0), { prev: null, next: 'b' });
  assert.deepStrictEqual(neighbors(['a', 'b', 'c'], 2), { prev: 'b', next: null });
});
test('a list of one has no neighbours', () => {
  assert.deepStrictEqual(neighbors(['a'], 0), { prev: null, next: null });
});
test('an empty list or a bad index has none either', () => {
  assert.deepStrictEqual(neighbors([], 0), { prev: null, next: null });
  assert.deepStrictEqual(neighbors(['a', 'b'], -1), { prev: null, next: null });
  assert.deepStrictEqual(neighbors(['a', 'b'], 5), { prev: null, next: null });
});

test('a short drag leaves the sheet as it was', () => {
  assert.strictEqual(settle(false, -10, -0.05), false);
  assert.strictEqual(settle(true, 10, 0.05), true);
});
test('a long drag up opens, a long drag down closes', () => {
  assert.strictEqual(settle(false, -80, -0.1), true);
  assert.strictEqual(settle(true, 80, 0.1), false);
});
test('a flick wins over distance', () => {
  assert.strictEqual(settle(false, -12, -0.9), true);
  assert.strictEqual(settle(true, 12, 0.9), false);
});
test('dragging the wrong way does not flip an already-settled sheet', () => {
  assert.strictEqual(settle(true, -80, -0.1), true);
  assert.strictEqual(settle(false, 80, 0.1), false);
});
