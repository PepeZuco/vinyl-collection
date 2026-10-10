"""The generated playlist cover: which rows it shows, how long ones are cut, and
that the picture is one Spotify will take (a 640×640 JPEG under 256 KB as base64).
"""

import base64
import io

from PIL import Image

import cover_art
from playlist_filters import normalize_filters


def rows(raw):
    return cover_art.rows(normalize_filters(raw))


# ── fitting a list into the column ────────────────────────────────────────────

def test_fit_keeps_a_list_that_fits():
    assert cover_art.fit(["Jazz", "Soul"], len, 20) == "Jazz, Soul"


def test_fit_counts_what_it_leaves_out():
    assert cover_art.fit(["Jazz", "Soul", "Rock", "Funk"], len, 14) == "Jazz, Soul +2"


def test_fit_cuts_a_single_long_name():
    assert cover_art.fit(["Supercalifragilistic"], len, 10) == "Supercali…"


def test_fit_cuts_the_first_name_when_even_it_does_not_fit_with_the_count():
    out = cover_art.fit(["Supercalifragilistic", "Jazz"], len, 12)
    assert out == "Supercal… +1" and len(out) <= 12


# ── rows ──────────────────────────────────────────────────────────────────────

def test_rows_follow_a_fixed_order_whatever_the_filters_order():
    got = rows({"source": "all", "bought_from": "2024-03-01", "places": ["Tokyo"],
                "pepe_min": 4, "year_from": 1970, "genres": ["Jazz"]})
    assert [icon for icon, _ in got] == ["genre", "year", "rating", "place", "bought", "source"]


def test_genres_and_places_are_lists_to_fit():
    got = dict(rows({"genres": ["Soul", "jazz"], "places": ["Tokyo"]}))
    assert got["genre"] == [["jazz", "Soul"]]
    assert got["place"] == [["Tokyo"]]


def test_a_year_range_and_a_single_year():
    assert dict(rows({"year_from": 1970, "year_to": 1979}))["year"] == ["1970–1979"]
    assert dict(rows({"year_from": 1970, "year_to": 1970}))["year"] == ["1970"]
    assert dict(rows({"year_from": 1970}))["year"] == ["≥1970"]
    assert dict(rows({"decades": [1960, 1980]}))["year"] == [["1960s", "1980s"]]


def test_both_ratings_take_a_line_each():
    assert dict(rows({"pepe_min": 4, "jenni_min": 4.5}))["rating"] == ["Pepe ≥4", "Jenni ≥4.5"]
    assert dict(rows({"pepe_min": 4, "jenni_min": 4.5, "rating_mode": "or"}))["rating"] == \
        ["Pepe ≥4", "or Jenni ≥4.5"]
    assert dict(rows({"jenni_min": 3}))["rating"] == ["Jenni ≥3"]


def test_whole_years_of_buying_read_as_years():
    assert dict(rows({"bought_from": "2023-01-01", "bought_to": "2024-12-31"}))["bought"] == ["2023–2024"]
    assert dict(rows({"bought_from": "2024-01-01", "bought_to": "2024-12-31"}))["bought"] == ["2024"]


def test_other_buying_dates_take_a_line_each():
    assert dict(rows({"bought_from": "2024-03-01", "bought_to": "2024-06-30"}))["bought"] == \
        ["from 2024-03-01", "to 2024-06-30"]
    assert dict(rows({"bought_to": "2024-06-30"}))["bought"] == ["to 2024-06-30"]


def test_source_rows():
    assert dict(rows({"source": "all"}))["source"] == ["+ compilations"]
    assert dict(rows({"source": "compilations"}))["source"] == ["compilations", "only"]
    assert "source" not in dict(rows({}))


def test_no_filters_is_the_whole_collection():
    assert rows({}) == [("collection", ["whole collection"])]
    assert rows({"liked": False}) == [("collection", ["whole collection"])]


def test_footer_says_liked_or_every_track_and_the_count():
    assert cover_art.footer({"liked": True}, 42) == "liked · 42 tracks"
    assert cover_art.footer({"liked": False}, 1) == "every track · 1 track"


# ── the picture ───────────────────────────────────────────────────────────────

def _image(data):
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def test_render_is_a_640_square_jpeg_spotify_accepts():
    data = cover_art.render(normalize_filters({"genres": ["Jazz", "Soul"], "year_from": 1970,
                                               "year_to": 1979, "pepe_min": 4, "jenni_min": 4.5,
                                               "places": ["Tokyo"]}), 42)
    img = _image(data)
    assert img.format == "JPEG" and img.size == (640, 640)
    assert len(base64.b64encode(data)) <= cover_art.MAX_BASE64


def test_render_survives_every_filter_at_once_with_long_values():
    f = normalize_filters({
        "liked": False, "genres": [f"Genre number {i}" for i in range(12)],
        "year_from": 1950, "year_to": 2025, "pepe_min": 0.5, "jenni_min": 5, "rating_mode": "or",
        "places": ["A record shop with an extraordinarily long name in Lisbon", "Tokyo"],
        "bought_from": "2019-02-03", "bought_to": "2025-11-30", "source": "compilations"})
    img = _image(cover_art.render(f, 12345))
    assert img.size == (640, 640)


def test_render_is_the_same_for_the_same_playlist():
    f = normalize_filters({"genres": ["Jazz"]})
    assert cover_art.render(f, 3) == cover_art.render(f, 3)


def test_render_draws_the_brand_record_on_the_left():
    img = _image(cover_art.render(normalize_filters({}), 3)).convert("RGB")
    r, g, b = img.getpixel((200, 320))  # inside the yellow ring of the cropped record
    assert r > 200 and g > 160 and b < 90
    r, g, b = img.getpixel((600, 600))  # the black side
    assert max(r, g, b) < 30


def test_a_footer_too_wide_keeps_just_the_count():
    assert cover_art.footer({"liked": False}, 1234, len, 30) == "every track · 1234 tracks"
    assert cover_art.footer({"liked": False}, 1234, len, 20) == "1234 tracks"


def test_countries_are_drawn_as_flags():
    f = normalize_filters({"countries": ["br", "US"]})
    assert cover_art.rows(f) == [("place", [["\U0001F1E7\U0001F1F7", "\U0001F1FA\U0001F1F8"]])]


def test_flags_are_pictures_not_letters():
    pic = cover_art._flag_image("\U0001F1E7\U0001F1F7", 40)
    assert pic is not None and pic.height == 40 and pic.width > 40


def test_fewer_filters_get_bigger_type():
    assert cover_art.row_size(2, 2) > cover_art.row_size(5, 6) > cover_art.row_size(7, 8)
    assert cover_art.row_size(7, 8) == 26
