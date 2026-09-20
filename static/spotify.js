/* The Spotify link a record carries, and how the detail drawer shows it.
 *
 * cleanLink mirrors _spotify_url in app.py, which is the enforcing copy. It
 * only tidies — nothing is ever rejected, since a scan can hand back any link.
 * rowHTML is the one place a stored link becomes an href, so it refuses
 * anything that is not http(s).
 *
 * Loaded as a plain script in the browser, where `const VinylSpotify` lands in
 * the global lexical scope; required as a module by the tests. */

const VinylSpotify = (function () {

  const URI  = /^spotify:([a-z]+):([A-Za-z0-9]+)$/;
  const WEB  = /^https?:\/\/open\.spotify\.com\/(?:intl-[a-z]+\/)?([a-z]+\/[A-Za-z0-9]+)(?:[\/?#].*)?$/;
  const HTTP = /^https?:\/\//i;

  const esc = s => String(s).replace(/[&<>"']/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  function cleanLink(raw) {
    const v = String(raw === undefined || raw === null ? '' : raw).trim();
    let m = URI.exec(v);
    if (m) return 'https://open.spotify.com/' + m[1] + '/' + m[2];
    m = WEB.exec(v);
    return m ? 'https://open.spotify.com/' + m[1] : v;
  }

  /* A record with no link is not on Spotify as far as the collection knows,
   * whether or not it was explicitly flagged. */
  function rowHTML(r) {
    const url = String(r.spotify_url || '').trim();
    if (HTTP.test(url)) {
      return '<a class="sp-open" href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">'
        + '<i class="ti ti-brand-spotify"></i> Open in Spotify <i class="ti ti-external-link"></i></a>';
    }
    return '<span class="sp-none"><i class="ti ti-brand-spotify"></i> Not on Spotify</span>';
  }

  return { cleanLink, rowHTML };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylSpotify;
