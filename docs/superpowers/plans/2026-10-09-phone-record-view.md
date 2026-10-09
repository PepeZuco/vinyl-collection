# Phone Record View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remake the opened-record experience on a phone as a fixed screen: a gyroscope-tilting cover, previous/next records at the bottom, essentials in the middle, and an expandable sheet (Tracks, Info, Timeline); admin gets a discreet fixed edit button.

**Architecture:** Keep the existing `#dmLayout` / `#dmCarousel` / `#dmInfo` skeleton and the `dmSetCurrent` render path, so history deep links, rating bars, likes and the cover zoom keep working. Replace the scrolling-page layout with a fixed flex column; the same `#dmInfo` DOM is either a collapsed panel (header + tracks) or, with `.sheet-open` on `#dmLayout`, a raised sheet (tabs + Tracks, Info, Timeline). Tilt moves into a reusable `VinylCoverTilt.follow()` shared by the inline cover and the existing full-screen cover. Pure logic (neighbours, sheet drag settle) lives in a new `static/phonedetail.js`.

**Tech Stack:** Flask + one Jinja template (`templates/index.html`), plain browser JS in `static/`, `node --test` + jsdom wrapped by pytest.

**Spec:** `docs/superpowers/specs/2026-10-09-phone-record-view-design.md`

## Global Constraints

- Phone means `max-width:760px` (`isPhone()`); the desktop drawer (`.detail-layout`, `#ddInfo`, `ddCarousel`, `#detailFoot`) must render exactly as before.
- Reduced motion (`prefers-reduced-motion: reduce`): no tilt anywhere.
- Fixed chrome pays the safe-area insets: `env(safe-area-inset-top|bottom,0px)`.
- iOS motion permission is requested synchronously inside the tap (before any `await`); denied/unsupported leaves the cover flat, no error.
- The inline tilt and the full-screen cover's tilt never run together.
- Phone record screen has no delete button; delete already exists in the phone edit form (`#editRootDelete`, `armEditDelete()`), so nothing is added there.
- `test_boot` hangs by design (see project memory): do not run `tests/test_boot.py`; run the targeted tests named in each task.
- Do not commit unless the user asks; leave changes in the tree. Never put scratch files in the repo tree (use the session scratchpad).

## Review Focus

- Record is first/last in the list, or the only one: the missing neighbour's slot is empty, nothing throws (Task 2, Task 3).
- Neighbour has no cover, or a censored one: bottom row shows a disc icon / the blurred wrapper, never the raw art (Task 3).
- Sheet open, then a like/rating re-renders the same record: the sheet stays open; switching record closes it (Task 3).
- Motion permission denied or rejected, or no sensor: cover stays flat, no exception (Task 1, Task 4).
- Phone rotated to landscape mid-tilt: baseline re-measured, no jump (Task 1).
- Opening the zoomed cover mid-tilt, then closing it: the inline tilt pauses then resumes, and `closeDetail` stops it for good (Task 4).

---

## File Structure

- Modify `static/covertilt.js`: add `follow(win, getEl)` (listener + rAF easing + baseline + `rebase`/`stop`).
- Create `static/phonedetail.js`: `VinylPhoneDetail` = `neighbors`, `settle` (pure).
- Modify `templates/index.html`: markup, CSS, glue (detail layout, nav row, sheet, tilt wiring, edit button).
- Create `tests/test_phonedetail.js` + `tests/test_phonedetail.py`; extend `tests/test_covertilt.js`, `tests/test_phone_dom.js`.
- Create `docs/phone-record-view-manual-verification.md`.

---

### Task 1: `VinylCoverTilt.follow`

**Files:**
- Modify: `static/covertilt.js` (add function, export it)
- Test: `tests/test_covertilt.js`

**Interfaces:**
- Consumes: existing `screenTilt`, `tiltFrom`, `smooth` in the same file.
- Produces: `VinylCoverTilt.follow(win, getEl) -> { rebase(): void, stop(): void }`. `getEl()` returns the element (or null) whose `--rx --ry --gx --gy` custom properties are written each frame. `rebase()` forgets the baseline and the eased state. `stop()` removes the listener, cancels the frame, and removes the four properties from `getEl()`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_covertilt.js` (and add `follow` to the destructured require at the top):

```js
// ── follow: the listener + easing the inline cover and the zoomed cover share ──

function fakeWin(angle = 0) {
  const w = {
    screen: { orientation: { angle } },
    _l: {}, _q: [], _id: 0,
    addEventListener(t, f) { this._l[t] = f; },
    removeEventListener(t, f) { if (this._l[t] === f) delete this._l[t]; },
    requestAnimationFrame(f) { const id = ++this._id; this._q.push([id, f]); return id; },
    cancelAnimationFrame(id) { this._q = this._q.filter(([i]) => i !== id); },
    fire(beta, gamma) { if (this._l.deviceorientation) this._l.deviceorientation({ beta, gamma }); },
    flush(n = 80) { for (let i = 0; i < n && this._q.length; i++) this._q.shift()[1](); },
  };
  return w;
}
function fakeEl() {
  const props = {};
  return { props, style: {
    setProperty(k, v) { props[k] = v; },
    removeProperty(k) { delete props[k]; },
  } };
}

test('follow: the first reading is flat, a later one leans the element', () => {
  const win = fakeWin(), el = fakeEl();
  follow(win, () => el);
  win.fire(55, 0); win.flush();
  assert.strictEqual(Number(el.props['--ry']), 0);
  win.fire(55, 10); win.flush();
  assert.ok(Number(el.props['--ry']) > 0, 'right edge down turns the cover');
  assert.ok(Number(el.props['--gx']) < 50, 'the glare runs the other way');
});

test('follow: a reading with no sensor data (nulls) is ignored', () => {
  const win = fakeWin(), el = fakeEl();
  follow(win, () => el);
  win.fire(null, null); win.flush();
  assert.deepStrictEqual(el.props, {});
});

test('follow: stop removes the listener and clears the element', () => {
  const win = fakeWin(), el = fakeEl();
  const f = follow(win, () => el);
  win.fire(55, 0); win.fire(55, 10); win.flush();
  f.stop();
  assert.strictEqual(win._l.deviceorientation, undefined);
  assert.deepStrictEqual(el.props, {});
  win.fire(55, 30); win.flush();
  assert.deepStrictEqual(el.props, {}, 'a stopped follower never moves again');
});

test('follow: rebase takes the next reading as flat again', () => {
  const win = fakeWin(), el = fakeEl();
  const f = follow(win, () => el);
  win.fire(55, 0); win.fire(55, 20); win.flush();
  f.rebase();
  win.fire(55, 20); win.flush();      // how the phone is held now
  assert.ok(Math.abs(Number(el.props['--ry'] || 0)) < 0.5, 'no jump after a rebase');
});

test('follow: turning to landscape re-measures instead of jumping', () => {
  const win = fakeWin(0), el = fakeEl();
  follow(win, () => el);
  win.fire(55, 0); win.flush();
  win.screen.orientation.angle = 90;
  win.fire(5, 55); win.flush();
  assert.ok(Math.abs(Number(el.props['--rx'])) < 0.5 && Math.abs(Number(el.props['--ry'])) < 0.5);
});

test('follow: a missing element is tolerated', () => {
  const win = fakeWin();
  follow(win, () => null);
  win.fire(55, 0); win.fire(55, 10);
  assert.doesNotThrow(() => win.flush());
});
```

- [ ] **Step 2: Run to verify failure**

Run: `node --test tests/test_covertilt.js`
Expected: FAIL — `follow is not a function` (undefined export).

- [ ] **Step 3: Implement** — in `static/covertilt.js`, before the `return { MAX_TILT, ...` line add:

```js
  /* The listener, the baseline and the easing, for whichever element getEl()
   * names right now (it is asked every frame: the inline cover's current slide
   * changes as you swipe). Reads are eased a fraction of the way per frame and
   * the loop stops once it arrives, so a phone lying still costs no frames.
   * rebase() makes the next reading "flat" again — call it when the cover on
   * show changes. stop() ends it and leaves the element as if never tilted. */
  const KEYS = ['rx', 'ry', 'gx', 'gy'];
  const REST = () => ({ rx: 0, ry: 0, gx: 50, gy: 50 });

  function follow(win, getEl) {
    const st = { on: true, base: null, shown: REST(), target: null, raf: 0 };

    function frame() {
      st.raf = 0;
      if (!st.on || !st.target) return;
      st.shown = smooth(st.shown, st.target, 0.2);
      const el = getEl();
      if (el) KEYS.forEach(k => el.style.setProperty('--' + k, st.shown[k].toFixed(2)));
      if (KEYS.some(k => st.shown[k] !== st.target[k])) st.raf = win.requestAnimationFrame(frame);
    }

    function onOrient(e) {
      // desktop Chrome fires one reading of nulls when there is no sensor at all
      if (!st.on || e.beta == null || e.gamma == null) return;
      const o = win.screen && win.screen.orientation;
      const angle = (o && o.angle) || win.orientation || 0;
      const cur = screenTilt(e.beta, e.gamma, angle);
      // flat is however the phone was held — and again after a turn to
      // landscape, where the old baseline is in the other axes
      if (!st.base || st.base.angle !== angle) st.base = Object.assign({ angle }, cur);
      st.target = tiltFrom(st.base, cur);
      if (!st.raf) st.raf = win.requestAnimationFrame(frame);
    }

    win.addEventListener('deviceorientation', onOrient);
    return {
      rebase() {
        if (st.raf) win.cancelAnimationFrame(st.raf);
        st.raf = 0; st.base = null; st.target = null; st.shown = REST();
      },
      stop() {
        st.on = false;
        win.removeEventListener('deviceorientation', onOrient);
        if (st.raf) win.cancelAnimationFrame(st.raf);
        st.raf = 0;
        const el = getEl();
        if (el) KEYS.forEach(k => el.style.removeProperty('--' + k));
      },
    };
  }

```

and change the return line to `return { MAX_TILT, wantsTilt, hasShrinkWrap, screenTilt, tiltFrom, smooth, requestMotion, follow };`

- [ ] **Step 4: Run to verify pass**

Run: `node --test tests/test_covertilt.js && pytest tests/test_covertilt.py -q`
Expected: all PASS.

---

### Task 2: `VinylPhoneDetail` pure logic

**Files:**
- Create: `static/phonedetail.js`
- Create: `tests/test_phonedetail.js`, `tests/test_phonedetail.py`
- Modify: `templates/index.html` (script tag after `covertilt.js`, ~line 4975)

**Interfaces:**
- Produces: `VinylPhoneDetail.neighbors(list, idx) -> { prev, next }` (items or `null`; both `null` when `list.length < 2` or `idx` out of range; no wrap-around). `VinylPhoneDetail.settle(open, dy, velocity) -> boolean` (new sheet state after a drag on the handle: `dy` px moved, positive = down; `velocity` px/ms, positive = down).

- [ ] **Step 1: Write the failing tests** — `tests/test_phonedetail.js`:

```js
// Pure logic for the phone's record screen: which records sit at the bottom,
// and what a drag on the sheet handle decides. Run by tests/test_phonedetail.py.
const test = require('node:test');
const assert = require('node:assert');
const { neighbors, settle } = require('../static/phonedetail.js');

test('neighbours of a middle record are its two sides', () => {
  assert.deepStrictEqual(neighbors(['a', 'b', 'c'], 1), { prev: 'a', next: 'c' });
});
test('the first record has no previous, the last no next', () => {
  assert.deepStrictEqual(neighbors(['a', 'b', 'c'], 0), { prev: null, next: 'b' });
  assert.deepStrictEqual(neighbors(['a', 'b', 'c'], 2), { prev: 'b', next: null });
});
test('a list of one has no neighbours', () => {
  assert.deepStrictEqual(neighbors(['a'], 0), { prev: null, next: null });
});
test('an empty list or a bad index has none either', () => {
  assert.deepStrictEqual(neighbors([], 0), { prev: null, next: null });
  assert.deepStrictEqual(neighbors(['a', 'b'], -1), { prev: null, next: null });
  assert.deepStrictEqual(neighbors(['a', 'b'], 5), { prev: null, next: null });
});

test('a short drag leaves the sheet as it was', () => {
  assert.strictEqual(settle(false, -10, -0.05), false);
  assert.strictEqual(settle(true, 10, 0.05), true);
});
test('a long drag up opens, a long drag down closes', () => {
  assert.strictEqual(settle(false, -80, -0.1), true);
  assert.strictEqual(settle(true, 80, 0.1), false);
});
test('a flick wins over distance', () => {
  assert.strictEqual(settle(false, -12, -0.9), true);
  assert.strictEqual(settle(true, 12, 0.9), false);
});
test('dragging the wrong way does not flip an already-settled sheet', () => {
  assert.strictEqual(settle(true, -80, -0.1), true);
  assert.strictEqual(settle(false, 80, 0.1), false);
});
```

`tests/test_phonedetail.py`:

```python
"""Run the phone record screen's pure logic under pytest (mirrors test_covertilt.py)."""

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_phonedetail_js():
    result = subprocess.run(
        ["node", "--test", "tests/test_phonedetail.js"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 2: Run to verify failure**

Run: `node --test tests/test_phonedetail.js`
Expected: FAIL — cannot find module `../static/phonedetail.js`.

- [ ] **Step 3: Implement** — `static/phonedetail.js`:

```js
/* The phone's record screen: the two decisions that need no DOM.
 *
 * neighbors  - which records sit in the bottom row. The ends of the list have
 *              nothing past them, so that side is null (the row leaves it
 *              empty); the swipe on the cover does not wrap, and neither does
 *              this.
 * settle     - what a drag on the sheet's handle decides. A flick decides by
 *              direction alone; a slower drag has to travel DRAG_PX; anything
 *              less, or the wrong way, leaves the sheet where it was.
 *
 * Loaded as a plain script in the browser, where `const VinylPhoneDetail`
 * lands in the global lexical scope; required as a module by the tests. */
const VinylPhoneDetail = (() => {
  const DRAG_PX = 48;     // px a slow drag must travel to change the sheet
  const FLICK = 0.4;      // px/ms above which direction alone decides

  function neighbors(list, idx) {
    if (!Array.isArray(list) || list.length < 2 || idx < 0 || idx >= list.length) {
      return { prev: null, next: null };
    }
    return { prev: idx > 0 ? list[idx - 1] : null,
             next: idx < list.length - 1 ? list[idx + 1] : null };
  }

  function settle(open, dy, velocity) {
    if (Math.abs(velocity) >= FLICK) return velocity < 0;
    if (dy <= -DRAG_PX) return true;
    if (dy >= DRAG_PX) return false;
    return open;
  }

  return { DRAG_PX, FLICK, neighbors, settle };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylPhoneDetail;
```

In `templates/index.html`, after `<script src="/static/covertilt.js"></script>` add `<script src="/static/phonedetail.js"></script>`.

- [ ] **Step 4: Run to verify pass**

Run: `node --test tests/test_phonedetail.js && pytest tests/test_phonedetail.py -q`
Expected: PASS.

---

### Task 3: The fixed screen — nav row, sheet, section order

**Files:**
- Modify: `templates/index.html` — CSS block `/* ── mobile detail: …` (~956–1058), `renderDetailContent` (~6286), crate helpers (~6349–6375), `detailSectionsHTML` / `DD_SECTIONS` / `DETAIL_PANES` / `detailBarHeight` / `detailSyncSpy` (~6628–6720), `dmMeasureChrome` (~6740), `dmSetCurrent` (~7013), `detailCenterOnCurrent` (~7050), `dmBind` (~7066), `scrollFocusIntoView` (~7303), `renderDetailFoot` (~7372).
- Test: `tests/test_phone_dom.js`

**Interfaces:**
- Consumes: `VinylPhoneDetail.neighbors/settle` (Task 2); existing `dmList`, `dmIdx`, `dmSetCurrent`, `dmCenterSlide`, `censorWrap(r, html, {eye})`, `detailNavRecords()`, `esc`.
- Produces: DOM ids `#dmNav` (children `.dm-nav-btn.prev|.next[data-id]`, or `.empty`), `#dmSecs`, `.dm-handle`, class `sheet-open` on `#dmLayout`; functions `dmNavHTML()`, `dmSetSheet(open)`, `dmMeasureChrome()` (now sets `--dm-top-h`, `--dm-nav-h`). Removes `dmBuildCrate`, `dmThumbHTML`, `dmHighlightCrate`, `dmCenterCrateThumb`, `.dm-crate*`, `.dm-thumb*`, `.dm-foot`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_phone_dom.js`:

```js
// ── the phone's fixed record screen ─────────────────────────────────────────
const navIds = doc => ({
  prev: (doc.querySelector('#dmNav .dm-nav-btn.prev') || {}).dataset,
  next: (doc.querySelector('#dmNav .dm-nav-btn.next') || {}).dataset,
});
const listIds = read => read('detailNavRecords().map(r => r.id)');

test('the bottom row names the records on either side', async () => {
  const { win, doc, read } = await boot({ phone: true });
  try {
    const ids = listIds(read);
    win.openDetail(ids[1]);
    const nav = navIds(doc);
    assert.strictEqual(Number(nav.prev.id), ids[0]);
    assert.strictEqual(Number(nav.next.id), ids[2]);
    assert.strictEqual(doc.querySelector('#dmCrate'), null, 'the crate strip is gone');
  } finally { win.close(); }
});

test('the first record leaves its previous slot empty, the last its next', async () => {
  const { win, doc, read } = await boot({ phone: true });
  try {
    const ids = listIds(read);
    win.openDetail(ids[0]);
    assert.ok(doc.querySelector('#dmNav .dm-nav-btn.prev.empty'));
    assert.ok(!doc.querySelector('#dmNav .dm-nav-btn.prev[data-id]'));
    win.openDetail(ids[ids.length - 1]);
    assert.ok(doc.querySelector('#dmNav .dm-nav-btn.next.empty'));
  } finally { win.close(); }
});

test('tapping a bottom cover goes to that record', async () => {
  const { win, doc, read } = await boot({ phone: true });
  try {
    const ids = listIds(read);
    win.openDetail(ids[1]);
    press(win, doc.querySelector('#dmNav .dm-nav-btn.next'));
    assert.strictEqual(read('currentDetailId'), ids[2]);
    assert.strictEqual(Number(doc.querySelector('#dmNav .dm-nav-btn.prev').dataset.id), ids[1]);
    assert.strictEqual(doc.getElementById('dmLayout').dataset.rid, String(ids[2]));
  } finally { win.close(); }
});

test('a neighbour without artwork shows a disc, a censored one stays wrapped', async () => {
  const { win, doc, read } = await boot({ phone: true });
  try {
    // 14 is censored and 15 has no cover; open whichever record sits before them
    const ids = listIds(read);
    for (const bad of [14, 15]) {
      const at = ids.indexOf(bad);
      if (at < 1) continue;
      win.openDetail(ids[at - 1]);
      const art = doc.querySelector(`#dmNav .dm-nav-btn.next[data-id="${bad}"] .art`);
      assert.ok(art, `record ${bad} is the next neighbour`);
      if (bad === 15) assert.ok(art.querySelector('.ti-disc'), 'a disc stands in for the missing cover');
      else assert.notStrictEqual(art.firstElementChild.tagName, 'IMG', 'the blur wrapper is kept');
    }
  } finally { win.close(); }
});

test('the sheet starts closed and the handle opens and closes it', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openDetail(13);
    const lay = doc.getElementById('dmLayout');
    assert.ok(!lay.classList.contains('sheet-open'));
    press(win, doc.querySelector('.dm-handle'));
    assert.ok(lay.classList.contains('sheet-open'));
    assert.strictEqual(doc.querySelector('.dm-handle').getAttribute('aria-expanded'), 'true');
    press(win, doc.querySelector('.dm-handle'));
    assert.ok(!lay.classList.contains('sheet-open'));
  } finally { win.close(); }
});

test('the phone sheet reads Tracks, then Info, then Timeline', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openDetail(13);
    assert.deepStrictEqual(
      [...doc.querySelectorAll('#dmSecs > .dd-sec')].map(s => s.id),
      ['dmSec-tracks', 'dmSec-info', 'dmSec-timeline']);
    assert.deepStrictEqual(
      [...doc.querySelectorAll('#dmTabs .dm-tab')].map(b => b.dataset.ddsec),
      ['tracks', 'info', 'timeline']);
    // the desktop column is untouched
    assert.deepStrictEqual(
      [...doc.querySelectorAll('#ddInfo > .dd-sec')].map(s => s.id),
      ['ddSec-info', 'ddSec-tracks', 'ddSec-timeline']);
  } finally { win.close(); }
});

test('an open sheet survives a re-render of the same record, not a change of record', async () => {
  const { win, doc, read } = await boot({ phone: true });
  try {
    const ids = listIds(read);
    win.openDetail(ids[1]);
    press(win, doc.querySelector('.dm-handle'));
    win.__peek(`renderDetailContent(records.find(r => r.id === ${ids[1]}))`);   // what a like does
    assert.ok(doc.getElementById('dmLayout').classList.contains('sheet-open'), 'still open');
    press(win, doc.querySelector('#dmNav .dm-nav-btn.next'));
    assert.ok(!doc.getElementById('dmLayout').classList.contains('sheet-open'), 'a new record starts closed');
  } finally { win.close(); }
});

test('a drag up on the handle opens the sheet, a tap right after is swallowed', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openDetail(13);
    const h = doc.querySelector('.dm-handle');
    const ev = (type, y, t) => {
      const e = new win.Event(type, { bubbles: true, cancelable: true });
      e.touches = type === 'touchend' ? [] : [{ clientY: y }];
      Object.defineProperty(e, 'timeStamp', { value: t });
      h.dispatchEvent(e);
    };
    ev('touchstart', 400, 0); ev('touchmove', 300, 100); ev('touchend', 300, 110);
    assert.ok(doc.getElementById('dmLayout').classList.contains('sheet-open'));
    press(win, h);   // the click the browser fires after the touch
    assert.ok(doc.getElementById('dmLayout').classList.contains('sheet-open'), 'not toggled back');
  } finally { win.close(); }
});

test('a single record has an empty bottom row and does not throw', async () => {
  const { win, doc, errors } = await boot({ phone: true });
  try {
    win.__peek('filtered = () => records.slice(0, 1)');
    win.openDetail(win.__peek('records[0].id'));
    assert.ok(doc.querySelector('#dmNav .dm-nav-btn.prev.empty'));
    assert.ok(doc.querySelector('#dmNav .dm-nav-btn.next.empty'));
    assert.deepStrictEqual(errors, []);
  } finally { win.close(); }
});
```

> Before running: `filtered` may be a `function` declaration, not a `let`. If `filtered = …` throws in `__peek`, replace that test body with `win.__peek('detailNavRecords = () => records.slice(0, 1)')` (function declarations are assignable in the page scope). Pick whichever works and keep it.

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_phone_dom.py -q`
Expected: the new tests FAIL (`#dmNav` missing); existing tests still pass or fail only where noted in Step 8.

- [ ] **Step 3: Rewrite the phone CSS block.** In `templates/index.html` replace the whole block from the comment `/* ── mobile detail: cover carousel + crate of spines + info sheet ─…` through the closing `}` of that `@media(max-width:760px)` (ends after the `.tl-heart{…}` rule; find it with `grep -n "mobile detail: cover carousel\|^/\* form \*/" templates/index.html`) with:

```css
/* ── mobile detail: a fixed screen — tilting cover, details, bottom row ───── */
.detail-mobile-layout{display:none}
@media(max-width:760px){
  #detailOverlay{padding:0}
  #detailOverlay .modal.modal-wide{
    max-width:none;width:100%;height:100%;max-height:100%;
    border-radius:0;border:none;display:flex;flex-direction:column;
  }
  #detailOverlay .modal-head{display:none}
  #detailOverlay .modal-body{padding:0;flex:1;overflow:hidden;display:flex}
  #detailOverlay #detailBody{flex:1;width:100%;min-width:0}
  #detailOverlay .modal-foot{display:none}
  .detail-layout{display:none}
  /* Nothing here scrolls as a page: the tracklist scrolls in its own area and
     the raised sheet scrolls inside itself. */
  .detail-mobile-layout{
    --dm-cover:min(72vw,34vh);
    display:flex;flex-direction:column;position:relative;width:100%;height:100%;
    background:var(--bg);overflow:hidden;
  }

  .dm-top{
    display:flex;align-items:center;justify-content:space-between;
    /* black-translucent status bar hands its strip to the page; without this
       inset the close button sits under the clock in a home-screen install */
    padding:calc(12px + env(safe-area-inset-top,0px)) 14px 8px;
    flex-shrink:0;background:var(--bg);
  }
  .dm-close{width:36px;height:36px;border-radius:50%;border:1px solid var(--border);
    background:var(--card);color:var(--muted);display:flex;align-items:center;
    justify-content:center;font-size:16px;cursor:pointer}
  .dm-count{font-size:11px;letter-spacing:.12em;color:var(--muted);
    font-variant-numeric:tabular-nums;text-transform:uppercase}
  .dm-count b{color:var(--accent);font-weight:700}
  .dm-top-spacer{width:36px}

  /* The cover swipes like before; the current one tilts (JS writes --rx/--ry/
     --gx/--gy on it, see VinylCoverTilt.follow). */
  .dm-carousel{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;gap:14px;
    padding:6px calc(50% - var(--dm-cover) / 2) 10px;scrollbar-width:none;
    -webkit-overflow-scrolling:touch;flex-shrink:0;perspective:900px}
  .dm-carousel::-webkit-scrollbar{display:none}
  .dm-slide{flex:0 0 var(--dm-cover);width:var(--dm-cover);scroll-snap-align:center;scroll-snap-stop:always;
    aspect-ratio:1;border-radius:8px;overflow:hidden;position:relative;background:#0a0a0a;
    transition:transform .25s,opacity .25s;transform:scale(.94);opacity:.55}
  [data-theme="light"] .dm-slide{background:#ddd8cd}
  .dm-slide.cur{transform:rotateX(calc(var(--rx,0) * 1deg)) rotateY(calc(var(--ry,0) * 1deg));
    opacity:1;box-shadow:0 10px 30px rgba(0,0,0,.45);will-change:transform;transition:opacity .25s}
  .dm-slide img{width:100%;height:100%;object-fit:cover;display:block}
  .dm-slide-ph{width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:#3a3a3a}
  [data-theme="light"] .dm-slide-ph{color:#b0a99b}
  .dm-slide.cur img{cursor:zoom-in}
  /* shrink-wrap on a NEW record: same sheen as the zoomed cover */
  .dm-glare{display:none;position:absolute;inset:0;pointer-events:none;mix-blend-mode:screen;
    box-shadow:inset 0 0 0 1px rgba(255,255,255,.08);
    background:
      radial-gradient(circle at calc(var(--gx,50) * 1%) calc(var(--gy,50) * 1%),
        rgba(255,255,255,.14), rgba(255,255,255,0) 40%),
      linear-gradient(115deg, rgba(255,255,255,0) calc(var(--gx,50) * 1% - 22%),
        rgba(255,255,255,.09) calc(var(--gx,50) * 1% - 6%),
        rgba(255,255,255,0) calc(var(--gx,50) * 1% + 8%))}
  .dm-slide.sealed.cur .dm-glare{display:block}

  /* The details: header (album, artist, ratings) stays; the tracklist scrolls
     beneath it. Raised (.sheet-open), the same box covers the cover and shows
     the tabs and all three blocks. */
  .dm-info{flex:1 1 auto;min-height:0;display:flex;flex-direction:column;padding:0 16px;
    background:var(--bg)}
  .dm-handle{align-self:center;flex:0 0 auto;width:100%;height:22px;padding:0;border:0;
    background:none;cursor:pointer;position:relative}
  .dm-handle::after{content:"";position:absolute;left:50%;top:9px;width:40px;height:4px;
    margin-left:-20px;border-radius:2px;background:var(--border)}
  .dm-info .dm-tabs{display:none;flex-shrink:0;margin:10px 0 0}
  .dm-secs{flex:1 1 auto;min-height:0;overflow-y:auto;overscroll-behavior:contain;margin:8px -16px 0;
    padding:0 16px 12px}
  .dm-secs .dd-sec{display:none}
  .dm-secs #dmSec-tracks{display:block}
  #dmLayout.sheet-open .dm-info{position:absolute;left:0;right:0;z-index:5;
    top:var(--dm-top-h,56px);bottom:var(--dm-nav-h,72px);
    border-radius:16px 16px 0 0;box-shadow:0 -10px 30px rgba(0,0,0,.35)}
  #dmLayout.sheet-open .dm-info .dm-tabs{display:flex}
  #dmLayout.sheet-open .dm-secs .dd-sec{display:block}

  /* previous / next */
  .dm-nav{display:flex;justify-content:space-between;gap:12px;flex-shrink:0;position:relative;z-index:6;
    padding:10px 14px calc(10px + env(safe-area-inset-bottom,0px));
    border-top:1px solid var(--border);background:var(--bg)}
  .dm-nav-btn{flex:1 1 0;min-width:0;display:flex;align-items:center;gap:10px;
    background:none;border:0;padding:0;color:var(--text);text-align:left;cursor:pointer}
  .dm-nav-btn.next{flex-direction:row-reverse;text-align:right}
  .dm-nav-btn.empty{visibility:hidden}
  .dm-nav-btn .art{flex:0 0 48px;width:48px;height:48px;border-radius:6px;overflow:hidden;
    background:#26231d;color:#4a463e;display:flex;align-items:center;justify-content:center;
    font-size:20px;opacity:.85}
  [data-theme="light"] .dm-nav-btn .art{background:#c9c2b4;color:#a39c8e}
  .dm-nav-btn .art img{width:100%;height:100%;object-fit:cover;display:block;pointer-events:none}
  .dm-nav-btn .cap{min-width:0;display:flex;flex-direction:column}
  .dm-nav-btn .cap small{font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
  .dm-nav-btn .cap b{font-size:12.5px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  #dmLayout.has-edit .dm-nav-btn.next{margin-right:50px}   /* clear the edit button */

  /* admin: small, quiet, fixed bottom right */
  .dm-edit{position:absolute;right:14px;bottom:calc(14px + env(safe-area-inset-bottom,0px));z-index:7;
    width:38px;height:38px;border-radius:50%;border:1px solid var(--border);background:var(--card);
    color:var(--muted);display:flex;align-items:center;justify-content:center;font-size:16px;
    opacity:.6;cursor:pointer}
  .dm-edit:active{opacity:1}
  .dm-edit[hidden]{display:none}   /* display:flex above beats the UA [hidden] rule */

  /* A thumb, not a cursor, is aiming for this — 44px matches the platform's
     touch-target guidance. */
  .tl-heart{min-width:44px;min-height:44px;padding:0;
    display:flex;align-items:center;justify-content:center;font-size:16px}
}
```

(Keep the unscoped `.dm-album`, `.dm-rates`, `.dm-tabs`, etc. rules above this block as they are — they are shared with the desktop drawer.)

- [ ] **Step 4: Slides carry the glare and the sealed class.** Replace `dmSlideHTML`:

```js
function dmSlideHTML(rec) {
  const img = rec.cover_url
    ? censorWrap(rec, `<img src="${rec.cover_url}" alt="${esc(rec.album_name)}" loading="lazy" onerror="this.style.display='none'">`)
    : `<div class="dm-slide-ph"><i class="ti ti-disc" style="font-size:56px"></i></div>`;
  const sealed = VinylCoverTilt.hasShrinkWrap(rec) ? ' sealed' : '';
  return `<div class="dm-slide${sealed}" data-id="${rec.id}">${img}<span class="dm-glare"></span></div>`;
}
```

- [ ] **Step 5: Markup, nav, sheet, crate removal.**

In `renderDetailContent`, replace the `dmLayout` template (the crate wrap, `dmInfo`, `dmFoot` lines) and the calls after it:

```js
    <div class="detail-mobile-layout" id="dmLayout" data-rid="${r.id}">
      <div class="dm-top" id="dmTop">
        <button class="dm-close" onclick="closeDetail()" title="close"><i class="ti ti-x"></i></button>
        <span class="dm-count" id="dmCount"></span>
        <span class="dm-top-spacer"></span>
      </div>
      <div class="dm-carousel" id="dmCarousel">${dmList.map(dmSlideHTML).join('')}</div>
      <div class="dm-info" id="dmInfo"></div>
      <div class="dm-nav" id="dmNav"></div>
      <button type="button" class="dm-edit" id="dmEdit" hidden title="edit" aria-label="edit record"
              onclick="openEdit(currentDetailId)"><i class="ti ti-pencil"></i></button>
    </div>`;
  dmBind();
  ddBind();
  dmSetCurrent(dmIdx);
  dmSetSheet(keepSheet);
```

and above the `innerHTML=` assignment, after `keepScrollMobile`:

```js
  const keepSheet = !!(prevDm && prevDm.dataset.rid === String(r.id) && prevDm.classList.contains('sheet-open'));
```

and change the restore: `const dm = document.getElementById('dmSecs'); if (dm && keepScrollMobile) dm.scrollTop = keepScrollMobile;` and the earlier `keepScrollMobile` read to `const prevSecs = document.getElementById('dmSecs'); const keepScrollMobile = prevDm && prevSecs && prevDm.dataset.rid === String(r.id) ? prevSecs.scrollTop : 0;`. Keep the existing `dmMeasureChrome()` call after `dmSetCurrent`.

Delete `dmThumbHTML`, `dmBuildCrate`, `dmHighlightCrate`, `dmCenterCrateThumb` and their section comment. Add (next to `dmCenterSlide`):

```js
function dmNavHTML() {
  const { prev, next } = VinylPhoneDetail.neighbors(dmList, dmIdx);
  const side = (rec, dir, cap) => {
    if (!rec) return `<span class="dm-nav-btn ${dir} empty"></span>`;
    const art = rec.cover_url
      ? censorWrap(rec, `<img src="${rec.cover_url}" alt="" loading="lazy">`, {eye: false})
      : `<i class="ti ti-disc"></i>`;
    return `<button type="button" class="dm-nav-btn ${dir}" data-id="${rec.id}"
        aria-label="${cap}: ${esc(rec.album_name)}">
      <span class="art">${art}</span>
      <span class="cap"><small>${cap}</small><b>${esc(rec.album_name) || 'untitled'}</b></span></button>`;
  };
  return side(prev, 'prev', 'previous') + side(next, 'next', 'next');
}

/* The raised sheet. Class on #dmLayout; the handle mirrors it for assistive tech. */
function dmSetSheet(open) {
  const lay = document.getElementById('dmLayout');
  if (!lay) return;
  lay.classList.toggle('sheet-open', !!open);
  const h = lay.querySelector('.dm-handle');
  if (h) {
    h.setAttribute('aria-expanded', open ? 'true' : 'false');
    h.setAttribute('aria-label', open ? 'show less' : 'show more');
  }
  dmMeasureChrome();
}
```

- [ ] **Step 6: Sections, panes, spy.** In `detailSectionsHTML` replace the body (keep its doc comment, update the sentence about the phone to say the phone is a raised sheet):

```js
function detailSectionsHTML(r, pane) {
  const order = DETAIL_PANES[pane].order;
  const TABS = { info: ['info-circle', 'Info'], tracks: ['playlist', 'Tracks'], timeline: ['timeline', 'Timeline'] };
  const BODY = { info: dmInfoTabHTML, tracks: dmTracksTabHTML, timeline: dmTimelineTabHTML };
  const tabBtn = id =>
    `<button class="dm-tab" data-ddsec="${id}" onclick="detailGoToSection('${pane}','${id}')"
       ><i class="ti ti-${TABS[id][0]}"></i>${TABS[id][1]}</button>`;
  const tabs = `<div class="dm-tabs dd-tabs" id="${pane}Tabs">${order.map(tabBtn).join('')}</div>`;
  const secs = order.map(id =>
    `<section class="dd-sec" id="${pane}Sec-${id}">${BODY[id](r)}</section>`).join('');
  if (pane !== 'dm') return dmHeaderHTML(r, pane) + tabs + secs;
  // The phone: a handle, the header, the tab row (shown only when raised), and
  // one scroller holding the blocks (only Tracks shows until raised).
  return `<button type="button" class="dm-handle" aria-expanded="false" aria-label="show more"></button>`
    + dmHeaderHTML(r, pane) + tabs + `<div class="dm-secs" id="dmSecs">${secs}</div>`;
}
```

Replace `DETAIL_PANES` and its comment lead:

```js
const DETAIL_PANES = {
  dd: { scroller: 'ddInfo', chrome: null, order: ['info', 'tracks', 'timeline'] },
  // the phone's tab row sits above its scroller rather than over it
  dm: { scroller: 'dmSecs', chrome: null, order: ['tracks', 'info', 'timeline'], tabsOutside: true },
};
```

`detailBarHeight`:

```js
function detailBarHeight(pane) {
  const p = DETAIL_PANES[pane];
  const el = id => { const n = id && document.getElementById(id); return n ? n.offsetHeight : 0; };
  return (p.tabsOutside ? 0 : el(pane + 'Tabs')) + el(p.chrome);
}
```

In `detailSyncSpy`, replace the two `DD_SECTIONS` uses with a local `const order = DETAIL_PANES[pane].order;` (`let active = order[0]; order.forEach(...)`, and `active = order[order.length - 1]`). Leave `const DD_SECTIONS` removed if `grep -n DD_SECTIONS templates/index.html tests/*.js` then shows no other use; otherwise keep it.

- [ ] **Step 7: Measure, render, bind, focus, foot.**

`dmMeasureChrome`:

```js
/* The raised sheet fills the gap between the header and the bottom row, so it
 * needs both heights. Measured rather than written into the stylesheet twice. */
function dmMeasureChrome() {
  const lay = document.getElementById('dmLayout');
  if (!lay) return;
  const h = id => { const n = document.getElementById(id); return n ? n.offsetHeight : 0; };
  lay.style.setProperty('--dm-top-h', h('dmTop') + 'px');
  lay.style.setProperty('--dm-nav-h', h('dmNav') + 'px');
}
```

`dmSetCurrent`: remove `dmHighlightCrate(idx); dmCenterCrateThumb(idx, true);`; after `const info = …; if (info) info.innerHTML = dmInfoHTML(rec);` add:

```js
  const nav = document.getElementById('dmNav');
  if (nav) nav.innerHTML = dmNavHTML();
  // a different record starts with the sheet down; the same one (a like, a
  // rating) keeps it where it was
  const lay = document.getElementById('dmLayout');
  const sameRecord = !lay || lay.dataset.rid === String(rec.id);
  if (lay) lay.dataset.rid = String(rec.id);
  dmSetSheet(!!lay && sameRecord && lay.classList.contains('sheet-open'));
```

Also remove the final `dmMeasureChrome();` comment line about the foot (keep the call).

`detailCenterOnCurrent` phone branch: delete the `dmCenterCrateThumb(dmIdx, false);` line.

`dmBind`: replace the crate listener with:

```js
  document.getElementById('dmNav').addEventListener('click', e => {
    const b = e.target.closest('.dm-nav-btn[data-id]');
    if (!b) return;
    const idx = dmList.findIndex(r => r.id === Number(b.dataset.id));
    if (idx === -1) return;
    dmSetCurrent(idx);
    dmCenterSlide(idx, true);
  });

  // The handle: a tap toggles the sheet; a drag on it decides by distance or
  // flick (VinylPhoneDetail.settle). The click the browser sends after a drag
  // is swallowed so it cannot undo it.
  const lay = document.getElementById('dmLayout');
  let y0 = null, t0 = 0, y1 = 0, t1 = 0, swallow = false;
  lay.addEventListener('touchstart', e => {
    if (!e.target.closest('.dm-handle')) return;
    y0 = y1 = e.touches[0].clientY; t0 = t1 = e.timeStamp;
  }, {passive: true});
  lay.addEventListener('touchmove', e => {
    if (y0 === null) return;
    y1 = e.touches[0].clientY; t1 = e.timeStamp;
  }, {passive: true});
  lay.addEventListener('touchend', () => {
    if (y0 === null) return;
    const dy = y1 - y0, v = dy / Math.max(1, t1 - t0);
    y0 = null;
    if (Math.abs(dy) < 8) return;                       // a tap: the click handles it
    dmSetSheet(VinylPhoneDetail.settle(lay.classList.contains('sheet-open'), dy, v));
    swallow = true; setTimeout(() => { swallow = false; }, 350);
  });
  lay.addEventListener('click', e => {
    if (!e.target.closest('.dm-handle') || swallow) return;
    dmSetSheet(!lay.classList.contains('sheet-open'));
  });
```

`scrollFocusIntoView` phone branch: after `const el = …` add the raise:

```js
  const phone = window.matchMedia('(max-width:760px)').matches;
  if (el && phone) dmSetSheet(true);     // the event lives in a block the closed sheet hides
```
(reuse `phone` in the `pane` ternary).

`renderDetailFoot`: delete the `dmFoot` two lines and replace them with:

```js
  // phone: the one control is the small edit button; delete lives in the edit form
  const dmEdit = document.getElementById('dmEdit');
  if (dmEdit) dmEdit.hidden = !authed;
  const dmLay = document.getElementById('dmLayout');
  if (dmLay) dmLay.classList.toggle('has-edit', !!authed);
```
and fix its comment ("desktop drawer footer + …").

- [ ] **Step 8: Run, then repair what the redesign moved.**

Run: `pytest tests/test_phone_dom.py -q`
Expected: the new tests PASS. Existing tests that referenced `#dmLayout` scrolling, `#dmTabs` order, `#dmInfo #dmSec-*`, or `dmFoot` are in `tests/test_boot.js` (~3440–3540, which hangs and is not run); read them and update by hand: tab order → `tracks, info, timeline`; the scroll-restore tests → `#dmSecs`; "`#dmInfo #dmSec-…`" still holds. Run `grep -n "dmFoot\|dm-foot\|dmCrate\|dm-thumb" templates/index.html tests/*.js tests/*.py` — expected: no matches left (fix any).

- [ ] **Step 9: Safe-area check**

Run: `pytest tests/test_safe_areas.py -q`
Expected: PASS (new fixed chrome pays `env(safe-area-inset-*)`); if it flags `.dm-edit`/`.dm-nav`, add the missing inset.

---

### Task 4: Gyroscope by default

**Files:**
- Modify: `templates/index.html` — `openDetail` (~7279), `closeDetail` (~7421), `dmSetCurrent`, `openCoverView` / `coverOnOrient` / `coverTiltFrame` / `closeCoverView` (~7075–7135)
- Test: `tests/test_phone_dom.js`

**Interfaces:**
- Consumes: `VinylCoverTilt.follow/requestMotion/wantsTilt` (Task 1), `.dm-slide.cur` (Task 3), `isPhone()`.
- Produces: `startSlideTilt()`, `stopSlideTilt()`, `clearSlideLean()`; module vars `slideFollow`, `slideTiltToken`, `motionGranted`. The zoomed cover now uses `follow` too (`coverFollow`, `coverTiltToken`); `coverTilt`, `coverOnOrient`, `coverTiltFrame` are removed.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_phone_dom.js`:

```js
// ── the cover tilts as soon as the record is open ───────────────────────────
const curSlide = doc => doc.querySelector('#dmCarousel .dm-slide.cur');
const ry = el => Number(el.style.getPropertyValue('--ry') || 0);

test('the open record\'s cover leans with the phone, no tap needed', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.DeviceOrientationEvent = function () {};
    win.openDetail(13);
    await frames(2);
    orient(win, 55, 0); orient(win, 55, 15);
    await frames(30);
    assert.ok(ry(curSlide(doc)) > 0, 'it turns with the phone');
    assert.ok(curSlide(doc).classList.contains('sealed'), 'a NEW record carries the shrink-wrap');
  } finally { win.close(); }
});

test('iOS is asked inside the tap that opens the record, and only once', async () => {
  const { win } = await boot({ phone: true });
  try {
    let asked = 0;
    win.DeviceOrientationEvent = function () {};
    win.DeviceOrientationEvent.requestPermission = async () => { asked++; return 'granted'; };
    win.openDetail(1);
    assert.strictEqual(asked, 1, 'asked synchronously');
    await frames(2);
    win.openDetail(13);
    await frames(2);
    assert.strictEqual(asked, 1, 'a granted answer is remembered');
  } finally { win.close(); }
});

test('a refused or rejected permission leaves the cover flat without an error', async () => {
  const { win, doc, errors } = await boot({ phone: true });
  try {
    win.DeviceOrientationEvent = function () {};
    win.DeviceOrientationEvent.requestPermission = async () => { throw new Error('nope'); };
    win.openDetail(13);
    await frames(2);
    orient(win, 55, 0); orient(win, 55, 20);
    await frames(10);
    assert.strictEqual(ry(curSlide(doc)), 0);
    assert.deepStrictEqual(errors, []);
  } finally { win.close(); }
});

test('reduced motion keeps the record\'s cover flat', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.DeviceOrientationEvent = function () {};
    const mm = win.matchMedia;
    win.matchMedia = q => /prefers-reduced-motion/.test(q) ? { matches: true } : mm(q);
    win.openDetail(13);
    await frames(2);
    orient(win, 55, 0); orient(win, 55, 20);
    await frames(10);
    assert.strictEqual(ry(curSlide(doc)), 0);
  } finally { win.close(); }
});

test('desktop does not tilt anything', async () => {
  const { win, doc } = await boot({ phone: false });
  try {
    win.DeviceOrientationEvent = function () {};
    win.openDetail(13);
    await frames(2);
    orient(win, 55, 0); orient(win, 55, 20);
    await frames(10);
    assert.strictEqual(ry(curSlide(doc)), 0);
  } finally { win.close(); }
});

test('swiping to another record starts that cover flat', async () => {
  const { win, doc, read } = await boot({ phone: true });
  try {
    win.DeviceOrientationEvent = function () {};
    const ids = read('detailNavRecords().map(r => r.id)');
    win.openDetail(ids[1]);
    await frames(2);
    orient(win, 55, 0); orient(win, 55, 20);
    await frames(30);
    assert.ok(ry(curSlide(doc)) > 0);
    press(win, doc.querySelector('#dmNav .dm-nav-btn.next'));
    assert.strictEqual(ry(curSlide(doc)), 0, 'the new cover is not left mid-lean');
    assert.strictEqual(
      [...doc.querySelectorAll('#dmCarousel .dm-slide')].filter(s => ry(s) !== 0).length, 0);
  } finally { win.close(); }
});

test('the zoomed cover takes over the tilt and gives it back', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.DeviceOrientationEvent = function () {};
    win.openDetail(13);
    await frames(2);
    press(win, curSlide(doc).querySelector('img'));          // zoom
    await frames(2);
    orient(win, 55, 0); orient(win, 55, 20);
    await frames(30);
    assert.strictEqual(ry(curSlide(doc)), 0, 'the small cover rests while the big one leans');
    assert.ok(Number(doc.getElementById('coverViewCard').style.getPropertyValue('--ry')) > 0);
    win.closeCoverView();
    await frames(2);
    orient(win, 55, 0); orient(win, 55, 20);
    await frames(30);
    assert.ok(ry(curSlide(doc)) > 0, 'back on the record, it leans again');
  } finally { win.close(); }
});

test('closing the record stops listening to the phone', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.DeviceOrientationEvent = function () {};
    win.openDetail(13);
    await frames(2);
    const slide = curSlide(doc);
    win.closeDetail();
    orient(win, 55, 0); orient(win, 55, 20);
    await frames(10);
    assert.strictEqual(ry(slide), 0);
  } finally { win.close(); }
});
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_phone_dom.py -q`
Expected: the new tilt tests FAIL (slide never leans); the existing full-screen cover tests PASS.

- [ ] **Step 3: Wire the inline tilt.** In `templates/index.html`, just above `// ── the phone's full-screen cover` add:

```js
// ── the record's own cover leans, from the moment it is open ────────────────
// The same maths and easing as the zoomed cover (static/covertilt.js). iOS only
// shows its motion prompt for a call made inside the tap, so openDetail() calls
// startSlideTilt() synchronously; a granted answer is remembered so paging
// through records never asks again.
let slideFollow = null, slideTiltToken = null, motionGranted = false;

function prefersReducedMotion() {
  return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
}

function curSlideEl() { return document.querySelector('#dmCarousel .dm-slide.cur'); }

function clearSlideLean() {
  document.querySelectorAll('#dmCarousel .dm-slide').forEach(s =>
    ['--rx', '--ry', '--gx', '--gy'].forEach(p => s.style.removeProperty(p)));
}

function stopSlideTilt() {
  slideTiltToken = null;
  if (slideFollow) { slideFollow.stop(); slideFollow = null; }
}

function startSlideTilt() {
  stopSlideTilt();
  if (!isPhone() || !VinylCoverTilt.wantsTilt(prefersReducedMotion())) return;
  const token = slideTiltToken = {};
  const ask = motionGranted ? Promise.resolve('granted') : VinylCoverTilt.requestMotion(window);
  ask.then(answer => {
    if (answer !== 'granted') return;
    motionGranted = true;
    // closed, replaced, or the zoomed cover took over while the prompt was up
    if (slideTiltToken !== token || currentDetailId == null) return;
    if (!document.getElementById('coverView').classList.contains('hidden')) return;
    slideFollow = VinylCoverTilt.follow(window, curSlideEl);
  });
}
```

Call sites:
- `openDetail`: add `startSlideTilt();` right after `currentDetailId = id;` (before `renderDetailContent`; still synchronous in the tap).
- `closeDetail`: add `stopSlideTilt();` as the first line.
- `dmSetCurrent`: after the nav/sheet lines from Task 3 add `clearSlideLean(); if (slideFollow) slideFollow.rebase();`.

- [ ] **Step 4: Move the zoomed cover onto `follow`.** Replace the block from `let coverTilt = null; …` through `closeCoverView` (`coverTilt`, `openCoverView`, `coverOnOrient`, `coverTiltFrame`, `closeCoverView`) with:

```js
let coverFollow = null, coverTiltToken = null;   // while a tilting zoomed cover is open

function openCoverView(id) {
  const r = records.find(x => x.id === id);
  if (!r || !r.cover_url) return;
  // the blur is a choice someone made about this cover; a tap is not a way round it
  if (r.censored && !revealedCovers.has(r.id)) return;
  closeCoverView();
  stopSlideTilt();                      // one cover leans at a time
  const img = document.getElementById('coverViewImg');
  img.src = r.cover_url;
  img.alt = r.album_name || '';
  const tilt = VinylCoverTilt.wantsTilt(prefersReducedMotion());
  const sealed = VinylCoverTilt.hasShrinkWrap(r);
  const card = document.getElementById('coverViewCard');
  card.classList.toggle('tilt', tilt);
  card.classList.toggle('sealed', sealed);
  document.getElementById('coverView').classList.remove('hidden');
  trackEvent('cover-open', { record: VinylAnalytics.recordLabel(r), sealed });
  if (!tilt) return;
  const token = coverTiltToken = {};
  // Asked here, still inside the tap, unless a record already got the answer.
  const ask = motionGranted ? Promise.resolve('granted') : VinylCoverTilt.requestMotion(window);
  ask.then(answer => {
    if (answer !== 'granted' || coverTiltToken !== token) return;
    motionGranted = true;
    coverFollow = VinylCoverTilt.follow(window, () => document.getElementById('coverViewCard'));
  });
}

function closeCoverView() {
  coverTiltToken = null;
  if (coverFollow) { coverFollow.stop(); coverFollow = null; }
  document.getElementById('coverView').classList.add('hidden');
  // back on the record behind it, its own cover leans again
  if (currentDetailId != null) startSlideTilt();
}
```

(Keep the comment block that introduces the full-screen cover; update its first line to mention the inline cover.) `closeCoverView()` is also called at the top of `openCoverView` and by Escape/tap handlers; the extra `startSlideTilt()` there is stopped again one line later by `stopSlideTilt()`.

- [ ] **Step 5: Run to verify pass**

Run: `pytest tests/test_phone_dom.py tests/test_covertilt.py tests/test_phonedetail.py -q`
Expected: all PASS, including the original full-screen cover tests (`a new record leans with the phone…`, `closing stops listening…`, `reduced motion opens the cover flat`, `iOS is asked, inside the tap`).

---

### Task 5: Admin edit button

**Files:**
- Test: `tests/test_phone_dom.js` (code already added in Task 3, Step 5 and 7)

**Interfaces:**
- Consumes: `#dmEdit`, `renderDetailFoot`, `openEdit`, `authed`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_phone_dom.js`:

```js
test('admin gets a small edit button on the record, a visitor does not', async () => {
  const { win, doc, read } = await boot({ phone: true });
  try {
    win.openDetail(13);
    const btn = doc.getElementById('dmEdit');
    assert.strictEqual(read('authed'), true, 'the fixture session is the admin');
    assert.strictEqual(btn.hidden, false);
    assert.ok(doc.getElementById('dmLayout').classList.contains('has-edit'));
    win.__peek('authed = false; renderDetailFoot(currentDetailId)');
    assert.strictEqual(btn.hidden, true);
    assert.ok(!doc.getElementById('dmLayout').classList.contains('has-edit'));
  } finally { win.close(); }
});

test('the edit button opens this record\'s edit form', async () => {
  const { win, doc, read } = await boot({ phone: true });
  try {
    win.openDetail(13);
    press(win, doc.getElementById('dmEdit'));
    assert.strictEqual(read('editingId'), 13);
    assert.ok(doc.getElementById('detailOverlay').classList.contains('hidden'), 'the record closed behind it');
  } finally { win.close(); }
});

test('the phone record screen has no delete button', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openDetail(13);
    assert.strictEqual(doc.querySelector('#dmLayout .btn-danger'), null);
    assert.strictEqual(doc.getElementById('dmFoot'), null);
  } finally { win.close(); }
});

test('the edit form on the phone still carries delete', async () => {
  const { win, doc } = await boot({ phone: true });
  try {
    win.openDetail(13);
    press(win, doc.getElementById('dmEdit'));
    assert.ok(doc.getElementById('editRootDelete'), 'delete lives in the form');
  } finally { win.close(); }
});
```

- [ ] **Step 2: Run to verify** (implementation landed in Task 3)

Run: `pytest tests/test_phone_dom.py -q -k "edit or delete"`
Expected: PASS. If `authed` is not `true` in the fixture boot (the stub answers `/api/auth/status` with `authed:true`, but boot timing may leave it unset), add `await frames(5)` after `boot` in the first test.

---

### Task 6: Verify in a real phone viewport and document

**Files:**
- Create: `docs/phone-record-view-manual-verification.md`
- Modify: `docs/cover-tilt-manual-verification.md` (one line: the record's own cover now tilts too)

- [ ] **Step 1: Full targeted test run**

Run: `pytest tests/test_phone_dom.py tests/test_covertilt.py tests/test_phonedetail.py tests/test_safe_areas.py tests/test_carousel.py tests/test_timeline.py tests/test_tracks.py -q`
Expected: PASS. (Do not run `tests/test_boot.py` — it always times out; see Global Constraints.)

- [ ] **Step 2: Screenshot at phone size.** Restart Flask (template edits need it), then, using the project's no-root chromium recipe, capture a 390×844 viewport of a record with the sheet closed, with it open, and as admin. Check: cover square and centred; bottom row legible; edit button clear of the "next" slot; nothing under the clock or home indicator; tracklist scrolls inside its area.

- [ ] **Step 3: Write `docs/phone-record-view-manual-verification.md`** with this checklist (same style as the other `*-manual-verification.md` files):

```markdown
# Phone record view — manual verification

On a real phone (iOS Safari and Android Chrome), installed to the home screen if possible.

- [ ] Open a record from the grid: the cover tilts as you move the phone, no tap. iOS asks for motion access once.
- [ ] A NEW (sealed) record shows the shrink-wrap glare sliding opposite the tilt; a used one does not.
- [ ] Deny motion access: the cover stays flat, nothing breaks.
- [ ] Swipe the cover left/right: next/previous record; the new cover starts flat.
- [ ] The bottom row shows previous (left) and next (right) with cover and title; tap goes there; first/last record leaves one side empty.
- [ ] Middle: album + year, artist, Pepe/Jenni bars and total, then tracks; the tracklist scrolls without moving the header.
- [ ] Tap or drag up the handle: the sheet rises over the cover with Tracks, Info, Timeline; tabs jump between them; the bottom row stays.
- [ ] Drag down or tap the handle: it closes. Changing record closes it. Liking a song with the sheet open keeps it open.
- [ ] Tap the cover: the zoomed view leans and the small cover rests; closing it resumes the small one.
- [ ] A Timeline link (e.g. from the History page) opens the record with the sheet raised and the entry in view.
- [ ] Logged in: a small edit button sits bottom right, clear of the next cover; it opens the edit form, which has Delete.
- [ ] Logged out: no edit button.
- [ ] Rotate to landscape and back mid-tilt: no jump.
- [ ] Reduced-motion setting on: cover flat.
```

- [ ] **Step 4: Report.** Summarize what ran and passed (or failed) to the user; leave committing to them.

---

## Self-Review

- **Spec coverage:** fixed screen + bottom prev/next (Task 3), details + tracks in middle (Task 3), sheet with Tracks→Info→Timeline (Task 3), gyroscope by default + iOS permission + reduced motion + listener cleanup + zoom coexistence (Tasks 1, 4), admin edit button (Tasks 3, 5), delete (already in edit root; asserted in Task 5), tests (every task), screenshot (Task 6), desktop untouched (Task 3 asserts `ddSec` order).
- **Placeholders:** none; the one conditional (`filtered` vs `detailNavRecords` stub, and `authed` timing) gives both concrete alternatives.
- **Names:** `follow`, `rebase`, `stop`, `neighbors`, `settle`, `dmNavHTML`, `dmSetSheet`, `dmMeasureChrome`, `startSlideTilt`/`stopSlideTilt`/`clearSlideLean`, `coverFollow`, `#dmNav`, `#dmSecs`, `#dmEdit`, `.sheet-open`, `.has-edit` are used identically across tasks.
