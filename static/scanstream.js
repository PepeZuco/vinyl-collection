/* Reading the /api/scan progress stream.
 *
 * EventSource would do this for free, but it issues a GET and cannot carry a
 * body — the photo path posts a data URI of the sleeve, which is megabytes.
 * So the fetch body is read by hand and the frames parsed here.
 *
 * Pure string handling, kept out of index.html so it is testable: see
 * tests/test_scanstream.js. */
const VinylScanStream = (function () {

  /* Frames are separated by a blank line. The network decides where chunks
   * break, so anything after the last blank line is an incomplete frame and
   * is held until the rest of it arrives. */
  function createParser() {
    let buffer = '';
    return {
      push(chunk) {
        buffer += chunk;
        const blocks = buffer.split('\n\n');
        buffer = blocks.pop();          // the tail: incomplete until proven otherwise
        const frames = [];
        for (const block of blocks) {
          let event = null, data = null;
          for (const line of block.split('\n')) {
            if (line.startsWith('event: ')) event = line.slice(7);
            else if (line.startsWith('data: ')) data = line.slice(6);
          }
          if (!event || data === null) continue;
          try {
            frames.push({ event, data: JSON.parse(data) });
          } catch (e) {
            /* A frame we cannot read is dropped, not thrown: one malformed
             * event must not kill a scan the user already paid for. */
          }
        }
        return frames;
      },
    };
  }

  return { createParser };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylScanStream;
