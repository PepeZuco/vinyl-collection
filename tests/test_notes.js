// Tests for the notes column's parse/serialize rules.
// Run by tests/test_notes.py so `pytest` stays the single command.
//
// These exist because a note can now be a photo with no words. Every filter in
// this file used to be `n.text && n.text.trim()`, which silently deletes such a
// note on save — the failure is invisible at the call site and destroys the
// user's photo, so the rules moved here where they can be pinned.

const test = require('node:test');
const assert = require('node:assert');

const { parseNotes, serializeNotes, noteImageIds, hasContent } = require('../static/notes.js');

// ── serialize ───────────────────────────────────────────────────────────────

test('a note with text is kept', () => {
  assert.strictEqual(serializeNotes([{ date: 'd', text: 'hello' }]),
                     JSON.stringify([{ date: 'd', text: 'hello' }]));
});

test('a note with a photo and no words is kept', () => {
  const notes = [{ date: 'd', text: '', images: ['a1'] }];
  assert.strictEqual(serializeNotes(notes), JSON.stringify(notes));
});

test('a note with neither words nor photos is dropped', () => {
  assert.strictEqual(serializeNotes([{ date: 'd', text: '   ', images: [] }]), '');
});

test('an empty list serializes to the empty string, not "[]"', () => {
  assert.strictEqual(serializeNotes([]), '');
});

test('a whitespace-only note is dropped from among real ones', () => {
  const out = JSON.parse(serializeNotes([
    { date: 'a', text: 'real' },
    { date: 'b', text: '  ' },
    { date: 'c', text: '', images: ['x'] },
  ]));
  assert.deepStrictEqual(out.map(n => n.date), ['a', 'c']);
});

// ── parse ───────────────────────────────────────────────────────────────────

test('a note with no images key parses without one', () => {
  const out = parseNotes(JSON.stringify([{ date: 'd', text: 't' }]), '2026-01-01');
  assert.deepStrictEqual(out, [{ date: 'd', text: 't' }]);
});

test('images survive a round trip', () => {
  const notes = [{ date: 'd', text: 't', images: ['a1', 'b2'] }];
  assert.deepStrictEqual(parseNotes(serializeNotes(notes), '2026-01-01'), notes);
});

test('a legacy plain-string note still migrates onto the fallback date', () => {
  assert.deepStrictEqual(parseNotes('bought at the fair', '2026-01-01'),
                         [{ date: '2026-01-01', text: 'bought at the fair' }]);
});

test('an empty column parses to nothing', () => {
  assert.deepStrictEqual(parseNotes('', '2026-01-01'), []);
});

// ── hasContent ──────────────────────────────────────────────────────────────
// Public because the detail history filters on it directly, so it is pinned
// directly rather than only through serializeNotes.

test('a note counts as content when it has words', () => {
  assert.strictEqual(hasContent({ date: 'd', text: 'hello' }), true);
});

test('a note counts as content when it has only a photo', () => {
  assert.strictEqual(hasContent({ date: 'd', text: '', images: ['a1'] }), true);
});

test('a note with neither is not content', () => {
  assert.strictEqual(hasContent({ date: 'd', text: '  ', images: [] }), false);
  assert.strictEqual(hasContent(null), false);
});

// ── ids ─────────────────────────────────────────────────────────────────────

test('every id across every note comes back once', () => {
  assert.deepStrictEqual(
    noteImageIds([{ images: ['a', 'b'] }, { text: 'none' }, { images: ['b', 'c'] }]),
    ['a', 'b', 'c']);
});

test('a note list with no images has no ids', () => {
  assert.deepStrictEqual(noteImageIds([{ date: 'd', text: 't' }]), []);
});
