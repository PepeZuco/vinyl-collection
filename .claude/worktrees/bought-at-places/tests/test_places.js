// Tests for the place rules — the URL normalization is a security boundary:
// a stored javascript: URL becomes an href in the drawer, so the rejecting
// branch is pinned here rather than trusted to the caller.

const test = require('node:test');
const assert = require('node:assert');

const { normalizeUrl, validName, sortPlaces, mergeTarget, placeUrl } =
  require('../static/places.js');

// ── normalizeUrl ────────────────────────────────────────────────────────────

test('an empty link stays empty — a place without one is normal', () => {
  assert.strictEqual(normalizeUrl(''), '');
  assert.strictEqual(normalizeUrl('   '), '');
  assert.strictEqual(normalizeUrl(null), '');
  assert.strictEqual(normalizeUrl(undefined), '');
});

test('a scheme-less host gets https://', () => {
  assert.strictEqual(normalizeUrl('tracksrio.com'), 'https://tracksrio.com');
  assert.strictEqual(normalizeUrl('  tracksrio.com/loja  '), 'https://tracksrio.com/loja');
});

test('a protocol-relative link gets https:// without doubling the slashes', () => {
  assert.strictEqual(normalizeUrl('//tracksrio.com'), 'https://tracksrio.com');
});

test('http and https are kept as typed', () => {
  assert.strictEqual(normalizeUrl('http://x.com'), 'http://x.com');
  assert.strictEqual(normalizeUrl('https://x.com/a?b=c#d'), 'https://x.com/a?b=c#d');
});

test('a javascript: link is rejected', () => {
  assert.strictEqual(normalizeUrl('javascript:alert(1)'), null);
  assert.strictEqual(normalizeUrl('JavaScript:alert(1)'), null);
});

test('any other scheme is rejected', () => {
  assert.strictEqual(normalizeUrl('ftp://x.com'), null);
  assert.strictEqual(normalizeUrl('data:text/html,hi'), null);
});

test('a scheme with no host is rejected', () => {
  assert.strictEqual(normalizeUrl('https://'), null);
});

test('bare host with port gets https://', () => {
  assert.strictEqual(normalizeUrl('tracksrio.com:8080/loja'), 'https://tracksrio.com:8080/loja');
  assert.strictEqual(normalizeUrl('localhost:3000'), 'https://localhost:3000');
});

test('http(s) URLs with ports are kept as typed', () => {
  assert.strictEqual(normalizeUrl('https://tracksrio.com:8080/loja'), 'https://tracksrio.com:8080/loja');
});

test('scheme with no host forms are rejected', () => {
  assert.strictEqual(normalizeUrl('https:///'), null);
  assert.strictEqual(normalizeUrl('https://:8080'), null);
  assert.strictEqual(normalizeUrl('https://@'), null);
});

test('http(s) URLs with userinfo are kept as typed', () => {
  assert.strictEqual(normalizeUrl('https://user:pw@tracksrio.com/x'), 'https://user:pw@tracksrio.com/x');
});

test('invariant: all results are empty, null, or http(s)', () => {
  const inputs = [
    'javascript:alert(1)',
    'data:text/html,hi',
    'ftp://x.com',
    '//x.com',
    'x.com',
    'https://x.com',
    'JavaScript:alert(1)',
  ];
  inputs.forEach(input => {
    const result = normalizeUrl(input);
    assert(result === '' || result === null || /^https?:\/\//.test(result),
      `normalizeUrl('${input}') = ${result} — not empty, null, or http(s)`);
  });
});

// ── validName ───────────────────────────────────────────────────────────────

test('a name needs at least one non-space character', () => {
  assert.strictEqual(validName('Tracks Rio'), true);
  assert.strictEqual(validName('  x  '), true);
  assert.strictEqual(validName('   '), false);
  assert.strictEqual(validName(''), false);
  assert.strictEqual(validName(null), false);
});

// ── sortPlaces ──────────────────────────────────────────────────────────────

test('places sort by name, ignoring case, without mutating the input', () => {
  const input = [
    { id: 1, name: 'tracks', url: '' },
    { id: 2, name: 'Feira da Glória', url: '' },
    { id: 3, name: 'Amoeba', url: '' },
  ];
  const out = sortPlaces(input);
  assert.deepStrictEqual(out.map(p => p.id), [3, 2, 1]);
  assert.deepStrictEqual(input.map(p => p.id), [1, 2, 3]);
});

// ── mergeTarget ─────────────────────────────────────────────────────────────

test('a rename onto another place names that place as the merge target', () => {
  const places = [{ id: 1, name: 'Tracks', url: '' }, { id: 2, name: 'Amoeba', url: '' }];
  assert.strictEqual(mergeTarget('amoeba', places, 1).id, 2);
});

test('a rename that only changes case on the place being edited is not a merge', () => {
  const places = [{ id: 1, name: 'Tracks', url: '' }, { id: 2, name: 'Amoeba', url: '' }];
  assert.strictEqual(mergeTarget('TRACKS', places, 1), null);
});

test('a brand new name is not a merge', () => {
  const places = [{ id: 1, name: 'Tracks', url: '' }];
  assert.strictEqual(mergeTarget('Feira da Glória', places, 1), null);
});

// ── placeUrl ────────────────────────────────────────────────────────────────

test('a place with a link resolves to it', () => {
  const places = [{ id: 1, name: 'Tracks Rio', url: 'https://tracksrio.com' }];
  assert.strictEqual(placeUrl('Tracks Rio', places), 'https://tracksrio.com');
  assert.strictEqual(placeUrl('  Tracks Rio  ', places), 'https://tracksrio.com');
});

test('a place with no link, an unknown name and no name all resolve to empty', () => {
  const places = [{ id: 1, name: 'Tracks Rio', url: '' }];
  assert.strictEqual(placeUrl('Tracks Rio', places), '');
  assert.strictEqual(placeUrl('Nowhere', places), '');
  assert.strictEqual(placeUrl('', places), '');
  assert.strictEqual(placeUrl(null, places), '');
});
