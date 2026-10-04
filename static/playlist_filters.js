/* The playlist filter rules, for the popup's live "N records match" and its
 * suggested name. playlist_filters.py is the enforcing copy — the server
 * filters and validates; this one only previews, so a bad value is dropped
 * here rather than reported. Both are held to
 * tests/fixtures/playlist_filter_cases.json.
 *
 * Loaded as a plain script in the browser, where `const VinylPlaylistFilters`
 * lands in the global lexical scope; required as a module by the tests. */

const VinylPlaylistFilters = (function () {

  const BASE = 'Zucoloto Vinyl';
  const MAX = 100;
  const DAY = /^\d{4}-\d{2}-\d{2}$/;
  const YEAR = /\d{4}/;
  const PLAYLIST_LINK = /^(?:https?:\/\/open\.spotify\.com\/(?:intl-[a-z]+\/)?playlist\/|spotify:playlist:)/i;
  const SOURCES = ['albums', 'compilations', 'all'];
  const OWNED = ['owned', 'wishlist', 'all'];

  const tidy = s => String(s === undefined || s === null ? '' : s).split(/\s+/).filter(Boolean).join(' ');
  const fold = s => tidy(s).toLowerCase();
  const blank = v => v === undefined || v === null || (typeof v === 'string' && !v.trim());

  function names(v) {
    const seen = new Set(), out = [];
    for (const x of (Array.isArray(v) ? v : [v])) {
      const t = tidy(x);
      if (t && !seen.has(t.toLowerCase())) { seen.add(t.toLowerCase()); out.push(t); }
    }
    return out.sort((a, b) => {
      const x = a.toLowerCase(), y = b.toLowerCase();
      return x < y ? -1 : x > y ? 1 : 0;
    });
  }

  function year(v) {
    if (blank(v) || !/^\s*\d{4}\s*$/.test(String(v))) return null;
    return parseInt(v, 10);
  }

  function stars(v) {
    if (blank(v)) return null;
    const s = Number(v);
    return Number.isFinite(s) && s >= 0.5 && s <= 5 && (s * 2) % 1 === 0 ? s : null;
  }

  function day(v) {
    if (blank(v)) return null;
    const s = String(v).trim();
    const d = new Date(s + 'T00:00:00Z');
    return DAY.test(s) && !isNaN(d) && d.toISOString().slice(0, 10) === s ? s : null;
  }

  function ordered(lo, hi) {
    return lo !== null && hi !== null && lo > hi ? [hi, lo] : [lo, hi];
  }

  function normalize(raw) {
    raw = raw || {};
    const f = { liked: raw.liked !== false };
    const [yf, yt] = ordered(year(raw.year_from), year(raw.year_to));
    if (yf !== null) f.year_from = yf;
    if (yt !== null) f.year_to = yt;
    for (const k of ['genres', 'places']) {
      if (!blank(raw[k])) {
        const l = names(raw[k]);
        if (l.length) f[k] = l;
      }
    }
    const p = stars(raw.pepe_min), j = stars(raw.jenni_min);
    if (p !== null) f.pepe_min = p;
    if (j !== null) f.jenni_min = j;
    if (p !== null && j !== null) f.rating_mode = raw.rating_mode === 'or' ? 'or' : 'and';
    if (SOURCES.includes(raw.source) && raw.source !== 'albums') f.source = raw.source;
    if (OWNED.includes(raw.owned) && raw.owned !== 'owned') f.owned = raw.owned;
    const [bf, bt] = ordered(day(raw.bought_from), day(raw.bought_to));
    if (bf !== null) f.bought_from = bf;
    if (bt !== null) f.bought_to = bt;
    return f;
  }

  function recordYear(v) {
    const m = YEAR.exec(String(v === undefined || v === null ? '' : v));
    return m ? parseInt(m[0], 10) : null;
  }

  function linkKind(link) {
    return PLAYLIST_LINK.test(tidy(link)) ? 'playlist' : 'album';
  }

  function matches(r, f) {
    const owned = f.owned || 'owned';
    if (owned !== 'all' && (r.have_it !== false) !== (owned === 'owned')) return false;
    const source = f.source || 'albums';
    if (source !== 'all' && linkKind(r.spotify_url) !== (source === 'compilations' ? 'playlist' : 'album')) return false;
    if ('year_from' in f || 'year_to' in f) {
      const y = recordYear(r.year);
      if (y === null) return false;
      if ('year_from' in f && y < f.year_from) return false;
      if ('year_to' in f && y > f.year_to) return false;
    }
    if (f.genres && !f.genres.some(g => g.toLowerCase() === fold(r.genre))) return false;
    const checks = [];
    if ('pepe_min' in f) checks.push((Number(r.my_rating) || 0) >= f.pepe_min);
    if ('jenni_min' in f) checks.push((Number(r.wife_rating) || 0) >= f.jenni_min);
    if (checks.length && !(f.rating_mode === 'or' ? checks.some(Boolean) : checks.every(Boolean))) return false;
    if (f.places && !f.places.some(p => p.toLowerCase() === fold(r.bought_where))) return false;
    if ('bought_from' in f || 'bought_to' in f) {
      const d = String(r.bought_date || '').slice(0, 10);
      if (!DAY.test(d)) return false;
      if ('bought_from' in f && d < f.bought_from) return false;
      if ('bought_to' in f && d > f.bought_to) return false;
    }
    return true;
  }

  function hasLiked(r) {
    let t = r.tracks;
    if (typeof t === 'string') {
      try { t = t ? JSON.parse(t) : []; } catch (e) { t = []; }
    }
    return Array.isArray(t) && t.some(s => s && s.liked_at);
  }

  function matching(records, f) {
    return (records || []).filter(r => r && tidy(r.spotify_url)
      && matches(r, f) && (!f.liked || hasLiked(r)));
  }

  function countMatching(records, f) {
    return matching(records, f).length;
  }

  const num = x => String(Number(x));

  function span(lo, hi) {
    const has = v => v !== undefined && v !== null;
    if (has(lo) && has(hi)) return lo === hi ? String(lo) : lo + '–' + hi;
    return has(lo) ? '≥' + lo : '≤' + hi;
  }

  function parts(f) {
    const out = [];
    if (f.genres) out.push(f.genres.join(', '));
    if ('year_from' in f || 'year_to' in f) out.push(span(f.year_from, f.year_to));
    const r = [];
    if ('pepe_min' in f) r.push('Pepe ≥' + num(f.pepe_min));
    if ('jenni_min' in f) r.push('Jenni ≥' + num(f.jenni_min));
    if (r.length) out.push(r.join(f.rating_mode === 'or' ? ' or ' : ' and '));
    if (f.places) out.push(f.places.join(', '));
    if ('bought_from' in f || 'bought_to' in f) out.push('bought ' + span(f.bought_from, f.bought_to));
    if (f.source === 'compilations') out.push('compilations only');
    else if (f.source === 'all') out.push('+ compilations');
    if (f.owned === 'wishlist') out.push('wishlist');
    else if (f.owned === 'all') out.push('+ wishlist');
    return out;
  }

  function suggestName(f) {
    const name = [BASE + (f.liked !== false ? ' — Liked' : '')].concat(parts(f)).join(' · ');
    return name.length <= MAX ? name : name.slice(0, MAX - 1).trimEnd() + '…';
  }

  return { normalize, linkKind, matches, matching, countMatching, suggestName };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylPlaylistFilters;
