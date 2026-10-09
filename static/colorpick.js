/* Picking a record's colors off a photo.
 *
 * The overlay in index.html shows the photo, follows the finger and writes the
 * result into the paint form. This file holds the arithmetic underneath it:
 * where the photo sits inside its box, which pixel a tap lands on, what color
 * a patch around that pixel averages to, and where the loupe goes.
 *
 * Nothing here touches the DOM or reads a global. Loaded as a plain script in
 * the browser, where `const VinylColorPick` lands in the global lexical scope
 * for the inline script below it; required as a module by the tests.
 */
const VinylColorPick = (() => {

  function rgbToHex(r, g, b) {
    const hex = v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0');
    return '#' + hex(r) + hex(g) + hex(b);
  }

  /* The photo is drawn whole inside its box (object-fit: contain), so it is
   * letterboxed one way or the other; this is the rectangle it fills. */
  function fitContain(boxW, boxH, imgW, imgH) {
    const scale = Math.min(boxW / imgW, boxH / imgH);
    const w = imgW * scale, h = imgH * scale;
    return { x: (boxW - w) / 2, y: (boxH - h) / 2, w, h };
  }

  /* A point in the box, as a pixel of the full-resolution photo. Clamped, not
   * rejected: a drag that strays into the letterbox keeps the crosshair on the
   * photo's edge instead of dropping it. */
  function toImagePoint(px, py, fit, imgW, imgH) {
    const clamp = (v, max) => Math.max(0, Math.min(max - 1, Math.floor(v)));
    return {
      x: clamp((px - fit.x) / fit.w * imgW, imgW),
      y: clamp((py - fit.y) / fit.h * imgH, imgH),
    };
  }

  /* A single camera pixel is noisy — grain, glare, a speck of dust — so the
   * color is the mean of a (2r+1)² square around the tap, counting only the
   * pixels that fall inside the photo. `data` is RGBA, row-major (ImageData). */
  function averagePatch(data, width, height, cx, cy, radius) {
    let r = 0, g = 0, b = 0, n = 0;
    for (let y = Math.max(0, cy - radius); y <= Math.min(height - 1, cy + radius); y++) {
      for (let x = Math.max(0, cx - radius); x <= Math.min(width - 1, cx + radius); x++) {
        const i = (y * width + x) * 4;
        r += data[i]; g += data[i + 1]; b += data[i + 2]; n++;
      }
    }
    return { r: r / n, g: g / n, b: b / n };
  }

  /* The loupe floats above the finger, which would otherwise cover the very
   * spot being picked; at the top of the box there is no room above, so it
   * drops below. Sideways it is kept inside the box. */
  function loupePlacement(x, y, boxW, size, gap) {
    const left = Math.max(0, Math.min(boxW - size, x - size / 2));
    const above = y - gap - size;
    return { left, top: above >= 0 ? above : y + gap };
  }

  return { rgbToHex, fitContain, toImagePoint, averagePatch, loupePlacement };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylColorPick;
