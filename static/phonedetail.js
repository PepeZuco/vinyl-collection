/* The phone's record screen: the two decisions that need no DOM.
 *
 * neighbors  - which records sit in the bottom row. The ends of the list have
 *              nothing past them, so that side is null (the row leaves it
 *              empty); the swipe on the cover does not wrap, and neither does
 *              this.
 * settle     - what a drag on the sheet's handle decides. A flick decides by
 *              direction alone; a slower drag has to travel DRAG_PX; anything
 *              less, or the wrong way, leaves the sheet where it was.
 *
 * Loaded as a plain script in the browser, where `const VinylPhoneDetail`
 * lands in the global lexical scope; required as a module by the tests. */
const VinylPhoneDetail = (() => {
  const DRAG_PX = 48;     // px a slow drag must travel to change the sheet
  const FLICK = 0.4;      // px/ms above which direction alone decides

  function neighbors(list, idx) {
    if (!Array.isArray(list) || list.length < 2 || idx < 0 || idx >= list.length) {
      return { prev: null, next: null };
    }
    return { prev: idx > 0 ? list[idx - 1] : null,
             next: idx < list.length - 1 ? list[idx + 1] : null };
  }

  function settle(open, dy, velocity) {
    if (Math.abs(velocity) >= FLICK) return velocity < 0;
    if (dy <= -DRAG_PX) return true;
    if (dy >= DRAG_PX) return false;
    return open;
  }

  return { DRAG_PX, FLICK, neighbors, settle };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylPhoneDetail;
