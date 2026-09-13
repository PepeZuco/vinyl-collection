/* Where you are, in the address bar.
 *
 * The app had no URL state at all — not one pushState, hash or
 * URLSearchParams. You could not link to a record or to a filter, Back left
 * the app entirely, and a refresh lost your place (and, before covers moved
 * off the record list, re-downloaded 45MB to do it).
 *
 * Two rules shape what follows. Only what differs from the defaults is
 * written, so arriving at the app does not immediately dirty the address bar
 * and a short link stays short. And a hash is untrusted input like any other:
 * it can only select from what the app already offers, never introduce a tab
 * or a facet the app does not have.
 *
 * Facet values ride as REPEATED parameters rather than one joined string.
 * Shops and genres carry commas, ampersands and equals signs — "Benedito,
 * Calixto & Sons" would break any separator worth typing.
 *
 * Loaded as a plain script in the browser, where `const VinylUrlState` lands
 * in the global lexical scope for the inline script below it; required as a
 * module by the tests. */

const VinylUrlState = (function () {

  const DEFAULTS = {
    tab: 'collection',
    text: '',
    ownership: 'owned',
    facets: {},
    crate: 'bought_date',
    sort: 'bought_date',
    dir: 'desc',
    view: 'grid',
    recordId: null,
  };

  const TABS = ['collection', 'timeline', 'stats'];
  const OWNERSHIPS = ['owned', 'wishlist'];
  const DIRS = ['asc', 'desc'];
  const VIEWS = ['grid', 'list'];

  /* The facets a link may name. Listed here rather than read from the filter
   * model so a hash can never reach a dimension the bar does not offer — and
   * pinned to that model by a test, because two lists that must agree will
   * otherwise drift and quietly drop a filter from a link. */
  const FACET_IDS = ['genre', 'condition', 'decade', 'country', 'store', 'cleaning', 'played'];

  const FACET_PREFIX = 'f.';

  function encode(state) {
    const s = Object.assign({}, DEFAULTS, state || {});
    const parts = [];
    const put = (k, v) => parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(v));

    if (s.tab !== DEFAULTS.tab) put('tab', s.tab);
    if (s.text) put('q', s.text);
    if (s.ownership !== DEFAULTS.ownership) put('own', s.ownership);
    if (s.crate !== DEFAULTS.crate) put('crate', s.crate);
    if (s.sort !== DEFAULTS.sort) put('sort', s.sort);
    if (s.dir !== DEFAULTS.dir) put('dir', s.dir);
    if (s.view !== DEFAULTS.view) put('view', s.view);

    // Sorted, so the same view always produces the same hash and an unchanged
    // screen never pushes a new history entry.
    const facets = s.facets || {};
    Object.keys(facets).sort().forEach(id => {
      if (FACET_IDS.indexOf(id) === -1) return;
      const values = facets[id] || [];
      // A facet ticked to nothing is a real state — an empty shelf that says
      // why — and needs a marker of its own, since repeating a param zero
      // times writes nothing at all.
      if (!values.length) { put(FACET_PREFIX + id, ''); put('n.' + id, '1'); return; }
      values.forEach(v => put(FACET_PREFIX + id, v));
    });

    if (s.recordId !== null && s.recordId !== undefined) put('rec', s.recordId);
    return parts.join('&');
  }

  function decode(hash) {
    const out = JSON.parse(JSON.stringify(DEFAULTS));
    const raw = String(hash == null ? '' : hash).replace(/^#/, '');
    if (!raw) return out;

    const pairs = [];
    raw.split('&').forEach(chunk => {
      if (!chunk) return;
      const eq = chunk.indexOf('=');
      const k = eq === -1 ? chunk : chunk.slice(0, eq);
      const v = eq === -1 ? '' : chunk.slice(eq + 1);
      try {
        pairs.push([decodeURIComponent(k), decodeURIComponent(v)]);
      } catch (e) { /* a malformed escape drops its own parameter, not the page */ }
    });

    const first = name => {
      const hit = pairs.find(([k]) => k === name);
      return hit ? hit[1] : null;
    };
    const oneOf = (value, allowed, fallback) =>
      (value !== null && allowed.indexOf(value) !== -1) ? value : fallback;

    out.tab = oneOf(first('tab'), TABS, DEFAULTS.tab);
    out.text = first('q') || '';
    out.ownership = oneOf(first('own'), OWNERSHIPS, DEFAULTS.ownership);
    out.dir = oneOf(first('dir'), DIRS, DEFAULTS.dir);
    out.view = oneOf(first('view'), VIEWS, DEFAULTS.view);
    // crate and sort name options the page owns, so they are taken as given
    // and the page falls back if it does not recognise one.
    out.crate = first('crate') || DEFAULTS.crate;
    out.sort = first('sort') || DEFAULTS.sort;

    FACET_IDS.forEach(id => {
      const values = pairs.filter(([k]) => k === FACET_PREFIX + id).map(([, v]) => v);
      const emptied = pairs.some(([k]) => k === 'n.' + id);
      if (emptied) { out.facets[id] = []; return; }
      if (values.length) out.facets[id] = values;
    });

    const rec = first('rec');
    const n = rec === null ? NaN : Number(rec);
    out.recordId = Number.isFinite(n) && rec !== '' ? n : null;

    return out;
  }

  return { DEFAULTS, TABS, OWNERSHIPS, FACET_IDS, encode, decode };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylUrlState;
