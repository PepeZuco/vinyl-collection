// Tests for the event model behind the Timeline tab.
// Run by tests/test_timeline.py so `pytest` stays the single command.
//
// Calendar and History were two tabs over the same events at different zooms —
// and they disagreed about which records counted: the calendar read every
// record, the growth chart read owned-and-dated ones. This model is the one
// answer to "what happened, and when", and the caller decides the scope.

// Pinned before anything constructs a Date: an evening event must stay on its
// own evening, which says nothing without an offset. Sao Paulo is UTC-3 and the
// collection's own timezone.
process.env.TZ = 'America/Sao_Paulo';

const test = require('node:test');
const assert = require('node:assert');

const { ALL_TYPES, eventsByDay } = require('../static/timeline.js');

let nextId = 1;
function rec(fields) {
  return Object.assign(
    { id: nextId++, artist: 'Tim Maia', album_name: 'Uma Onda',
      bought_date: '', play_dates: '', cleaned_dates: '', notes: '' },
    fields);
}
const json = (...v) => JSON.stringify(v);

// The template owns these parsers; the model takes them rather than duplicating
// their legacy-migration rules.
const deps = {
  parsePlayDates: (raw) => { try { const p = JSON.parse(raw || '[]'); return Array.isArray(p) ? p : []; } catch (e) { return []; } },
  parseNotes: (raw) => { try { const p = JSON.parse(raw || '[]'); return Array.isArray(p) ? p : []; } catch (e) { return []; } },
};
deps.parseCleanedDates = deps.parsePlayDates;

const days = (records, types) => eventsByDay(records, types || ALL_TYPES, deps);
const on = (records, day, types) => (days(records, types).get(day) || []);

// ── each kind of event ──────────────────────────────────────────────────────

test('a bought date puts a bought event on its day', () => {
  const got = on([rec({ bought_date: '2026-08-23' })], '2026-08-23');
  assert.deepStrictEqual(got.map(e => e.type), ['bought']);
});

test('every play date puts a played event on its own day', () => {
  const r = rec({ play_dates: json('2026-08-23T21:12:00', '2026-08-25T15:41:00') });
  const map = days([r]);
  assert.deepStrictEqual(map.get('2026-08-23').map(e => e.type), ['played']);
  assert.deepStrictEqual(map.get('2026-08-25').map(e => e.type), ['played']);
});

test('every cleaning date puts a cleaned event on its day', () => {
  const got = on([rec({ cleaned_dates: json('2026-08-02T16:40:00') })], '2026-08-02');
  assert.deepStrictEqual(got.map(e => e.type), ['cleaned']);
});

test('a note with text puts a note event on its day, carrying the text', () => {
  const r = rec({ notes: json({ date: '2026-08-23T21:20:00', text: 'clicky side B' }) });
  const got = on([r], '2026-08-23');
  assert.deepStrictEqual(got.map(e => e.type), ['note']);
  assert.strictEqual(got[0].text, 'clicky side B');
});

test('a note with no text is not an event', () => {
  const r = rec({ notes: json({ date: '2026-08-23', text: '   ' }) });
  assert.strictEqual(days([r]).size, 0);
});

test('every event carries the record it belongs to', () => {
  const r = rec({ bought_date: '2026-08-23' });
  assert.strictEqual(on([r], '2026-08-23')[0].r, r);
});

// ── the type switches ───────────────────────────────────────────────────────

test('a type that is switched off contributes nothing', () => {
  const r = rec({ bought_date: '2026-08-23', play_dates: json('2026-08-23T21:00:00') });
  const types = Object.assign({}, ALL_TYPES, { bought: false });
  assert.deepStrictEqual(on([r], '2026-08-23', types).map(e => e.type), ['played']);
});

test('switching every type off empties the timeline', () => {
  const r = rec({ bought_date: '2026-08-23', play_dates: json('2026-08-23') });
  const none = { bought: false, cleaned: false, played: false, note: false };
  assert.strictEqual(days([r], none).size, 0);
});

// ── dates that do not hold ──────────────────────────────────────────────────

test('a record with no dates contributes nothing', () => {
  assert.strictEqual(days([rec({})]).size, 0);
});

test('an unparseable date is dropped rather than thrown on', () => {
  const map = days([rec({ bought_date: '2026-02-30' }), rec({ bought_date: '2026-02-11' })]);
  assert.deepStrictEqual([...map.keys()], ['2026-02-11']);
});

test('play dates that are not valid JSON are ignored', () => {
  assert.strictEqual(days([rec({ play_dates: 'not json' })]).size, 0);
});

// ── the day an event belongs to ─────────────────────────────────────────────

test('a late-evening event stays on its own day', () => {
  // Stored as a local wall clock with no zone. Reading it as UTC would file
  // this on the 24th, which is the bug the stamp format exists to avoid.
  const r = rec({ play_dates: json('2026-08-23T23:30:00') });
  assert.deepStrictEqual([...days([r]).keys()], ['2026-08-23']);
});

// ── how a day reads ─────────────────────────────────────────────────────────

test('a day is ordered by clock time', () => {
  const r = rec({ play_dates: json('2026-08-23T21:12:00', '2026-08-23T09:05:00') });
  assert.deepStrictEqual(on([r], '2026-08-23').map(e => e.time), ['09:05', '21:12']);
});

test('events with no clock lead the day, in bought-cleaned-played-note order', () => {
  const r = rec({
    bought_date: '2026-08-23',
    cleaned_dates: json('2026-08-23'),
    play_dates: json('2026-08-23'),
    notes: json({ date: '2026-08-23', text: 'a note' }),
  });
  assert.deepStrictEqual(on([r], '2026-08-23').map(e => e.type),
    ['bought', 'cleaned', 'played', 'note']);
});

test('two records at the same moment fall back to album order', () => {
  const records = [
    rec({ album_name: 'Zeta', bought_date: '2026-08-23' }),
    rec({ album_name: 'Alpha', bought_date: '2026-08-23' }),
  ];
  assert.deepStrictEqual(on(records, '2026-08-23').map(e => e.r.album_name), ['Alpha', 'Zeta']);
});

test('records merge onto the same day', () => {
  const records = [
    rec({ bought_date: '2026-08-23T10:00:00' }),
    rec({ bought_date: '2026-08-23T11:00:00' }),
  ];
  assert.strictEqual(on(records, '2026-08-23').length, 2);
});

// ── scope is the caller's business ──────────────────────────────────────────

test('the model filters nothing itself, so one shared query governs the tab', () => {
  // The calendar used to read every record while the growth chart read only
  // owned ones, so the same tab disagreed with itself about the collection.
  const wishlist = rec({ have_it: false, notes: json({ date: '2026-08-23', text: 'want' }) });
  assert.strictEqual(on([wishlist], '2026-08-23').length, 1);
  assert.strictEqual(days([]).size, 0);
});


test('type order beats album order for clockless events on the same day', () => {
  // Alphabetically Alpha precedes Beta, and Alpha's note is added first — so
  // this only comes out right if the type comparator actually runs.
  const records = [
    rec({ album_name: 'Alpha', notes: json({ date: '2026-08-23', text: 'a note' }) }),
    rec({ album_name: 'Beta', bought_date: '2026-08-23' }),
  ];
  assert.deepStrictEqual(on(records, '2026-08-23').map(e => e.type), ['bought', 'note']);
});

// ── an event's name ─────────────────────────────────────────────────────────

const { keyOf } = require('../static/timeline.js');

test('bought keys carry no index, because bought_date is one column', () => {
  assert.strictEqual(keyOf('bought', '2026-08-23'), 'bought:2026-08-23');
});

test('a list-backed event is named by its type, stamp and position', () => {
  assert.strictEqual(keyOf('played', '2026-08-23T21:12:00', 0),
    'played:2026-08-23T21:12:00:0');
});

test('two clockless cleanings on one day get different keys', () => {
  // Rows written before times were kept carry a bare date, so the stamp alone
  // would collide. This is why every list-backed type is indexed.
  const r = rec({ cleaned_dates: json('2026-08-23', '2026-08-23') });
  const got = on([r], '2026-08-23').map(e => e.key);
  assert.strictEqual(new Set(got).size, 2, 'keys collided: ' + got.join(' '));
});

test('every event carries its key, its raw stamp and its day', () => {
  const r = rec({ play_dates: json('2026-08-23T21:12:00') });
  const ev = on([r], '2026-08-23')[0];
  assert.strictEqual(ev.key, 'played:2026-08-23T21:12:00:0');
  assert.strictEqual(ev.at, '2026-08-23T21:12:00');
  assert.strictEqual(ev.day, '2026-08-23');
});

test('a note is indexed by its position in the raw notes array', () => {
  // The empty note still occupies index 0, so the note that follows it is 1.
  // Filtering first would renumber it and break the key the drawer expects.
  const r = rec({ notes: json({ date: '2026-08-23', text: '' },
                              { date: '2026-08-23', text: 'clicky side B' }) });
  assert.strictEqual(on([r], '2026-08-23')[0].key, 'note:2026-08-23:1');
});
