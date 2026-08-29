/* Cover rules for the add/edit form.
 *
 * Covers no longer travel with the record: /api/records reports a `cover_url`
 * and the bytes are fetched separately, which keeps the record list at ~100KB
 * instead of 45MB. The consequence for the form is that it holds a URL it
 * cannot send back, so "the user did not touch the cover" and "the user removed
 * the cover" stop looking the same. They must not be sent the same way either —
 * the first has to omit the field so the server leaves the stored cover alone,
 * and only the second may send an empty string.
 *
 * Loaded as a plain script in the browser, where `const VinylCover` lands in the
 * global lexical scope for the inline script below it; required as a module by
 * the tests. */

const VinylCover = (function () {

  /* The cover part of a save payload.
   *
   * `dirty` is set only by picking, scanning or clearing a cover — never by
   * opening a record. So an edit that changes a rating sends nothing here, and
   * the stored cover survives. */
  function coverFields(state) {
    if (!state || !state.dirty) return {};
    return { cover_data: state.uri || '' };
  }

  /* What the form's preview should display: a cover picked in this session wins,
   * otherwise the saved one, otherwise nothing. */
  function coverPreviewSrc(record, pendingUri) {
    if (pendingUri) return pendingUri;
    return (record && record.cover_url) || '';
  }

  return { coverFields, coverPreviewSrc };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylCover;
