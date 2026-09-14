// Tests for the SSE frame parser behind the analysing panel.
// Run by tests/test_scanstream.py so `pytest` stays the single command.

const test = require('node:test');
const assert = require('node:assert');

const { createParser } = require('../static/scanstream.js');

test('one whole frame in one chunk', () => {
  const p = createParser();
  assert.deepStrictEqual(p.push('event: step\ndata: {"id":"mb"}\n\n'),
                         [{ event: 'step', data: { id: 'mb' } }]);
});

test('two frames in one chunk come back in order', () => {
  const p = createParser();
  const got = p.push('event: step\ndata: {"id":"a"}\n\nevent: step\ndata: {"id":"b"}\n\n');
  assert.deepStrictEqual(got.map(f => f.data.id), ['a', 'b']);
});

// The network decides where chunks break, not the server — a frame split
// mid-JSON must not be parsed until its blank line arrives.
test('a frame split across two chunks is held until complete', () => {
  const p = createParser();
  assert.deepStrictEqual(p.push('event: step\ndata: {"id":'), []);
  assert.deepStrictEqual(p.push('"mb"}\n\n'), [{ event: 'step', data: { id: 'mb' } }]);
});

test('a frame split exactly on its blank line is held', () => {
  const p = createParser();
  assert.deepStrictEqual(p.push('event: done\ndata: {"ok":true}\n'), []);
  assert.deepStrictEqual(p.push('\n'), [{ event: 'done', data: { ok: true } }]);
});

test('unparseable data is dropped rather than throwing', () => {
  const p = createParser();
  assert.deepStrictEqual(p.push('event: step\ndata: not json\n\n'), []);
});
