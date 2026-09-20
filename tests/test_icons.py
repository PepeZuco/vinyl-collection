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
