// Tests for the phone's full-screen cover: the tilt every record gets, and the
// shrink-wrap glare only a NEW one does.
// Run by tests/test_covertilt.py so `pytest` stays the single command.
//
// jsdom has no gyroscope, so the part worth pinning down here is the maths
// between a deviceorientation reading and the transform it produces: that the
// way you were holding the phone when the cover opened reads as flat, that the
// cover never leans past the cap, that the glare runs AGAINST the tilt (the
// light stays put and the sleeve moves under it) and sweeps the whole sleeve
// over the lean, and that landscape does not swap the axes on you. What it feels like in the hand is in
// docs/cover-tilt-manual-verification.md.

const test = require('node:test');
const assert = require('node:assert');

const {
  MAX_TILT, wantsTilt, hasShrinkWrap, screenTilt, tiltFrom, smooth, requestMotion,
} = require('../static/covertilt.js');

const near = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-9, `${msg}: ${a} != ${b}`);

// ── who tilts ───────────────────────────────────────────────────────────────

test('every record tilts, unless motion is reduced', () => {
  assert.strictEqual(wantsTilt(false), true);
  assert.strictEqual(wantsTilt(true), false);
});

test('only a new record is in shrink-wrap', () => {
  assert.strictEqual(hasShrinkWrap({ condition: 'new' }), true);
  assert.strictEqual(hasShrinkWrap({ condition: 'used' }), false);
  assert.strictEqual(hasShrinkWrap({ condition: '' }), false);
  assert.strictEqual(hasShrinkWrap({}), false);
});

// ── from the device's axes to the screen's ──────────────────────────────────

test('portrait reads beta as front-back and gamma as left-right', () => {
  assert.deepStrictEqual(screenTilt(40, 10, 0), { fb: 40, lr: 10 });
});

test('landscape turns the axes with the screen', () => {
  // rotated a quarter turn counter-clockwise: the device's right edge is up
  assert.deepStrictEqual(screenTilt(40, 10, 90), { fb: -10, lr: 40 });
  assert.deepStrictEqual(screenTilt(40, 10, 270), { fb: 10, lr: -40 });
  assert.deepStrictEqual(screenTilt(40, 10, -90), { fb: 10, lr: -40 });
  assert.deepStrictEqual(screenTilt(40, 10, 180), { fb: -40, lr: -10 });
});

// ── a reading against the baseline ──────────────────────────────────────────

test('the way the phone was held when the cover opened is flat', () => {
  const base = { fb: 55, lr: -8 };
  const t = tiltFrom(base, { fb: 55, lr: -8 });
  near(t.rx, 0, 'rx'); near(t.ry, 0, 'ry');
  near(t.gx, 50, 'glare x'); near(t.gy, 50, 'glare y');
});

test('tilting the phone right turns the cover right, and the glare goes left', () => {
  const t = tiltFrom({ fb: 0, lr: 0 }, { fb: 0, lr: 10 });
  assert.ok(t.ry > 0, 'cover turns with the phone');
  assert.ok(t.gx < 50, 'glare runs the other way');
  near(t.rx, 0, 'no front-back tilt');
});

test('tipping the top away leans the cover back, and the glare goes down', () => {
  const t = tiltFrom({ fb: 50, lr: 0 }, { fb: 60, lr: 0 });
  assert.ok(t.rx < 0, 'top leans back');
  assert.ok(t.gy > 50, 'glare runs the other way');
});

test('the cover never leans past the cap, however far the phone goes', () => {
  const t = tiltFrom({ fb: 0, lr: 0 }, { fb: 80, lr: -80 });
  near(Math.abs(t.rx), MAX_TILT, 'rx capped');
  near(Math.abs(t.ry), MAX_TILT, 'ry capped');
});

test('over the full lean the glare crosses the whole sleeve, edge to edge', () => {
  // It used to wander ±40% round the middle, which reads as a spot that
  // never leaves the cover. A light on shrink-wrap slides right off it.
  const right = tiltFrom({ fb: 0, lr: 0 }, { fb: 0, lr: 80 });
  const left = tiltFrom({ fb: 0, lr: 0 }, { fb: 0, lr: -80 });
  assert.ok(right.gx < 0, `off the left edge at full right lean, got ${right.gx}`);
  assert.ok(left.gx > 100, `off the right edge at full left lean, got ${left.gx}`);
  const back = tiltFrom({ fb: 0, lr: 0 }, { fb: 80, lr: 0 });
  const fwd = tiltFrom({ fb: 0, lr: 0 }, { fb: -80, lr: 0 });
  assert.ok(back.gy > 100 && fwd.gy < 0, 'and top to bottom');
});

test('crossing the 180° seam is a small tilt, not a full turn', () => {
  // beta runs -180..180; holding the phone past upright wraps it
  const t = tiltFrom({ fb: 178, lr: 0 }, { fb: -178, lr: 0 });
  assert.ok(Math.abs(t.rx) < MAX_TILT, `rx ${t.rx} should be a 4° nudge`);
});

// ── smoothing ───────────────────────────────────────────────────────────────

test('smoothing moves part of the way and lands exactly when close', () => {
  const a = { rx: 0, ry: 0, gx: 50, gy: 50 };
  const b = { rx: 10, ry: -10, gx: 20, gy: 80 };
  const s = smooth(a, b, 0.25);
  near(s.rx, 2.5, 'rx'); near(s.ry, -2.5, 'ry'); near(s.gx, 42.5, 'gx'); near(s.gy, 57.5, 'gy');
  assert.deepStrictEqual(smooth(a, a, 0.25), a);
});

// ── permission ──────────────────────────────────────────────────────────────

test('no DeviceOrientationEvent at all is unsupported', async () => {
  assert.strictEqual(await requestMotion({}), 'unsupported');
});

test('a browser that does not ask (Android) is granted', async () => {
  assert.strictEqual(await requestMotion({ DeviceOrientationEvent: function () {} }), 'granted');
});

test('iOS asks, and the answer is passed through', async () => {
  const yes = function () {}; yes.requestPermission = async () => 'granted';
  const no = function () {};  no.requestPermission = async () => 'denied';
  assert.strictEqual(await requestMotion({ DeviceOrientationEvent: yes }), 'granted');
  assert.strictEqual(await requestMotion({ DeviceOrientationEvent: no }), 'denied');
});

test('iOS asks synchronously, inside the tap that opened the cover', () => {
  // Safari only shows the prompt if requestPermission is called in the same
  // task as the user gesture — an await before it would lose the tap.
  let called = false;
  const ev = function () {}; ev.requestPermission = () => { called = true; return Promise.resolve('granted'); };
  requestMotion({ DeviceOrientationEvent: ev });
  assert.strictEqual(called, true);
});

test('a permission call that throws is a denial, not an error', async () => {
  const ev = function () {}; ev.requestPermission = () => { throw new Error('not a gesture'); };
  assert.strictEqual(await requestMotion({ DeviceOrientationEvent: ev }), 'denied');
  const rej = function () {}; rej.requestPermission = () => Promise.reject(new Error('nope'));
  assert.strictEqual(await requestMotion({ DeviceOrientationEvent: rej }), 'denied');
});
