"""Was this album ever actually pressed on vinyl?

MusicBrainz answers that one level below the release group: a group is the
abstract album and carries no format, so a streaming-only remix and a 1977 LP
look identical there. The pressings live on releases, which do carry a format.
"""
import json
from unittest.mock import patch, Mock

import jsonschema
import pytest

import scan


@pytest.fixture(autouse=True)
def no_real_sleeping(monkeypatch):
    """Neutralise the 1 req/sec throttle so the suite doesn't crawl."""
    monkeypatch.setattr(scan.time, "sleep", lambda _s: None)
    monkeypatch.setattr(scan, "_mb_last_call", 0.0)


def _releases(*rgids, count=None):
    """A release-search payload whose rows belong to the given groups."""
    return {"count": count if count is not None else len(rgids),
            "releases": [{"id": f"rel-{i}", "title": "x",
                          "release-group": {"id": rgid}}
                         for i, rgid in enumerate(rgids)]}


def _claude_response(payload: dict):
    block = Mock()
    block.type = "text"
    block.text = json.dumps(payload)
    message = Mock()
    message.content = [block]
    message.usage = Mock(input_tokens=120, output_tokens=8)
    return message


# ── the format clause ───────────────────────────────────────────────────────

def test_the_clause_names_every_vinyl_format_as_a_quoted_phrase():
    """MusicBrainz indexes a format as its whole name, not as words.

    Measured against the live API for Pink Floyd's "Animals": `format:vinyl`
    returns 1 release and `format:vinyl*` returns 1, while the four names
    ORed together return 31. A bare or prefixed term looks like it works and
    silently confirms almost nothing, so the clause has to spell each name
    out — with the inch mark escaped, or the phrase ends at `12`.
    """
    clause = scan._vinyl_format_clause()

    assert 'format:"12\\" Vinyl"' in clause
    assert 'format:"7\\" Vinyl"' in clause
    assert 'format:"10\\" Vinyl"' in clause
    assert 'format:"Vinyl"' in clause
    assert " OR " in clause
    # Parenthesised, or the ORs bind loose and swallow the AND beside them.
    assert clause.startswith("(") and clause.endswith(")")


# ── vinyl_rgids: the small, exact lookup used by a scan ──────────────────────

def test_returns_only_the_groups_that_have_a_pressing():
    with patch.object(scan, "_mb_get", return_value=_releases("g1", "g1", "g3")):
        assert scan.vinyl_rgids(["g1", "g2", "g3"]) == {"g1", "g3"}


def test_all_the_groups_go_out_in_one_query():
    """Three candidates must not cost three seconds of MusicBrainz throttle."""
    with patch.object(scan, "_mb_get", return_value=_releases("g1")) as get:
        scan.vinyl_rgids(["g1", "g2", "g3"])

    assert get.call_count == 1
    query = get.call_args.kwargs["params"]["query"]
    assert "rgid:g1" in query and "rgid:g2" in query and "rgid:g3" in query
    assert scan._vinyl_format_clause() in query


def test_no_groups_asks_musicbrainz_nothing():
    with patch.object(scan, "_mb_get") as get:
        assert scan.vinyl_rgids([]) == set()
    get.assert_not_called()


def test_an_unreachable_musicbrainz_confirms_nothing_instead_of_raising():
    """Silence is not evidence of no pressing — it just leaves the verdict to
    Claude. Raising here would fail a scan that already read the sleeve."""
    with patch.object(scan, "_mb_get",
                      side_effect=scan.MusicBrainzUnavailable("down")):
        assert scan.vinyl_rgids(["g1"]) == set()


# ── vinyl_rgids_for_artist: the paged sweep used by a search ─────────────────

def test_paging_stops_as_soon_as_every_wanted_group_is_accounted_for():
    pages = [_releases(*[f"g{i}" for i in range(100)], count=500),
             _releases(*["gX", "want-b"], count=500)]
    with patch.object(scan, "_mb_get", side_effect=pages) as get:
        found = scan.vinyl_rgids_for_artist("arid-1", {"g0", "want-b"})

    assert {"g0", "want-b"} <= found
    assert get.call_count == 2      # never reaches the third page


def test_the_sweep_gives_up_at_the_page_cap():
    """Pink Floyd has 605 vinyl album releases. An uncapped sweep would add
    seven seconds of throttled requests to one search; the groups still
    unaccounted for fall through to Claude instead."""
    full = _releases(*[f"g{i}" for i in range(100)], count=9999)
    with patch.object(scan, "_mb_get", return_value=full) as get:
        scan.vinyl_rgids_for_artist("arid-1", {"never-here"})

    assert get.call_count == scan.MB_VINYL_PAGES


def test_a_short_page_means_there_is_nothing_left_to_page():
    with patch.object(scan, "_mb_get", return_value=_releases("g1")) as get:
        assert scan.vinyl_rgids_for_artist("arid-1", {"unfindable"}) == {"g1"}

    assert get.call_count == 1


def test_a_sweep_cut_short_keeps_what_it_already_found():
    pages = [_releases(*[f"g{i}" for i in range(100)], count=500),
             scan.MusicBrainzUnavailable("down")]
    with patch.object(scan, "_mb_get", side_effect=pages):
        found = scan.vinyl_rgids_for_artist("arid-1", {"never-here"})

    assert "g7" in found


def test_the_sweep_searches_the_same_universe_the_discography_came_from():
    """lookup_discography shows albums, not singles or compilations. Sweeping
    wider would spend the page budget on pressings of rows nobody can see."""
    with patch.object(scan, "_mb_get", return_value=_releases("g1")) as get:
        scan.vinyl_rgids_for_artist("arid-1", {"g1"})

    query = get.call_args.kwargs["params"]["query"]
    assert "arid:arid-1" in query
    assert "primarytype:Album" in query
    assert "-secondarytype:Compilation" in query
    assert "-secondarytype:Live" in query
    assert scan._vinyl_format_clause() in query


# ── confirm_vinyl: Claude's read on the same question ───────────────────────

RELEASES = [
    {"artist": "Pink Floyd", "album_name": "Animals", "year": "1977"},
    {"artist": "Pink Floyd", "album_name": "Animals (2018 Remix)", "year": "2018"},
]


def test_one_verdict_comes_back_per_release():
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"verdicts": ["yes", "no"]})

    with patch.object(scan, "_anthropic_client", return_value=client):
        assert scan.confirm_vinyl(RELEASES) == ["yes", "no"]


def test_the_whole_list_goes_out_in_one_call():
    """Forty releases must cost one Haiku call, not forty."""
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"verdicts": ["yes"] * 40})

    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.confirm_vinyl([dict(RELEASES[0]) for _ in range(40)])

    assert client.messages.create.call_count == 1


def test_uses_haiku():
    client = Mock()
    client.messages.create.return_value = _claude_response({"verdicts": ["yes"]})

    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.confirm_vinyl(RELEASES[:1])

    assert client.messages.create.call_args.kwargs["model"] == "claude-haiku-4-5"


def test_no_effort_in_output_config():
    """`effort` errors on Haiku 4.5 — it exists only from Opus 4.5 upwards.

    Sending it would 400 every call, which confirm_vinyl's except-Exception
    would then swallow into a permanent all-unsure. Structured outputs
    (output_config.format) are fine on every model, so format stays.
    """
    client = Mock()
    client.messages.create.return_value = _claude_response({"verdicts": ["yes"]})

    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.confirm_vinyl(RELEASES[:1])

    config = client.messages.create.call_args.kwargs["output_config"]
    assert "effort" not in config
    assert "format" in config


def test_the_releases_are_named_in_the_prompt():
    client = Mock()
    client.messages.create.return_value = _claude_response({"verdicts": ["yes", "no"]})

    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.confirm_vinyl(RELEASES)

    sent = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Animals" in sent and "Pink Floyd" in sent and "1977" in sent


def test_a_short_answer_is_padded_rather_than_misaligned():
    """A verdict list shorter than the releases would shift every badge onto
    the wrong record if it were zipped as-is."""
    client = Mock()
    client.messages.create.return_value = _claude_response({"verdicts": ["yes"]})

    with patch.object(scan, "_anthropic_client", return_value=client):
        assert scan.confirm_vinyl(RELEASES) == ["yes", "unsure"]


def test_a_long_answer_is_truncated():
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"verdicts": ["yes", "no", "yes", "no"]})

    with patch.object(scan, "_anthropic_client", return_value=client):
        assert scan.confirm_vinyl(RELEASES) == ["yes", "no"]


def test_a_verdict_outside_the_enum_becomes_unsure():
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"verdicts": ["definitely", "no"]})

    with patch.object(scan, "_anthropic_client", return_value=client):
        assert scan.confirm_vinyl(RELEASES) == ["unsure", "no"]


def test_an_api_failure_leaves_every_release_unsure():
    """Unsure, not no: a search that found the releases is still worth showing,
    and badging the whole grid "no vinyl" because Claude was down is a lie."""
    client = Mock()
    client.messages.create.side_effect = RuntimeError("boom")

    with patch.object(scan, "_anthropic_client", return_value=client):
        assert scan.confirm_vinyl(RELEASES) == ["unsure", "unsure"]


def test_no_releases_spends_nothing():
    with patch.object(scan, "_anthropic_client") as client:
        assert scan.confirm_vinyl([]) == []
    client.assert_not_called()


def test_the_call_lands_in_the_spend_ledger():
    client = Mock()
    client.messages.create.return_value = _claude_response({"verdicts": ["yes", "no"]})

    spent = []
    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.confirm_vinyl(RELEASES, usage_out=spent)

    assert spent == [{"model": "claude-haiku-4-5",
                      "input_tokens": 120, "output_tokens": 8}]


def test_the_schema_admits_only_the_three_verdicts():
    verdicts = scan._VINYL_SCHEMA["properties"]["verdicts"]

    jsonschema.validate(["yes", "no", "unsure"], verdicts)   # must not raise
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(["maybe"], verdicts)


# ── _vinyl_status: how the two answers combine ──────────────────────────────

@pytest.mark.parametrize("mb_has,verdict,expected", [
    (True,  "yes",    "confirmed"),
    # MusicBrainz catalogues pressings; Claude recalls them. A catalogued
    # pressing outranks a recollection that it never existed.
    (True,  "no",     "confirmed"),
    (True,  "unsure", "confirmed"),
    # MusicBrainz silence is not evidence — its format data is thin, badly so
    # for Brazilian pressings, which is most of this collection.
    (False, "yes",    "likely"),
    (False, "unsure", "likely"),
    (False, "no",     "none"),
])
def test_the_truth_table(mb_has, verdict, expected):
    assert scan._vinyl_status(mb_has, verdict) == expected


# ── flag_vinyl: the whole question, answered over a list of rows ────────────

def test_every_row_is_stamped():
    rows = [{"mbid": "g1", "artist": "A", "album_name": "One"},
            {"mbid": "g2", "artist": "A", "album_name": "Two"},
            {"mbid": "g3", "artist": "A", "album_name": "Three"}]

    with patch.object(scan, "vinyl_rgids", return_value={"g1"}), \
         patch.object(scan, "confirm_vinyl", return_value=["no", "yes", "no"]):
        scan.flag_vinyl(rows)

    assert [r["vinyl"] for r in rows] == ["confirmed", "likely", "none"]


def test_a_search_sweeps_by_artist_rather_than_by_group():
    """Forty groups ORed into one rgid query risks a single prolific album's
    pressings filling the page and hiding the other thirty-nine."""
    rows = [{"mbid": f"g{i}", "artist": "A", "album_name": str(i)}
            for i in range(40)]

    with patch.object(scan, "vinyl_rgids_for_artist",
                      return_value=set()) as sweep, \
         patch.object(scan, "vinyl_rgids") as by_group, \
         patch.object(scan, "confirm_vinyl", return_value=["no"] * 40):
        scan.flag_vinyl(rows, arid="arid-1")

    by_group.assert_not_called()
    assert sweep.call_args.args[0] == "arid-1"
    assert sweep.call_args.args[1] == {f"g{i}" for i in range(40)}


def test_no_rows_asks_nobody():
    with patch.object(scan, "vinyl_rgids") as by_group, \
         patch.object(scan, "confirm_vinyl") as ask:
        scan.flag_vinyl([])

    by_group.assert_not_called()
    ask.assert_not_called()


def test_a_row_without_an_mbid_still_gets_a_verdict():
    """A Spotify scan MusicBrainz could not match has no group to look up, so
    Claude is the only one who can answer."""
    rows = [{"mbid": None, "artist": "A", "album_name": "One"}]

    with patch.object(scan, "vinyl_rgids", return_value=set()), \
         patch.object(scan, "confirm_vinyl", return_value=["yes"]):
        scan.flag_vinyl(rows)

    assert rows[0]["vinyl"] == "likely"
