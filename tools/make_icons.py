#!/usr/bin/env python3
"""Render static/vinyl-icon.svg into the home-screen PNGs.

Run by hand when the mark changes; not imported by the app and deliberately
not in requirements.txt, so the deploy does not grow a rendering stack for
three files that change approximately never.

    python tools/make_icons.py

iOS masks the tile into a squircle itself and composites any alpha onto black,
so the mark is drawn onto the app's own ground here rather than shipped
transparent, and the corners are left square.

Needs Pillow, and prefers cairosvg to rasterise the SVG directly; cairosvg
needs native cairo and will not install everywhere, so if it is missing this
falls back to drawing the mark itself (the same eight concentric circles,
values read off static/vinyl-icon.svg by hand).
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


def render_mark_cairosvg(px: int) -> "Image.Image":
    """The SVG rasterised at px x px, with transparency intact."""
    import cairosvg
    from PIL import Image

    png = cairosvg.svg2png(url=str(SVG), output_width=px, output_height=px)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def render_mark_pillow(px: int) -> "Image.Image":
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


def render_mark(px: int) -> "Image.Image":
    """The mark at px x px, rasterised from the SVG when possible."""
    try:
        return render_mark_cairosvg(px)
    except ImportError:
        return render_mark_pillow(px)


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
        from PIL import Image  # noqa: F401
    except ImportError:
        print("needs pillow (and optionally cairosvg):  pip install pillow cairosvg", file=sys.stderr)
        return 1
    for size in SIZES:
        path = OUT / f"icon-{size}.png"
        build(size).save(path, "PNG", optimize=True)
        print(f"wrote {path.relative_to(ROOT)}  {size}x{size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
