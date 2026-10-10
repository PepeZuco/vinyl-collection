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
  MAX_TILT, wantsTilt, hasShrinkWrap, screenTilt, tiltFrom, smooth, requestMotion, follow,
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

// ── follow: the listener + easing the inline cover and the zoomed cover share ──

function fakeWin(angle = 0) {
  const w = {
    screen: { orientation: { angle } },
    _l: {}, _q: [], _id: 0,
    addEventListener(t, f) { this._l[t] = f; },
    removeEventListener(t, f) { if (this._l[t] === f) delete this._l[t]; },
    requestAnimationFrame(f) { const id = ++this._id; this._q.push([id, f]); return id; },
    cancelAnimationFrame(id) { this._q = this._q.filter(([i]) => i !== id); },
    fire(beta, gamma) { if (this._l.deviceorientation) this._l.deviceorientation({ beta, gamma }); },
    flush(n = 80) { for (let i = 0; i < n && this._q.length; i++) this._q.shift()[1](); },
  };
  return w;
}
function fakeEl() {
  const props = {};
  return { props, style: {
    setProperty(k, v) { props[k] = v; },
    removeProperty(k) { delete props[k]; },
  } };
}

test('follow: the first reading is flat, a later one leans the element', () => {
  const win = fakeWin(), el = fakeEl();
  follow(win, () => el);
  win.fire(55, 0); win.flush();
  assert.strictEqual(Number(el.props['--ry']), 0);
  win.fire(55, 10); win.flush();
  assert.ok(Number(el.props['--ry']) > 0, 'right edge down turns the cover');
  assert.ok(Number(el.props['--gx']) < 50, 'the glare runs the other way');
});

test('follow: a reading with no sensor data (nulls) is ignored', () => {
  const win = fakeWin(), el = fakeEl();
  follow(win, () => el);
  win.fire(null, null); win.flush();
  assert.deepStrictEqual(el.props, {});
});

test('follow: stop removes the listener and clears the element', () => {
  const win = fakeWin(), el = fakeEl();
  const f = follow(win, () => el);
  win.fire(55, 0); win.fire(55, 10); win.flush();
  f.stop();
  assert.strictEqual(win._l.deviceorientation, undefined);
  assert.deepStrictEqual(el.props, {});
  win.fire(55, 30); win.flush();
  assert.deepStrictEqual(el.props, {}, 'a stopped follower never moves again');
});

test('follow: rebase takes the next reading as flat again', () => {
  const win = fakeWin(), el = fakeEl();
  const f = follow(win, () => el);
  win.fire(55, 0); win.fire(55, 20); win.flush();
  f.rebase();
  win.fire(55, 20); win.flush();      // how the phone is held now
  assert.ok(Math.abs(Number(el.props['--ry'] || 0)) < 0.5, 'no jump after a rebase');
});

test('follow: turning to landscape re-measures instead of jumping', () => {
  const win = fakeWin(0), el = fakeEl();
  follow(win, () => el);
  win.fire(55, 0); win.flush();
  win.screen.orientation.angle = 90;
  win.fire(5, 55); win.flush();
  assert.ok(Math.abs(Number(el.props['--rx'])) < 0.5 && Math.abs(Number(el.props['--ry'])) < 0.5);
});

test('follow: a missing element is tolerated', () => {
  const win = fakeWin();
  follow(win, () => null);
  win.fire(55, 0); win.fire(55, 10);
  assert.doesNotThrow(() => win.flush());
});
