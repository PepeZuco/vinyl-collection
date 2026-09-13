// Tests for the add/edit form's cover rules.
// Run by tests/test_cover_form.py so `pytest` stays the single command.
//
// These exist because covers stopped travelling with the record. The form used
// to hold the cover's bytes and send them back on every save; now it holds only
// a URL it cannot send, so it has to say nothing rather than say "empty" — and
// getting that wrong destroys the artwork on every unrelated edit.

const test = require('node:test');
const assert = require('node:assert');

const { coverFields, coverPreviewSrc } = require('../static/cover.js');

// ── what the form sends ─────────────────────────────────────────────────────

test('an untouched cover is omitted from the payload', () => {
  assert.deepStrictEqual(coverFields({ dirty: false, uri: '' }), {});
});

test('an untouched cover is omitted even when the record has one on screen', () => {
  // The preview is showing /api/records/7/cover; the form never held its bytes.
  assert.deepStrictEqual(coverFields({ dirty: false, uri: '' }), {});
});

test('a newly picked cover is sent as its data URI', () => {
  assert.deepStrictEqual(
    coverFields({ dirty: true, uri: 'data:image/png;base64,AAAA' }),
    { cover_data: 'data:image/png;base64,AAAA' });
});

test('a cleared cover is sent as an empty string, not omitted', () => {
  // Omitting would mean "leave it alone", which is the opposite of removing it.
  assert.deepStrictEqual(coverFields({ dirty: true, uri: '' }), { cover_data: '' });
});

// ── what the form shows ─────────────────────────────────────────────────────

test('the preview shows a freshly picked cover over the saved one', () => {
  assert.strictEqual(
    coverPreviewSrc({ cover_url: '/api/records/7/cover?v=abc' }, 'data:image/png;base64,AAAA'),
    'data:image/png;base64,AAAA');
});

test('the preview falls back to the saved cover URL', () => {
  assert.strictEqual(
    coverPreviewSrc({ cover_url: '/api/records/7/cover?v=abc' }, ''),
    '/api/records/7/cover?v=abc');
});

test('the preview is empty for a record that has no cover', () => {
  assert.strictEqual(coverPreviewSrc({ cover_url: '' }, ''), '');
});

test('the preview is empty when adding a record from scratch', () => {
  assert.strictEqual(coverPreviewSrc(null, ''), '');
});
