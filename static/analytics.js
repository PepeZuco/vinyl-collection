/* Custom events for the Umami tracker the index route adds when
 * UMAMI_WEBSITE_ID is set.
 *
 * Analytics must never cost the app anything: with no tracker on the page
 * (local runs, the tests, an ad blocker, the deferred script not loaded yet)
 * every call is a silent no-op, and a tracker that throws is swallowed.
 * Values are trimmed to what Umami keeps (50-character event names,
 * 500-character strings) and empty ones dropped, so a call site can pass
 * whatever it has to hand.
 *
 * Loaded as a plain script in the browser, where `const VinylAnalytics` lands
 * in the global lexical scope; required as a module by the tests. */

const VinylAnalytics = (function () {

  const NAME_MAX = 50;
  const VALUE_MAX = 500;

  function clean(data) {
    if (!data) return undefined;
    const out = {};
    Object.keys(data).forEach(k => {
      const v = data[k];
      if (v === null || v === undefined || v === '') return;
      out[k] = typeof v === 'string' ? v.slice(0, VALUE_MAX) : v;
    });
    return out;
  }

  /* `tracker` is for the tests; the page leaves it out and gets window.umami. */
  function track(name, data, tracker) {
    const t = arguments.length > 2 ? tracker
      : (typeof window !== 'undefined' ? window.umami : undefined);
    if (!name || !t || typeof t.track !== 'function') return false;
    try {
      t.track(String(name).slice(0, NAME_MAX), clean(data));
      return true;
    } catch (e) {
      return false;
    }
  }

  function recordLabel(r) {
    if (!r) return '';
    return [r.artist, r.album_name].filter(Boolean).join(' — ');
  }

  return { track, recordLabel };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylAnalytics;
