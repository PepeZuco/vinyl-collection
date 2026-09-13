/* The desktop drawer's vertical cover carousel: how hard a gesture pushes, and
 * where the strip has to sit afterwards.
 *
 * Both halves used to live inline in the template, and both were wrong.
 *
 * Power. A swipe advanced by how far the finger had travelled and by nothing
 * else, and the wheel advanced exactly one record per event behind a 260ms
 * lockout. So a hard flick and a slow drag of the same length did the same
 * thing, and spinning the wheel hard did no more than nudging it. A gesture has
 * a speed as well as a length, and this reads both: the drag moves the record
 * the finger actually dragged to, and the speed it was going when it left the
 * glass throws in the rest, the way a real scroller's momentum would.
 *
 * Position. The strip cannot be measured off the DOM at the moment it changes,
 * because the slides resize through a CSS transition: read `offsetTop` in the
 * frame that `data-dist` changes and every slide still reports the size it is
 * transitioning AWAY from. The scroll target came out short by however much the
 * slides above the current one were about to resize, which is why the current
 * record settled with more records above it than below, or the reverse,
 * depending on which way you had just moved. So the position is arithmetic on
 * the ladder the new index IMPLIES, never a measurement of the outgoing layout.
 *
 * The ladder lives here rather than in the stylesheet because this file needs
 * the settled sizes before the browser has them; ddBind writes it back out as
 * custom properties, and the CSS reads it from there.
 *
 * Loaded as a plain script in the browser, where `const VinylCarousel` lands in
 * the global lexical scope for the inline script below it; required as a module
 * by the tests. */

const VinylCarousel = (function () {

  /* Slide edge length by distance from the current record. The last entry
   * covers everything further away — past three neighbours the taper has done
   * its job and the rest is an even sliver. */
  const LADDER = [220, 150, 104, 70, 48];
  const GAP = 14;

  /* One record per this many pixels of finger travel. Roughly the pitch of the
   * taper near the middle, so the strip keeps up with the finger. */
  const DRAG_PER_RECORD = 70;
  /* How far a release is projected forward, in milliseconds of travel at the
   * speed the finger left at. Long enough that a flick clearly outruns a drag,
   * short enough that it does not feel thrown. */
  const PROJECTION_MS = 130;
  /* px/ms. A touchend a millisecond after the last touchmove reports a wild
   * speed; without a ceiling one bad sample would fling the user out of the
   * collection entirely. */
  const MAX_VELOCITY = 4;
  const MAX_FLING = 12;

  /* One notch of a classic mouse wheel is deltaY 100 in every browser that
   * matters, so a notch is a record. Trackpads send far smaller deltas, which
   * is what the leftover in createWheelStepper is for. */
  const WHEEL_PER_RECORD = 100;
  const WHEEL_LINE_PX = 16;
  const WHEEL_PAGE_PX = 400;
  const MAX_WHEEL = 10;
  /* A gap this long means the last gesture is over and its leftover is stale. */
  const WHEEL_IDLE_MS = 400;

  const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
  /* Rounds away from zero symmetrically. Math.round breaks ties upward, which
   * would make a flick up and the same flick down disagree by a record. */
  const steps = n => Math.sign(n) * Math.round(Math.abs(n));

  function opt(opts, key, fallback) {
    const v = opts && opts[key];
    return v == null ? fallback : v;
  }

  /* The edge length of the slide `dist` records away from the current one. */
  function sizeAt(dist, ladder) {
    const l = ladder || LADDER;
    return l[Math.min(l.length - 1, Math.abs(dist))];
  }

  /* The scroll offset that puts record `index` in the middle of the window.
   *
   * `index` is the record that has just BECOME current, so every other slide is
   * sized by its distance from it — that is the whole point, and the reason
   * this is arithmetic rather than a DOM read. */
  function centerOffset(index, count, opts) {
    const ladder = opt(opts, 'ladder', LADDER);
    const gap = opt(opts, 'gap', GAP);
    const clientHeight = opt(opts, 'clientHeight', 0);
    let top = opt(opts, 'padTop', 0);
    for (let k = 0; k < index && k < count; k++) top += sizeAt(k - index, ladder) + gap;
    return top + sizeAt(0, ladder) / 2 - clientHeight / 2;
  }

  /* The padding the strip needs above and below so that the first and last
   * records can reach the middle at all.
   *
   * This was a fixed 280px, which is only correct for a window exactly 560px
   * tall. In a taller drawer the browser clamps scrollTop at 0 before the first
   * record reaches the centre, and it sits high with the whole collection below
   * it — half of the "not centred" report. Half the window, less half the slide
   * being centred, is the value that always works. */
  function centerPadding(clientHeight, opts) {
    const ladder = opt(opts, 'ladder', LADDER);
    return Math.max(0, clientHeight / 2 - sizeAt(0, ladder) / 2);
  }

  /* Records the finger itself has dragged past. Applied live, during the drag,
   * so the strip tracks the finger instead of sitting still until release. */
  function dragSteps(dy, opts) {
    return steps(dy / opt(opts, 'perRecord', DRAG_PER_RECORD));
  }

  /* Records the release throws in on top, from the speed in px/ms the finger
   * was travelling when it lifted. A finger that comes to rest first adds
   * nothing, which is how a slow, deliberate drag stays on the record it
   * chose. */
  function flingSteps(velocity, opts) {
    const perRecord = opt(opts, 'perRecord', DRAG_PER_RECORD);
    const projection = opt(opts, 'projectionMs', PROJECTION_MS);
    const ceiling = opt(opts, 'maxVelocity', MAX_VELOCITY);
    const max = opt(opts, 'max', MAX_FLING);
    const v = clamp(velocity, -ceiling, ceiling);
    return clamp(steps(v * projection / perRecord), -max, max);
  }

  /* The wheel, which arrives as a stream of events rather than one gesture.
   *
   * Keeps the leftover between events, so a trackpad's dribble of 8px deltas
   * adds up to a record instead of being rounded away eight times over, and so
   * a hard spin spends everything it is given instead of being rate-limited
   * into one record per lockout. The leftover is dropped after a pause: it
   * belongs to the gesture that banked it, not to the next one. */
  function createWheelStepper(opts) {
    const perRecord = opt(opts, 'perRecord', WHEEL_PER_RECORD);
    const linePx = opt(opts, 'lineHeight', WHEEL_LINE_PX);
    const pagePx = opt(opts, 'pageHeight', WHEEL_PAGE_PX);
    const max = opt(opts, 'max', MAX_WHEEL);
    const idleMs = opt(opts, 'idleResetMs', WHEEL_IDLE_MS);
    let leftover = 0, last = -Infinity;

    return {
      step(deltaY, deltaMode, now) {
        const t = now == null ? 0 : now;
        if (t - last > idleMs) leftover = 0;
        last = t;
        leftover += deltaY * (deltaMode === 1 ? linePx : deltaMode === 2 ? pagePx : 1);
        const n = Math.trunc(leftover / perRecord);
        /* The unclamped n comes off the leftover even when the return is
         * capped: one absurd delta should not bank thousands of pixels that
         * then march the list along on its own. */
        leftover -= n * perRecord;
        return clamp(n, -max, max);
      },
      reset() { leftover = 0; last = -Infinity; },
    };
  }

  return {
    LADDER, GAP, sizeAt, centerOffset, centerPadding,
    dragSteps, flingSteps, createWheelStepper,
  };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylCarousel;
