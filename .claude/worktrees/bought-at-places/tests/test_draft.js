// Tests for the add/edit form's unsaved work.
// Run by tests/test_draft.py so `pytest` stays the single command.
//
// closeForm() had no dirty check and the overlay's backdrop click called it
// directly, so a tap outside the sheet threw away everything typed — including
// a photo scan that had just cost a real API call. These rules decide when
// there is something to lose, and what survives a closed tab.

process.env.TZ = 'America/Sao_Paulo';

const test = require('node:test');
const assert = require('node:assert');

const { isDirty, save, load, clear, KEY } = require('../static/draft.js');

// A stand-in for localStorage, including the one that refuses to store.
function store(opts) {
  const map = new Map();
  return {
    getItem: k => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => {
      if (opts && opts.full) throw new Error('QuotaExceededError');
      map.set(k, String(v));
    },
    removeItem: k => map.delete(k),
    _map: map,
  };
}

const form = (over) => Object.assign(
  { artist: 'Tim Maia', album_name: 'Uma Onda', year: '1993', genre: 'Soul & Funk',
    bought_date: '', bought_where: '', condition: '', play_count: 0, have_it: true,
    my_rating: 0, wife_rating: 0, notes: '[]', play_dates: '[]', cleaned_dates: '[]',
    country: 'BR' },
  over);

// ── is there anything to lose ───────────────────────────────────────────────

test('a form nobody touched is not dirty', () => {
  const baseline = form();
  assert.strictEqual(isDirty(form(), baseline), false);
});

test('a changed field makes the form dirty', () => {
  assert.strictEqual(isDirty(form({ album_name: 'Racional' }), form()), true);
});

test('a changed rating makes the form dirty', () => {
  assert.strictEqual(isDirty(form({ my_rating: 4 }), form()), true);
});

test('order of keys does not decide dirtiness', () => {
  const a = { artist: 'A', album_name: 'B' };
  const b = { album_name: 'B', artist: 'A' };
  assert.strictEqual(isDirty(a, b), false);
});

test('a field added since the baseline counts as a change', () => {
  assert.strictEqual(isDirty(form({ cover_data: 'data:image/png;base64,AA' }), form()), true);
});

test('an empty form against no baseline is not dirty', () => {
  // openAdd on a fresh form: nothing typed, nothing to warn about.
  assert.strictEqual(isDirty({}, {}), false);
});

test('a number and its string are the same value, since inputs report strings', () => {
  // fPlays reads back '0' where the baseline captured 0; that is not an edit.
  assert.strictEqual(isDirty(form({ play_count: '0' }), form({ play_count: 0 })), false);
  assert.strictEqual(isDirty(form({ play_count: '2' }), form({ play_count: 0 })), true);
});

// ── what survives a closed tab ──────────────────────────────────────────────

test('a saved draft comes back with what was in it', () => {
  const s = store();
  save(s, form({ album_name: 'Racional' }), 1000);
  const got = load(s, 1000, 60000);
  assert.strictEqual(got.draft.album_name, 'Racional');
});

test('nothing saved reads back as nothing', () => {
  assert.strictEqual(load(store(), 1000, 60000), null);
});

test('clearing a draft leaves nothing behind', () => {
  const s = store();
  save(s, form(), 1000);
  clear(s);
  assert.strictEqual(load(s, 1000, 60000), null);
  assert.strictEqual(s.getItem(KEY), null);
});

test('a draft older than the window is not offered', () => {
  const stale = store();
  save(stale, form(), 1000);
  assert.strictEqual(load(stale, 1000 + 60001, 60000), null);
});

test('a draft inside the window still is', () => {
  // Its own store: declining a stale draft clears it, so one store cannot
  // answer both halves.
  const fresh = store();
  save(fresh, form(), 1000);
  assert.ok(load(fresh, 1000 + 59999, 60000));
});

test('a stale draft is cleared as it is declined, not left to rot', () => {
  const s = store();
  save(s, form(), 1000);
  load(s, 1000 + 60001, 60000);
  assert.strictEqual(s.getItem(KEY), null);
});

test('a draft carries which record it belonged to', () => {
  const s = store();
  save(s, form(), 1000, 42);
  assert.strictEqual(load(s, 1000, 60000).editingId, 42);
});

test('a draft for a new record carries no id', () => {
  const s = store();
  save(s, form(), 1000);
  assert.strictEqual(load(s, 1000, 60000).editingId, null);
});

// ── storage that will not cooperate ─────────────────────────────────────────

test('a full or blocked storage loses the draft rather than the form', () => {
  // Private windows and blocked site data throw on setItem. Losing the
  // convenience is fine; throwing out of a keystroke handler is not.
  assert.doesNotThrow(() => save(store({ full: true }), form(), 1000));
});

test('unreadable stored text reads back as no draft', () => {
  const s = store();
  s.setItem(KEY, 'not json at all');
  assert.strictEqual(load(s, 1000, 60000), null);
});

test('a missing storage is simply no draft', () => {
  assert.strictEqual(load(null, 1000, 60000), null);
  assert.doesNotThrow(() => save(null, form(), 1000));
  assert.doesNotThrow(() => clear(null));
});
