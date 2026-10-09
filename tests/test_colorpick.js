// The photo color picker's arithmetic, tested without a DOM or a camera.
// Run by tests/test_colorpick.py so `pytest` stays the single command.
//
// The overlay itself is wiring; these are the parts with an answer worth
// pinning — where the photo sits in its box, which pixel a tap lands on, what
// color a patch of noisy camera pixels averages to, and where the loupe goes
// so the finger doesn't cover it.

const test = require('node:test');
const assert = require('node:assert');

const {
  rgbToHex, fitContain, toImagePoint, averagePatch, loupePlacement,
} = require('../static/colorpick.js');

// ── hex ─────────────────────────────────────────────────────────────────────

test('rgb becomes a lowercase #rrggbb, zero-padded', () => {
  assert.strictEqual(rgbToHex(255, 136, 0), '#ff8800');
  assert.strictEqual(rgbToHex(1, 2, 3), '#010203');
});

test('fractional and out-of-range channels are rounded and clamped', () => {
  assert.strictEqual(rgbToHex(254.6, -4, 300), '#ff00ff');
});

// ── fitting the photo in its box ────────────────────────────────────────────

test('a wide photo in a square box is letterboxed top and bottom', () => {
  assert.deepStrictEqual(fitContain(400, 400, 800, 400), { x: 0, y: 100, w: 400, h: 200 });
});

test('a tall photo in a wide box is pillarboxed left and right', () => {
  assert.deepStrictEqual(fitContain(600, 300, 300, 600), { x: 225, y: 0, w: 150, h: 300 });
});

// ── which pixel a tap lands on ──────────────────────────────────────────────

const fit = { x: 0, y: 100, w: 400, h: 200 };   // 800x400 photo, half scale

test('a tap inside the photo maps to its pixel at full resolution', () => {
  assert.deepStrictEqual(toImagePoint(200, 200, fit, 800, 400), { x: 400, y: 200 });
});

test('a tap in the letterbox clamps to the nearest edge pixel', () => {
  // dragging off the photo keeps the crosshair on it rather than losing it
  assert.deepStrictEqual(toImagePoint(-50, 20, fit, 800, 400), { x: 0, y: 0 });
  assert.deepStrictEqual(toImagePoint(999, 999, fit, 800, 400), { x: 799, y: 399 });
});

// ── averaging a patch ───────────────────────────────────────────────────────

// RGBA pixels, row-major, like ImageData.data
function image(w, h, pixel) {
  const data = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const [r, g, b] = pixel(x, y);
    data.set([r, g, b, 255], (y * w + x) * 4);
  }
  return data;
}

test('a patch of one color averages to that color', () => {
  const data = image(5, 5, () => [10, 20, 30]);
  assert.deepStrictEqual(averagePatch(data, 5, 5, 2, 2, 1), { r: 10, g: 20, b: 30 });
});

test('noise in the patch averages out', () => {
  // a checkerboard of black and white reads as mid grey, not either extreme
  const data = image(4, 4, (x, y) => ((x + y) % 2 ? [0, 0, 0] : [200, 200, 200]));
  const c = averagePatch(data, 4, 4, 1, 1, 1);   // 3x3: five 200s, four 0s
  assert.deepStrictEqual(c, { r: 1000 / 9, g: 1000 / 9, b: 1000 / 9 });
});

test('a patch at the corner only counts pixels inside the photo', () => {
  // left column red, the rest blue; the corner patch sees 2 red, 2 blue
  const data = image(4, 4, x => (x === 0 ? [255, 0, 0] : [0, 0, 255]));
  assert.deepStrictEqual(averagePatch(data, 4, 4, 0, 0, 1), { r: 127.5, g: 0, b: 127.5 });
});

// ── the loupe ───────────────────────────────────────────────────────────────

test('the loupe sits centred above the finger', () => {
  assert.deepStrictEqual(loupePlacement(200, 300, 400, 100, 30), { left: 150, top: 170 });
});

test('near the top it flips below the finger instead of leaving the box', () => {
  assert.deepStrictEqual(loupePlacement(200, 60, 400, 100, 30), { left: 150, top: 90 });
});

test('near a side it is pushed back inside the box', () => {
  assert.strictEqual(loupePlacement(10, 300, 400, 100, 30).left, 0);
  assert.strictEqual(loupePlacement(395, 300, 400, 100, 30).left, 300);
});
