'use strict';

/* Picks what the idle screensaver shows next.
 *
 * Everything about *when* it appears and how it fades lives in index.html
 * with the rest of the DOM/timer glue, like openDetail and friends. What's
 * worth pulling out and testing on its own is the queue: only records you
 * actually own get shown, in a random order, and a lap never repeats its
 * last record as the first of the next lap.
 *
 * Loaded as a plain script in the browser; required as a module by the
 * tests (tests/test_idle_spotlight.js). */

const VinylIdleSpotlight = (function () {

  function ownedPool(records) {
    return (records || []).filter(function (r) { return r && r.have_it; });
  }

  // Fisher-Yates. `rng` is injectable so the order is reproducible in tests;
  // defaults to Math.random for real use. Never mutates its input.
  function shuffle(records, rng) {
    const rand = rng || Math.random;
    const arr = records.slice();
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(rand() * (i + 1));
      const tmp = arr[i]; arr[i] = arr[j]; arr[j] = tmp;
    }
    return arr;
  }

  // The queue after showing queue[0]. Mid-lap this just drops the head; once
  // the lap ends it draws a fresh shuffle of the whole pool, retrying until
  // the new head isn't the record the lap just ended on -- otherwise the
  // same record could sit on screen through the crossfade unnoticed.
  function advance(queue, pool, rng) {
    if (queue.length > 1) return queue.slice(1);
    const avoidId = queue[0] && queue[0].id;
    if (pool.length <= 1) return pool.slice();
    let next;
    for (let tries = 0; tries < 20; tries++) {
      next = shuffle(pool, rng);
      if (!avoidId || next[0].id !== avoidId) break;
    }
    return next;
  }

  return { ownedPool: ownedPool, shuffle: shuffle, advance: advance };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylIdleSpotlight;
