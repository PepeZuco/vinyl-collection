/* The notes column's parse/serialize rules.
 *
 * Notes are stored as JSON: [{date, text, images?}]. A note is valid with text
 * OR at least one image — a photo with no words is a note, and the filter that
 * used to demand text would silently delete it on save.
 *
 * `images` holds ids, never bytes. The bytes live in the NoteImage table and
 * are served from /api/note-images/<id>, because this column is not deferred
 * and six consumers read it straight off /api/records.
 *
 * Loaded as a plain script in the browser, where `const VinylNotes` lands in
 * the global lexical scope for the inline script below it; required as a
 * module by the tests. */

const VinylNotes = (function () {

  function hasContent(note) {
    if (!note) return false;
    if (note.text && note.text.trim()) return true;
    return !!(note.images && note.images.length);
  }

  /* Migration: a raw value that is not a JSON array is a legacy single note,
   * dated with the record's purchase day (or today) by the caller. */
  function parseNotes(raw, fallbackDate) {
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed;
    } catch (e) {}
    return [{ date: fallbackDate, text: raw }];
  }

  /* '' rather than '[]' for an empty list: the column's empty value is the
   * empty string, and every reader treats it that way. */
  function serializeNotes(arr) {
    const clean = (arr || []).filter(hasContent);
    return clean.length ? JSON.stringify(clean) : '';
  }

  /* Every image id a note list refers to, deduped and ordered, for the callers
   * that need to know what a record points at without holding any bytes. */
  function noteImageIds(notes) {
    const seen = [];
    (notes || []).forEach(function (n) {
      ((n && n.images) || []).forEach(function (id) {
        if (id && seen.indexOf(id) === -1) seen.push(id);
      });
    });
    return seen;
  }

  return { parseNotes, serializeNotes, noteImageIds, hasContent };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylNotes;
