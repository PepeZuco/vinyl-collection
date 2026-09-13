// Tests for the desktop drawer's vertical cover carousel.
// Run by tests/test_carousel.py so `pytest` stays the single command.
//
// Two faults are pinned down here, both of them invisible to every other test
// because the carousel used to compute all of this inline in the template.
//
// The gesture half: a swipe advanced by how FAR the finger travelled and by
// nothing else, and the wheel advanced exactly one record per event no matter
// how hard the wheel was spun. Neither read the power of the movement, so a
// hard flick and a slow drag of the same length did the same thing.
//
// The geometry half: the scroll target was measured off the live DOM in the
// same frame the slides were told to change size, i.e. while their width/height
// transitions still sat at their starting values. The target was therefore
// computed from the OLD layout, and the current record settled off-centre by
// however much the slides above it had resized — more records above than below,
// or the reverse, depending on which way you had just moved.

const test = require('node:test');
const assert = require('node:assert');

const {
  LADDER, GAP, sizeAt, centerOffset, centerPadding, dragSteps, flingSteps,
  createWheelStepper,
} = require('../static/carousel.js');

// ── the size ladder ─────────────────────────────────────────────────────────

test('the current record is the biggest slide and the taper only shrinks', () => {
  for (let i = 1; i < LADDER.length; i++) {
    assert.ok(LADDER[i] < LADDER[i - 1],
      `slide at distance ${i} (${LADDER[i]}) is not smaller than its neighbour`);
  }
});

test('distance is symmetrical — a record three above is drawn like one three below', () => {
  assert.equal(sizeAt(-3), sizeAt(3));
  assert.equal(sizeAt(0), LADDER[0]);
});

test('everything past the end of the ladder is drawn at the smallest size', () => {
  const last = LADDER[LADDER.length - 1];
  assert.equal(sizeAt(LADDER.length), last);
  assert.equal(sizeAt(99), last);
  assert.equal(sizeAt(-99), last);
});

// ── centring ────────────────────────────────────────────────────────────────
//
// centerOffset answers one question: what scrollTop puts record `index` in the
// middle of the window, GIVEN that `index` is the record that just became
// current and the slides have settled into the sizes that implies. It is
// arithmetic on the ladder rather than a DOM measurement precisely so it can
// be asked before the CSS transitions have run.

const CH = 600;                                  // a plausible drawer height
const pad = centerPadding(CH);
const at = (index, count) => centerOffset(index, count, { clientHeight: CH, padTop: pad });

test('the padding lets the first record reach the middle on its own', () => {
  // With the right padding the very first record is centred at scrollTop 0 —
  // there is nothing above it to scroll through. A fixed padding smaller than
  // half the window cannot do this: the browser clamps at 0 and the record
  // sits high, with every other record below it. That was the bug.
  assert.equal(at(0, 10), 0);
});

test('the padding is half the window, less half the current slide', () => {
  assert.equal(centerPadding(600), 300 - LADDER[0] / 2);
  assert.equal(centerPadding(1000), 500 - LADDER[0] / 2);
});

test('a window shorter than the current slide asks for no padding rather than negative', () => {
  assert.equal(centerPadding(100), 0);
});

test('the last record reaches the middle too', () => {
  // Symmetry: centring the last of N sits as far from the end of the content
  // as centring the first sits from its start.
  const count = 10;
  const contentHeight = 2 * pad + LADDER[0] +
    // every other slide, at its distance from the last record
    Array.from({ length: count - 1 }, (_, k) => sizeAt(k - (count - 1)) + GAP)
      .reduce((a, b) => a + b, 0);
  assert.equal(at(count - 1, count), contentHeight - CH);
});

test('each step down moves the strip by the two slides that swapped size', () => {
  // Stepping 0 -> 1 both re-centres and resizes. In the settled layout the two
  // centres sit a pitch apart, but slide 0 has also shrunk to distance 1, which
  // lifts its own centre by half of what it gave up. The strip moves by the
  // difference — and getting this wrong by exactly that shrink is the
  // off-centre drift being fixed here.
  const pitch = LADDER[1] / 2 + GAP + LADDER[0] / 2;
  const shrink = (LADDER[0] - LADDER[1]) / 2;
  assert.equal(at(1, 10) - at(0, 10), pitch - shrink);
});

test('the offset is computed from the settled ladder, not the outgoing one', () => {
  // The regression this file exists for. Stepping 4 -> 5 was measured off the
  // DOM in the frame the sizes were told to change, so record 4 was still full
  // size and record 5 still a distance-1 slide. Centring record 5 has to be
  // arithmetic on the ladder record 5 IMPLIES, not on the one still on screen.
  let top = pad;
  for (let k = 0; k < 5; k++) top += sizeAt(k - 5) + GAP;
  assert.equal(at(5, 20), top + LADDER[0] / 2 - CH / 2);

  // What the old code effectively asked for: the same walk with record 4 still
  // at distance 0 and record 5 at distance 1. It has to come out different, or
  // this whole fix is a no-op.
  let stale = pad;
  for (let k = 0; k < 5; k++) stale += sizeAt(k - 4) + GAP;
  const staleTarget = stale + sizeAt(1) / 2 - CH / 2;
  assert.notEqual(at(5, 20), staleTarget,
    'centring on the outgoing layout landed in the same place — nothing was fixed');
});

test('centring never depends on records that are not there', () => {
  // A one-record list has nothing to walk past, so it centres at scrollTop 0.
  assert.equal(at(0, 1), 0);
});

// ── how far a drag moves ────────────────────────────────────────────────────

test('dragging one slide-pitch moves exactly one record', () => {
  assert.equal(dragSteps(70), 1);
  assert.equal(dragSteps(-70), -1);
});

test('a drag shorter than half a pitch moves nothing', () => {
  assert.equal(dragSteps(20), 0);
  assert.equal(dragSteps(-20), 0);
});

test('a long drag moves proportionally — this part was already right', () => {
  assert.equal(dragSteps(280), 4);
  assert.equal(dragSteps(-280), -4);
});

// ── how much extra a flick throws in ────────────────────────────────────────
//
// This is the half that was missing. flingSteps reads the speed the finger was
// travelling at the moment it left the glass, in px/ms, and projects it forward
// the way a scroller's momentum would.

test('a finger that stops before it lifts adds nothing', () => {
  assert.equal(flingSteps(0), 0);
});

test('a soft, slow release stays on the single record the drag chose', () => {
  // 70px over half a second: 0.14 px/ms. Deliberate, unhurried, one record.
  assert.equal(flingSteps(70 / 500), 0);
});

test('a hard flick carries several records past where the finger stopped', () => {
  const soft = flingSteps(0.15);
  const hard = flingSteps(1.2);
  const harder = flingSteps(2.8);
  assert.ok(hard > soft, 'a hard flick did not outrun a soft one');
  assert.ok(harder > hard, 'a harder flick did not outrun a hard one');
  assert.ok(hard >= 2, `a hard flick added only ${hard} record(s)`);
});

test('the direction of the throw is the direction of the finger', () => {
  assert.equal(flingSteps(-1.2), -flingSteps(1.2));
});

test('an impossibly fast reading cannot throw the list to its end', () => {
  // A touchend one millisecond after the last touchmove reports a wild
  // velocity. Clamped, or a stray sample would fling the user 200 records away.
  const absurd = flingSteps(500);
  assert.ok(Math.abs(absurd) <= 12, `a bad velocity sample threw ${absurd} records`);
  assert.equal(absurd, flingSteps(1000), 'the clamp is not flat');
});

test('drag and fling combine — a hard flick beats the same drag done slowly', () => {
  const dy = 120, perRecord = 70;
  const slow = dragSteps(dy) + flingSteps(dy / 900);
  const fast = dragSteps(dy) + flingSteps(dy / 100);
  assert.equal(slow, Math.round(dy / perRecord), 'a slow drag should be distance alone');
  assert.ok(fast >= slow + 2, `the flick added only ${fast - slow} over the slow drag`);
});

// ── the wheel ───────────────────────────────────────────────────────────────
//
// The wheel used to move one record per event and then ignore the wheel for
// 260ms, so spinning hard and nudging gently were the same gesture. It now
// spends the delta it is given, and keeps the remainder so a trackpad's stream
// of tiny deltas adds up to a record instead of being rounded away.

test('one notch of a mouse wheel is one record', () => {
  const w = createWheelStepper();
  assert.equal(w.step(100, 0, 0), 1);
});

test('a hard spin in a single event moves several records', () => {
  const w = createWheelStepper();
  assert.equal(w.step(500, 0, 0), 5);
});

test('spinning hard is not rate-limited into one record at a time', () => {
  // Five notches arriving 10ms apart used to yield one record, because the
  // second through fifth landed inside the lockout and were dropped.
  const w = createWheelStepper();
  let moved = 0;
  for (let i = 0; i < 5; i++) moved += w.step(100, 0, i * 10);
  assert.equal(moved, 5);
});

test('a trackpad’s small deltas accumulate instead of being lost', () => {
  const w = createWheelStepper();
  let moved = 0;
  for (let i = 0; i < 10; i++) moved += w.step(10, 0, i * 10);
  assert.equal(moved, 1, 'ten 10px deltas should be one 100px record');
});

test('the leftover is dropped once the gesture is over', () => {
  const w = createWheelStepper();
  assert.equal(w.step(90, 0, 0), 0);          // banked, not yet a record
  // A new gesture, long after. Were the first 90 still banked this would tip
  // over into a record the user never asked for.
  assert.equal(w.step(90, 0, 5000), 0, 'stale leftover leaked into a new gesture');
  // Within that new gesture it does accumulate, as usual.
  assert.equal(w.step(20, 0, 5010), 1);
});

test('scrolling back and forth nets out', () => {
  const w = createWheelStepper();
  assert.equal(w.step(100, 0, 0), 1);
  assert.equal(w.step(-100, 0, 10), -1);
});

test('line and page deltas are read in their own units', () => {
  // deltaMode 1 counts lines and 2 counts pages; taking either as pixels makes
  // a Firefox wheel event move a hundredth of what it should.
  const lines = createWheelStepper();
  const pixels = createWheelStepper();
  assert.equal(pixels.step(7, 0, 0), 0, 'seven pixels is not a record');
  assert.ok(lines.step(7, 1, 0) >= 1, 'seven lines was read as seven pixels');
  const pages = createWheelStepper();
  assert.ok(pages.step(1, 2, 0) >= 1, 'a page delta moved nothing');
});

test('a single event cannot fling the whole collection past', () => {
  const w = createWheelStepper();
  const n = w.step(100000, 0, 0);
  assert.ok(n <= 10, `one event moved ${n} records`);
});
