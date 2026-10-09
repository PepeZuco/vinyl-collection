/* The phone's full-screen cover, and the tilt a NEW record gets in it.
 *
 * A new record is a sealed one, and a sealed sleeve is something you turn in
 * your hand to watch the light slide across the shrink-wrap. So while the
 * cover is open the phone's orientation leans it in 3D, and a glare streak
 * runs the opposite way: the light stays put and the sleeve moves under it.
 *
 * Flat is however the phone was being held when the cover opened, not "lying
 * on a table" — nobody looks at a phone at beta 0, and measuring from there
 * would open every cover already leaning back into the cap.
 *
 * Only the maths and the permission step live here; the overlay and the
 * deviceorientation listener are the template's. Loaded as a plain script in
 * the browser, where `const VinylCoverTilt` lands in the global lexical scope
 * for the inline script below it; required as a module by the tests. */
const VinylCoverTilt = (() => {
  const MAX_TILT = 12;   // degrees the cover leans at most, either axis
  const GAIN = 0.6;      // cover degrees per degree of phone
  const GLARE = 40;      // % the glare travels from the middle at full lean

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  // beta runs -180..180, so a phone held just past upright jumps from 179 to
  // -179; the difference is a 2° nudge, not a 358° turn
  const wrap = d => ((d + 180) % 360 + 360) % 360 - 180;

  function wantsTilt(rec, reducedMotion) {
    return !!rec && rec.condition === 'new' && !reducedMotion;
  }

  /* beta/gamma are the DEVICE's axes; what the cover has to follow is the
   * screen's, which turns under them in landscape. fb is the top edge tipping
   * toward/away from you, lr the right edge going down/up. Small-angle, which
   * is all a ±12° lean off a baseline needs. */
  function screenTilt(beta, gamma, angle) {
    switch (((angle % 360) + 360) % 360) {
      case 90:  return { fb: -gamma, lr: beta };
      case 180: return { fb: -beta,  lr: -gamma };
      case 270: return { fb: gamma,  lr: -beta };
      default:  return { fb: beta,   lr: gamma };
    }
  }

  /* rx/ry are the cover's rotateX/rotateY in degrees; gx/gy the glare's
   * centre as a % of the cover. */
  function tiltFrom(base, cur) {
    const rx = clamp(-wrap(cur.fb - base.fb) * GAIN, -MAX_TILT, MAX_TILT);
    const ry = clamp(wrap(cur.lr - base.lr) * GAIN, -MAX_TILT, MAX_TILT);
    return {
      rx, ry,
      gx: 50 - (ry / MAX_TILT) * GLARE,
      gy: 50 - (rx / MAX_TILT) * GLARE,
    };
  }

  // Sensor readings jitter by a degree or so even in a steady hand; easing a
  // fraction of the way each frame turns that into drift instead of shake.
  function smooth(prev, target, k) {
    const out = {};
    for (const key of Object.keys(target)) {
      const d = target[key] - prev[key];
      out[key] = Math.abs(d) < 0.01 ? target[key] : prev[key] + d * k;
    }
    return out;
  }

  /* 'granted' | 'denied' | 'unsupported'. iOS only shows its prompt when
   * requestPermission is called in the same task as the tap, so it is called
   * before anything is awaited — call this straight from the click handler. */
  function requestMotion(win) {
    const DOE = win && win.DeviceOrientationEvent;
    if (!DOE) return Promise.resolve('unsupported');
    if (typeof DOE.requestPermission !== 'function') return Promise.resolve('granted');
    try {
      return Promise.resolve(DOE.requestPermission())
        .then(r => (r === 'granted' ? 'granted' : 'denied'), () => 'denied');
    } catch (e) {
      return Promise.resolve('denied');
    }
  }

  return { MAX_TILT, wantsTilt, screenTilt, tiltFrom, smooth, requestMotion };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylCoverTilt;
