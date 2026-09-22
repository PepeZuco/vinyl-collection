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


def _png_color_type(data: bytes) -> int:
    """The IHDR colour-type byte, without pulling in Pillow.

    iOS masks the tile into a squircle itself and composites any alpha onto
    black, so a re-render that saved these with a transparent background
    would still pass every other check here and only show up on the phone as
    a black box behind the mark. 2 is truecolour with no alpha channel; 6
    would be truecolour+alpha, the regression this guards against.
    """
    return data[25]


@pytest.mark.parametrize("name,expected", [
    ("icon-180.png", 180),
    ("icon-192.png", 192),
    ("icon-512.png", 512),
])
def test_icon_serves_at_its_declared_size(client, name, expected):
    res = client.get(f"/static/{name}")
    assert res.status_code == 200
    assert res.mimetype == "image/png"
    data = res.get_data()
    assert _png_size(data) == (expected, expected)
    assert _png_color_type(data) == 2, "icon must be flat — no alpha channel"


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


def test_the_overlay_also_follows_where_the_visual_viewport_scrolled_to():
    """Height alone is not enough, and getting that wrong was worse than not
    fixing the keyboard at all.

    A position:fixed element is pinned to the LAYOUT viewport, which does not
    move. Focusing a field makes the browser scroll the VISUAL viewport down to
    reveal it, so the two diverge by `offsetTop`. A sheet sized to vv.height but
    still anchored at layout top then shows only the overlap — in practice a
    band holding one input and the Back/Next row, with the collection visible
    underneath. The form has to follow both numbers.
    """
    html = app_module.app.test_client().get("/").get_data(as_text=True)
    assert "vv.offsetTop" in html, (
        "syncViewportHeight stopped reading visualViewport.offsetTop — the form "
        "will detach from the visible window as soon as a field is focused"
    )
    assert "--vvt" in html
    assert "#formOverlay{top:var(--vvt,0px);bottom:auto;height:var(--vvh,100%)}" in html, (
        "the fixed overlay is no longer the element being moved and sized; "
        "sizing only the modal inside it is what left the sheet stranded at "
        "layout top"
    )
