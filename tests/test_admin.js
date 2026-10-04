// The review list's rules — which album rows can be ticked, and which start
// ticked. Pure, so they are pinned here rather than through the DOM.

const test = require('node:test');
const assert = require('node:assert');

const { canTick, defaultTicked, chunk, songsLabel, progressText } =
  require('../static/admin.js');

const album = extra => Object.assign({ key: 'k', artist: 'A', album_name: 'B',
  songs: ['x'], unverified: false, duplicate_of: null, have_it: null,
  vinyl: 'confirmed' }, extra);

test('a confirmed, verified album can be ticked and starts ticked', () => {
  assert.strictEqual(canTick(album()), true);
  assert.strictEqual(defaultTicked(album()), true);
});

test('a likely album can be ticked but starts unticked', () => {
  assert.strictEqual(canTick(album({ vinyl: 'likely' })), true);
  assert.strictEqual(defaultTicked(album({ vinyl: 'likely' })), false);
});

test('an album never pressed on vinyl cannot be ticked', () => {
  assert.strictEqual(canTick(album({ vinyl: 'none' })), false);
  assert.strictEqual(defaultTicked(album({ vinyl: 'none' })), false);
});

test('an album already owned or wishlisted cannot be ticked', () => {
  const owned = album({ duplicate_of: { id: 1 }, have_it: true, vinyl: undefined });
  assert.strictEqual(canTick(owned), false);
  assert.strictEqual(defaultTicked(owned), false);
  assert.strictEqual(canTick(album({ duplicate_of: { id: 2 }, have_it: false })), false);
});

test('an album still being checked cannot be ticked yet', () => {
  assert.strictEqual(canTick(album({ vinyl: undefined })), false);
});

test('an unverified confirmed album can be ticked but starts unticked', () => {
  const a = album({ unverified: true });
  assert.strictEqual(canTick(a), true);
  assert.strictEqual(defaultTicked(a), false);
});

test('chunk splits into fixed-size pieces, last one short', () => {
  assert.deepStrictEqual(chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]);
  assert.deepStrictEqual(chunk([], 24), []);
});

test('songsLabel names up to three songs', () => {
  assert.strictEqual(songsLabel(['A']), '1 song: A');
  assert.strictEqual(songsLabel(['A', 'B', 'C']), '3 songs: A, B, C');
  assert.strictEqual(songsLabel(['A', 'B', 'C', 'D', 'E']), '5 songs: A, B, C, …');
});

test('progressText words each stage', () => {
  assert.strictEqual(progressText('reading'), 'reading songs and naming albums…');
  assert.strictEqual(progressText('resolving', 24, 140), 'checking vinyl 24 / 140');
});
