"""The cover picture of a filtered Spotify playlist, drawn from its filters.

The app's record (static/vinyl-icon.svg) sits cropped on the left; on the
black to its right, one row per filter with an icon in a ring colour, and the
track count at the foot. Pure like playlist_filters: filters and a count in,
JPEG bytes out — the same playlist always draws the same picture.

Drawn with Pillow alone, at twice the size and scaled down for smooth edges,
so the server needs no SVG renderer or system fonts: the font ships in
static/fonts. Spotify takes a JPEG of at most 256 KB, sent as base64.
"""

import io
import os

from PIL import Image, ImageDraw, ImageFont

SIZE = 640
MAX_BASE64 = 256 * 1024

PURPLE, YELLOW, PINK, INK = "#9B7FD4", "#F5C518", "#D4608A", "#111111"
BG, TEXT, MUTED = "#0b0b0b", "#f2f2f2", "#9a9a9a"
ROW_COLOURS = (YELLOW, PURPLE, PINK)

_FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "fonts", "Ubuntu.ttf")
_S = 2  # supersampling

# Layout, in 640-px units.
_RECORD_X, _RECORD_K = 10, 5.6       # centre x, px per vinyl-icon.svg unit
_ICON_X, _ICON = 360, 30
_TEXT_X, _TEXT_RIGHT = 404, 616
_TITLE_Y = 58
_ROWS_TOP, _ROWS_BOTTOM = 130, 500
_ROW_FONT, _LINE, _MAX_GAP = 26, 32, 46
_FOOT_Y = 548


# ── what the cover says ───────────────────────────────────────────────────────

def fit(items, measure, width):
    """`items` joined with commas, as many as fit in `width`, then "+N" for the rest.
    A first item too long even alone is cut with an ellipsis."""
    n = len(items)
    for k in range(n, 0, -1):
        text = ", ".join(items[:k]) + ("" if k == n else f" +{n - k}")
        if measure(text) <= width:
            return text
    suffix = f" +{n - 1}" if n > 1 else ""
    head = items[0]
    while head and measure(head.rstrip(" ,") + "…" + suffix) > width:
        head = head[:-1]
    return head.rstrip(" ,") + "…" + suffix


def _num(x):
    return str(int(x)) if float(x).is_integer() else str(x)


def _span(lo, hi):
    if lo is not None and hi is not None:
        return str(lo) if lo == hi else f"{lo}–{hi}"
    return f"≥{lo}" if lo is not None else f"≤{hi}"


def _bought(lo, hi):
    if lo and hi and lo.endswith("-01-01") and hi.endswith("-12-31"):
        return [_span(int(lo[:4]), int(hi[:4]))]
    return ([f"from {lo}"] if lo else []) + ([f"to {hi}"] if hi else [])


def rows(filters):
    """[(icon, lines)] in a fixed order. A line is text, or a list of names to `fit`."""
    f = filters
    out = []
    if f.get("genres"):
        out.append(("genre", [f["genres"]]))
    years = [[f"{d}s" for d in f["decades"]]] if f.get("decades") else []
    if "year_from" in f or "year_to" in f:
        years.append(_span(f.get("year_from"), f.get("year_to")))
    if years:
        out.append(("year", years))
    ratings = []
    if "pepe_min" in f:
        ratings.append(f"Pepe ≥{_num(f['pepe_min'])}")
    if "jenni_min" in f:
        ratings.append(f"Jenni ≥{_num(f['jenni_min'])}")
    if len(ratings) == 2 and f.get("rating_mode") == "or":
        ratings[1] = "or " + ratings[1]
    if ratings:
        out.append(("rating", ratings))
    if f.get("countries"):
        out.append(("place", [f["countries"]]))
    if f.get("places"):
        out.append(("place", [f["places"]]))
    if "bought_from" in f or "bought_to" in f:
        out.append(("bought", _bought(f.get("bought_from"), f.get("bought_to"))))
    if f.get("source") == "all":
        out.append(("source", ["+ compilations"]))
    elif f.get("source") == "compilations":
        out.append(("source", ["compilations", "only"]))
    return out or [("collection", ["whole collection"])]


def footer(filters, total, measure=None, width=None):
    """"liked · 42 tracks"; just the count when `measure` says the rest will not fit."""
    kind = "liked" if filters.get("liked", True) else "every track"
    count = f"{total} track{'' if total == 1 else 's'}"
    text = f"{kind} · {count}"
    return count if measure and measure(text) > width else text


# ── drawing ───────────────────────────────────────────────────────────────────

def _font(size):
    font = ImageFont.truetype(_FONT, size * _S)
    font.set_variation_by_name("Bold")
    return font


def _record(d):
    cx, cy, k = _RECORD_X * _S, SIZE // 2 * _S, _RECORD_K * _S

    def disc(r, fill=None, outline=None, width=0):
        d.ellipse((cx - r * k, cy - r * k, cx + r * k, cy + r * k),
                  fill=fill, outline=outline, width=round(width * k))
    disc(58, PURPLE)
    disc(44, YELLOW)
    disc(22, PINK)
    disc(16, INK)
    disc(13.5, outline=PINK, width=1)
    disc(10.5, outline=PINK, width=1)
    disc(4, PINK)
    disc(1.5, INK)


def _icon(d, name, x, y, size, colour):
    """A filled icon in a size×size box at (x, y), in 640-px units; drawn on a 24-unit grid."""
    u = size * _S / 24
    ox, oy = x * _S, y * _S
    P = lambda px, py: (ox + px * u, oy + py * u)
    box = lambda x0, y0, x1, y1: (*P(x0, y0), *P(x1, y1))

    if name == "genre":     # a pair of beamed notes
        d.ellipse(box(2, 15, 10, 22), fill=colour)
        d.ellipse(box(14, 13, 22, 20), fill=colour)
        d.rectangle(box(7.5, 4, 10, 18.5), fill=colour)
        d.rectangle(box(19.5, 2, 22, 16.5), fill=colour)
        d.polygon([P(7.5, 4), P(22, 1), P(22, 5.5), P(7.5, 8.5)], fill=colour)
    elif name == "year":    # a calendar page
        d.rounded_rectangle(box(2, 4, 22, 22), radius=2.5 * u, outline=colour, width=round(2.4 * u))
        d.rectangle(box(2, 4, 22, 10), fill=colour)
        d.rectangle(box(6, 1, 8.5, 6), fill=colour)
        d.rectangle(box(15.5, 1, 18, 6), fill=colour)
        for cx in (7, 12, 17):
            d.rectangle(box(cx - 1.4, 13.5, cx + 1.4, 16.3), fill=colour)
    elif name == "rating":  # a star
        d.polygon([P(12, 1), P(15.1, 8.3), P(23, 9), P(17, 14.2), P(18.8, 22),
                   P(12, 17.9), P(5.2, 22), P(7, 14.2), P(1, 9), P(8.9, 8.3)], fill=colour)
    elif name == "place":   # a map pin
        d.ellipse(box(4, 1, 20, 17), fill=colour)
        d.polygon([P(4.6, 12), P(19.4, 12), P(12, 23)], fill=colour)
        d.ellipse(box(9, 6, 15, 12), fill=BG)
    elif name == "bought":  # a shopping bag
        d.arc(box(7, 1.5, 17, 11.5), 180, 360, fill=colour, width=round(2.4 * u))
        d.rectangle(box(7, 6, 9.4, 9), fill=colour)
        d.rectangle(box(14.6, 6, 17, 9), fill=colour)
        d.rounded_rectangle(box(3, 8, 21, 23), radius=2 * u, fill=colour)
    elif name == "source":  # two records, one over the other
        d.ellipse(box(9, 1, 23, 15), fill=colour)
        d.ellipse(box(14.5, 6.5, 17.5, 9.5), fill=BG)
        d.ellipse(box(0.5, 8, 16.5, 24), fill=BG)
        d.ellipse(box(2, 9.5, 15, 22.5), fill=colour)
        d.ellipse(box(7, 14.5, 10, 17.5), fill=BG)
    elif name == "collection":  # one record
        d.ellipse(box(1, 1, 23, 23), fill=colour)
        d.ellipse(box(7, 7, 17, 17), outline=BG, width=round(1.2 * u))
        d.ellipse(box(10.5, 10.5, 13.5, 13.5), fill=BG)
    elif name == "heart":
        d.ellipse(box(1.5, 3, 12.5, 14), fill=colour)
        d.ellipse(box(11.5, 3, 22.5, 14), fill=colour)
        d.polygon([P(2.1, 11), P(21.9, 11), P(12, 21.5)], fill=colour)
    else:
        raise ValueError(f"no icon {name!r}")


def _spaced(d, x, y, text, font, fill, spacing):
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += font.getlength(ch) + spacing


def render(filters, total):
    """The cover as JPEG bytes, small enough for Spotify."""
    img = Image.new("RGB", (SIZE * _S, SIZE * _S), BG)
    d = ImageDraw.Draw(img)
    _record(d)

    _spaced(d, _ICON_X * _S, _TITLE_Y * _S, "ZUCOLOTO VINYL", _font(22), YELLOW, 3 * _S)

    font = _font(_ROW_FONT)
    width = (_TEXT_RIGHT - _TEXT_X) * _S
    laid = [(icon, [fit(line if isinstance(line, list) else [line], font.getlength, width)
                    for line in lines])
            for icon, lines in rows(filters)]
    lines = sum(len(ls) for _, ls in laid)
    room = _ROWS_BOTTOM - _ROWS_TOP - lines * _LINE
    gap = min(_MAX_GAP, room / max(len(laid) - 1, 1)) if len(laid) > 1 else 0
    y = _ROWS_TOP + (room - gap * (len(laid) - 1)) / 2
    for i, (icon, ls) in enumerate(laid):
        _icon(d, icon, _ICON_X, y + 1, _ICON, ROW_COLOURS[i % len(ROW_COLOURS)])
        for j, line in enumerate(ls):
            d.text((_TEXT_X * _S, (y + j * _LINE) * _S), line, font=font, fill=TEXT)
        y += len(ls) * _LINE + gap

    _icon(d, "heart" if filters.get("liked", True) else "collection",
          _ICON_X, _FOOT_Y + 2, 24, PINK)
    small = _font(22)
    text = footer(filters, total, small.getlength, (_TEXT_RIGHT - _ICON_X - 36) * _S)
    d.text(((_ICON_X + 36) * _S, _FOOT_Y * _S), text, font=small, fill=MUTED)

    return to_spotify_jpeg(img.resize((SIZE, SIZE), Image.LANCZOS))


def to_spotify_jpeg(img):
    """An RGB picture as JPEG bytes under Spotify's 256 KB (as base64) cap.

    Quality drops until it fits; a photo too busy to fit even then is shrunk.
    """
    for scale in (1, 0.75, 0.5):
        if scale != 1:
            img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
        for quality in (90, 80, 70, 60, 50):
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=quality)
            data = buf.getvalue()
            if (len(data) + 2) // 3 * 4 <= MAX_BASE64:
                return data
    return data
