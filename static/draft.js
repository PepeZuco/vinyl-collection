/* Unsaved work in the add/edit form.
 *
 * closeForm() used to discard without asking, and the overlay's backdrop click
 * called it directly — so a tap just outside the sheet threw away everything
 * typed. After a photo scan that is worse than an inconvenience: the scan is a
 * vision call that has already been billed, and re-doing it costs again.
 *
 * Two separate jobs, deliberately kept apart. isDirty answers "is there
 * anything to lose", which is what gates the confirmation on close. The
 * storage half keeps the last draft alive across a closed tab, so a crash or a
 * stray navigation is recoverable rather than merely warned about.
 *
 * Loaded as a plain script in the browser, where `const VinylDraft` lands in
 * the global lexical scope for the inline script below it; required as a module
 * by the tests. */

const VinylDraft = (function () {

  const KEY = 'vinyl-form-draft';

  /* Form fields come back from the DOM as strings even where the baseline
   * captured a number — fPlays reads '0' where openAdd set 0 — so values are
   * compared as text. Nothing in a record is a type where '2' and 2 mean
   * different things. */
  function same(a, b) {
    return String(a === undefined || a === null ? '' : a) ===
           String(b === undefined || b === null ? '' : b);
  }

  function isDirty(current, baseline) {
    const cur = current || {};
    const base = baseline || {};
    const keys = new Set([...Object.keys(cur), ...Object.keys(base)]);
    for (const k of keys) {
      if (!same(cur[k], base[k])) return true;
    }
    return false;
  }

  /* Storage is best-effort throughout: a private window, blocked site data or
   * a full quota all throw, and losing the convenience is acceptable where
   * throwing out of a keystroke handler is not. */
  function save(store, draft, now, editingId) {
    if (!store) return;
    try {
      store.setItem(KEY, JSON.stringify({
        savedAt: now,
        editingId: editingId === undefined ? null : editingId,
        draft: draft,
      }));
    } catch (e) { /* nothing to do but carry on without a draft */ }
  }

  /* The last draft, if there is one and it is recent enough to still be what
   * the person meant. An old one is cleared as it is declined: offering to
   * restore last week's half-typed record is worse than offering nothing. */
  function load(store, now, maxAgeMs) {
    if (!store) return null;
    let raw;
    try { raw = store.getItem(KEY); } catch (e) { return null; }
    if (!raw) return null;

    let parsed;
    try { parsed = JSON.parse(raw); } catch (e) { clear(store); return null; }
    if (!parsed || typeof parsed !== 'object' || !parsed.draft) { clear(store); return null; }

    if (now - parsed.savedAt > maxAgeMs) { clear(store); return null; }
    return {
      draft: parsed.draft,
      savedAt: parsed.savedAt,
      editingId: parsed.editingId === undefined ? null : parsed.editingId,
    };
  }

  function clear(store) {
    if (!store) return;
    try { store.removeItem(KEY); } catch (e) { /* see save() */ }
  }

  return { KEY, isDirty, save, load, clear };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylDraft;
