from unittest.mock import patch

import scan


def _rows(n):
    return [{"mbid": f"m{i}", "artist": "Jorge Ben", "album_name": f"A{i}"}
            for i in range(n)]


def test_every_row_gets_its_own_cover_in_input_order():
    """A pool completes out of order; the grid must not."""
    rows = _rows(5)
    with patch.object(scan, "fetch_cover",
                      side_effect=lambda c, *_a: "art:" + c["album_name"]):
        scan.search_covers(rows)

    assert [r["cover_data"] for r in rows] == [
        "art:A0", "art:A1", "art:A2", "art:A3", "art:A4"]


def test_rows_past_the_cap_are_left_without_artwork():
    rows = _rows(scan.COVER_FETCH_LIMIT + 3)
    with patch.object(scan, "fetch_cover", return_value="art") as fetch:
        scan.search_covers(rows)

    assert fetch.call_count == scan.COVER_FETCH_LIMIT
    assert rows[scan.COVER_FETCH_LIMIT]["cover_data"] is None
    assert rows[-1]["cover_data"] is None


def test_one_row_blowing_up_does_not_lose_the_others():
    """fetch_cover is documented never to raise, but the pool must not trust
    that absolutely — a single bad row cannot cost the whole grid."""
    rows = _rows(3)

    def boom(candidate, *_args):
        if candidate["album_name"] == "A1":
            raise RuntimeError("cover art archive said no")
        return "art:" + candidate["album_name"]

    with patch.object(scan, "fetch_cover", side_effect=boom):
        scan.search_covers(rows)

    assert [r["cover_data"] for r in rows] == ["art:A0", None, "art:A2"]


def test_an_empty_list_is_fine():
    scan.search_covers([])
