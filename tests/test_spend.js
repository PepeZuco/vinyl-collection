// Tests for the pure scan-spend formatting behind the form's cost readout.
// Run by tests/test_spend.py so `pytest` stays the single command.

const test = require('node:test');
const assert = require('node:assert');

const { formatMoney, scanHintText, sheetSpendText } = require('../static/spend.js');

// A scan costs a fraction of a cent, but the readout is dollars either way —
// one shape of money on screen, whatever the size of the number.
const USAGE = { month_usd: 0.042, total_usd: 0.19, month_scans: 6, total_scans: 27,
                estimate: { photo: 0.0071, spotify: 0.00042 } };

// ── formatMoney ────────────────────────────────────────────────────────────

test('nothing spent still reads as a price', () => {
  assert.strictEqual(formatMoney(0), '$0.00');
});

test('a fraction of a cent rounds to the nearest cent', () => {
  assert.strictEqual(formatMoney(0.00042), '$0.00');
  assert.strictEqual(formatMoney(0.0071), '$0.01');
});

test('a few cents keep their two decimals', () => {
  assert.strictEqual(formatMoney(0.034), '$0.03');
  assert.strictEqual(formatMoney(0.042), '$0.04');
});

test('tens of cents stay under the dollar', () => {
  assert.strictEqual(formatMoney(0.42), '$0.42');
});

test('a dollar or more reads the same way', () => {
  assert.strictEqual(formatMoney(1.937), '$1.94');
});

test('an amount just short of a dollar rounds up to one', () => {
  assert.strictEqual(formatMoney(0.999), '$1.00');
});

// ── scanHintText ────────────────────────────────────────────────────────────

test('with nothing handed in the hint says what to hand in', () => {
  assert.strictEqual(scanHintText({ armed: false, source: null, usage: null }),
                     'add a cover or a spotify link first');
});

test('with something handed in the hint says nothing is sent yet', () => {
  assert.strictEqual(scanHintText({ armed: true, source: 'photo', usage: null }),
                     'nothing is sent until you tap analyse');
});

test('an armed photo scan is quoted at the photo estimate', () => {
  assert.strictEqual(
    scanHintText({ armed: true, source: 'photo', usage: USAGE }),
    'nothing is sent until you tap analyse · this one ≈ $0.01 · $0.04 this month');
});

test('an armed spotify scan is quoted at the spotify estimate', () => {
  assert.strictEqual(
    scanHintText({ armed: true, source: 'spotify', usage: USAGE }),
    'nothing is sent until you tap analyse · this one ≈ $0.00 · $0.04 this month');
});

test('the idle hint still reports the month so far', () => {
  assert.strictEqual(scanHintText({ armed: false, source: null, usage: USAGE }),
                     'add a cover or a spotify link first · $0.04 this month');
});

test('a verb replaces "analyse" for a button that is not labelled that', () => {
  assert.strictEqual(
    scanHintText({ armed: true, source: 'search', usage: null, verb: 'search' }),
    'nothing is sent until you tap search');
});

test('no verb still means analyse, for every caller that never passed one', () => {
  assert.strictEqual(
    scanHintText({ armed: true, source: 'photo', usage: null }),
    'nothing is sent until you tap analyse');
});

// ── sheetSpendText ──────────────────────────────────────────────────────────

test('the sheet quotes both ways in before either is picked', () => {
  assert.strictEqual(sheetSpendText(USAGE),
                     'photo ≈ $0.01 · spotify ≈ $0.00 · $0.04 spent this month');
});

test('the sheet says nothing until the numbers have loaded', () => {
  assert.strictEqual(sheetSpendText(null), '');
});
