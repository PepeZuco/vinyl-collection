'use strict';

/* The guided tour: what it says, where it points, and when it offers itself.
 *
 * The spotlight, the popover, tab switching and keyboard handling live in
 * index.html with the rest of the DOM glue, like the idle screensaver. What's
 * pulled out here is everything that decides rather than draws, so it can be
 * tested without a browser: the steps, which selector a step uses on a phone,
 * which step comes next when one has nothing on screen to point at, where the
 * popover card fits, and whether a first-time visitor gets the offer.
 *
 * Loaded as a plain script in the browser; required as a module by the
 * tests (tests/test_tour.js). */

const VinylTour = (function () {

  const SEEN_KEY = 'vinyl-tour-seen';

  // `tab` is switched to before the step shows. `target` is a selector, or
  // {desktop, phone} where the two layouts differ; no target centres the card
  // with nothing lit. A target that isn't on screen skips the step, so a
  // control hidden on one breakpoint never leaves the tour pointing at air.
  // `{count}` in a text is filled in with the number of records owned.
  const STEPS = [
    {
      id: 'welcome', tab: 'collection',
      title: 'Welcome to the shelf',
      text: '{count} records, each one logged, rated and identified with the help of AI. ' +
        'This minute-long tour shows how to find the one you are after, and how the records got here.',
    },
    {
      id: 'search', tab: 'collection', target: '#filterRow .search',
      title: 'Search anything',
      text: 'Type an artist or album. The sliders button picks where to look: tick Song to find ' +
        'which record has a track. Accents and typos are forgiven.',
    },
    {
      id: 'filters', tab: 'collection', target: { desktop: '#barAcc', phone: '#mFilterBtn' },
      title: 'Narrow it down',
      text: 'Switch between the records owned and the wishlist, tap a saved view like ' +
        '“Gathering dust”, or open any filter: genre, decade, country, where it was bought ' +
        'or when it was last played.',
    },
    {
      id: 'arrange', tab: 'collection', target: { desktop: '#arrangeDropdown', phone: '#sortTrigger' },
      title: 'Sort, and the crates follow',
      text: 'Sort by artist and the shelf splits into A, B, C; by date added, into months; by ' +
        'year, into decades. Or crate by genre or country instead, and switch between covers ' +
        'and a compact list.',
    },
    {
      id: 'dice', tab: 'collection', target: '#randomBtn',
      title: 'Can’t decide?',
      text: 'Roll the dice for a random record from whatever is filtered right now: ' +
        'filter to Jazz from the 70s and let it choose.',
    },
    {
      id: 'record', tab: 'collection',
      target: '#recordsContainer .vcard, #recordsContainer .list-row',
      title: 'Open a record',
      text: 'Every record opens to its tracklist, Pepe’s and Jenni’s ratings, notes and the ' +
        'history of when it was bought, cleaned and played.',
    },
    {
      id: 'playlists', tab: 'playlists', target: '#playlistsBody',
      title: 'The shelf, on Spotify',
      text: 'Each playlist is a saved filter on the collection, like the liked songs from the Jazz ' +
        'records bought this year. A sync keeps it in step with the shelf: a record sold or a ' +
        'song unliked drops out.',
    },
    {
      id: 'claude', tab: 'features', target: '#featureCard-claude',
      title: 'How records get in: Claude',
      text: 'A photo of the sleeve goes to Claude’s vision model, which names the album. ' +
        'MusicBrainz and a Claude vinyl check confirm a real pressing exists. Open the card to ' +
        'run the pipeline step by step, cost of each call included.',
    },
    {
      id: 'spotify', tab: 'features', target: '#featureCard-spotify',
      title: 'Or just paste a link',
      text: 'A Spotify album or track link is resolved through Spotify’s API, Claude files it ' +
        'under one of the collection’s genres, and the shelf is checked for duplicates before ' +
        'anything is saved.',
    },
    {
      id: 'replay', tab: 'collection', target: '#tourBtn',
      title: 'That’s the tour',
      text: 'Replay it any time from this button. Enjoy the records.',
    },
  ];

  function targetOf(step, phone) {
    const t = step && step.target;
    if (!t) return null;
    if (typeof t === 'string') return t;
    return (phone ? t.phone : t.desktop) || null;
  }

  // The next step from `from` in direction `dir` (+1 / -1) whose target is
  // available, or -1 past either end. `available(step)` is the DOM check,
  // injected so the walk itself is testable.
  function stepIndex(steps, from, dir, available) {
    for (let i = from + dir; i >= 0 && i < steps.length; i += dir) {
      if (available(steps[i])) return i;
    }
    return -1;
  }

  // Where the popover card goes, in viewport pixels. Below the target when it
  // fits, above when it doesn't, and pinned to the bottom over a target too
  // tall for either (a whole playlist list on a phone). Always centred on the
  // target horizontally and clamped `gap` away from the viewport's edges.
  function placePopover(rect, pop, vp, gap) {
    const clampLeft = x => Math.max(gap, Math.min(x, vp.width - pop.width - gap));
    if (!rect) {
      return { side: 'center', top: (vp.height - pop.height) / 2, left: (vp.width - pop.width) / 2 };
    }
    const left = clampLeft(rect.left + rect.width / 2 - pop.width / 2);
    const bottom = rect.top + rect.height;
    if (bottom + gap + pop.height <= vp.height - gap) return { side: 'below', top: bottom + gap, left };
    if (rect.top - gap - pop.height >= gap) return { side: 'above', top: rect.top - gap - pop.height, left };
    return { side: 'inside', top: vp.height - pop.height - gap, left };
  }

  // Only a visitor landing on the plain page: the owner knows the app, and a
  // shared link to a record or a filter is someone with somewhere to be.
  // Storage that's missing or throws (private mode, blocked site data) means
  // no offer at all, rather than one on every single visit.
  function shouldOffer(storage, ctx) {
    if (!storage || ctx.authed) return false;
    if (ctx.hash && ctx.hash !== '#') return false;
    try { return storage.getItem(SEEN_KEY) !== '1'; } catch (e) { return false; }
  }

  function markSeen(storage) {
    try { if (storage) storage.setItem(SEEN_KEY, '1'); } catch (e) { /* nothing to remember with */ }
  }

  return { STEPS, SEEN_KEY, targetOf, stepIndex, placePopover, shouldOffer, markSeen };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylTour;
