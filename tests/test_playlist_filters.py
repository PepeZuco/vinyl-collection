"""The playlist filter rules. The shared fixture is also run by the JS twin
(tests/test_playlist_filters.js), so a case added there pins both languages."""

import json

import pytest

import playlist_filters as pf
from conftest import FIXTURES

CASES = json.loads((FIXTURES / "playlist_filter_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES["match"], ids=[c["why"] for c in CASES["match"]])
def test_shared_match_cases(case):
    f = pf.normalize_filters(case["filters"])
    assert bool(pf.select([case["record"]], f)) is case["match"]


@pytest.mark.parametrize("case", CASES["names"], ids=[c["name"] for c in CASES["names"]])
def test_shared_name_cases(case):
    assert pf.suggest_name(pf.normalize_filters(case["filters"])) == case["name"]


def test_liked_defaults_to_true_and_empties_are_dropped():
    assert pf.normalize_filters({"year_from": "", "genres": [], "places": [" "],
                                 "pepe_min": None, "bought_to": ""}) == {"liked": True}
    assert pf.normalize_filters(None) == {"liked": True}


def test_rating_mode_only_with_both_minimums():
    assert "rating_mode" not in pf.normalize_filters({"pepe_min": 4, "rating_mode": "or"})
    assert pf.normalize_filters({"pepe_min": 4, "jenni_min": 4})["rating_mode"] == "and"


def test_key_ignores_order_case_and_spacing():
    a = pf.normalize_filters({"genres": ["Rock", "jazz"], "places": ["Tracks"]})
    b = pf.normalize_filters({"genres": [" JAZZ ", "rock", "Rock"], "places": ["tracks"]})
    assert pf.filter_key(a) == pf.filter_key(b)


def test_key_tells_liked_from_every_track():
    assert pf.filter_key(pf.normalize_filters({})) != \
           pf.filter_key(pf.normalize_filters({"liked": False}))


def test_key_does_not_care_about_number_spelling():
    assert pf.filter_key(pf.normalize_filters({"year_from": "1970", "pepe_min": "4"})) == \
           pf.filter_key(pf.normalize_filters({"year_from": 1970, "pepe_min": 4.0}))


def test_decades_are_sorted_unique_years():
    assert pf.normalize_filters({"decades": ["1980", 1960, 1960]})["decades"] == [1960, 1980]
    assert "decades" not in pf.normalize_filters({"decades": []})
    assert pf.filter_key(pf.normalize_filters({"decades": [1980, 1960]})) == \
           pf.filter_key(pf.normalize_filters({"decades": ["1960", "1980"]}))


@pytest.mark.parametrize("raw, field", [
    ({"decades": [1975]}, "decades"),
    ({"decades": ["sixties"]}, "decades"),
    ({"year_from": "seventies"}, "year_from"),
    ({"year_to": 99}, "year_to"),
    ({"pepe_min": 6}, "pepe_min"),
    ({"jenni_min": 3.3}, "jenni_min"),
    ({"bought_from": "2024-13-01"}, "bought_from"),
    ({"bought_to": "yesterday"}, "bought_to"),
    ({"rating_mode": "xor", "pepe_min": 1, "jenni_min": 1}, "rating_mode"),
    ({"liked": "yes"}, "liked"),
    ({"genres": {"a": 1}}, "genres"),
])
def test_invalid_values_name_their_field(raw, field):
    with pytest.raises(pf.FilterError) as e:
        pf.normalize_filters(raw)
    assert e.value.field == field


def test_long_names_are_cut_to_100_with_an_ellipsis():
    f = pf.normalize_filters({"genres": [f"Genre number {i}" for i in range(20)]})
    name = pf.suggest_name(f)
    # <= because the cut drops a trailing space before the ellipsis.
    assert len(name) <= 100 and name.endswith("…")


def test_describe_says_what_is_in_it():
    assert pf.describe(pf.normalize_filters({})) == "liked songs · whole collection"
    assert pf.describe(pf.normalize_filters({"liked": False, "year_from": 1970, "year_to": 1979})) \
        == "every track · 1970–1979"


def test_select_keeps_order():
    recs = [{"year": "1971"}, {"year": "1990"}, {"year": "1975"}]
    assert pf.select(recs, pf.normalize_filters({"year_to": 1980})) == [recs[0], recs[2]]


def test_source_defaults_to_albums_and_keeps_old_keys():
    # Playlists saved before the source filter existed must keep their key.
    assert pf.normalize_filters({"source": "albums"}) == {"liked": True}
    assert pf.filter_key(pf.normalize_filters({"source": "all"})) != \
           pf.filter_key(pf.normalize_filters({}))
    with pytest.raises(pf.FilterError) as e:
        pf.normalize_filters({"source": "singles"})
    assert e.value.field == "source"


def test_owned_defaults_to_owned_and_keeps_old_keys():
    assert pf.normalize_filters({"owned": "owned"}) == {"liked": True}
    assert pf.normalize_filters({"owned": "wishlist"})["owned"] == "wishlist"
    with pytest.raises(pf.FilterError) as e:
        pf.normalize_filters({"owned": "borrowed"})
    assert e.value.field == "owned"
