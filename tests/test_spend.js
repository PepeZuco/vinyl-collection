// Tests for the pure scan-spend formatting behind the form's cost readout.
// Run by tests/test_spend.py so `pytest` stays the single command.

const test = require('node:test');
const assert = require('node:assert');

const { formatMoney, scanHintText, sheetSpendText } = require('../static/spend.js');

// A scan costs a fraction of a cent, so the readout is in cents until the
// running total is big enough for dollars to say anything.
const USAGE = { month_usd: 0.042, total_usd: 0.19, month_scans: 6, total_scans: 27,
                estimate: { photo: 0.0071, spotify: 0.00042 } };

// ── formatMoney ─────────────────────────────────────────────────────────────

test('nothing spent reads as zero cents', () => {
  assert.strictEqual(formatMoney(0), '0¢');
});

test('a fraction of a cent keeps two decimals', () => {
  assert.strictEqual(formatMoney(0.00042), '0.04¢');
  assert.strictEqual(formatMoney(0.0071), '0.71¢');
});

test('a few cents keep one decimal', () => {
  assert.strictEqual(formatMoney(0.034), '3.4¢');
});

test('tens of cents are whole cents', () => {
  assert.strictEqual(formatMoney(0.42), '42¢');
});

test('a dollar or more switches to dollars', () => {
  assert.strictEqual(formatMoney(1.937), '$1.94');
});

test('an amount that would round to a hundred cents shows as a dollar', () => {
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
    'nothing is sent until you tap analyse · this one ≈ 0.71¢ · 4.2¢ this month');
});

test('an armed spotify scan is quoted at the spotify estimate', () => {
  assert.strictEqual(
    scanHintText({ armed: true, source: 'spotify', usage: USAGE }),
    'nothing is sent until you tap analyse · this one ≈ 0.04¢ · 4.2¢ this month');
});

test('the idle hint still reports the month so far', () => {
  assert.strictEqual(scanHintText({ armed: false, source: null, usage: USAGE }),
                     'add a cover or a spotify link first · 4.2¢ this month');
});

// ── sheetSpendText ──────────────────────────────────────────────────────────

test('the sheet quotes both ways in before either is picked', () => {
  assert.strictEqual(sheetSpendText(USAGE),
                     'photo ≈ 0.71¢ · spotify ≈ 0.04¢ · 4.2¢ spent this month');
});

test('the sheet says nothing until the numbers have loaded', () => {
  assert.strictEqual(sheetSpendText(null), '');
});
