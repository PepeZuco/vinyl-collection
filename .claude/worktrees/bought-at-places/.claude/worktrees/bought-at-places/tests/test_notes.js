// Tests for the notes column's parse/serialize rules.
// Run by tests/test_notes.py so `pytest` stays the single command.
//
// These exist because a note can now be a photo with no words. Every filter in
// this file used to be `n.text && n.text.trim()`, which silently deletes such a
// note on save — the failure is invisible at the call site and destroys the
// user's photo, so the rules moved here where they can be pinned.

const test = require('node:test');
const assert = require('node:assert');

const { parseNotes, serializeNotes, noteImageIds, hasContent, isImageId,
        normalizeNote } = require('../static/notes.js');

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

const ID_A = 'a'.repeat(32), ID_B = 'b'.repeat(32), ID_C = 'c'.repeat(32);

test('images survive a round trip', () => {
  const notes = [{ date: 'd', text: 't', images: [ID_A, ID_B] }];
  assert.deepStrictEqual(parseNotes(serializeNotes(notes), '2026-01-01'), notes);
});

/* An id is interpolated into an inline onclick downstream, where esc() does
 * not help -- it leaves the apostrophe that closes the string alone. The stored
 * value is attacker-reachable: PUT /api/records/<id> writes the notes column
 * through unvalidated, and a CSV import accepts any key. So the shape is the
 * defence, and it is checked here rather than at each render site. */
test('an id that could break out of a handler never survives parsing', () => {
  const hostile = "x'),window.pwned=1;//";
  const notes = parseNotes(JSON.stringify(
    [{ date: 'd', text: 't', images: [hostile, ID_A] }]), '2026-01-01');
  assert.deepStrictEqual(notes[0].images, [ID_A]);
});

test('a note left with nothing real to show stops being a note', () => {
  // Its only image was unusable, so there is no photo and no text.
  const notes = parseNotes(JSON.stringify(
    [{ date: 'd', text: '', images: ['../../etc/passwd'] }]), '2026-01-01');
  assert.strictEqual(serializeNotes(notes), '');
});

test('isImageId accepts exactly the 32 lowercase hex a real id is', () => {
  assert.strictEqual(isImageId(ID_A), true);
  assert.strictEqual(isImageId('A'.repeat(32)), false);  // uppercase
  assert.strictEqual(isImageId('a'.repeat(31)), false);  // too short
  assert.strictEqual(isImageId('a'.repeat(33)), false);  // too long
  assert.strictEqual(isImageId('g'.repeat(32)), false);  // not hex
  assert.strictEqual(isImageId(null), false);
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
    noteImageIds([{ images: [ID_A, ID_B] }, { text: 'none' },
                  { images: [ID_B, ID_C] }]),
    [ID_A, ID_B, ID_C]);
});

test('a note list with no images has no ids', () => {
  assert.deepStrictEqual(noteImageIds([{ date: 'd', text: 't' }]), []);
});

// ── normalizeNote ───────────────────────────────────────────────────────────
// The one place that turns what the form holds -- a date, a textarea, a strip
// of ids, a checkbox -- into a stored note. Both writing a note and editing
// one already saved come through here, so the rules cannot drift apart between
// them: the privacy key in particular is written ONLY when it is true, because
// _public_notes in app.py reads an absent key as public and a note the user
// published must be indistinguishable from one never marked.

test('a note keeps its date and its trimmed words', () => {
  assert.deepStrictEqual(
    normalizeNote({ date: '2026-01-01', text: '  hello  ' }),
    { date: '2026-01-01', text: 'hello', images: [] });
});

test('a published note carries no privacy key at all', () => {
  const note = normalizeNote({ date: 'd', text: 't', private: false });
  assert.strictEqual('private' in note, false);
});

test('a private note is marked private', () => {
  assert.strictEqual(normalizeNote({ date: 'd', text: 't', private: true }).private, true);
});

test('a photo with no words is still a note', () => {
  assert.deepStrictEqual(normalizeNote({ date: 'd', text: '   ', images: [ID_A] }),
                         { date: 'd', text: '', images: [ID_A] });
});

test('a note with neither words nor photos is not a note', () => {
  assert.strictEqual(normalizeNote({ date: 'd', text: '  ', images: [] }), null);
});

test('a note with no date is not a note', () => {
  assert.strictEqual(normalizeNote({ date: '', text: 'real words' }), null);
});

test('an unusable id never reaches the column', () => {
  assert.deepStrictEqual(
    normalizeNote({ date: 'd', text: 't', images: ["x'),window.pwned=1;//", ID_A] }).images,
    [ID_A]);
});

test('the same photo attached twice is held once', () => {
  assert.deepStrictEqual(
    normalizeNote({ date: 'd', text: 't', images: [ID_A, ID_A, ID_B] }).images,
    [ID_A, ID_B]);
});

test('normalizing does not write through to the caller\'s image list', () => {
  const images = [ID_A];
  normalizeNote({ date: 'd', text: 't', images }).images.push(ID_B);
  assert.deepStrictEqual(images, [ID_A]);
});
