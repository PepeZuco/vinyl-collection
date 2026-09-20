# Phone Add/Edit Redraw Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redraw the add/edit record form for one thumb in standalone Safari, and give the app a real home-screen icon instead of the letter Z.

**Architecture:** Everything is phone-only — inside the existing `@media(max-width:760px)` block at `templates/index.html:2320`, or behind a new `isPhone()` helper. The decidable rules (rail states, chip ranking, preview strings, collapse decisions) are extracted into a new `static/phoneform.js` module so they can be tested as pure functions, matching how `static/grouping.js` and `static/draft.js` are tested. DOM wiring is proven by extending `tests/test_boot.js`. No field id changes, so `formValues()`, `applyDraft()`, the scan writers and the queue are untouched.

**Tech Stack:** Flask + Jinja (one template, `templates/index.html`), vanilla JS in `static/*.js` with a dual browser/CommonJS export, `pytest` as the single test command, `node --test` for JS run via a `tests/test_*.py` wrapper, jsdom bootstrapped into a scratch dir by `tests/test_boot.py`.

**Spec:** `docs/superpowers/specs/2026-09-19-phone-add-edit-redraw-design.md`

## Global Constraints

- **Breakpoint is 760px**, everywhere. CSS uses `@media(max-width:760px)`; JS reads the same number through `isPhone()`. Never duplicate the literal.
- **No field ids change.** `#fArtist`, `#fAlbum`, `#fYear`, `#fGenre`, `#fCountry`, `#fWhere`, `#fDate`, `#fTime`, `#fCondition`, `#fHaveIt`, `#fPlays`, `#fSpotifyUrl`, `#fCensored`, `#fNoteText`, `#fNoteDate`, `#fNoteTime`, `#fNotePrivate`, `#fSizePick`, `#fDiscPick`, `#fVinylColor`, `#fLabelColor` all keep their ids and their positions in `formValues()`.
- **`#formSaveBtn` exists exactly once** in the DOM at all times. On the phone it is *moved* into the nav bar, never duplicated — `syncSaveLabel()` and the wishlist relabel at `templates/index.html:5915` address one element.
- **Desktop renders exactly what it renders today.** Four `.fstep` buttons with labels and captions, `.modal-head` with title + `×`, `.modal-foot` with cancel/back/next/save, step 1 opening on the cover well, `openEdit` going straight to step 1, the `<datalist>` for *Bought at*, and all log sections expanded.
- **No package.json.** jsdom is installed into a scratch dir by the test wrapper and the test skips when it cannot be. Never add a node toolchain to this repo.
- **Inputs inside `#formOverlay` stay at 16px minimum** — below that iOS zooms the page on focus. The rule at `templates/index.html:2331` must keep covering every new control.
- **Colour tokens only.** `var(--accent)`, `var(--card)`, `var(--border)`, `var(--text)`, `var(--label)`, `var(--muted)`, `var(--danger)`, `var(--bg)`, `var(--surface)`. Both `[data-theme="dark"]` and `[data-theme="light"]` must read correctly; never hardcode a hex that only works in one.
- **Event colours for the log rows:** played `var(--ev-played)`, cleaned `var(--ev-cleaned)`, note `var(--ev-note)`.
- **Home-screen app title is exactly `Vinyl`.**
- **Commit after every task.** Message style in this repo: lowercase `type: summary`, a blank line, then prose explaining *why*. End with the `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` trailer.

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `tools/make_icons.py` | create | One-off renderer: `static/vinyl-icon.svg` → the three PNGs. Not imported by the app, not in `requirements.txt` |
| `static/icon-180.png`, `icon-192.png`, `icon-512.png` | create | Home-screen and manifest icons, flat, no alpha |
| `static/manifest.json` | create | Web app manifest |
| `static/phoneform.js` | create | `VinylPhoneForm` — the pure rules. No DOM access, no globals read |
| `templates/index.html` | modify | Head meta (`:5`, `:7`), phone CSS (`:2320`), form markup (`:2989-3322`), `FORM_STEPS`/`setFormStep` (`:6935`), `openAdd`/`openEdit` (`:6780`/`:6847`), `submitForm` (`:7106`), `toast` (`:9167`) |
| `tests/test_phoneform.js` | create | Pure tests for `VinylPhoneForm` |
| `tests/test_phoneform.py` | create | `node --test` wrapper, mirroring `tests/test_draft.py` |
| `tests/test_icons.py` | create | Flask-side: the PNGs serve, the manifest parses, the head declares them |
| `tests/test_boot.js` | modify | Harness fixes + a phone-mode boot proving the wiring |
| `docs/phone-form-manual-verification.md` | create | What a headless DOM cannot check |

`static/phoneform.js` is loaded by adding one `<script src="/static/phoneform.js"></script>` beside the others at `templates/index.html:3615-3631`. `test_boot.js` inlines `/static/*.js` automatically, so no harness change is needed for the module itself.

---

## Task 1: Icon, manifest and standalone meta

Self-contained, no JS, immediately visible on the phone. Nothing below depends on it, and it is the half of the request that is pure win.

**Files:**
- Create: `tools/make_icons.py`, `static/icon-180.png`, `static/icon-192.png`, `static/icon-512.png`, `static/manifest.json`
- Modify: `templates/index.html:5` (viewport meta), `templates/index.html:7` (after the favicon link)
- Test: `tests/test_icons.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `static/manifest.json` and the three PNGs at fixed paths. No JS surface. Task 2 depends on `viewport-fit=cover` being in the viewport meta.

- [ ] **Step 1: Write the failing test**

Create `tests/test_icons.py`:

```python
"""The home-screen icon and the standalone metadata.

iOS generates a tile from the page when no apple-touch-icon is declared — in
practice the first letter of <title>, which is why the app installed to a home
screen showed a letter Z. These tests pin down the three things that fixes:
the icon files exist and are the right size, the manifest parses, and the head
actually points at them.
"""

import json
import struct

import pytest

import app as app_module


@pytest.fixture()
def client():
    return app_module.app.test_client()


def _png_size(data: bytes):
    """Width and height out of a PNG's IHDR, without pulling in Pillow."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return struct.unpack(">II", data[16:24])


@pytest.mark.parametrize("name,expected", [
    ("icon-180.png", 180),
    ("icon-192.png", 192),
    ("icon-512.png", 512),
])
def test_icon_serves_at_its_declared_size(client, name, expected):
    res = client.get(f"/static/{name}")
    assert res.status_code == 200
    assert res.mimetype == "image/png"
    assert _png_size(res.get_data()) == (expected, expected)


def test_manifest_parses_and_its_icons_resolve(client):
    res = client.get("/static/manifest.json")
    assert res.status_code == 200
    manifest = json.loads(res.get_data(as_text=True))
    assert manifest["display"] == "standalone"
    assert manifest["short_name"] == "Vinyl"
    assert manifest["background_color"] == "#0c0c0c"
    for icon in manifest["icons"]:
        assert client.get(icon["src"]).status_code == 200


def test_head_declares_the_icon_and_the_manifest(client):
    html = client.get("/").get_data(as_text=True)
    assert '<link rel="apple-touch-icon" href="/static/icon-180.png">' in html
    assert '<link rel="manifest" href="/static/manifest.json">' in html
    assert '<meta name="apple-mobile-web-app-capable" content="yes">' in html
    assert '<meta name="mobile-web-app-capable" content="yes">' in html
    assert 'name="apple-mobile-web-app-status-bar-style" content="black-translucent"' in html


def test_home_screen_title_is_short(client):
    """The tile caption truncates near 12 characters; the full title does not fit."""
    html = client.get("/").get_data(as_text=True)
    assert '<meta name="apple-mobile-web-app-title" content="Vinyl">' in html


def test_viewport_opts_into_the_safe_area():
    """black-translucent puts the status bar over the page, so the page has to
    be told to extend under it — without this the header slides under the clock."""
    html = app_module.app.test_client().get("/").get_data(as_text=True)
    viewport = next(l for l in html.splitlines() if 'name="viewport"' in l)
    assert "viewport-fit=cover" in viewport
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_icons.py -v`
Expected: FAIL — `test_icon_serves_at_its_declared_size` 404s on all three, `test_manifest_parses_and_its_icons_resolve` 404s, and the head assertions fail.

- [ ] **Step 3: Write the icon renderer**

Create `tools/make_icons.py`:

```python
#!/usr/bin/env python3
"""Render static/vinyl-icon.svg into the home-screen PNGs.

Run by hand when the mark changes; not imported by the app and deliberately
not in requirements.txt, so the deploy does not grow a rendering stack for
three files that change approximately never.

    python tools/make_icons.py

iOS masks the tile into a squircle itself and composites any alpha onto black,
so the mark is drawn onto the app's own ground here rather than shipped
transparent, and the corners are left square.
"""

import io
import pathlib
import sys

GROUND = (12, 12, 12)          # #0c0c0c, the app's dark ground
MARK_FRACTION = 0.86           # the mark's diameter as a share of the tile
SIZES = (180, 192, 512)

ROOT = pathlib.Path(__file__).resolve().parent.parent
SVG = ROOT / "static" / "vinyl-icon.svg"
OUT = ROOT / "static"


def render_mark(px: int) -> "Image.Image":
    """The SVG at px x px with transparency intact."""
    import cairosvg
    from PIL import Image

    png = cairosvg.svg2png(url=str(SVG), output_width=px, output_height=px)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def build(size: int) -> "Image.Image":
    from PIL import Image

    mark_px = round(size * MARK_FRACTION)
    tile = Image.new("RGB", (size, size), GROUND)
    mark = render_mark(mark_px)
    offset = (size - mark_px) // 2
    tile.paste(mark, (offset, offset), mark)   # alpha as the mask
    return tile


def main() -> int:
    try:
        import cairosvg  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        print("needs cairosvg and Pillow:  pip install cairosvg pillow", file=sys.stderr)
        return 1
    for size in SIZES:
        path = OUT / f"icon-{size}.png"
        build(size).save(path, "PNG", optimize=True)
        print(f"wrote {path.relative_to(ROOT)}  {size}x{size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Generate the PNGs**

```bash
cd /mnt/c/Users/jujuz/Documents/Portifolio/vinyl-collection
pip install cairosvg pillow
python tools/make_icons.py
```

Expected: three lines confirming `static/icon-180.png 180x180`, `icon-192.png 192x192`, `icon-512.png 512x512`.

If `cairosvg` will not install (it needs native cairo), fall back to rendering with Pillow alone — the mark is eight concentric circles and can be drawn directly:

```python
def render_mark(px: int):
    """Fallback: draw the mark instead of rasterising the SVG.

    Radii and colours are read off static/vinyl-icon.svg, which uses a
    120-unit viewBox; keep the two in step by hand if the mark changes.
    """
    from PIL import Image, ImageDraw

    ss = 4                                    # supersample, then downscale
    img = Image.new("RGBA", (px * ss, px * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    unit = px * ss / 120.0
    def circle(r, fill=None, outline=None, width=1):
        c = 60 * unit
        box = [c - r * unit, c - r * unit, c + r * unit, c + r * unit]
        d.ellipse(box, fill=fill, outline=outline, width=max(1, round(width * unit)))
    circle(58, "#9B7FD4"); circle(44, "#F5C518"); circle(22, "#D4608A")
    circle(16, "#111111")
    circle(13, None, "#D4608A", 1); circle(10, None, "#D4608A", 1)
    circle(4, "#D4608A"); circle(1.5, "#111111")
    return img.resize((px, px), Image.LANCZOS)
```

- [ ] **Step 5: Write the manifest**

Create `static/manifest.json`:

```json
{
  "name": "Zucoloto's Vinyl Collection",
  "short_name": "Vinyl",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#0c0c0c",
  "theme_color": "#0c0c0c",
  "icons": [
    {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"}
  ]
}
```

- [ ] **Step 6: Update the head**

Replace `templates/index.html:5`:

```html
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
```

Insert immediately after `templates/index.html:7` (the existing favicon link):

```html
<!-- Without an apple-touch-icon iOS invents a tile from the page, which in
     practice is the first letter of the title — the Z of "Zucoloto's". The
     PNG is flat with square corners on the app's own ground: iOS applies the
     squircle mask itself and composites any alpha onto black.
     Anyone who already added the app keeps the old tile until they remove and
     re-add the shortcut; iOS caches it at install time. -->
<link rel="apple-touch-icon" href="/static/icon-180.png">
<link rel="manifest" href="/static/manifest.json">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<!-- black-translucent puts the status bar over the page, which is why the
     viewport opts into the safe area above and .modal-foot pays the bottom
     inset back below. -->
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<!-- The tile caption truncates near 12 characters; "Zucoloto's Vin…" is worse
     than a short true name. -->
<meta name="apple-mobile-web-app-title" content="Vinyl">
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/test_icons.py -v`
Expected: PASS, 8 tests (3 parametrised sizes + 5).

- [ ] **Step 8: Run the whole suite for regressions**

Run: `python -m pytest -q`
Expected: no new failures. `tests/test_boot.py` may skip if npm is unavailable — that is the designed behaviour, not a failure.

- [ ] **Step 9: Commit**

```bash
git add tools/make_icons.py static/icon-180.png static/icon-192.png \
        static/icon-512.png static/manifest.json templates/index.html tests/test_icons.py
git commit -m "feat: a real home-screen icon instead of the letter Z

No apple-touch-icon was declared, so iOS generated a tile from the page — the
first letter of the title. The mark already existed as static/vinyl-icon.svg;
it is rendered onto the app's own #0c0c0c ground at three sizes, because iOS
composites alpha onto black and masks the squircle itself.

Also declares the app standalone. black-translucent hands the status bar to
the page, so the viewport opts into viewport-fit=cover in the same change —
the safe-area padding that pays for it follows.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: Safe areas and the keyboard

The biggest felt improvement for the least structural change, and independent of everything below. Depends on Task 1 only for `viewport-fit=cover`.

**Files:**
- Modify: `templates/index.html` — new CSS inside the `@media(max-width:760px)` block at `:2320`; new JS near the other boot-time listeners
- Test: `tests/test_boot.js` (harness fix + one assertion), `tests/test_icons.py` (one CSS assertion)

**Interfaces:**
- Consumes: `viewport-fit=cover` from Task 1.
- Produces: `syncViewportHeight()`, the `--vvh` custom property on `document.documentElement`, and the `focusin` handler. Task 3 consumes `isPhone()`, which is introduced here.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_icons.py`:

```python
def test_the_form_pays_back_the_safe_area_insets():
    """viewport-fit=cover lets the page paint edge to edge, which makes the
    overlay responsible for keeping its own chrome clear of the notch and the
    home indicator."""
    html = app_module.app.test_client().get("/").get_data(as_text=True)
    assert "env(safe-area-inset-top" in html
    assert "env(safe-area-inset-bottom" in html


def test_the_overlay_is_sized_from_the_visual_viewport():
    """iOS does not resize the layout viewport for the keyboard, so a
    bottom-pinned action bar ends up behind it."""
    html = app_module.app.test_client().get("/").get_data(as_text=True)
    assert "visualViewport" in html
    assert "--vvh" in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_icons.py -v -k "safe_area or visual_viewport"`
Expected: FAIL — neither string is in the template yet.

- [ ] **Step 3: Add the CSS**

Inside the `@media(max-width:760px)` block at `templates/index.html:2320`, after the `#formOverlay .modal.modal-wide` rule:

```css
  /* The keyboard does not shrink the layout viewport on iOS, so a footer
     pinned to the bottom of a 100%-tall box ends up behind it — Back, Next
     and Save simply gone until the field is dismissed. --vvh is the visual
     viewport's height, written by syncViewportHeight(); the fallback keeps
     the box full-height everywhere the property is never set. */
  #formOverlay .modal.modal-wide{
    height:var(--vvh,100%);
    padding-top:env(safe-area-inset-top,0px);
  }
  /* viewport-fit=cover paints under the home indicator, so the footer buys
     its own clearance back. */
  #formOverlay .modal-foot{padding-bottom:calc(11px + env(safe-area-inset-bottom,0px))}
```

The existing `#formOverlay .modal.modal-wide` rule at `:2322` sets `height:100%`; replace that declaration rather than adding a second one, so there is one source for the height.

- [ ] **Step 4: Add the JS**

Add near the other boot-time listeners, before `init()` runs:

```js
/* ── the phone breakpoint, in one place ────────────────────────────────────
 * 760px is the media query the form's mobile rules already use. Reading it
 * through matchMedia rather than off innerWidth means an iPad rotating into
 * range gets the phone layout without a reload. */
const phoneMQ = window.matchMedia('(max-width:760px)');
function isPhone(){ return !!(phoneMQ && phoneMQ.matches); }

/* iOS leaves the layout viewport at full height when the keyboard opens, so
 * a bottom-pinned bar ends up behind it. visualViewport reports what is
 * actually on screen; writing it to a custom property keeps the CSS
 * declarative. `scroll` matters as much as `resize`: iOS scrolls the visual
 * viewport to lift a focused field clear of the keyboard, and the overlay has
 * to follow it. */
function syncViewportHeight(){
  const vv = window.visualViewport;
  if (!vv) return;                       // desktop, and jsdom
  document.documentElement.style.setProperty('--vvh', vv.height + 'px');
}
if (window.visualViewport){
  ['resize','scroll'].forEach(e => window.visualViewport.addEventListener(e, syncViewportHeight));
  syncViewportHeight();
}

/* A field focused behind the keyboard has to be scrolled clear, and the
 * scroll has to wait for the keyboard's animation: issued during it, the
 * scroll is measured against the pre-keyboard viewport and undoes itself. */
document.addEventListener('focusin', e => {
  if (!isPhone() || !e.target.closest) return;
  const f = e.target.closest('#formOverlay input,#formOverlay textarea,#formOverlay select');
  if (!f) return;
  setTimeout(() => f.scrollIntoView({block:'center', behavior:'smooth'}), 300);
});
```

- [ ] **Step 5: Fix the boot harness's matchMedia stub**

`tests/test_boot.js` stubs `matchMedia` with only `addListener`/`removeListener` and a hardcoded `matches:false`. `isPhone()` is built on it, and Task 3 needs a test to turn phone mode on. Replace the line at `tests/test_boot.js` reading `win.matchMedia = win.matchMedia || (q => ...)` with:

```js
  /* The app reads the phone breakpoint through matchMedia, so the stub has to
   * be steerable: boot({phone:true}) makes (max-width:760px) match. Both
   * listener spellings are answered — the app feature-detects, and asserting
   * on a stub that only has the old one would hide a break in that detection. */
  const mqls = [];
  win.matchMedia = q => {
    const mql = {
      media: q,
      matches: PHONE && /max-width:\s*760px/.test(q),
      addEventListener(_t, fn){ this._fn = fn; },
      removeEventListener(){ this._fn = null; },
      addListener(fn){ this._fn = fn; },
      removeListener(){ this._fn = null; },
    };
    mqls.push(mql);
    return mql;
  };
  win.__setPhone = on => {                      // drive a breakpoint change
    for (const m of mqls){
      const next = on && /max-width:\s*760px/.test(m.media);
      if (next !== m.matches){ m.matches = next; if (m._fn) m._fn(m); }
    }
  };
```

`PHONE` comes from `boot()`'s options. Change `boot()`'s signature from `boot(hash)` to `boot(hash, opts)` and add near the top of the function:

```js
  const PHONE = !!(opts && opts.phone);
```

Every existing call site passes only `hash`, so `opts` is `undefined` and `PHONE` is `false` — the current behaviour exactly.

- [ ] **Step 6: Add a boot assertion**

Add to `tests/test_boot.js`:

```js
test('the page boots on a phone without throwing', async () => {
  const { errors } = await boot('', { phone: true });
  assert.deepStrictEqual(errors, []);
});

test('isPhone follows the breakpoint', async () => {
  const { win } = await boot('');
  assert.strictEqual(win.isPhone(), false);
  win.__setPhone(true);
  assert.strictEqual(win.isPhone(), true);
});
```

If `boot()` does not already return `win`, add it to the returned object. Check what it returns before writing this — the existing tests show the shape.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/test_icons.py tests/test_boot.py -v`
Expected: PASS. `test_boot.py` skips without npm — if it skips, note it and move on rather than trying to force an install.

- [ ] **Step 8: Run the whole suite**

Run: `python -m pytest -q`
Expected: no new failures.

- [ ] **Step 9: Commit**

```bash
git add templates/index.html tests/test_boot.js tests/test_icons.py
git commit -m "fix: keep the form's action bar above the iOS keyboard

The footer is sticky to the bottom of a 100%-tall flex column. iOS does not
shrink the layout viewport when the keyboard opens, so that bottom is behind
the keyboard and Back/Next/Save are unreachable until the field is dismissed.

Sizes the overlay from visualViewport.height instead, via a --vvh custom
property so the CSS stays declarative, and scrolls the focused field clear
after the keyboard's animation rather than during it. Also pays back the
safe-area insets that viewport-fit=cover just took on.

Introduces isPhone() as the one reader of the 760px breakpoint, and makes the
boot harness's matchMedia stub steerable so it can be tested.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: `static/phoneform.js` — the pure rules

No UI. Everything decidable is extracted and tested here first, so Tasks 4–8 are wiring rather than logic.

**Files:**
- Create: `static/phoneform.js`, `tests/test_phoneform.js`, `tests/test_phoneform.py`
- Modify: `templates/index.html` — one `<script src>` beside the others at `:3615-3631`

**Interfaces:**
- Consumes: nothing. Pure module, no DOM, no globals.
- Produces: `VinylPhoneForm` with exactly these members, used by Tasks 4–8:
  - `STEPS` — array of `{n, phone}` for `n` 1..4
  - `railStates(current)` → array of 4 strings, each `'done' | 'now' | 'ahead'`
  - `rankPlaces(records, current, limit=4)` → array of place-name strings
  - `logSectionOpen(entries)` → boolean
  - `logCount(entries)` → string
  - `recordPreview(v)` / `purchasePreview(v)` / `logPreview(v)` / `objectPreview(v)` → string, each taking one plain object of field values
  - `dragDismisses(dy, dt)` → boolean

- [ ] **Step 1: Write the failing test**

Create `tests/test_phoneform.js`:

```js
// The phone form's decidable rules, tested without a DOM.
// Run by tests/test_phoneform.py so `pytest` stays the single command.
//
// Everything here is a pure function on purpose. The phone redraw is mostly
// wiring, and wiring is what test_boot.js is for; these are the parts that
// have an answer worth pinning — which rail segment is which, what a section
// row says about a record, and whether a drag was a dismissal or a scroll.

const test = require('node:test');
const assert = require('node:assert');

const {
  STEPS, railStates, rankPlaces, logSectionOpen, logCount,
  recordPreview, purchasePreview, logPreview, objectPreview, dragDismisses,
} = require('../static/phoneform.js');

// ── the rail ────────────────────────────────────────────────────────────────

test('the rail has one segment per step', () => {
  assert.strictEqual(railStates(1).length, 4);
  assert.strictEqual(STEPS.length, 4);
});

test('steps before the current one are done, the current one is now', () => {
  assert.deepStrictEqual(railStates(3), ['done', 'done', 'now', 'ahead']);
});

test('on the first step nothing is done yet', () => {
  assert.deepStrictEqual(railStates(1), ['now', 'ahead', 'ahead', 'ahead']);
});

test('on the last step nothing is ahead', () => {
  assert.deepStrictEqual(railStates(4), ['done', 'done', 'done', 'now']);
});

test('the phone step names match the sections the form already uses', () => {
  assert.deepStrictEqual(STEPS.map(s => s.phone),
    ['The record', 'The purchase', 'The log', 'The object']);
});

// ── place chips ─────────────────────────────────────────────────────────────
// Safari draws a <datalist> as a strip under the keyboard, so the phone offers
// the places you actually use as chips instead. Ranked by how often they were
// used, not alphabetically the way the datalist is.

const recs = n => Array.from({length: n}, () => ({}));
function at(place, n) { return recs(n).map(() => ({bought_where: place})); }

test('places rank by how often they were used', () => {
  const records = [...at('Tracks', 5), ...at('Amazon', 2), ...at('Baratos', 9)];
  assert.deepStrictEqual(rankPlaces(records, ''), ['Baratos', 'Tracks', 'Amazon']);
});

test('the ranking stops at the limit', () => {
  const records = [...at('A', 5), ...at('B', 4), ...at('C', 3), ...at('D', 2), ...at('E', 1)];
  assert.deepStrictEqual(rankPlaces(records, '', 4), ['A', 'B', 'C', 'D']);
});

test('the current value is pinned first even when it is rare', () => {
  const records = [...at('A', 9), ...at('B', 8), ...at('C', 7), ...at('D', 6), ...at('Rare', 1)];
  assert.deepStrictEqual(rankPlaces(records, 'Rare', 4), ['Rare', 'A', 'B', 'C']);
});

test('a current value already in the top four is not duplicated', () => {
  const records = [...at('A', 9), ...at('B', 8)];
  assert.deepStrictEqual(rankPlaces(records, 'B', 4), ['B', 'A']);
});

test('blank places are not offered', () => {
  const records = [...at('', 9), ...at('A', 1), {bought_where: null}];
  assert.deepStrictEqual(rankPlaces(records, ''), ['A']);
});

test('a place is matched after trimming, so a stray space is not a second chip', () => {
  const records = [{bought_where: 'Tracks'}, {bought_where: ' Tracks '}];
  assert.deepStrictEqual(rankPlaces(records, ''), ['Tracks']);
});

// ── collapsed log sections ──────────────────────────────────────────────────

test('an empty section starts collapsed', () => {
  assert.strictEqual(logSectionOpen([]), false);
});

test('a section with entries starts open, so the collapse only ever hides nothing', () => {
  assert.strictEqual(logSectionOpen(['2026-08-20T20:00:00']), true);
});

test('a missing list is treated as empty rather than throwing', () => {
  assert.strictEqual(logSectionOpen(undefined), false);
});

test('an empty section counts as none, not zero', () => {
  assert.strictEqual(logCount([]), 'none');
});

test('a filled section counts its entries', () => {
  assert.strictEqual(logCount(['a', 'b', 'c']), '3');
});

// ── edit-root previews ──────────────────────────────────────────────────────
// Each row says what it already holds, so you can see whether the thing you
// came to change is right without opening anything.

test('the record row reads artist, year and country', () => {
  assert.strictEqual(
    recordPreview({artist: 'Tim Maia', year: '1975', country: 'Brazil'}),
    'Tim Maia · 1975 · Brazil');
});

test('the record row omits the parts that are blank', () => {
  assert.strictEqual(recordPreview({artist: 'Tim Maia', year: '', country: ''}), 'Tim Maia');
});

test('the purchase row reads place, date and condition', () => {
  assert.strictEqual(
    purchasePreview({haveIt: true, where: 'Tracks', date: '2026-09-12', condition: 'used'}),
    'Tracks · 12 Sep 2026 · used');
});

test('a wishlist record says so instead of showing a purchase it never had', () => {
  assert.strictEqual(purchasePreview({haveIt: false, where: '', date: '', condition: ''}),
                     'Wishlist');
});

test('an owned record with nothing filled in says so', () => {
  assert.strictEqual(purchasePreview({haveIt: true, where: '', date: '', condition: ''}),
                     'nothing recorded');
});

test('the log row reads both ratings and both counts', () => {
  assert.strictEqual(
    logPreview({myRating: 5, wifeRating: 7, plays: 3, notes: 1}),
    'Pepe 5 · Jenni 7 · 3 plays · 1 note');
});

test('the log row omits the zero parts', () => {
  assert.strictEqual(logPreview({myRating: 0, wifeRating: 7, plays: 1, notes: 0}),
                     'Jenni 7 · 1 play');
});

test('a wholly unlogged record says nothing is logged', () => {
  assert.strictEqual(logPreview({myRating: 0, wifeRating: 0, plays: 0, notes: 0}),
                     'nothing logged');
});

test('the object row reads size, discs and tracks', () => {
  assert.strictEqual(objectPreview({size: '12"', discs: 1, tracks: 11, painted: false}),
                     '12" · 1 disc · 11 tracks');
});

test('the object row pluralises discs', () => {
  assert.strictEqual(objectPreview({size: '12"', discs: 2, tracks: 20, painted: false}),
                     '12" · 2 discs · 20 tracks');
});

test('a painted record says so, since that is the part you would come back for', () => {
  assert.strictEqual(objectPreview({size: '7"', discs: 1, tracks: 2, painted: true}),
                     '7" · 1 disc · 2 tracks · painted');
});

test('an empty tracklist is left out rather than reported as zero', () => {
  assert.strictEqual(objectPreview({size: '12"', discs: 1, tracks: 0, painted: false}),
                     '12" · 1 disc');
});

// ── drag to dismiss ─────────────────────────────────────────────────────────
// Bound to the nav area only, never the scrolling body — but it still has to
// tell a dismissal from a stray touch.

test('a long drag dismisses', () => {
  assert.strictEqual(dragDismisses(100, 400), true);
});

test('a short slow drag does not', () => {
  assert.strictEqual(dragDismisses(30, 400), false);
});

test('a short fast flick dismisses on velocity alone', () => {
  assert.strictEqual(dragDismisses(40, 50), true);       // 0.8 px/ms
});

test('an upward drag never dismisses', () => {
  assert.strictEqual(dragDismisses(-200, 100), false);
});

test('a zero-duration drag does not divide by zero', () => {
  assert.strictEqual(dragDismisses(10, 0), false);
});
```

- [ ] **Step 2: Write the test runner**

Create `tests/test_phoneform.py`:

```python
"""Run the phone form's rules under pytest.

Mirrors tests/test_draft.py: the rules are pure functions in
static/phoneform.js, so they need a JS runtime, and shelling out to node's
test runner keeps `pytest` as the one command.
"""

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_phoneform_js():
    result = subprocess.run(
        ["node", "--test", "tests/test_phoneform.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python -m pytest tests/test_phoneform.py -v`
Expected: FAIL — `Cannot find module '../static/phoneform.js'`.

- [ ] **Step 4: Write the module**

Create `static/phoneform.js`:

```js
/* The add/edit form's phone rules.
 *
 * The phone redraw is mostly wiring — moving the save button, swapping a
 * datalist for chips, collapsing sections that are empty. This file holds the
 * part of it that has an answer worth pinning down and testing on its own:
 * which rail segment is which, how the places are ranked, what each section
 * row says about the record behind it, and whether a drag was a dismissal.
 *
 * Nothing here touches the DOM or reads a global. Loaded as a plain script in
 * the browser, where `const VinylPhoneForm` lands in the global lexical scope
 * for the inline script below it; required as a module by the tests.
 */
const VinylPhoneForm = (() => {

  /* The phone's names for the four steps. The desktop spine keeps its verbs
   * (Identify / Acquire / Log / Tracklist); these are the section headers the
   * form already uses inside the steps, so the rail label and the content the
   * user is looking at agree. */
  const STEPS = [
    { n: 1, phone: 'The record' },
    { n: 2, phone: 'The purchase' },
    { n: 3, phone: 'The log' },
    { n: 4, phone: 'The object' },
  ];

  function railStates(current) {
    return STEPS.map(s => s.n < current ? 'done' : s.n === current ? 'now' : 'ahead');
  }

  /* Safari renders a <datalist> as a thin strip under the keyboard, which is
   * unusable one-handed. The phone offers chips instead — and ranks them by
   * how often the place was actually used, where the datalist is alphabetical.
   * The record's own value is pinned first whatever its rank, because the one
   * place guaranteed to be relevant is the one already on the record. */
  function rankPlaces(records, current, limit = 4) {
    const counts = new Map();
    for (const r of (records || [])) {
      const name = String((r && r.bought_where) || '').trim();
      if (!name) continue;
      counts.set(name, (counts.get(name) || 0) + 1);
    }
    const pinned = String(current || '').trim();
    const ranked = [...counts.entries()]
      // count descending, then name, so a tie is stable rather than
      // insertion-ordered — two places used once each should not swap
      // position because a record was edited.
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([name]) => name)
      .filter(name => name !== pinned);
    return (pinned ? [pinned, ...ranked] : ranked).slice(0, limit);
  }

  /* Collapsed only when there is nothing to hide. Every edit of a played
   * record opens its play list already expanded, so the collapse never costs
   * a tap to reach something that exists. */
  function logSectionOpen(entries) { return !!(entries && entries.length); }

  /* "none" rather than "0": the row is answering "anything to log yet?", and
   * a zero reads like a value that was measured. */
  function logCount(entries) {
    const n = (entries && entries.length) || 0;
    return n ? String(n) : 'none';
  }

  // ── section previews ──────────────────────────────────────────────────────
  // Each row says what it holds so you can see whether the thing you came to
  // change is already right without opening it.

  const join = parts => parts.filter(Boolean).join(' · ');
  const plural = (n, one) => `${n} ${one}${n === 1 ? '' : 's'}`;

  const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

  /* An ISO day as "12 Sep 2026". Parsed by hand rather than through Date:
   * `new Date('2026-09-12')` is UTC midnight, which in São Paulo is the 11th. */
  function shortDate(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
    if (!m) return '';
    return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}`;
  }

  function recordPreview(v) {
    return join([v.artist, v.year, v.country]) || 'not identified';
  }

  function purchasePreview(v) {
    if (!v.haveIt) return 'Wishlist';
    return join([v.where, shortDate(v.date), v.condition]) || 'nothing recorded';
  }

  function logPreview(v) {
    return join([
      v.myRating ? `Pepe ${v.myRating}` : '',
      v.wifeRating ? `Jenni ${v.wifeRating}` : '',
      v.plays ? plural(v.plays, 'play') : '',
      v.notes ? plural(v.notes, 'note') : '',
    ]) || 'nothing logged';
  }

  function objectPreview(v) {
    return join([
      v.size,
      v.discs ? plural(v.discs, 'disc') : '',
      v.tracks ? plural(v.tracks, 'track') : '',
      v.painted ? 'painted' : '',
    ]) || 'nothing set';
  }

  /* Drag to dismiss, bound to the nav area only so it can never fight the
   * body's scroll. Two ways to qualify: far enough, or fast enough. Without
   * the velocity arm a deliberate flick that only travels 40px springs back,
   * which reads as the gesture not working. */
  const DRAG_DISTANCE = 80;     // px
  const DRAG_VELOCITY = 0.5;    // px/ms

  function dragDismisses(dy, dt) {
    if (dy <= 0) return false;                       // upward is not a dismissal
    if (dy >= DRAG_DISTANCE) return true;
    return dt > 0 && (dy / dt) >= DRAG_VELOCITY;
  }

  return {
    STEPS, railStates, rankPlaces, logSectionOpen, logCount,
    recordPreview, purchasePreview, logPreview, objectPreview,
    shortDate, dragDismisses,
    DRAG_DISTANCE, DRAG_VELOCITY,
  };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VinylPhoneForm;
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_phoneform.py -v`
Expected: PASS.

If `rankPlaces` tie-breaking fails, check the test `places rank by how often they were used` — `Baratos` (9) then `Tracks` (5) then `Amazon` (2) is strict count order with no tie, so a failure there is a real bug in the sort, not the tie-break.

- [ ] **Step 6: Load the module in the page**

Add to `templates/index.html`, after the `<script src="/static/draft.js"></script>` line at `:3622`:

```html
<script src="/static/phoneform.js"></script>
```

- [ ] **Step 7: Run the whole suite**

Run: `python -m pytest -q`
Expected: no new failures. `test_boot.js` inlines `/static/*.js` by pattern, so the new module is picked up with no harness change.

- [ ] **Step 8: Commit**

```bash
git add static/phoneform.js tests/test_phoneform.js tests/test_phoneform.py templates/index.html
git commit -m "feat: extract the phone form's rules into static/phoneform.js

The redraw is mostly wiring, and wiring belongs in test_boot.js. These are the
parts with an answer worth pinning on their own: rail segment states, place
ranking, the four section previews, and the drag-dismiss threshold.

Pure functions, no DOM, dual-exported the way static/draft.js is, so they are
testable under node --test without jsdom — which this project installs into a
scratch dir and skips when it cannot.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: The nav bar, the rail and the footer

The first task that touches `setFormStep`. Desktop parity is the thing to watch.

**Files:**
- Modify: `templates/index.html` — `FORM_STEPS` at `:6935`, `setFormStep` at `:6944`, the modal head at `:2991-2995`, the modal foot at `:3313-3320`, CSS in the `:2320` block
- Test: `tests/test_boot.js`

**Interfaces:**
- Consumes: `isPhone()` (Task 2); `VinylPhoneForm.STEPS`, `.railStates` (Task 3).
- Produces: `rebuildFormChrome()` — re-renders head, spine/rail and foot for the current mode and `formStep`. Called by `setFormStep` and by `onBreakpointChange`. Tasks 5–8 call it after changing `formEditRoot`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_boot.js`:

```js
test('desktop keeps the four-step spine', async () => {
  const { win } = await boot('');
  win.openAdd();
  const steps = win.document.querySelectorAll('#formSpine .fstep');
  assert.strictEqual(steps.length, 4);
  assert.match(steps[0].textContent, /Identify/);
  assert.strictEqual(win.document.querySelectorAll('#formRail .rail-seg').length, 0);
});

test('the phone gets a rail instead of the spine', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  assert.strictEqual(win.document.querySelectorAll('#formSpine .fstep').length, 0);
  assert.strictEqual(win.document.querySelectorAll('#formRail .rail-seg').length, 4);
});

test('the rail marks the steps behind the current one done', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  win.setFormStep(3);
  const cls = [...win.document.querySelectorAll('#formRail .rail-seg')]
    .map(s => s.className.replace('rail-seg', '').trim());
  assert.deepStrictEqual(cls, ['done', 'done', 'now', 'ahead']);
});

test('the rail names the step the phone is on', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  win.setFormStep(2);
  assert.match(win.document.getElementById('formRailLabel').textContent, /The purchase/);
  assert.match(win.document.getElementById('formRailCount').textContent, /2\s*\/\s*4/);
});

test('rail segments are not reachable by a thumb or a tab', async () => {
  // A 3px strip is not a touch target; Back and the rail label carry navigation.
  const { win } = await boot('', { phone: true });
  win.openAdd();
  for (const seg of win.document.querySelectorAll('#formRail .rail-seg')) {
    assert.strictEqual(seg.tagName, 'I');
    assert.strictEqual(seg.getAttribute('onclick'), null);
    assert.strictEqual(seg.getAttribute('tabindex'), null);
  }
});

test('the save button exists exactly once in both modes', async () => {
  for (const phone of [false, true]) {
    const { win } = await boot('', { phone });
    win.openAdd();
    assert.strictEqual(win.document.querySelectorAll('#formSaveBtn').length, 1,
      `#formSaveBtn duplicated on ${phone ? 'phone' : 'desktop'}`);
  }
});

test('the phone moves save into the nav bar', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  assert.ok(win.document.querySelector('.modal-head #formSaveBtn'),
            'save should live in the nav bar on a phone');
});

test('the wishlist relabel still finds the button after the move', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  win.setHaveIt(false);
  assert.match(win.document.getElementById('formSaveBtn').textContent, /wishlist/i);
});

test('a breakpoint change while the form is open swaps the chrome', async () => {
  const { win } = await boot('');
  win.openAdd();
  assert.strictEqual(win.document.querySelectorAll('#formSpine .fstep').length, 4);
  win.__setPhone(true);
  assert.strictEqual(win.document.querySelectorAll('#formRail .rail-seg').length, 4);
  assert.strictEqual(win.document.querySelectorAll('#formSpine .fstep').length, 0);
});

test('the last step turns the next button into the save action', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  win.setFormStep(4);
  const next = win.document.getElementById('formNextBtn');
  assert.strictEqual(next.disabled, false);
  assert.match(next.textContent, /save/i);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_boot.py -v`
Expected: FAIL — `#formRail` does not exist.

- [ ] **Step 3: Add the markup**

In `templates/index.html`, replace the modal head at `:2991-2995` with:

```html
    <div class="modal-head">
      <button class="btn btn-ghost btn-sm head-cancel" id="formHeadCancel"
              onclick="closeForm()"><i class="ti ti-x"></i></button>
      <span class="modal-title" id="formTitle">add record</span>
      <!-- Moved here by rebuildFormChrome on a phone, and back to the foot on
           desktop. One element, never two: syncSaveLabel and the wishlist
           relabel both address it by id. -->
      <span class="head-save-slot" id="formHeadSaveSlot"></span>
    </div>
    <!-- the phone's rail; empty and hidden on desktop -->
    <div class="form-rail" id="formRail" hidden></div>
    <div class="form-rail-label" id="formRailLabelRow" hidden>
      <b id="formRailLabel"></b>
      <span id="formRailCount"></span>
    </div>
```

Keep `.form-spine` exactly where it is at `:3020`.

Add a slot in the foot for the save button to return to, replacing `templates/index.html:3318`:

```html
      <span class="foot-save-slot" id="formFootSaveSlot">
        <button class="btn btn-primary" id="formSaveBtn">save</button>
      </span>
```

- [ ] **Step 4: Add `rebuildFormChrome` and rewire `setFormStep`**

Replace the spine-rendering block inside `setFormStep` (`templates/index.html:6960-6967`) with a call, and add the function below it:

```js
/* One renderer for both modes, called by setFormStep and by a breakpoint
 * change. Two layouts kept in step by a branch rather than by discipline:
 * the desktop half renders exactly what setFormStep rendered before. */
function rebuildFormChrome(){
  const phone  = isPhone();
  const spine  = document.getElementById('formSpine');
  const rail   = document.getElementById('formRail');
  const railRow= document.getElementById('formRailLabelRow');
  const save   = document.getElementById('formSaveBtn');

  spine.hidden = phone;
  rail.hidden = railRow.hidden = !phone;

  if (phone){
    spine.innerHTML = '';
    rail.innerHTML = VinylPhoneForm.railStates(formStep)
      .map(state => `<i class="rail-seg ${state}"></i>`).join('');
    document.getElementById('formRailLabel').textContent =
      VinylPhoneForm.STEPS[formStep - 1].phone;
    document.getElementById('formRailCount').textContent = `${formStep} / ${FORM_STEPS.length}`;
    document.getElementById('formHeadSaveSlot').appendChild(save);
  } else {
    rail.innerHTML = '';
    spine.innerHTML = FORM_STEPS.map(st => `
      <button type="button" class="fstep${st.n === formStep ? ' on' : ''}${st.n < formStep ? ' done' : ''}"
              onclick="setFormStep(${st.n})">
        <span class="fstep-n">${st.n < formStep ? '<i class="ti ti-check"></i>' : st.n}</span>
        <span class="fstep-t"><b>${st.label}</b><small>${st.sub}</small></span>
      </button>`).join('');
    document.getElementById('formFootSaveSlot').appendChild(save);
  }

  /* On the last step there is nowhere to advance to. Today the next button
   * simply greys out, which leaves a dead control in the footer's main slot;
   * it becomes the wizard's terminal action instead. The nav bar's save is
   * still the one that is live from step one. */
  const next = document.getElementById('formNextBtn');
  const last = formStep === FORM_STEPS.length;
  next.disabled = false;
  next.innerHTML = last
    ? '<i class="ti ti-check"></i> save record'
    : 'next <i class="ti ti-arrow-right"></i>';
  next.onclick = last ? submitForm : () => setFormStep(formStep + 1);
  document.getElementById('formBackBtn').disabled = formStep === 1;
}
```

Remove the two lines in `setFormStep` that set `formBackBtn.disabled` and `formNextBtn.disabled` (`:6955-6956`) — `rebuildFormChrome` owns both now. Replace them and the spine block with a single `rebuildFormChrome();` call placed before `resetFormScroll()`.

Also remove the inline `onclick="setFormStep(formStep + 1)"` from the `#formNextBtn` markup at `templates/index.html:3317`, since `rebuildFormChrome` assigns `onclick` — leaving both means the inline handler fires too and the last step both saves and advances.

- [ ] **Step 5: Guard the two step lists against drifting**

`FORM_STEPS` (in the template, at `:6935`) is **not** changed — it keeps `label` and `sub` for the desktop spine. The phone names live in `VinylPhoneForm.STEPS`, and `rebuildFormChrome` reads them from there.

That leaves two lists that must stay the same length: `rebuildFormChrome` indexes `VinylPhoneForm.STEPS[formStep - 1]` using a step number bounded by `FORM_STEPS.length`. Add to `tests/test_boot.js`:

```js
test('the two step lists agree on how many steps there are', async () => {
  // rebuildFormChrome indexes VinylPhoneForm.STEPS by a step number that
  // setFormStep clamps to FORM_STEPS.length. A fifth step added to one list
  // and not the other reads undefined.phone and throws.
  const { win } = await boot('');
  assert.strictEqual(win.FORM_STEPS.length, win.VinylPhoneForm.STEPS.length);
});
```

- [ ] **Step 6: Add the CSS**

Inside the `@media(max-width:760px)` block at `templates/index.html:2320`:

```css
  /* nav bar: cancel · title · save. The × became a word because on a phone
     the head is the only place the two verbs can both sit, and an icon next
     to a text button reads as a lesser action than it is. */
  #formOverlay .modal-head{display:flex;align-items:center;gap:10px;padding:10px 14px 11px}
  #formOverlay .modal-title{flex:1;text-align:center;font-family:var(--font-mono);
    font-size:12.5px;letter-spacing:.08em;text-transform:uppercase}
  #formOverlay .head-cancel{order:-1}
  #formOverlay #formSaveBtn{height:auto;padding:4px 2px;background:none;border:none;
    color:var(--accent);font-weight:700;font-size:15px}
  /* the rail — a progress readout, not a control: four segments at 3px are
     not a touch target, so navigation stays with Back and the label */
  #formOverlay .form-rail{display:flex;gap:5px;padding:0 14px 10px}
  #formOverlay .form-rail .rail-seg{flex:1;height:3px;border-radius:2px;
    background:var(--border);display:block}
  #formOverlay .form-rail .rail-seg.done{background:var(--ev-played)}
  #formOverlay .form-rail .rail-seg.now{background:var(--accent)}
  #formOverlay .form-rail-label{display:flex;align-items:baseline;justify-content:space-between;
    padding:0 14px 12px}
  #formOverlay .form-rail-label b{font-size:18px;font-weight:700;letter-spacing:-.02em}
  #formOverlay .form-rail-label span{font-family:var(--font-mono);font-size:11px;
    color:var(--muted);letter-spacing:.06em}
  /* back shrinks to its icon so next keeps the width its role deserves */
  #formOverlay .modal-foot #formBackBtn{flex:0 0 62px}
  #formOverlay .modal-foot .btn.hidden-phone{display:none}
  /* the draft flag moves off the footer, onto the rail line */
  #formOverlay .draft-flag{position:absolute;right:14px;margin:0}
```

Hide the foot's duplicate cancel on the phone by adding `hidden-phone` to its class in the markup at `templates/index.html:3315`:

```html
      <button class="btn hidden-phone" onclick="closeForm()">cancel</button>
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/test_boot.py -v`
Expected: PASS.

- [ ] **Step 8: Run the whole suite**

Run: `python -m pytest -q`
Expected: no new failures. Watch `tests/test_draft.js` and `tests/test_queue.js` especially — both drive the form.

- [ ] **Step 9: Commit**

```bash
git add templates/index.html tests/test_boot.js
git commit -m "feat: a nav bar and a progress rail for the form on a phone

The four-across spine squeezes four labelled buttons into a phone's width and
hides their captions under 560px, and the footer gives four equal buttons to
two actions that matter — because cancel and save are already in reach.

Phone: cancel · title · save in the head, a four-segment rail plus the step
name below it, and a footer of back-as-an-icon plus one full-width primary.
On the last step the next button becomes the save action rather than greying
out. Save is moved, never duplicated, so syncSaveLabel keeps addressing one
element.

Desktop renders exactly what it rendered before; rebuildFormChrome is the one
renderer with a branch, so the two cannot drift.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: Step 1 — the lookup rows and the identity strip

**Files:**
- Modify: `templates/index.html` — the `.form-cover-col` block at `:3024-3100`, CSS in the `:2320` block, `openAdd` at `:6780`
- Test: `tests/test_boot.js`

**Interfaces:**
- Consumes: `isPhone()` (Task 2); `rebuildFormChrome()` (Task 4).
- Produces: `lookupDismissed` (module-level boolean, reset by `openAdd`), `renderStep1Phone()`, `hasIdentity()` → boolean.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_boot.js`:

```js
test('step 1 opens on the three lookups, not on the fields', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  const rows = [...win.document.querySelectorAll('#phoneLookup .frow')];
  assert.strictEqual(rows.length, 3);
  assert.deepStrictEqual(rows.map(r => r.dataset.lookup), ['camera', 'search', 'spotify']);
});

test('each lookup row calls the function that already does that job', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  const called = [];
  for (const fn of ['openCamera', 'openSearchOverlay', 'openSpotifyOverlay']) {
    win[fn] = () => called.push(fn);
  }
  for (const r of win.document.querySelectorAll('#phoneLookup .frow')) r.click();
  assert.deepStrictEqual(called, ['openCamera', 'openSearchOverlay', 'openSpotifyOverlay']);
});

test('filling artist and album replaces the lookups with the identity strip', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  win.document.getElementById('fArtist').value = 'Tim Maia';
  win.document.getElementById('fAlbum').value = 'Racional Vol. 1';
  win.renderStep1Phone();
  assert.strictEqual(win.document.getElementById('phoneLookup').hidden, true);
  assert.strictEqual(win.document.getElementById('phoneIdentity').hidden, false);
  assert.match(win.document.getElementById('phoneIdentity').textContent, /Tim Maia/);
});

test('fill it in myself reveals the fields with no match', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  win.document.getElementById('phoneLookupSkip').click();
  assert.strictEqual(win.document.getElementById('phoneLookup').hidden, true);
  assert.strictEqual(win.document.getElementById('fArtist').closest('.form-section').hidden, false);
});

test('the identity strip follows the fields as they are typed', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  win.document.getElementById('fArtist').value = 'Tim Maia';
  win.document.getElementById('fAlbum').value = 'Racional';
  win.renderStep1Phone();
  win.document.getElementById('fYear').value = '1975';
  win.renderStep1Phone();
  assert.match(win.document.getElementById('phoneIdentity').textContent, /1975/);
});

test('the sensitive-cover checkbox only appears once there is a cover', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  const row = win.document.getElementById('fCensored').closest('.check-row');
  assert.strictEqual(row.hidden, true);
  win.showCover('data:image/png;base64,iVBORw0KGgo=');
  win.renderStep1Phone();
  assert.strictEqual(row.hidden, false);
});

test('opening a fresh record forgets that the last one skipped the lookup', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  win.document.getElementById('phoneLookupSkip').click();
  win.openAdd();
  assert.strictEqual(win.document.getElementById('phoneLookup').hidden, false);
});

test('desktop never renders the lookup rows', async () => {
  const { win } = await boot('');
  win.openAdd();
  assert.strictEqual(win.document.getElementById('phoneLookup').hidden, true);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_boot.py -v`
Expected: FAIL — `#phoneLookup` does not exist.

- [ ] **Step 3: Add the markup**

In `templates/index.html`, immediately inside `<div class="form-step" data-step="1">` and before `<div class="form-layout">` at `:3023`:

```html
        <!-- Every add starts with a lookup — camera, search, or a Spotify
             link — and never with typing. Opening on an empty artist field
             with the three lookups wedged into a 42px row led with the thing
             that is never used first. Phone only; hidden on desktop. -->
        <div class="phone-lookup" id="phoneLookup" hidden>
          <p class="lead">How do you want to find it?
            <small>Whatever you pick fills the fields below. Nothing costs a
                   credit until you tap Analyse.</small></p>
          <button type="button" class="frow hero" data-lookup="camera" onclick="openCamera()">
            <span class="fic"><i class="ti ti-camera"></i></span>
            <span class="ftx"><b>Shoot the sleeve</b><span>Camera, then Analyse</span></span>
            <i class="ti ti-chevron-right chev"></i>
          </button>
          <button type="button" class="frow se" data-lookup="search" onclick="openSearchOverlay()">
            <span class="fic"><i class="ti ti-list-search"></i></span>
            <span class="ftx"><b>Search by name</b><span>Artist or album title</span></span>
            <i class="ti ti-chevron-right chev"></i>
          </button>
          <button type="button" class="frow sp" data-lookup="spotify" onclick="openSpotifyOverlay()">
            <span class="fic"><i class="ti ti-brand-spotify"></i></span>
            <span class="ftx"><b>Paste a Spotify link</b><span>From the share sheet</span></span>
            <i class="ti ti-chevron-right chev"></i>
          </button>
          <div class="orline">or</div>
          <button type="button" class="ghostrow" id="phoneLookupSkip" onclick="skipLookup()">
            <i class="ti ti-pencil"></i> Fill it in myself
          </button>
        </div>

        <!-- what the cover well collapses into once there is something to show -->
        <div class="phone-identity" id="phoneIdentity" hidden></div>
```

Wrap the sensitive-cover checkbox at `:3048-3051` so it can be hidden — it already sits in a `.check-row`; give it an id:

```html
          <div class="check-row" id="censorRow" style="margin-top:10px">
```

- [ ] **Step 4: Add the JS**

```js
/* Set by "Fill it in myself": there is no match and there is not going to be
 * one, so the lookups step aside for the fields. Reset per record by openAdd. */
let lookupDismissed = false;

function hasIdentity(){
  return !!(document.getElementById('fArtist').value.trim()
         || document.getElementById('fAlbum').value.trim()
         || coverDataUri || editingCoverUrl);
}

function skipLookup(){
  lookupDismissed = true;
  renderStep1Phone();
  document.getElementById('fArtist').focus();
}

/* Step 1 has three states on a phone: choose a lookup, or — once anything
 * identifies the record — the identity strip above the fields. The strip
 * holds no state of its own; it re-reads the fields every time, so the scan,
 * the draft restore and plain typing all reach it without knowing it exists. */
function renderStep1Phone(){
  const phone = isPhone();
  const identified = hasIdentity();
  const lookup = document.getElementById('phoneLookup');
  const strip  = document.getElementById('phoneIdentity');
  const layout = document.querySelector('#formOverlay .form-layout');
  const censor = document.getElementById('censorRow');
  const hasCover = !!(coverDataUri || editingCoverUrl);

  if (!phone){
    lookup.hidden = true;
    strip.hidden = true;
    if (layout) layout.hidden = false;
    censor.hidden = false;
    return;
  }

  const showLookup = !identified && !lookupDismissed;
  lookup.hidden = !showLookup;
  if (layout) layout.hidden = showLookup;
  strip.hidden = showLookup || !identified;
  // Meaningless without a cover, and a full row in exactly the state where
  // there is least room for one.
  censor.hidden = !hasCover;

  if (strip.hidden) return;

  const cover = VinylCover.coverPreviewSrc({cover_url: editingCoverUrl}, coverDataUri);
  const line = [document.getElementById('fYear').value,
                document.getElementById('fCountry').value,
                document.getElementById('fGenre').value].filter(Boolean).join(' · ');
  // Re-pick reopens the last scan's results without paying for a new call;
  // with a cover but no scan behind it, Analyse is what belongs here instead.
  const action = scanCandidates.length
    ? `<button type="button" class="repick" onclick="reopenScanOverlay()">Pick a different match</button>`
    : hasCover
      ? `<button type="button" class="repick" onclick="runPendingScan()">Analyse</button>`
      : '';
  strip.innerHTML = `
    <div class="pi-cover">${cover ? `<img src="${esc(cover)}" alt="">` : '<i class="ti ti-photo"></i>'}</div>
    <div class="pi-meta">
      <b>${esc(document.getElementById('fArtist').value) || 'Unknown artist'}</b>
      <i>${esc(document.getElementById('fAlbum').value)}</i>
      ${line ? `<em>${esc(line)}</em>` : ''}
      ${action}
    </div>`;
}
```

Call it from three places:
1. At the end of `rebuildFormChrome()`, so a breakpoint change re-renders it.
2. In `formChanged()`, after `rememberDraft()` — this is what makes the strip follow typing and the scan.
3. In `openAdd()`, after `lookupDismissed = false;`.

Add `lookupDismissed = false;` to `openAdd()` beside the other per-record resets at `:6781`, and to `openEdit()` set `lookupDismissed = true` — an existing record is already identified, and a wishlist entry with no artist yet should still show its fields rather than a lookup.

- [ ] **Step 5: Add the CSS**

Inside the `@media(max-width:760px)` block:

```css
  /* the three ways an add actually starts */
  #formOverlay .phone-lookup{display:flex;flex-direction:column;gap:10px}
  #formOverlay .lead{font-size:16.5px;font-weight:600;letter-spacing:-.015em;margin:2px 0 4px}
  #formOverlay .lead small{display:block;font-size:13px;font-weight:400;color:var(--muted);
    margin-top:4px;letter-spacing:0}
  #formOverlay .frow{display:flex;align-items:center;gap:13px;min-height:66px;padding:12px 14px;
    border:1px solid var(--border);border-radius:13px;background:var(--card);
    color:var(--text);font-family:var(--font);text-align:left;width:100%}
  #formOverlay .frow.hero{border-color:var(--accent);
    background:color-mix(in srgb,var(--accent) 8%,var(--card))}
  #formOverlay .frow .fic{width:40px;height:40px;border-radius:11px;flex-shrink:0;
    display:flex;align-items:center;justify-content:center;font-size:21px;
    background:color-mix(in srgb,var(--accent) 14%,transparent);color:var(--accent)}
  #formOverlay .frow.sp .fic{background:color-mix(in srgb,#1DB954 14%,transparent);color:#1DB954}
  #formOverlay .frow.se .fic{background:color-mix(in srgb,var(--ev-note) 16%,transparent);
    color:var(--ev-note)}
  #formOverlay .frow .ftx{flex:1;min-width:0}
  #formOverlay .frow .ftx b{display:block;font-size:15.5px;font-weight:700;letter-spacing:-.01em}
  #formOverlay .frow .ftx span{display:block;font-size:12.5px;color:var(--muted);margin-top:1px}
  #formOverlay .frow .chev{color:var(--muted);font-size:17px;flex-shrink:0}
  #formOverlay .orline{display:flex;align-items:center;gap:12px;color:var(--muted);
    font-family:var(--font-mono);font-size:10.5px;letter-spacing:.16em;text-transform:uppercase}
  #formOverlay .orline::before,#formOverlay .orline::after{content:"";flex:1;height:1px;
    background:var(--border)}
  #formOverlay .ghostrow{display:flex;align-items:center;justify-content:center;gap:8px;
    height:46px;border:1px dashed var(--border);border-radius:11px;background:transparent;
    color:var(--label);font-size:14px;font-family:var(--font);width:100%}

  /* the cover well, once it has done its job */
  #formOverlay .phone-identity{display:flex;gap:13px;align-items:flex-start;padding:12px;
    border:1px solid var(--border);border-radius:13px;background:var(--card);margin-bottom:14px}
  #formOverlay .pi-cover{width:84px;height:84px;border-radius:8px;flex-shrink:0;overflow:hidden;
    background:var(--bg);display:flex;align-items:center;justify-content:center;
    color:var(--muted);font-size:24px}
  #formOverlay .pi-cover img{width:100%;height:100%;object-fit:cover;display:block}
  #formOverlay .pi-meta{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px}
  #formOverlay .pi-meta b{font-size:16px;font-weight:700;letter-spacing:-.015em}
  #formOverlay .pi-meta i{font-style:normal;font-size:14px;color:var(--label)}
  #formOverlay .pi-meta em{font-style:normal;font-family:var(--font-mono);font-size:11px;
    color:var(--muted);letter-spacing:.05em;margin-top:2px}
  #formOverlay .repick{align-self:flex-start;margin-top:6px;font-size:12px;color:var(--accent);
    border:1px solid var(--border);border-radius:7px;padding:7px 10px;background:transparent;
    font-family:var(--font)}

  /* the cover well and the scan triplet are what the two above replace */
  #formOverlay .cover-drop,#formOverlay .cover-picker-row,
  #formOverlay .scan-actions,#formOverlay #scanRepickBtn{display:none}
  #formOverlay .form-layout{display:block}
  /* full-width fields at a thumb's size; only year and genre share a row */
  #formOverlay .form-grid{grid-template-columns:1fr}
  #formOverlay .form-grid .form-group.half{grid-column:auto}
  #formOverlay .field input,#formOverlay .field select{height:50px}
```

To get Year and Genre side by side, wrap those two `.form-group`s at `:3120-3130` in a `<div class="two">` and add:

```css
  #formOverlay .two{display:grid;grid-template-columns:1fr 1fr;gap:10px}
```

Give `.two` `display:contents` on desktop so the existing `.form-grid` layout is unchanged:

```css
@media(min-width:761px){ .two{display:contents} }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_boot.py -v`
Expected: PASS.

- [ ] **Step 7: Run the whole suite**

Run: `python -m pytest -q`
Expected: no new failures. `tests/test_cover_form.js` and `tests/test_scan_cover.py` are the ones to watch — both touch the cover well.

- [ ] **Step 8: Commit**

```bash
git add templates/index.html tests/test_boot.js
git commit -m "feat: step 1 opens on the lookup, not on an empty artist field

Every add starts with a lookup — camera, search, or a Spotify link — and never
with typing. Step 1 opened on the 180px cover well followed by the fields,
with the three lookups squeezed three-across into a 42px row underneath: it
led with the thing that is never used first and buried the three that are.

Phone: three 66px rows, and 'fill it in myself' for the case they miss. Once
anything identifies the record the well collapses to an 84px thumb in an
identity strip, which is the ~200px that puts Country above the fold. The
strip re-reads the fields rather than holding state, so the scan and the draft
restore reach it without knowing it exists.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: Steps 2, 3 and 4

**Files:**
- Modify: `templates/index.html` — step 2 at `:3155-3200`, step 3 at `:3202-3272`, step 4 at `:3274-3320`, CSS in the `:2320` block, `populateWhereList` at `:5922`
- Test: `tests/test_boot.js`

**Interfaces:**
- Consumes: `VinylPhoneForm.rankPlaces`, `.logSectionOpen`, `.logCount` (Task 3); `isPhone()` (Task 2).
- Produces: `renderPlaceChips()`, `toggleLogSection(kind)`, `renderLogCollapse()`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_boot.js`:

```js
test('bought at offers the places you actually use, most-used first', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  win.setFormStep(2);
  const chips = [...win.document.querySelectorAll('#wherePhoneChips .chip')].map(c => c.textContent);
  // the fixture has 11 records at "Benedito Calixto" and one at "Amazon"
  assert.strictEqual(chips[0], 'Benedito Calixto');
  assert.ok(chips.includes('Amazon'));
  assert.ok(chips.length <= 4);
});

test('tapping a place chip writes the field', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  win.setFormStep(2);
  win.document.querySelector('#wherePhoneChips .chip').click();
  assert.strictEqual(win.document.getElementById('fWhere').value, 'Benedito Calixto');
});

test('the datalist is still there for desktop', async () => {
  const { win } = await boot('');
  win.openAdd();
  assert.ok(win.document.querySelectorAll('#whereList option').length > 0);
  assert.strictEqual(win.document.getElementById('wherePhoneChips').hidden, true);
});

test('empty log sections start collapsed on a phone', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  win.setFormStep(3);
  assert.strictEqual(win.document.getElementById('playDatesSection').dataset.collapsed, 'true');
  assert.match(win.document.getElementById('playDatesCount').textContent, /none/);
});

test('a section with entries starts open, so the collapse never hides anything', async () => {
  const { win } = await boot('', { phone: true });
  win.openEdit(1);                       // fixture record 1 has a play date
  win.setFormStep(3);
  assert.strictEqual(win.document.getElementById('playDatesSection').dataset.collapsed, 'false');
});

test('the plus on a collapsed section opens it rather than navigating', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  win.setFormStep(3);
  win.document.querySelector('#playDatesSection .log-plus').click();
  assert.strictEqual(win.document.getElementById('playDatesSection').dataset.collapsed, 'false');
});

test('desktop leaves every log section expanded', async () => {
  const { win } = await boot('');
  win.openAdd();
  win.setFormStep(3);
  assert.strictEqual(win.document.getElementById('playDatesSection').dataset.collapsed, 'false');
});

test('size and discs are full width on a phone', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  win.setFormStep(4);
  // the pickers come out of the 2-up grid; each sits in its own full-width row
  const grid = win.document.querySelector('#fSizePick').closest('.form-grid');
  assert.ok(grid.classList.contains('stack-phone'));
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_boot.py -v`
Expected: FAIL — `#wherePhoneChips` does not exist.

- [ ] **Step 3: Add the place chips**

Markup, after the `#whereList` datalist at `templates/index.html:3183`:

```html
                <!-- Safari draws a <datalist> as a thin strip under the
                     keyboard, which is unusable one-handed. The chips are the
                     same places, ranked by use instead of alphabetically. The
                     input still takes anything typed. -->
                <div class="place-chips" id="wherePhoneChips" hidden></div>
```

JS, beside `populateWhereList` at `:5922`:

```js
function renderPlaceChips(){
  const box = document.getElementById('wherePhoneChips');
  box.hidden = !isPhone();
  if (box.hidden) { box.innerHTML = ''; return; }
  const current = document.getElementById('fWhere').value;
  box.innerHTML = VinylPhoneForm.rankPlaces(records, current)
    .map(p => `<button type="button" class="chip${p === current.trim() ? ' on' : ''}"
                       onclick="pickPlace(this.dataset.place)"
                       data-place="${esc(p)}">${esc(p)}</button>`).join('');
}

function pickPlace(name){
  document.getElementById('fWhere').value = name;
  renderPlaceChips();            // move the pick to the front, mark it on
  formChanged();
}
```

Call `renderPlaceChips()` from `rebuildFormChrome()` and from `populateWhereList()`.

- [ ] **Step 4: Add the collapsed log sections**

The three sections already have ids: `#playDatesSection`, `#cleanedDatesSection`, and the notes section at `:3243` which needs one — add `id="notesSection"`.

JS:

```js
/* Plays, cleanings and notes are three open cards with headers, date rows and
 * add buttons — on a step whose own lead says it is almost always empty. On a
 * phone they collapse to one row each, and a section that already has entries
 * opens expanded, so the collapse only ever hides nothing. */
const LOG_SECTIONS = [
  { id: 'playDatesSection',    countId: 'playDatesCount',    entries: () => formPlayDates },
  { id: 'cleanedDatesSection', countId: 'cleanedDatesCount', entries: () => formCleanedDates },
  { id: 'notesSection',        countId: 'notesCount',        entries: () => formNotes },
];

function renderLogCollapse(){
  const phone = isPhone();
  for (const s of LOG_SECTIONS){
    const el = document.getElementById(s.id);
    if (!el) continue;
    const entries = s.entries() || [];
    // Desktop is never collapsed; on a phone, only what is empty.
    const collapsed = phone && !VinylPhoneForm.logSectionOpen(entries);
    el.dataset.collapsed = String(collapsed);
    const count = document.getElementById(s.countId);
    if (count) count.textContent = phone ? VinylPhoneForm.logCount(entries) : count.textContent;
    let plus = el.querySelector('.log-plus');
    if (phone && !plus){
      plus = document.createElement('button');
      plus.type = 'button';
      plus.className = 'log-plus';
      plus.innerHTML = '<i class="ti ti-plus"></i>';
      plus.onclick = () => { el.dataset.collapsed = 'false'; };
      el.querySelector('header').appendChild(plus);
    }
    if (plus) plus.hidden = !phone || !collapsed;
  }
}
```

The notes section has no count element today — add one to its header at `:3244`:

```html
          <header><i class="ti ti-note"></i> Notes <span class="count" id="notesCount">markdown</span></header>
```

Call `renderLogCollapse()` from `rebuildFormChrome()`, and from `renderPlayDatesForm()` / `renderCleanedDatesForm()` / `renderNotesList()` so adding the first entry expands the section it went into.

CSS:

```css
  /* collapsed: the header is the whole row */
  #formOverlay .form-section[data-collapsed="true"] .sec-body{display:none}
  #formOverlay .form-section[data-collapsed="true"] > header{min-height:56px}
  #formOverlay .form-section > header{min-height:48px;font-size:11.5px}
  #formOverlay .log-plus{width:34px;height:34px;border-radius:9px;border:1px solid var(--border);
    background:var(--bg);color:var(--accent);display:flex;align-items:center;justify-content:center;
    margin-left:10px;flex-shrink:0}
  #formOverlay .place-chips{display:flex;gap:7px;flex-wrap:wrap;margin-top:8px}
  #formOverlay .chip{font-size:12.5px;color:var(--label);border:1px solid var(--border);
    border-radius:999px;padding:8px 13px;background:var(--card);font-family:var(--font)}
  #formOverlay .chip.on{color:var(--accent);background:color-mix(in srgb,var(--accent) 10%,transparent);
    border-color:color-mix(in srgb,var(--accent) 45%,var(--border))}
  /* ratings: 14px is a mis-tap between a 6 and a 7 */
  #formOverlay .rating-row .segs button{height:22px}
  /* full-width segmented pickers instead of a 2-up grid */
  #formOverlay .form-grid.stack-phone{grid-template-columns:1fr}
  #formOverlay .seg-pick button{height:46px;font-size:14px}
  /* paint: one row per colour, the hex beside its own well */
  #formOverlay .paint-row{flex-wrap:wrap}
  #formOverlay .paint-fields{flex-direction:column;gap:8px;width:100%}
  #formOverlay .paint-field{width:100%}
  #formOverlay .paint-field .paint-hex{margin-left:auto}
  #formOverlay #fPaintPreview{--d:44px}
```

Add `stack-phone` to the `.form-grid` wrapping the size and disc pickers at `:3275`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_boot.py -v`
Expected: PASS.

If `bought at offers the places you actually use` fails on the chip contents, read the fixture in `tests/test_boot.py` — it builds 12 records, 11 at `Benedito Calixto` and one at `Amazon`. The assertion is written against that; do not change the fixture to suit the test.

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest -q`
Expected: no new failures. `tests/test_places.js`, `tests/test_notes.js` and `tests/test_tracklist*` are the ones to watch.

- [ ] **Step 7: Commit**

```bash
git add templates/index.html tests/test_boot.js
git commit -m "feat: redraw steps 2-4 for a thumb

Bought at was a <datalist>, which Safari renders as a thin strip under the
keyboard — effectively unusable one-handed. The same places become chips,
ranked by how often they were used rather than alphabetically, with whatever
is on the record pinned first. The input still takes anything typed and the
datalist stays for desktop.

Plays, cleanings and notes collapse to one row each on a phone. A section that
already has entries opens expanded, so the collapse only ever hides what is
empty — which on step 3 is almost everything, on a step whose own lead text
says so.

Rating bars 14px -> 22px, size and discs full width instead of 2-up, and the
paint swatches one per row with the hex beside them.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: `saveQuiet()` and `toastUndo()`

No UI. Refactor plus one new primitive, so the existing save tests are the check.

**Files:**
- Modify: `templates/index.html` — `submitForm` at `:7106`, `toast` at `:9167`, the `#toast` CSS
- Test: `tests/test_boot.js`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `saveQuiet()` → `Promise<boolean>` — PUTs/POSTs, splices the response into `records`, calls `render()`, returns `true`; on failure toasts the error and returns `false`, touching no form state
  - `toastUndo(msg, onUndo)` — a 6s toast with an Undo button
  - `hideToast()` — shared dismissal
  - `setPlayCount(n)` — absolute counterpart to the existing `bumpPlayCount(d)`

- [ ] **Step 1: Fix the boot harness's PUT stub**

`saveQuiet` splices the PUT response into `records`; the stub returns `{ok:true}`, which would put a blank card where the album was. In `tests/test_boot.js`'s `fetch` stub, replace `if (opts && opts.method === 'PUT') return json({ ok: true });` with:

```js
    /* A save answers with the saved record, and saveQuiet splices what comes
     * back into `records`. Handing it {ok:true} draws a blank card where the
     * album was — the same failure the real submitForm guards against. */
    if (opts && (opts.method === 'PUT' || opts.method === 'POST')
             && u.includes('/api/records')) {
      const id = Number((u.match(/\/api\/records\/(\d+)/) || [])[1]) || 99;
      const sent = opts.body ? JSON.parse(opts.body) : {};
      const base = RECORDS.find(r => r.id === id) || RECORDS[0];
      return json(Object.assign({}, base, sent, { id }));
    }
```

Keep the existing generic `if (opts && opts.method === 'PUT') return json({ ok: true });` **after** it for the non-record PUTs (places, notes) that other tests rely on.

- [ ] **Step 2: Write the failing test**

Add to `tests/test_boot.js`:

```js
test('saveQuiet returns true and leaves the form open', async () => {
  const { win } = await boot('');
  win.openEdit(1);
  const ok = await win.saveQuiet();
  assert.strictEqual(ok, true);
  assert.strictEqual(win.document.getElementById('formOverlay').classList.contains('hidden'), false);
});

test('saveQuiet returns false on a failed save and touches no form state', async () => {
  const { win } = await boot('');
  win.openEdit(1);
  const before = win.document.getElementById('fArtist').value;
  win.fetch = async () => ({ ok: false, status: 500, json: async () => ({ error: 'nope' }) });
  assert.strictEqual(await win.saveQuiet(), false);
  assert.strictEqual(win.document.getElementById('fArtist').value, before);
});

test('saveQuiet puts the saved record into the collection', async () => {
  const { win } = await boot('');
  win.openEdit(1);
  win.document.getElementById('fArtist').value = 'Renamed';
  await win.saveQuiet();
  assert.strictEqual(win.records.find(r => r.id === 1).artist, 'Renamed');
});

test('submitForm still closes the form', async () => {
  const { win } = await boot('');
  win.openEdit(1);
  await win.submitForm();
  assert.strictEqual(win.document.getElementById('formOverlay').classList.contains('hidden'), true);
});

test('an undo toast offers a button and runs it', async () => {
  const { win } = await boot('');
  let undone = false;
  win.toastUndo('Play logged', () => { undone = true; });
  const btn = win.document.querySelector('#toast .toast-undo');
  assert.ok(btn, 'the undo toast should carry a button');
  btn.click();
  assert.strictEqual(undone, true);
});

test('a plain toast after an undo toast does not inherit the button', async () => {
  const { win } = await boot('');
  win.toastUndo('Play logged', () => {});
  win.toast('changes saved');
  assert.strictEqual(win.document.querySelector('#toast .toast-undo'), null);
  assert.strictEqual(win.document.getElementById('toast').textContent, 'changes saved');
});

test('setPlayCount sets rather than nudges', async () => {
  const { win } = await boot('');
  win.openEdit(1);
  win.setPlayCount(7);
  assert.strictEqual(Number(win.document.getElementById('fPlays').value), 7);
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python -m pytest tests/test_boot.py -v`
Expected: FAIL — `win.saveQuiet is not a function`.

- [ ] **Step 4: Split `submitForm`**

Replace `submitForm` at `templates/index.html:7106` with:

```js
/* The network half of a save, without the closing.
 *
 * Split out because the quick actions on the phone's edit screen save a
 * change and stay put — and because two save paths that both PUT a record is
 * exactly the pair that drifts. Returns true on success; on failure it
 * reports and returns false, and restoring whatever the caller changed is the
 * caller's job, since only the caller knows what that was. */
async function saveQuiet(){
  const body = formValues();
  const url = editingId ? `/api/records/${editingId}` : '/api/records';
  const method = editingId ? 'PUT' : 'POST';
  const res = await fetch(url, {method, headers:{'Content-Type':'application/json'},
                                body: JSON.stringify(body)});
  if (!res.ok){
    // The body here is {error:...}, not a record. Splicing that into `records`
    // draws a blank card where the album was.
    let message = 'save failed';
    try { const err = await res.json(); message = err.error || message; } catch (e) {}
    toast(res.status === 401 ? 'session expired — unlock and save again' : message);
    return false;
  }
  const rec = await res.json();
  if (editingId) records = records.map(x => x.id === editingId ? rec : x);
  else { records.push(rec); editingId = rec.id; }
  render();
  return true;
}

async function submitForm(){
  const wasEditing = editingId;
  if (!await saveQuiet()) return;
  toast(wasEditing ? 'changes saved'
                   : (records[records.length-1].have_it ? 'record added'
                                                        : 'added to the wishlist'));
  // A queue with more in it re-opens the form instead of closing it.
  if (addQueue && !VinylQueue.isLast(addQueue)){ advanceQueue(); return; }
  addQueue = null;
  closeForm(true);
}
```

> `saveQuiet` sets `editingId` after a POST so a quick action immediately
> afterwards updates the record rather than creating a second one. `submitForm`
> reads `wasEditing` before the call, because by the time it picks a message
> `editingId` is set either way.

- [ ] **Step 5: Add `toastUndo`, `hideToast` and `setPlayCount`**

Replace `toast` at `:9167` with:

```js
function hideToast(){
  document.getElementById('toast').classList.remove('show');
}

function toast(msg){
  const el = document.getElementById('toast');
  el.innerHTML = '';                     // a previous undo toast left a button
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, 2500);
}

/* 2500ms is right for "changes saved" and far too short to notice, read and
 * act on an undo. 6s is the shortest window that survives looking away. */
function toastUndo(msg, onUndo){
  const el = document.getElementById('toast');
  el.innerHTML = '<span></span><button type="button" class="toast-undo">Undo</button>';
  el.querySelector('span').textContent = msg;
  el.querySelector('.toast-undo').onclick = () => { hideToast(); onUndo(); };
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, 6000);
}
```

Beside `bumpPlayCount`:

```js
/* Absolute, where bumpPlayCount nudges. Restoring a snapshot needs to set the
 * count to what it was, not to guess how many nudges to undo. */
function setPlayCount(n){
  const el = document.getElementById('fPlays');
  el.value = Math.max(0, Number(n) || 0);
}
```

CSS for the button and the phone's inset:

```css
#toast .toast-undo{margin-left:14px;background:none;border:none;color:var(--accent);
  font-family:var(--font);font-size:13px;font-weight:700;padding:2px 4px;cursor:pointer}
@media(max-width:760px){
  #toast{bottom:calc(16px + env(safe-area-inset-bottom,0px))}
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_boot.py -v`
Expected: PASS.

- [ ] **Step 7: Run the whole suite**

Run: `python -m pytest -q`
Expected: no new failures. `tests/test_queue.js` exercises `submitForm`'s queue branch — it must still pass unchanged.

- [ ] **Step 8: Commit**

```bash
git add templates/index.html tests/test_boot.js
git commit -m "refactor: split the network half of submitForm out as saveQuiet

The phone's edit screen is about to gain quick actions that save a change and
stay put, and two paths that both PUT a record is exactly the pair that
drifts. saveQuiet does the request, splices the response into the collection
and reports; submitForm keeps the toast, the queue branch and the close.

Restoring after a failure is the caller's job — only the caller knows what it
changed. Adds toastUndo, which the quick actions need and which the 2.5s
text-only toast could not be: 6s and a button, with hideToast shared.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 8: The edit root screen and the quick actions

**Files:**
- Modify: `templates/index.html` — new markup after the `.form-spine` div, `openEdit` at `:6847`, `rebuildFormChrome` from Task 4, CSS in the `:2320` block
- Test: `tests/test_boot.js`

**Interfaces:**
- Consumes: `VinylPhoneForm.recordPreview/.purchasePreview/.logPreview/.objectPreview` (Task 3); `saveQuiet()`, `toastUndo()`, `setPlayCount()` (Task 7); `rebuildFormChrome()` (Task 4).
- Produces: `formEditRoot` (boolean), `renderEditRoot()`, `refreshEditRootPreviews()`, `openEditSection(n)`, `backToEditRoot()`, `quickLog(kind)`, `restoreDates(kind, before)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_boot.js`:

```js
test('editing on a phone opens a section list, not the wizard', async () => {
  const { win } = await boot('', { phone: true });
  win.openEdit(1);
  assert.strictEqual(win.document.getElementById('editRoot').hidden, false);
  assert.strictEqual(win.document.querySelectorAll('#editRoot .srow').length, 4);
  assert.strictEqual(win.document.getElementById('formRail').hidden, true);
});

test('editing on desktop still goes straight to step 1', async () => {
  const { win } = await boot('');
  win.openEdit(1);
  assert.strictEqual(win.document.getElementById('editRoot').hidden, true);
  assert.strictEqual(win.formStep, 1);
});

test('each section row previews what it already holds', async () => {
  const { win } = await boot('', { phone: true });
  win.openEdit(1);
  const rows = [...win.document.querySelectorAll('#editRoot .srow .stx span')];
  assert.match(rows[0].textContent, /Artist 1/);
  assert.match(rows[1].textContent, /Benedito Calixto/);
  assert.match(rows[2].textContent, /Pepe 3/);
});

test('a wishlist record says so instead of showing a purchase it never had', async () => {
  const { win } = await boot('', { phone: true });
  win.openEdit(9);                        // fixture record 9 is have_it:false
  const rows = [...win.document.querySelectorAll('#editRoot .srow .stx span')];
  assert.strictEqual(rows[1].textContent, 'Wishlist');
});

test('tapping a section goes to that step and offers a way back', async () => {
  const { win } = await boot('', { phone: true });
  win.openEdit(1);
  win.document.querySelectorAll('#editRoot .srow')[1].click();
  assert.strictEqual(win.formStep, 2);
  assert.strictEqual(win.document.getElementById('editRoot').hidden, true);
  assert.match(win.document.getElementById('formHeadCancel').textContent, /edit/i);
});

test('back from a section returns to the root', async () => {
  const { win } = await boot('', { phone: true });
  win.openEdit(1);
  win.openEditSection(3);
  win.backToEditRoot();
  assert.strictEqual(win.document.getElementById('editRoot').hidden, false);
});

test('logging a play appends today and saves once', async () => {
  const { win } = await boot('', { phone: true });
  win.openEdit(1);
  const before = win.formPlayDates.length;
  let puts = 0;
  const real = win.fetch;
  win.fetch = async (u, o) => { if (o && o.method === 'PUT') puts++; return real(u, o); };
  await win.quickLog('play');
  assert.strictEqual(win.formPlayDates.length, before + 1);
  assert.strictEqual(puts, 1);
});

test('logging a play bumps the count, like the card button does', async () => {
  const { win } = await boot('', { phone: true });
  win.openEdit(1);
  const before = Number(win.document.getElementById('fPlays').value);
  await win.quickLog('play');
  assert.strictEqual(Number(win.document.getElementById('fPlays').value), before + 1);
});

test('undo restores both the dates and the count, and saves again', async () => {
  const { win } = await boot('', { phone: true });
  win.openEdit(1);
  const dates = win.formPlayDates.length;
  const plays = Number(win.document.getElementById('fPlays').value);
  let puts = 0;
  const real = win.fetch;
  win.fetch = async (u, o) => { if (o && o.method === 'PUT') puts++; return real(u, o); };
  await win.quickLog('play');
  await win.document.querySelector('#toast .toast-undo').onclick();
  assert.strictEqual(win.formPlayDates.length, dates);
  assert.strictEqual(Number(win.document.getElementById('fPlays').value), plays);
  assert.strictEqual(puts, 2);
});

test('a failed quick save leaves the record as it was', async () => {
  const { win } = await boot('', { phone: true });
  win.openEdit(1);
  const dates = win.formPlayDates.length;
  const plays = Number(win.document.getElementById('fPlays').value);
  win.fetch = async () => ({ ok: false, status: 500, json: async () => ({ error: 'nope' }) });
  await win.quickLog('play');
  assert.strictEqual(win.formPlayDates.length, dates);
  assert.strictEqual(Number(win.document.getElementById('fPlays').value), plays);
});

test('a quick action updates the row it changed, without a reopen', async () => {
  const { win } = await boot('', { phone: true });
  win.openEdit(4);                       // fixture record 4 has no play dates
  const row = () => win.document.querySelectorAll('#editRoot .srow .stx span')[2].textContent;
  const before = row();
  await win.quickLog('play');
  assert.notStrictEqual(row(), before);
  assert.match(row(), /1 play/);
});

test('logging a cleaning does not touch the play count', async () => {
  const { win } = await boot('', { phone: true });
  win.openEdit(1);
  const plays = Number(win.document.getElementById('fPlays').value);
  await win.quickLog('clean');
  assert.strictEqual(Number(win.document.getElementById('fPlays').value), plays);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_boot.py -v`
Expected: FAIL — `#editRoot` does not exist.

- [ ] **Step 3: Add the markup**

In `templates/index.html`, immediately after the `.form-rail-label` div added in Task 4:

```html
    <!-- You open an existing record to change one thing, not to walk four
         steps. Phone only: the wizard's four steps become four doors, each
         one saying what it already holds, plus the three things you actually
         come here to do. -->
    <div class="edit-root" id="editRoot" hidden>
      <div class="er-head" id="editRootHead"></div>
      <div class="slist" id="editRootSections"></div>
      <div class="qa-t">One tap</div>
      <div class="qa">
        <button type="button" class="qbtn play" onclick="quickLog('play')">
          <i class="ti ti-player-play"></i>Log a play</button>
        <button type="button" class="qbtn clean" onclick="quickLog('clean')">
          <i class="ti ti-sparkles"></i>Log a clean</button>
        <button type="button" class="qbtn note" onclick="openEditSection(3)">
          <i class="ti ti-note"></i>Add a note</button>
      </div>
      <button type="button" class="er-del" id="editRootDelete"
              onclick="armEditDelete()">
        <i class="ti ti-trash"></i> Delete record</button>
    </div>
```

**The delete needs care.** There is no `deleteRecord`. The existing path is a two-stage inline confirm in the *detail drawer's* footer (`renderDetailFoot` at `:5787` sets `confirmDeleteId`, then `doDelete(id)` at `:5813`), and `doDelete` ends with `closeDetail()` — it closes the drawer, not the form. Calling it from the edit root would delete the record and leave the form open on one that no longer exists.

So the row reuses `doDelete`'s request but closes the right thing, and keeps the house's inline two-stage confirm rather than a `window.confirm`:

```js
/* The existing delete lives in the detail drawer and ends in closeDetail().
 * Called from the form it would leave the sheet open on a record that is
 * gone, so the form has its own closing — the request itself is doDelete's. */
let editDeleteArmed = false;

function armEditDelete(){
  const btn = document.getElementById('editRootDelete');
  if (!editDeleteArmed){
    editDeleteArmed = true;
    btn.classList.add('armed');
    btn.innerHTML = '<i class="ti ti-trash"></i> Tap again to delete';
    // Arming is not a commitment. Anywhere else disarms it, which is what
    // keeps a mis-tap at the bottom of a scroll from becoming a delete.
    setTimeout(() => { if (editDeleteArmed) disarmEditDelete(); }, 4000);
    return;
  }
  disarmEditDelete();
  const id = editingId;
  closeForm(true);                 // no discard prompt: the record is going
  doDelete(id);
}

function disarmEditDelete(){
  editDeleteArmed = false;
  const btn = document.getElementById('editRootDelete');
  if (btn){
    btn.classList.remove('armed');
    btn.innerHTML = '<i class="ti ti-trash"></i> Delete record';
  }
}
```

`renderEditRoot()` calls `disarmEditDelete()` so reopening a record never arrives armed.

Add a test for it in Step 1's block:

```js
test('delete takes two taps and closes the form, not the drawer', async () => {
  const { win } = await boot('', { phone: true });
  win.openEdit(1);
  const btn = win.document.getElementById('editRootDelete');
  btn.click();
  assert.match(btn.textContent, /tap again/i);
  assert.ok(win.records.some(r => r.id === 1), 'one tap must not delete');
  btn.click();
  assert.strictEqual(win.document.getElementById('formOverlay')
                        .classList.contains('hidden'), true);
});
```

*Add a note* routes to step 3 rather than composing inline: the note composer is
already there, and duplicating it on the root screen would be a second set of
`#fNoteText` ids. Step 3 opens with the notes section expanded because
`renderLogCollapse` expands what has entries — for an empty notes list, tapping
the quick action expands it explicitly:

```js
function openEditSection(n){
  formEditRoot = false;
  setFormStep(n);
  if (n === 3){
    const s = document.getElementById('notesSection');
    if (s) s.dataset.collapsed = 'false';
    document.getElementById('fNoteText').focus();
  }
}
```

- [ ] **Step 4: Add the JS**

```js
/* True while the phone's edit screen is showing its section list rather than
 * a step. The one thing rebuildFormChrome needs to know to render the root
 * chrome instead of the rail. */
let formEditRoot = false;

function backToEditRoot(){
  formEditRoot = true;
  rebuildFormChrome();
  renderEditRoot();
}

/* Read once from the form's own fields, so a row can never describe a record
 * the form has already moved on from. */
function editRootValues(){
  const v = id => document.getElementById(id).value;
  return {
    artist: v('fArtist'), year: v('fYear'), country: v('fCountry'),
    haveIt: document.getElementById('fHaveIt').checked,
    where: v('fWhere'), date: v('fDate'), condition: v('fCondition'),
    myRating, wifeRating,
    plays: (formPlayDates || []).length,
    notes: (formNotes || []).length,
    // Size and discs are .seg-pick widgets with no input behind them; the
    // values live in module-level vars, which is what formValues() reads too.
    size: formSize,
    discs: formDiscCount,
    tracks: (formTracks || []).length,
    painted: !!(formVinylColor || formLabelColor),
  };
}

const EDIT_SECTIONS = [
  { n:1, icon:'ti-disc',          title:'The record',   preview:'recordPreview'   },
  { n:2, icon:'ti-shopping-bag',  title:'The purchase', preview:'purchasePreview' },
  { n:3, icon:'ti-star',          title:'The log',      preview:'logPreview'      },
  { n:4, icon:'ti-list',          title:'The object',   preview:'objectPreview'   },
];

function renderEditRoot(){
  const root = document.getElementById('editRoot');
  root.hidden = !(isPhone() && formEditRoot);
  if (root.hidden) return;

  const cover = VinylCover.coverPreviewSrc({cover_url: editingCoverUrl}, coverDataUri);
  const v = editRootValues();
  document.getElementById('editRootHead').innerHTML = `
    <div class="pi-cover">${cover ? `<img src="${esc(cover)}" alt="">` : '<i class="ti ti-photo"></i>'}</div>
    <div class="pi-meta">
      <b>${esc(v.artist) || 'Unknown artist'}</b>
      <i>${esc(document.getElementById('fAlbum').value)}</i>
      <em>${esc([v.year, v.size].filter(Boolean).join(' · '))}</em>
    </div>`;
  refreshEditRootPreviews();
}

/* Rebuilds the four preview lines from the current field values. Called on
 * formChanged and after every quick action, so a row can never describe a
 * record that has already moved on. */
function refreshEditRootPreviews(){
  const box = document.getElementById('editRootSections');
  if (!box || document.getElementById('editRoot').hidden) return;
  const v = editRootValues();
  box.innerHTML = EDIT_SECTIONS.map(s => `
    <button type="button" class="srow" onclick="openEditSection(${s.n})">
      <span class="sic"><i class="ti ${s.icon}"></i></span>
      <span class="stx"><b>${s.title}</b><span>${esc(VinylPhoneForm[s.preview](v))}</span></span>
      <i class="ti ti-chevron-right chev"></i>
    </button>`).join('');
}

/* The common case by a wide margin, and today it costs six taps: edit, step 3,
 * scroll, add play date, pick today, save.
 *
 * Routed through addPlayDate/addCleanedDate rather than pushing onto the
 * arrays: addPlayDate also bumps the play count and re-renders, and a quick
 * action that skipped the bump would silently disagree with the card's own
 * + button. */
async function quickLog(kind){
  const before = [...(kind === 'play' ? formPlayDates : formCleanedDates)];
  const playsBefore = Number(document.getElementById('fPlays').value) || 0;
  (kind === 'play' ? addPlayDate : addCleanedDate)();
  if (!await saveQuiet()){ restoreDates(kind, before, playsBefore); return; }
  refreshEditRootPreviews();
  toastUndo(kind === 'play' ? 'Play logged' : 'Cleaning logged', async () => {
    restoreDates(kind, before, playsBefore);
    if (await saveQuiet()){ refreshEditRootPreviews(); toast('Undone'); }
  });
}

/* Whole-array restore, not a splice by index: addPlayDate appends a nowStamp()
 * and moves a separate count field, so putting both back from the snapshot is
 * the only version that cannot drift. */
function restoreDates(kind, before, playsBefore){
  if (kind === 'play'){
    formPlayDates = before;
    setPlayCount(playsBefore);
    renderPlayDatesForm();
  } else {
    formCleanedDates = before;
    renderCleanedDatesForm();
  }
  refreshEditRootPreviews();
}
```

Wire it up:
1. `openEdit` (`:6847`) — set `formEditRoot = isPhone();` before `setFormStep(1)`, and call `renderEditRoot()` after the overlay is shown.
2. `openAdd` (`:6780`) — set `formEditRoot = false;`.
3. `rebuildFormChrome` — when `formEditRoot` is true, hide the rail and the rail label, show `#editRoot`, hide the step bodies and the footer; when a section is open, set `#formHeadCancel` to `‹ edit` calling `backToEditRoot()` instead of the `×` calling `closeForm()`.
4. `formChanged()` — call `refreshEditRootPreviews()`.

The `rebuildFormChrome` addition:

```js
  // the phone's edit root: no rail, no footer, no step body
  const root = formEditRoot && phone;
  document.getElementById('editRoot').hidden = !root;
  rail.hidden = railRow.hidden = !phone || root;
  document.querySelector('#formOverlay .modal-foot').hidden = root;
  document.querySelectorAll('#formOverlay .form-step').forEach(el => {
    if (root) el.hidden = true;
  });
  const cancel = document.getElementById('formHeadCancel');
  if (phone && !root && editingId){
    cancel.innerHTML = '<i class="ti ti-chevron-left"></i> edit';
    cancel.onclick = backToEditRoot;
  } else {
    cancel.innerHTML = '<i class="ti ti-x"></i>';
    cancel.onclick = () => closeForm();
  }
  if (root) renderEditRoot();
```

> `setFormStep` sets `el.hidden` on every `.form-step` from the step number;
> `rebuildFormChrome` runs after it and overrides them all to hidden when the
> root is showing. Confirm the call order — `rebuildFormChrome()` must come
> after the `.form-step` loop in `setFormStep`, which is where Task 4 put it.

- [ ] **Step 5: Confirm the state `editRootValues` reads**

Every name it touches is module-level state in the template, already verified:

| Name | Declared at | Note |
|---|---|---|
| `myRating`, `wifeRating` | `:3641` | numbers, `0` when unset |
| `formNotes` | `:5964` | in-memory while the form is open |
| `formPlayDates`, `formCleanedDates` | `:5987`, `:5988` | arrays of stamp strings |
| `formTracks` | `:5995` | array |
| `formDiscCount` | `:5996` | number, floored at 1 |
| `formSize` | `:5997` | string, `''` when unset |
| `formVinylColor`, `formLabelColor` | `:5999` | strings, `''` when unset |

There is **no** `currentSize()` or `currentDiscCount()` — size and discs are `.seg-pick` widgets with no input element behind them, and `formValues()` at `:7097-7098` reads `formDiscCount` and `formSize` directly. Read the same vars; do not add a helper.

Sanity-check before moving on:

```bash
grep -n "let formSize\|let formDiscCount\|let formTracks\|let formNotes\|let myRating" templates/index.html
```

Expected: five hits at the lines above. If any has moved, use the line the grep reports.

- [ ] **Step 6: Add the CSS**

```css
  #formOverlay .edit-root{display:flex;flex-direction:column;gap:16px;padding:6px 14px 20px;
    overflow-y:auto;-webkit-overflow-scrolling:touch}
  #formOverlay .er-head{display:flex;gap:13px;align-items:center}
  #formOverlay .er-head .pi-cover{width:66px;height:66px}
  #formOverlay .slist{display:flex;flex-direction:column;border:1px solid var(--border);
    border-radius:12px;background:var(--card);overflow:hidden}
  #formOverlay .srow{display:flex;align-items:center;gap:12px;min-height:64px;padding:10px 13px;
    border:none;border-bottom:1px solid var(--border);background:transparent;color:var(--text);
    font-family:var(--font);text-align:left;width:100%}
  #formOverlay .srow:last-child{border-bottom:none}
  #formOverlay .sic{width:34px;height:34px;border-radius:9px;background:var(--bg);
    border:1px solid var(--border);display:flex;align-items:center;justify-content:center;
    font-size:17px;color:var(--accent);flex-shrink:0}
  #formOverlay .stx{flex:1;min-width:0}
  #formOverlay .stx b{display:block;font-size:15px;font-weight:600;letter-spacing:-.01em}
  #formOverlay .stx span{display:block;font-size:12.5px;color:var(--muted);white-space:nowrap;
    overflow:hidden;text-overflow:ellipsis;margin-top:1px}
  #formOverlay .qa-t{font-family:var(--font-mono);font-size:10px;font-weight:700;
    letter-spacing:.16em;text-transform:uppercase;color:var(--muted);
    display:flex;align-items:center;gap:10px}
  #formOverlay .qa-t::after{content:"";flex:1;height:1px;background:var(--border)}
  #formOverlay .qa{display:flex;gap:8px}
  #formOverlay .qbtn{flex:1;display:flex;flex-direction:column;align-items:center;
    justify-content:center;gap:6px;height:66px;border:1px solid var(--border);border-radius:12px;
    background:var(--card);font-size:11.5px;font-weight:600;color:var(--label);
    font-family:var(--font);text-align:center;padding:0 4px}
  #formOverlay .qbtn i{font-size:21px}
  #formOverlay .qbtn.play i{color:var(--ev-played)}
  #formOverlay .qbtn.clean i{color:var(--ev-cleaned)}
  #formOverlay .qbtn.note i{color:var(--ev-note)}
  /* findable, not inviting */
  #formOverlay .er-del{display:flex;align-items:center;justify-content:center;gap:8px;height:48px;
    border:1px solid color-mix(in srgb,var(--danger) 40%,transparent);border-radius:11px;
    background:transparent;color:var(--danger);font-size:14.5px;font-weight:600;
    font-family:var(--font);margin-top:4px}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/test_boot.py -v`
Expected: PASS.

- [ ] **Step 8: Run the whole suite**

Run: `python -m pytest -q`
Expected: no new failures.

- [ ] **Step 9: Commit**

```bash
git add templates/index.html tests/test_boot.js
git commit -m "feat: editing on a phone opens sections, not the wizard

You open an existing record to change one thing, not to walk 1-2-3-4. The
phone's edit screen lists the four sections instead, each previewing what it
already holds, so you can see whether the thing you came for is right without
opening anything.

The three log actions become one tap. Logging a play cost six before — edit,
step 3, scroll, add play date, pick today, save — and it is the most common
thing anyone does to a record they already own. Routed through addPlayDate so
the play count moves with it, and paired with a six-second Undo, because the
mistake it replaces was at least visible before it was saved.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 9: Drag to dismiss

Last because it is the only piece that can fight scrolling, and the only one worth dropping if it does not feel right on the device.

**Files:**
- Modify: `templates/index.html` — grabber markup in the modal head, JS, CSS
- Test: `tests/test_boot.js`

**Interfaces:**
- Consumes: `VinylPhoneForm.dragDismisses` (Task 3); `closeForm()`.
- Produces: nothing other tasks use.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_boot.js`:

```js
test('the phone form carries a grabber', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  assert.ok(win.document.querySelector('#formOverlay .sheet-grab'));
});

test('a long downward drag on the head closes the form', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  let closed = false;
  win.closeForm = () => { closed = true; };
  dragHead(win, 0, 140);
  assert.strictEqual(closed, true);
});

test('a short drag springs back instead of closing', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  let closed = false;
  win.closeForm = () => { closed = true; };
  dragHead(win, 0, 20);
  assert.strictEqual(closed, false);
});

test('an upward drag never closes', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  let closed = false;
  win.closeForm = () => { closed = true; };
  dragHead(win, 0, -200);
  assert.strictEqual(closed, false);
});

test('the body is not a drag surface, so scrolling is never a dismissal', async () => {
  const { win } = await boot('', { phone: true });
  win.openAdd();
  let closed = false;
  win.closeForm = () => { closed = true; };
  const body = win.document.querySelector('#formOverlay .modal-body');
  touch(win, body, 'touchstart', 0);
  touch(win, body, 'touchmove', 300);
  touch(win, body, 'touchend', 300);
  assert.strictEqual(closed, false);
});
```

Add the two helpers near the top of `tests/test_boot.js`, after the `boot` function:

```js
/* jsdom has no Touch constructor, and the app only ever reads
 * e.touches[0].clientY — so a plain object with that shape is enough. */
function touch(win, el, type, y){
  const e = new win.Event(type, {bubbles: true, cancelable: true});
  e.touches = type === 'touchend' ? [] : [{clientY: y}];
  e.changedTouches = [{clientY: y}];
  el.dispatchEvent(e);
}

function dragHead(win, from, to){
  const head = win.document.querySelector('#formOverlay .modal-head');
  touch(win, head, 'touchstart', from);
  touch(win, head, 'touchmove', to);
  touch(win, head, 'touchend', to);
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_boot.py -v`
Expected: FAIL — no `.sheet-grab`.

- [ ] **Step 3: Add the grabber markup**

Immediately inside `<div class="modal modal-wide">` in the form overlay, before `.modal-head`:

```html
    <div class="sheet-grab" aria-hidden="true"></div>
```

- [ ] **Step 4: Add the JS**

```js
/* Drag the sheet down to dismiss — what a thumb tries first.
 *
 * Bound to the head and the grabber only, never to .modal-body: a listener on
 * the scrolling area would have to tell a dismissal from a scroll at the top
 * of the list, and gets it wrong the moment the list is short enough not to
 * scroll. Routed through closeForm, so a dirty form still asks.
 *
 * Skipped under prefers-reduced-motion: the gesture is a moving sheet, and
 * cancel is right there for anyone who would rather not have one. */
(function initSheetDrag(){
  const overlay = document.getElementById('formOverlay');
  const sheet = overlay.querySelector('.modal.modal-wide');
  const handles = [overlay.querySelector('.sheet-grab'), overlay.querySelector('.modal-head')];
  let startY = null, startT = 0;

  const reduced = () => window.matchMedia('(prefers-reduced-motion:reduce)').matches;

  function onStart(e){
    if (!isPhone() || reduced() || !e.touches || !e.touches.length) return;
    startY = e.touches[0].clientY;
    startT = Date.now();
  }
  function onMove(e){
    if (startY === null || !e.touches || !e.touches.length) return;
    const dy = e.touches[0].clientY - startY;
    if (dy <= 0) return;
    e.preventDefault();                       // the page must not scroll with it
    sheet.style.transform = `translateY(${dy}px)`;
    sheet.style.transition = 'none';
  }
  function onEnd(e){
    if (startY === null) return;
    const y = (e.changedTouches && e.changedTouches[0]) ? e.changedTouches[0].clientY : startY;
    const dy = y - startY, dt = Date.now() - startT;
    startY = null;
    sheet.style.transition = '';
    sheet.style.transform = '';
    if (VinylPhoneForm.dragDismisses(dy, dt)) closeForm();
  }

  for (const h of handles){
    if (!h) continue;
    h.addEventListener('touchstart', onStart, {passive: true});
    h.addEventListener('touchmove', onMove, {passive: false});
    h.addEventListener('touchend', onEnd);
    h.addEventListener('touchcancel', onEnd);
  }
})();
```

> `onMove` calls `preventDefault`, so its listener cannot be passive — hence
> the explicit `{passive:false}`. The `touchstart` listener is passive because
> it never prevents anything, and a passive start is what keeps the head from
> delaying a tap on Cancel or Save.

- [ ] **Step 5: Add the CSS**

```css
  #formOverlay .sheet-grab{width:36px;height:5px;border-radius:3px;
    background:var(--border);margin:8px auto 0;flex-shrink:0}
  #formOverlay .modal.modal-wide{transition:transform .22s ease}
@media(prefers-reduced-motion:reduce){
  #formOverlay .modal.modal-wide{transition:none}
}
```

Hide the grabber on desktop — it sits inside `#formOverlay`, so add outside the media query:

```css
.sheet-grab{display:none}
@media(max-width:760px){ #formOverlay .sheet-grab{display:block} }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_boot.py -v`
Expected: PASS.

- [ ] **Step 7: Run the whole suite**

Run: `python -m pytest -q`
Expected: no new failures.

- [ ] **Step 8: Commit**

```bash
git add templates/index.html tests/test_boot.js
git commit -m "feat: drag the form sheet down to dismiss it

What a thumb tries first on a sheet with a grabber at the top. Bound to the
head and the grabber only, never to the scrolling body — a listener there has
to tell a dismissal from a scroll at the top of the list, and gets it wrong
whenever the list is short enough not to scroll at all.

Routed through closeForm, so a dirty form still asks before discarding, and
skipped under prefers-reduced-motion, where cancel is the whole interface.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 10: Manual verification doc

**Files:**
- Create: `docs/phone-form-manual-verification.md`

**Interfaces:** none.

- [ ] **Step 1: Read an existing manual doc for the house format**

```bash
sed -n '1,60p' docs/photo-lightbox-manual-verification.md
```

Match its structure — numbered scenarios, explicit steps, an expected result per step, and a note on what was actually checked against what.

- [ ] **Step 2: Write the doc**

Create `docs/phone-form-manual-verification.md` covering what a headless DOM cannot:

1. **The home-screen icon.** Add to Home Screen from Safari on a real iPhone. Expected: the purple/gold record, not a Z. Then: remove and re-add on a device that had the old shortcut, and confirm the tile updates — iOS caches it at install time, so this is the only way an existing install gets the new icon.
2. **Safe areas in standalone mode.** Launch from the home screen on a notched device. Expected: the header clears the status bar; the footer's buttons clear the home indicator; no white strip at the top.
3. **The keyboard.** Open Add, go to step 2, tap *Bought at*. Expected: Save stays visible above the keyboard; the field scrolls to the middle of the visible area; dismissing the keyboard returns the footer to the bottom without a jump.
4. **Landscape.** Repeat 3 in landscape. Expected: the same, at the shorter height.
5. **The lookup rows.** Add a record by camera, by search, and by Spotify link in turn. Expected: each route fills the fields and the rows are replaced by the identity strip; *Pick a different match* reopens the previous results without a new scan charge.
6. **Drag to dismiss.** Drag the head down 20px, then 140px, then flick it. Expected: spring back, close, close. Then with text typed: the discard confirmation appears.
7. **Scroll is not a dismissal.** On step 3 with several notes, scroll the body up and down quickly. Expected: the sheet never moves.
8. **Quick actions.** On a record with no plays, tap *Log a play*. Expected: the log row updates in place, the toast offers Undo for about six seconds, and tapping Undo restores both the play list and the play count. Confirm on the card in the grid behind it.
9. **Both themes.** Repeat 5 and 8 in light mode. Expected: every new control readable; the accent is the deep brown `#7A5A00`, not the gold.
10. **Desktop regression.** On a desktop browser, add and edit a record end to end. Expected: the four-step spine, the `×` in the head, cancel/back/next/save in the foot, the cover well on step 1, the datalist on *Bought at*, and every log section expanded.

- [ ] **Step 3: Commit**

```bash
git add docs/phone-form-manual-verification.md
git commit -m "docs: manual verification for the phone form redraw

The things a headless DOM cannot check: the keyboard actually staying clear of
the action bar, the drag threshold, the safe-area insets in standalone mode on
a notched device, and the home-screen icon after a remove and re-add — iOS
caches the tile at install time, so an existing install keeps the Z until the
shortcut is replaced.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage.** Every section maps to a task: §2 icon → Task 1; §3.1–3.2 safe areas and keyboard → Task 2; §3.3 `isPhone` → Task 2; §3.4–3.5 nav bar, rail, footer → Task 4; §3.6 grabber → Task 9; §4.1–4.2 step 1 → Task 5; §4.3–4.5 steps 2–4 → Task 6; §5.1 edit root → Task 8; §5.2 quick actions → Task 8; §5.3 `toastUndo` → Task 7; §5.4 delete → Task 8; §6 desktop parity → asserted in Tasks 4, 5, 6, 8 and scenario 10 of Task 10; §7.1 JS tests → Tasks 3–9; §7.2 `test_icons.py` → Task 1; §7.3 manual doc → Task 10. The pure rules of §7.1 land in Task 3 ahead of every consumer.

**Type consistency.** Every symbol a later task calls is produced by an earlier one's **Interfaces** block: `isPhone` (2) → 4,5,6,8; `VinylPhoneForm.*` (3) → 4,6,8,9; `rebuildFormChrome` (4) → 5,6,8; `saveQuiet`/`toastUndo`/`setPlayCount` (7) → 8; `formEditRoot` (8) → read by `rebuildFormChrome`, which Task 4 writes, so Task 4's version must tolerate the variable not existing yet — it is declared `let formEditRoot = false;` in Task 8, and Task 4's `rebuildFormChrome` does not reference it. Confirmed: the `formEditRoot` branch is added to `rebuildFormChrome` in Task 8 Step 4, not Task 4 Step 4.

**Three defects the review caught and fixed, rather than deferred:**

1. **The delete row had no function to call.** There is no `deleteRecord`. The real path is a two-stage inline confirm in the detail drawer, and its `doDelete(id)` ends in `closeDetail()` — called from the form it would delete the record and leave the sheet open on a ghost. Task 8 Step 3 now carries its own arm/confirm that closes the *form* and reuses `doDelete`'s request.
2. **`currentSize()` / `currentDiscCount()` do not exist.** Size and discs are `.seg-pick` widgets backed by the module-level `formSize` and `formDiscCount`, which is what `formValues()` reads. Task 8 Steps 4 and 5 now name the real state, with line numbers.
3. **Task 4 Step 5 contradicted itself** mid-step about whether `FORM_STEPS` changes. It does not; the step is now a drift guard on the two lists' lengths.

**Known risk, flagged not solved.** Task 4 moves `#formSaveBtn` between two slots with `appendChild`. If any code holds a reference to the button's *parent* rather than the button, it breaks. `syncSaveLabel` and the wishlist relabel both use `getElementById`, so they are safe; the test `the save button exists exactly once in both modes` guards the duplication case, and `the wishlist relabel still finds the button after the move` guards the lookup case.

**Second known risk.** Task 5's CSS hides `.cover-drop` on the phone, but `openCamera()` and `pickCoverFile()` write their result into `#coverPreview` inside it. Hidden is not removed, so the write still lands and `renderStep1Phone` reads `coverDataUri` rather than the DOM — but an executor who deletes the element instead of hiding it will break the camera. The step says `display:none` for this reason.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-19-phone-add-edit-redraw.md`. Two execution options:

**1. Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.
