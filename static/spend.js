/* What a scan costs, in words the form can show.
 *
 * Anthropic publishes no balance or remaining-credits endpoint, so "how much
 * is left" is not a question anything can answer. What the app CAN say is what
 * it has spent — the server keeps a ledger of every call — and what the next
 * scan is likely to cost, averaged over the scans already made.
 *
 * Pure string building, kept out of index.html so it is testable: see
 * tests/test_spend.js. */
const VinylSpend = (function () {

  /* Always dollars, always two decimals: $0.05, $1.94. A scan costs a
   * fraction of a cent, so the small end of the range collapses — a spotify
   * estimate reads $0.00 — but one shape of money on screen beats a readout
   * that changes units as the total grows. */
  function formatMoney(usd) {
    const value = Number(usd) || 0;
    return '$' + value.toFixed(2);
  }

  /* The line under the analyse button. It already carried the reason the
   * button is live or dead; the price rides along with it because that is the
   * last thing on screen before the money is spent.
   *
   * `usage` is null until the readout has loaded — the hint then says exactly
   * what it always said, rather than flashing a placeholder price.
   *
   * `verb` names the button this hint sits under — "analyse" by default, so
   * every existing caller reads the same as before. The search popup passes
   * 'search': its button is not labelled analyse, and saying so under it was
   * just wrong. */
  function scanHintText({ armed, source, usage, verb }) {
    const base = armed ? 'nothing is sent until you tap ' + (verb || 'analyse')
                       : 'add a cover or a spotify link first';
    if (!usage) return base;
    const month = formatMoney(usage.month_usd) + ' this month';
    const estimate = armed ? (usage.estimate || {})[source] : null;
    if (estimate == null) return base + ' · ' + month;
    return base + ' · this one ≈ ' + formatMoney(estimate) + ' · ' + month;
  }

  /* The sheet's own line. Both prices, because the sheet is where the two ways
   * in sit side by side and neither has been picked yet. */
  function sheetSpendText(usage) {
    if (!usage) return '';
    const estimate = usage.estimate || {};
    return 'photo ≈ ' + formatMoney(estimate.photo)
         + ' · spotify ≈ ' + formatMoney(estimate.spotify)
         + ' · ' + formatMoney(usage.month_usd) + ' spent this month';
  }

  return { formatMoney, scanHintText, sheetSpendText };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylSpend;
