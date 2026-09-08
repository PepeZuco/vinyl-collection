// tests/test_queue.js
// Tests for the pure add-queue model behind "record 2 of 3".
// Run by tests/test_queue.py so `pytest` stays the single command.

const test = require('node:test');
const assert = require('node:assert');

const VinylQueue = require('../static/queue.js');

const THREE = [
  { album_name: 'Força bruta', year: '1970' },
  { album_name: 'Negro é lindo', year: '1971' },
  { album_name: 'Ben', year: '1972' },
];

test('a fresh queue starts on the first record', () => {
  const q = VinylQueue.create(THREE);
  assert.strictEqual(VinylQueue.position(q), 1);
  assert.strictEqual(VinylQueue.total(q), 3);
  assert.strictEqual(VinylQueue.current(q).album_name, 'Força bruta');
});

test('the counter reads the way the header shows it', () => {
  let q = VinylQueue.create(THREE);
  assert.strictEqual(VinylQueue.counter(q), '1 of 3');
  q = VinylQueue.advance(q);
  assert.strictEqual(VinylQueue.counter(q), '2 of 3');
});

test('advancing does not mutate the queue it was given', () => {
  const q = VinylQueue.create(THREE);
  VinylQueue.advance(q);
  assert.strictEqual(VinylQueue.position(q), 1);
});

test('the last record says save rather than save and next', () => {
  let q = VinylQueue.create(THREE);
  assert.strictEqual(VinylQueue.saveLabel(q), 'save & next');
  q = VinylQueue.advance(VinylQueue.advance(q));
  assert.ok(VinylQueue.isLast(q));
  assert.strictEqual(VinylQueue.saveLabel(q), 'save');
});

test('advancing past the last record empties the queue', () => {
  let q = VinylQueue.create(THREE);
  for (let i = 0; i < 3; i++) q = VinylQueue.advance(q);
  assert.strictEqual(VinylQueue.current(q), null);
  assert.strictEqual(VinylQueue.remaining(q), 0);
});

test('skipping drops the record without counting it as done', () => {
  let q = VinylQueue.create(THREE);
  q = VinylQueue.skip(q);
  assert.strictEqual(VinylQueue.current(q).album_name, 'Negro é lindo');
  assert.strictEqual(VinylQueue.total(q), 2);
  assert.strictEqual(VinylQueue.counter(q), '1 of 2');
});

test('chips report which record is done, current and still waiting', () => {
  const q = VinylQueue.advance(VinylQueue.create(THREE));
  assert.deepStrictEqual(VinylQueue.chips(q).map(c => c.status),
    ['done', 'current', 'pending']);
  assert.strictEqual(VinylQueue.chips(q)[1].release.album_name, 'Negro é lindo');
});

test('a single record is immediately the last one', () => {
  const q = VinylQueue.create([THREE[0]]);
  assert.ok(VinylQueue.isLast(q));
  assert.strictEqual(VinylQueue.counter(q), '1 of 1');
  assert.strictEqual(VinylQueue.saveLabel(q), 'save');
});

test('an empty queue is finished and has nothing current', () => {
  const q = VinylQueue.create([]);
  assert.strictEqual(VinylQueue.current(q), null);
  assert.strictEqual(VinylQueue.remaining(q), 0);
  assert.ok(!VinylQueue.isLast(q));
});
