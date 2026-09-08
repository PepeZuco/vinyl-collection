/* The add-queue: the records picked from a search, walked one at a time
 * through the add form.
 *
 * Pure and immutable so the DOM wiring in index.html has nothing to get wrong
 * about counting — advance() and skip() return a new queue, and every label
 * the form shows is derived here rather than assembled at the call site.
 * See tests/test_queue.js. */
const VinylQueue = (function () {

  function create(releases) {
    return { releases: (releases || []).slice(), index: 0 };
  }

  function total(q) { return q.releases.length; }

  function current(q) {
    return q.index < q.releases.length ? q.releases[q.index] : null;
  }

  /* 1-based, for "2 of 3". Clamped so a finished queue does not read "4 of 3"
   * in the moment between the last save and the form closing. */
  function position(q) {
    return Math.min(q.index + 1, q.releases.length) || 0;
  }

  function remaining(q) { return Math.max(0, q.releases.length - q.index); }

  function isLast(q) {
    return q.releases.length > 0 && q.index === q.releases.length - 1;
  }

  function advance(q) {
    return { releases: q.releases.slice(), index: q.index + 1 };
  }

  /* Dropping a record is not the same as finishing it: it leaves the queue
   * shorter rather than moving further through it, so "1 of 3" becomes
   * "1 of 2" instead of "2 of 3". */
  function skip(q) {
    const releases = q.releases.slice();
    releases.splice(q.index, 1);
    return { releases: releases, index: q.index };
  }

  function counter(q) { return position(q) + ' of ' + total(q); }

  function saveLabel(q) { return isLast(q) ? 'save' : 'save & next'; }

  function chips(q) {
    return q.releases.map(function (release, i) {
      return {
        release: release,
        status: i < q.index ? 'done' : (i === q.index ? 'current' : 'pending'),
      };
    });
  }

  return { create, current, position, total, remaining, isLast,
           advance, skip, counter, saveLabel, chips };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylQueue;
