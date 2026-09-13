/* A place a record was bought at, and the link that place carries.
 *
 * The rules live here because one of them is a security boundary: the drawer
 * renders a place's url as an href, so anything that is not http(s) has to be
 * refused before it is ever stored. Both ends enforce it — app.py mirrors
 * normalizeUrl so a hand-rolled POST cannot get past the browser's copy.
 *
 * Loaded as a plain script in the browser, where `const VinylPlaces` lands in
 * the global lexical scope for the inline script below it; required as a
 * module by the tests. */

const VinylPlaces = (function () {

  const HTTP_PREFIX  = /^https?:\/\//i;                  // already an http(s) url
  const HOST_PORT    = /^[^\s:\/?#]+:\d+(?:[\/?#]|$)/;   // host:port, not a scheme
  const OTHER_SCHEME = /^[a-zA-Z][a-zA-Z0-9+.\-]*:/;     // some other scheme — refuse
  const HTTP_URL     = /^https?:\/\/(?:[^\s\/?#@]+@)?[^\s\/?#@:]+(?::\d+)?(?:[\/?#][^\s]*)?$/i;

  const str = v => String(v === undefined || v === null ? '' : v);

  /* '' for no link, the normalized url, or null when the value must be
   * refused. A bare host is assumed https; leading slashes are dropped first
   * so '//host' does not become 'https:////host'. The href rendered later is
   * a security boundary: a stored javascript: or other non-http scheme becomes
   * an href, enabling XSS. We distinguish host:port from schemes because colons
   * appear in both, but host:port is not a scheme token. */
  function normalizeUrl(raw) {
    let s = str(raw).trim();
    if (!s) return '';
    if (HTTP_PREFIX.test(s)) {
      // already http(s) — validate and return or refuse
      return HTTP_URL.test(s) ? s : null;
    }
    if (HOST_PORT.test(s)) {
      // bare host with explicit port — prepend https://
      s = 'https://' + s;
    } else if (OTHER_SCHEME.test(s)) {
      // some other scheme (ftp, javascript, data, etc.) — refuse
      return null;
    } else {
      // bare host or protocol-relative url — prepend https://, strip slashes
      s = 'https://' + s.replace(/^\/+/, '');
    }
    return HTTP_URL.test(s) ? s : null;
  }

  function validName(raw) {
    return str(raw).trim().length > 0;
  }

  function sortPlaces(places) {
    return (places || []).slice().sort((a, b) =>
      str(a.name).toLowerCase().localeCompare(str(b.name).toLowerCase()));
  }

  /* The place this rename would collapse into, or null. The place being
   * edited is excluded, so re-casing its own name is a rename and not a
   * merge onto itself. */
  function mergeTarget(name, places, editingId) {
    const key = str(name).trim().toLowerCase();
    if (!key) return null;
    return (places || []).find(p =>
      p.id !== editingId && str(p.name).trim().toLowerCase() === key) || null;
  }

  /* The link for a bought_where value. An unknown name resolves to '' rather
   * than undefined, so a read surface never builds a broken href. */
  function placeUrl(name, places) {
    const key = str(name).trim();
    if (!key) return '';
    const hit = (places || []).find(p => str(p.name).trim() === key);
    return (hit && hit.url) || '';
  }

  /* Mirrors esc() in templates/index.html — places.js has to escape on its own
   * because it is required by node in the tests, where the page's helper does
   * not exist. */
  const esc = s => String(s === undefined || s === null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  /* A place name as a link when its place carries one, and as plain text when
   * it does not — so a place with no link reads exactly as it did before this
   * feature existed. The url is escaped as well as the name: normalizeUrl only
   * refuses whitespace and non-http schemes, so a quote can legitimately sit in
   * a path and would otherwise close the href early. rel=noopener because
   * target=_blank without it hands the opened page a handle on this one. */
  function placeLinkHTML(name, places, fallback) {
    const shown = str(name).trim();
    if (!shown) return fallback === undefined ? '\u2014' : fallback;
    const url = placeUrl(shown, places);
    if (!url) return esc(shown);
    return '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">'
      + esc(shown) + ' <i class="ti ti-external-link"></i></a>';
  }

  return { normalizeUrl, validName, sortPlaces, mergeTarget, placeUrl, placeLinkHTML };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylPlaces;
