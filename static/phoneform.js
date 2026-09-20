/* The add/edit form's phone rules.
 *
 * The phone redraw is mostly wiring — moving the save button, swapping a
 * datalist for chips, collapsing sections that are empty. This file holds the
 * part of it that has an answer worth pinning down and testing on its own:
 * which rail segment is which, how the places are ranked, what each section
 * row says about the record behind it, and whether a drag was a dismissal.
 *
 * Nothing here touches the DOM or reads a global. Loaded as a plain script in
 * the browser, where `const VinylPhoneForm` lands in the global lexical scope
 * for the inline script below it; required as a module by the tests.
 */
const VinylPhoneForm = (() => {

  /* The phone's names for the four steps. The desktop spine keeps its verbs
   * (Identify / Acquire / Log / Tracklist); these are the section headers the
   * form already uses inside the steps, so the rail label and the content the
   * user is looking at agree. */
  const STEPS = [
    { n: 1, phone: 'The record' },
    { n: 2, phone: 'The purchase' },
    { n: 3, phone: 'The log' },
    { n: 4, phone: 'The object' },
  ];

  function railStates(current) {
    return STEPS.map(s => s.n < current ? 'done' : s.n === current ? 'now' : 'ahead');
  }

  /* Safari renders a <datalist> as a thin strip under the keyboard, which is
   * unusable one-handed. The phone offers chips instead — and ranks them by
   * how often the place was actually used, where the datalist is alphabetical.
   * The record's own value is pinned first whatever its rank, because the one
   * place guaranteed to be relevant is the one already on the record. */
  function rankPlaces(records, current, limit = 4) {
    const counts = new Map();
    for (const r of (records || [])) {
      const name = String((r && r.bought_where) || '').trim();
      if (!name) continue;
      counts.set(name, (counts.get(name) || 0) + 1);
    }
    const pinned = String(current || '').trim();
    const ranked = [...counts.entries()]
      // count descending, then name, so a tie is stable rather than
      // insertion-ordered — two places used once each should not swap
      // position because a record was edited.
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([name]) => name)
      .filter(name => name !== pinned);
    return (pinned ? [pinned, ...ranked] : ranked).slice(0, limit);
  }

  /* Collapsed only when there is nothing to hide. Every edit of a played
   * record opens its play list already expanded, so the collapse never costs
   * a tap to reach something that exists. */
  function logSectionOpen(entries) { return !!(entries && entries.length); }

  /* "none" rather than "0": the row is answering "anything to log yet?", and
   * a zero reads like a value that was measured. */
  function logCount(entries) {
    const n = (entries && entries.length) || 0;
    return n ? String(n) : 'none';
  }

  // ── section previews ──────────────────────────────────────────────────────
  // Each row says what it holds so you can see whether the thing you came to
  // change is already right without opening it.

  const join = parts => parts.filter(Boolean).join(' · ');
  const plural = (n, one) => `${n} ${one}${n === 1 ? '' : 's'}`;

  const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

  /* An ISO day as "12 Sep 2026". Parsed by hand rather than through Date:
   * `new Date('2026-09-12')` is UTC midnight, which in São Paulo is the 11th. */
  function shortDate(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
    if (!m) return '';
    return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}`;
  }

  function recordPreview(v) {
    return join([v.artist, v.year, v.country]) || 'not identified';
  }

  function purchasePreview(v) {
    if (!v.haveIt) return 'Wishlist';
    return join([v.where, shortDate(v.date), v.condition]) || 'nothing recorded';
  }

  function logPreview(v) {
    return join([
      v.myRating ? `Pepe ${v.myRating}` : '',
      v.wifeRating ? `Jenni ${v.wifeRating}` : '',
      v.plays ? plural(v.plays, 'play') : '',
      v.notes ? plural(v.notes, 'note') : '',
    ]) || 'nothing logged';
  }

  function objectPreview(v) {
    return join([
      v.size,
      v.discs ? plural(v.discs, 'disc') : '',
      v.tracks ? plural(v.tracks, 'track') : '',
      v.painted ? 'painted' : '',
    ]) || 'nothing set';
  }

  /* Drag to dismiss, bound to the nav area only so it can never fight the
   * body's scroll. Two ways to qualify: far enough, or fast enough. Without
   * the velocity arm a deliberate flick that only travels 40px springs back,
   * which reads as the gesture not working. */
  const DRAG_DISTANCE = 80;     // px
  const DRAG_VELOCITY = 0.5;    // px/ms

  function dragDismisses(dy, dt) {
    if (dy <= 0) return false;                       // upward is not a dismissal
    if (dy >= DRAG_DISTANCE) return true;
    return dt > 0 && (dy / dt) >= DRAG_VELOCITY;
  }

  return {
    STEPS, railStates, rankPlaces, logSectionOpen, logCount,
    recordPreview, purchasePreview, logPreview, objectPreview,
    shortDate, dragDismisses,
    DRAG_DISTANCE, DRAG_VELOCITY,
  };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylPhoneForm;
