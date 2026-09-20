// Tests for the Spotify link rules: cleaning a pasted link, and what the
// detail drawer shows for a link / a flagged record / neither.

const test = require('node:test');
const assert = require('node:assert');

const { cleanLink, rowHTML } = require('../static/spotify.js');

test('share-sheet tracking and locale are dropped', () => {
  assert.strictEqual(cleanLink(' https://open.spotify.com/intl-pt/album/xyz?si=abc '),
                     'https://open.spotify.com/album/xyz');
});

test('a spotify: URI becomes a web link', () => {
  assert.strictEqual(cleanLink('spotify:album:xyz'), 'https://open.spotify.com/album/xyz');
});

test('anything else is left as typed', () => {
  assert.strictEqual(cleanLink('https://example.com/a?si=1'), 'https://example.com/a?si=1');
  assert.strictEqual(cleanLink(''), '');
  assert.strictEqual(cleanLink(null), '');
});

test('a link renders an open button', () => {
  const html = rowHTML({spotify_url: 'https://open.spotify.com/album/xyz'});
  assert.match(html, /href="https:\/\/open\.spotify\.com\/album\/xyz"/);
  assert.match(html, /target="_blank"/);
  assert.match(html, /rel="noopener noreferrer"/);
});

test('no link means not on Spotify, flagged or not', () => {
  assert.match(rowHTML({spotify_url: ''}), /Not on Spotify/);
  assert.match(rowHTML({spotify_url: '', spotify_missing: true}), /Not on Spotify/);
  assert.doesNotMatch(rowHTML({spotify_url: ''}), /href=/);
});

test('a non-http link is never turned into an href', () => {
  const html = rowHTML({spotify_url: 'javascript:alert(1)'});
  assert.doesNotMatch(html, /href=/);
});

test('the link is escaped', () => {
  const html = rowHTML({spotify_url: 'https://open.spotify.com/a"b'});
  assert.doesNotMatch(html, /a"b/);
});
