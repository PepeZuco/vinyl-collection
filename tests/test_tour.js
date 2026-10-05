// Tests for the guided tour's rules.
// Run by tests/test_tour.py so `pytest` stays the single command.
//
// The spotlight, the popover and the tab switching live in index.html with
// the rest of the UI glue. What's worth testing on its own is the part that
// decides: which element a step points at on a phone vs. a desktop, which
// step comes next when one has nothing to point at, where the popover goes,
// and whether a first-time visitor gets offered the tour at all.

const test = require('node:test');
const assert = require('node:assert');

const {
  STEPS, targetOf, stepIndex, placePopover, shouldOffer, markSeen, SEEN_KEY,
} = require('../static/tour.js');

function memoryStorage(init) {
  const data = Object.assign({}, init);
  return {
    getItem: k => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v); },
    data,
  };
}

// ── STEPS ────────────────────────────────────────────────────────────────

test('the tour walks collection, then playlists, then readme', () => {
  const tabs = STEPS.map(s => s.tab).filter(Boolean);
  const order = tabs.filter((t, i) => t !== tabs[i - 1]);
  assert.deepStrictEqual(order, ['collection', 'playlists', 'features', 'collection']);
});

test('every step has a title and a text', () => {
  for (const s of STEPS) {
    assert.ok(s.title && s.title.length, `step ${s.id} has no title`);
    assert.ok(s.text && s.text.length, `step ${s.id} has no text`);
  }
});

test('step ids are unique', () => {
  const ids = STEPS.map(s => s.id);
  assert.strictEqual(new Set(ids).size, ids.length);
});

// ── targetOf ─────────────────────────────────────────────────────────────

test('targetOf returns a plain selector on either breakpoint', () => {
  const step = { target: '#searchInput' };
  assert.strictEqual(targetOf(step, false), '#searchInput');
  assert.strictEqual(targetOf(step, true), '#searchInput');
});

test('targetOf picks the phone selector on a phone', () => {
  const step = { target: { desktop: '#tabPlaylists', phone: '#mtabSpotify' } };
  assert.strictEqual(targetOf(step, false), '#tabPlaylists');
  assert.strictEqual(targetOf(step, true), '#mtabSpotify');
});

test('targetOf is null for a centered step', () => {
  assert.strictEqual(targetOf({}, false), null);
  assert.strictEqual(targetOf({ target: { desktop: '#x' } }, true), null);
});

// ── stepIndex ────────────────────────────────────────────────────────────

const steps = [{ id: 'a' }, { id: 'b' }, { id: 'c' }, { id: 'd' }];
const all = () => true;

test('stepIndex moves forward and back one step', () => {
  assert.strictEqual(stepIndex(steps, 1, 1, all), 2);
  assert.strictEqual(stepIndex(steps, 2, -1, all), 1);
});

test('stepIndex skips a step with nothing to point at', () => {
  const missing = s => s.id !== 'b';
  assert.strictEqual(stepIndex(steps, 0, 1, missing), 2);
  assert.strictEqual(stepIndex(steps, 2, -1, missing), 0);
});

test('stepIndex is -1 past either end', () => {
  assert.strictEqual(stepIndex(steps, 3, 1, all), -1);
  assert.strictEqual(stepIndex(steps, 0, -1, all), -1);
});

test('stepIndex from -1 forward finds the first available step', () => {
  assert.strictEqual(stepIndex(steps, -1, 1, s => s.id !== 'a'), 1);
});

// ── placePopover ─────────────────────────────────────────────────────────

const vp = { width: 1200, height: 800 };
const pop = { width: 320, height: 160 };

test('placePopover goes below the target when there is room', () => {
  const p = placePopover({ top: 100, left: 400, width: 200, height: 40 }, pop, vp, 12);
  assert.strictEqual(p.side, 'below');
  assert.strictEqual(p.top, 100 + 40 + 12);
  assert.strictEqual(p.left, 400 + 100 - 160);  // centred on the target
});

test('placePopover goes above when the target sits near the bottom', () => {
  const p = placePopover({ top: 700, left: 400, width: 200, height: 40 }, pop, vp, 12);
  assert.strictEqual(p.side, 'above');
  assert.strictEqual(p.top, 700 - 12 - 160);
});

test('placePopover keeps the card inside the viewport horizontally', () => {
  const left = placePopover({ top: 100, left: 0, width: 40, height: 40 }, pop, vp, 12);
  assert.strictEqual(left.left, 12);
  const right = placePopover({ top: 100, left: 1180, width: 20, height: 20 }, pop, vp, 12);
  assert.strictEqual(right.left, 1200 - 320 - 12);
});

test('placePopover centres the card when there is no target', () => {
  const p = placePopover(null, pop, vp, 12);
  assert.strictEqual(p.side, 'center');
  assert.strictEqual(p.left, (1200 - 320) / 2);
  assert.strictEqual(p.top, (800 - 160) / 2);
});

test('placePopover overlays a target taller than the room on either side', () => {
  const p = placePopover({ top: 60, left: 100, width: 1000, height: 700 }, pop, vp, 12);
  assert.strictEqual(p.side, 'inside');
  assert.strictEqual(p.top, 800 - 160 - 12);
});

// ── first-visit offer ────────────────────────────────────────────────────

test('a first-time visitor is offered the tour', () => {
  assert.strictEqual(shouldOffer(memoryStorage(), { authed: false, hash: '' }), true);
});

test('the offer is not repeated once seen', () => {
  const store = memoryStorage();
  markSeen(store);
  assert.strictEqual(store.data[SEEN_KEY], '1');
  assert.strictEqual(shouldOffer(store, { authed: false, hash: '' }), false);
});

test('the owner in edit mode is not offered the tour', () => {
  assert.strictEqual(shouldOffer(memoryStorage(), { authed: true, hash: '' }), false);
});

test('a deep link is not interrupted by the offer', () => {
  assert.strictEqual(shouldOffer(memoryStorage(), { authed: false, hash: '#r=12' }), false);
});

test('storage that throws means no offer, not a crash', () => {
  const broken = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };
  assert.strictEqual(shouldOffer(broken, { authed: false, hash: '' }), false);
  assert.doesNotThrow(() => markSeen(broken));
  assert.strictEqual(shouldOffer(null, { authed: false, hash: '' }), false);
});
