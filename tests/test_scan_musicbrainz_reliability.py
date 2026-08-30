"""MusicBrainz reliability and ranking.

Three faults this module pins down, all measured against the live API before
being fixed here:

1. musicbrainz.org sheds load with a 503 whose body is "the MusicBrainz web
   server is currently busy" and whose rate-limit headers show the caller's own
   quota nowhere near spent (X-RateLimit-Remaining 13/15, 523/1200) and
   Retry-After 0. Roughly a third to a half of identical back-to-back searches
   came back that way. The old code turned that into an empty candidate list,
   indistinguishable from "this record is not in MusicBrainz" — which is why
   the same photo scanned twice gave no matches and then matches.

2. The Lucene query wrapped both fields in double quotes, which makes each an
   exact-phrase match. Every one of these real sleeves returned zero groups
   quoted and the right album at score 100 unquoted: "Space Is the Place
   (Reissue)", "Kind of Blue [Mono]", "A Divina Comédia ou Ando Meio
   Desligado", and the OCR-style typo "Live at Carnagie Hal".

3. Candidates were used in the order MusicBrainz returned them, so a same-score
   near-miss or a single outranked the album actually being held: "Clube da
   Esquina" put "Clube da Esquina 2" (score 100) above "Clube da Esquina"
   (91), and AC/DC's "Back in Black" put the single above the album.
"""
from unittest.mock import patch, Mock

import pytest

import scan


@pytest.fixture(autouse=True)
def no_real_sleeping(monkeypatch):
    """Neutralise the 1 req/sec throttle so the suite doesn't crawl."""
    monkeypatch.setattr(scan.time, "sleep", lambda _s: None)
    monkeypatch.setattr(scan, "_mb_last_call", 0.0)


def _response(payload, status=200):
    mock = Mock()
    mock.status_code = status
    mock.json.return_value = payload
    mock.headers = {}
    if status >= 400:
        mock.raise_for_status.side_effect = scan.requests.HTTPError(
            f"{status} Server Error", response=mock
        )
    else:
        mock.raise_for_status = Mock()
    return mock


def _groups(*specs):
    """Build a release-group search payload.

    Each spec is (title, score, primary-type) or
    (title, score, primary-type, secondary-types, first-release-date).
    """
    groups = []
    for i, spec in enumerate(specs):
        title, score, ptype = spec[:3]
        secondary = spec[3] if len(spec) > 3 else None
        released = spec[4] if len(spec) > 4 else "1972"
        groups.append({
            "id": f"mbid-{i}", "score": score, "title": title,
            "primary-type": ptype, "secondary-types": secondary,
            "first-release-date": released,
            "artist-credit": [{"artist": {"id": "artist-1", "name": "Some Artist"}}],
        })
    return {"release-groups": groups}


ARTIST = {"id": "artist-1", "country": "BR"}


# ── 1. transient 503s are retried, not reported as "no such record" ──────────

def test_retries_a_503_and_returns_the_match():
    """A load-shed 503 followed by a 200 must yield the match, not an empty list.

    This is the reported bug exactly: same photo, no matches, scan again,
    matches.
    """
    responses = [
        _response({"error": "busy"}, status=503),
        _response(_groups(("Racional", 100, "Album"))),
        _response(ARTIST),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("Tim Maia", "Racional")

    assert [c["album_name"] for c in candidates] == ["Racional"]


def test_retries_a_timeout_too():
    responses = [
        scan.requests.Timeout("timed out"),
        _response(_groups(("Racional", 100, "Album"))),
        _response(ARTIST),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("Tim Maia", "Racional")

    assert [c["album_name"] for c in candidates] == ["Racional"]


def test_gives_up_after_the_attempt_budget():
    """Retries are bounded — a hard outage must not hang the scan."""
    with patch.object(scan.requests, "get",
                      return_value=_response({"error": "busy"}, 503)) as get:
        with pytest.raises(scan.MusicBrainzUnavailable):
            scan.lookup_musicbrainz("Tim Maia", "Racional")

    assert get.call_count == scan.MB_MAX_ATTEMPTS


def test_unavailable_is_distinct_from_no_such_release():
    """The two outcomes the UI must word differently.

    An outage raises; a genuine miss returns an empty list. Collapsing both
    into [] is what made the form claim MusicBrainz had no release group for a
    record it had simply failed to ask about.
    """
    with patch.object(scan.requests, "get",
                      return_value=_response({"release-groups": []})):
        assert scan.lookup_musicbrainz("Nobody", "Nothing") == []

    with patch.object(scan.requests, "get",
                      side_effect=scan.requests.RequestException):
        with pytest.raises(scan.MusicBrainzUnavailable):
            scan.lookup_musicbrainz("Tim Maia", "Racional")


def test_a_failed_country_lookup_still_yields_the_candidate():
    """Country is a nice-to-have; the release must survive losing it.

    Only the search failing means "we could not ask". An artist lookup that
    503s past its retries costs the country field and nothing else.
    """
    responses = [_response(_groups(("Racional", 100, "Album")))]
    responses += [_response({"error": "busy"}, 503)] * scan.MB_MAX_ATTEMPTS
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("Tim Maia", "Racional")

    assert len(candidates) == 1
    assert candidates[0]["country"] is None
    assert candidates[0]["year"] == "1972"


def test_retries_are_throttled_like_any_other_call():
    """Retrying must not burst past the 1 req/sec MusicBrainz asks for —
    hammering a server that just said it was busy is what gets a client
    blocked."""
    calls = []
    responses = [
        _response({"error": "busy"}, 503),
        _response(_groups(("Racional", 100, "Album"))),
        _response(ARTIST),
    ]
    with patch.object(scan, "_throttle_musicbrainz", side_effect=lambda: calls.append(1)):
        with patch.object(scan.requests, "get", side_effect=responses):
            scan.lookup_musicbrainz("Tim Maia", "Racional")

    assert len(calls) == 3   # two search attempts + one artist lookup


# ── 2. the query must survive ordinary sleeve text ───────────────────────────

def test_query_does_not_force_an_exact_phrase():
    with patch.object(scan.requests, "get",
                      return_value=_response({"release-groups": []})) as get:
        scan.lookup_musicbrainz("Sun Ra", "Space Is the Place")

    query = get.call_args.kwargs["params"]["query"]
    assert '"' not in query, f"still an exact-phrase query: {query}"


def test_query_binds_each_term_to_its_own_field():
    """Dropping the quotes must not drop the field binding: bare
    `artist:Sun Ra` binds only "Sun" and lets "Ra" drift into the default
    field, which matches other artists' releases."""
    with patch.object(scan.requests, "get",
                      return_value=_response({"release-groups": []})) as get:
        scan.lookup_musicbrainz("Sun Ra", "Space Is the Place")

    query = get.call_args.kwargs["params"]["query"]
    assert "artist:(Sun Ra)" in query
    assert "releasegroup:(Space Is the Place)" in query


@pytest.mark.parametrize("artist, album", [
    ("AC/DC", "Back in Black"),
    ("Sun Ra", "Space Is the Place (Reissue)"),
    ("Miles Davis", "Kind of Blue [Mono]"),
    ("Someone", 'The "Best" Of'),
    ("Someone", "Album: The Sequel"),
    ("Someone", "Yes / No ~ Maybe!"),
])
def test_lucene_metacharacters_are_escaped(artist, album):
    """Sleeve text is copied verbatim into a Lucene query. A slash, bracket,
    colon or quote read off the cover must not be able to change what the query
    means or make it unparseable — an unescaped `(` alone unbalances the
    field-binding parens and MusicBrainz rejects the whole search.
    """
    with patch.object(scan.requests, "get",
                      return_value=_response({"release-groups": []})) as get:
        scan.lookup_musicbrainz(artist, album)

    query = get.call_args.kwargs["params"]["query"]

    # Expected escaping worked out independently of the implementation: every
    # metacharacter in the sleeve text gets a backslash, and nothing else moves.
    def escaped(value):
        return "".join("\\" + c if c in '+-&|!(){}[]^"~*?:\\/' else c for c in value)

    assert query == f"artist:({escaped(artist)}) AND releasegroup:({escaped(album)})"

    # And the parens that bind the fields are still balanced, which is the
    # property the escaping exists to protect.
    depth = 0
    for i, ch in enumerate(query):
        if i and query[i - 1] == "\\":
            continue
        depth += (ch == "(") - (ch == ")")
        assert depth >= 0, f"unbalanced parens in {query!r}"
    assert depth == 0, f"unbalanced parens in {query!r}"


def test_album_is_optional():
    with patch.object(scan.requests, "get",
                      return_value=_response({"release-groups": []})) as get:
        scan.lookup_musicbrainz("Sun Ra", "")

    query = get.call_args.kwargs["params"]["query"]
    assert query == "artist:(Sun Ra)"


# ── 3. the best match must actually be the best match ────────────────────────

def test_exact_title_beats_a_higher_scoring_near_miss():
    """Measured live: "Clube da Esquina" returns "Clube da Esquina 2" at score
    100 ahead of "Clube da Esquina" at 91."""
    responses = [
        _response(_groups(("Clube da Esquina 2", 100, "Album"),
                          ("Clube da Esquina", 91, "Album"))),
        _response(ARTIST),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("Milton Nascimento", "Clube da Esquina")

    assert candidates[0]["album_name"] == "Clube da Esquina"


def test_album_beats_a_single_of_the_same_name():
    """Measured live: AC/DC "Back in Black" returns the single first, both at
    score 100. This is a vinyl LP collection — the album is the right answer,
    and the single carries a different year."""
    responses = [
        _response(_groups(("Back in Black", 100, "Single"),
                          ("Back in Black", 100, "Album"))),
        _response(ARTIST),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("AC/DC", "Back in Black")

    assert candidates[0]["type"] == "Album"


def test_exact_title_match_ignores_case_accents_and_punctuation():
    """MusicBrainz stores "A divina comédia ou ando meio desligado"; the sleeve
    reads "A Divina Comédia ou Ando Meio Desligado"."""
    responses = [
        _response(_groups(("Some Other Record", 100, "Album"),
                          ("A divina comédia ou ando meio desligado", 92, "Album"))),
        _response(ARTIST),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz(
            "Os Mutantes", "A Divina Comédia ou Ando Meio Desligado")

    assert candidates[0]["album_name"] == "A divina comédia ou ando meio desligado"


def test_low_scoring_noise_is_dropped():
    """Measured live: searching "A Divina Comédia" also returns '"A" e o "Z"'
    and "A Arte De Os Mutantes" at score 37. Offering those as candidates is
    what makes the scan feel like it guessed."""
    responses = [
        _response(_groups(("A divina comédia ou ando meio desligado", 100, "Album"),
                          ('"A" e o "Z"', 37, "Album"),
                          ("A Arte De Os Mutantes", 37, "Album"))),
        _response(ARTIST),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("Os Mutantes", "A Divina Comédia")

    assert [c["album_name"] for c in candidates] == [
        "A divina comédia ou ando meio desligado"]


def test_the_best_candidate_survives_the_score_floor():
    """A weak best match is still the best information available — the floor
    trims the tail, it must never empty a non-empty result.

    The title has to be the record's, though: a low score is not the same thing
    as a title that says something else, and only the score is under test here.
    Emptying the list for an irrelevant title is now the point of _title_match.
    """
    responses = [
        _response(_groups(("Pressing", 20, "Album"))),
        _response(ARTIST),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("Obscure", "Pressing")

    assert len(candidates) == 1


def test_ranking_happens_before_the_three_candidate_cut():
    """MusicBrainz is asked for 5 and the form shows 3. Truncating first can
    cut the exact match, so the ordering has to come first."""
    responses = [
        # All five are plausibly this record, so the ordering is what decides.
        _response(_groups(("Racional Ao Vivo", 99, "Album"),
                          ("Racional Remixado", 98, "Album"),
                          ("Racional Instrumental", 97, "Album"),
                          ("Racional Reissue", 96, "Album"),
                          ("Racional", 95, "Album"))),
        _response(ARTIST),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("Tim Maia", "Racional")

    assert candidates[0]["album_name"] == "Racional"
    assert len(candidates) == 3


def test_an_original_pressing_beats_a_later_compilation():
    """Measured live: "Tim Maia / Racional" returns the 2002 compilation "Tim
    Maia Racional" ahead of the 1975 and 1976 albums, all three at score 100.

    Taking the compilation stamps 2002 on a record pressed in 1975 — the year
    is the main thing this lookup exists to supply, so getting it from a CD-era
    repackage is the worst kind of wrong: confident and plausible.
    """
    responses = [
        _response(_groups(
            ("Tim Maia Racional", 100, "Album", ["Compilation"], "2002"),
            ("Racional (Vol 1)", 100, "Album", None, "1975-03-15"))),
        _response(ARTIST),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("Tim Maia", "Racional")

    assert candidates[0]["album_name"] == "Racional (Vol 1)"
    assert candidates[0]["year"] == "1975"
    # Still offered, just not first — the user may well own the compilation.
    assert candidates[1]["album_name"] == "Tim Maia Racional"


def test_a_live_album_is_not_demoted_like_a_compilation():
    """"Live" is a secondary type too, and a live LP is an ordinary record to
    own. Only Compilation is the one that usually means a later repackage."""
    responses = [
        _response(_groups(
            ("Live at Carnegie Hall", 100, "Album", ["Live"], "1973"),
            ("Bill Withers Greatest Hits", 100, "Album", ["Compilation"], "1981"))),
        _response(ARTIST),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("Bill Withers", "Live at Carnegie Hall")

    assert candidates[0]["album_name"] == "Live at Carnegie Hall"


def test_an_exact_title_still_wins_over_the_compilation_rule():
    """If the sleeve really does name the compilation, it is the right answer."""
    responses = [
        _response(_groups(
            ("Nova Bis", 100, "Album", ["Compilation"], "1975"),
            ("Something Else", 100, "Album", None, "1973"))),
        _response(ARTIST),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("Tim Maia", "Nova Bis")

    assert candidates[0]["album_name"] == "Nova Bis"


def test_retries_back_off_instead_of_hammering_once_a_second():
    """A 1-second gap three times over does not outlast a MusicBrainz load-shed.

    Driven live, back-to-back searches kept failing all three attempts while the
    shed lasted. The gap has to widen, or the retry budget is spent inside the
    same bad couple of seconds it was meant to ride out.
    """
    slept = []
    responses = [_response({"error": "busy"}, 503)] * (scan.MB_MAX_ATTEMPTS - 1)
    responses += [_response(_groups(("Racional", 100, "Album"))), _response(ARTIST)]

    with patch.object(scan.time, "sleep", side_effect=slept.append):
        with patch.object(scan.requests, "get", side_effect=responses):
            candidates = scan.lookup_musicbrainz("Tim Maia", "Racional")

    assert [c["album_name"] for c in candidates] == ["Racional"]
    backoffs = [s for s in slept if s >= scan.MB_RETRY_BACKOFF]
    assert len(backoffs) == scan.MB_MAX_ATTEMPTS - 1, f"no widening gap: {slept}"
    assert backoffs == sorted(backoffs) and backoffs[-1] > backoffs[0], \
        f"gap did not widen: {backoffs}"


def test_a_server_named_retry_after_is_honoured():
    """When MusicBrainz says how long to wait, waiting less is rude and waiting
    much more is slow. Capped, so a wild header cannot stall a scan."""
    slept = []
    busy = _response({"error": "busy"}, 503)
    busy.headers = {"Retry-After": "3"}
    responses = [busy, _response(_groups(("Racional", 100, "Album"))), _response(ARTIST)]

    with patch.object(scan.time, "sleep", side_effect=slept.append):
        with patch.object(scan.requests, "get", side_effect=responses):
            scan.lookup_musicbrainz("Tim Maia", "Racional")

    assert 3 in slept, f"Retry-After was ignored: {slept}"


def test_an_absurd_retry_after_is_capped():
    slept = []
    busy = _response({"error": "busy"}, 503)
    busy.headers = {"Retry-After": "9000"}
    responses = [busy, _response(_groups(("Racional", 100, "Album"))), _response(ARTIST)]

    with patch.object(scan.time, "sleep", side_effect=slept.append):
        with patch.object(scan.requests, "get", side_effect=responses):
            scan.lookup_musicbrainz("Tim Maia", "Racional")

    assert max(slept) <= scan.MB_MAX_BACKOFF, f"uncapped wait: {slept}"


def test_the_optional_country_lookup_gives_up_sooner_than_the_search():
    """The search is worth waiting for; the country is not. Spending the full
    budget on it would add seconds to a scan for a field the form can live
    without."""
    responses = [_response(_groups(("Racional", 100, "Album")))]
    responses += [_response({"error": "busy"}, 503)] * scan.MB_MAX_ATTEMPTS
    with patch.object(scan.requests, "get", side_effect=responses) as get:
        candidates = scan.lookup_musicbrainz("Tim Maia", "Racional")

    assert candidates[0]["country"] is None
    # one search + the country's own smaller budget
    assert get.call_count == 1 + scan.MB_COUNTRY_ATTEMPTS
    assert scan.MB_COUNTRY_ATTEMPTS < scan.MB_MAX_ATTEMPTS


# ── 5. a record MusicBrainz does not have must come back empty ───────────────
#
# The sleeve that exposed this: Cartola's volume of the Abril Cultural series
# "Nova História da Música Popular Brasileira". Browsing the artist confirms
# MusicBrainz holds 25 Cartola release groups and none of them is it, though the
# series itself is there for Chico Buarque, Milton Nascimento, Noel Rosa and
# seven more. So the honest answer is "not found" — but the search returned four
# confident-looking hits, because releasegroup:(a b c) is an OR over the terms
# and this title's tail, "da Música Popular Brasileira", is four common words
# that a great many Brazilian compilations share.

def test_a_title_sharing_only_common_words_is_not_a_match():
    """Live, this scored 100: "Coleção Folha Raízes da Música Popular
    Brasileira, Volume 3" against "Nova História da Música Popular Brasileira".

    It shares the four generic words and neither distinctive one. Offering it
    puts 2010 on a 1970s LP, which is the failure the user actually sees.
    """
    responses = [
        _response(_groups(
            ("Coleção Folha Raízes da Música Popular Brasileira, Volume 3",
             100, "Album", ["Compilation"], "2010"),
            ("A música brasileira deste século por seus autores e intérpretes: "
             "Cartola", 70, "Album", ["Live"], ""),
            ("Nova Bis - Cartola", 65, "Album", ["Compilation"], "2005"))),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz(
            "Cartola", "Nova História da Música Popular Brasileira")

    assert candidates == []


def test_the_same_series_still_matches_the_artist_it_does_have():
    """The control for the test above, and a regression in its own right.

    MusicBrainz does hold this series for Chico Buarque, at score 100. The
    rejection above must come from the title not matching, not from the app
    having become shy about long titles.
    """
    responses = [
        _response(_groups(
            ("Nova História da Música Popular Brasileira: Chico Buarque",
             100, "Album", ["Compilation"], "1976"),)),
        _response(ARTIST),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz(
            "Chico Buarque", "Nova História da Música Popular Brasileira")

    assert candidates[0]["year"] == "1976"


def test_a_strong_compilation_beats_a_weak_non_compilation():
    """The compilation rule must break ties, not overrule the score.

    Measured live on the sleeve above: demoting every compilation put "A música
    brasileira deste século ... Chico Buarque" (a 2000 live album, score 55)
    ahead of the correct 1976 volume (score 100), because the correct answer is
    itself a compilation. A whole series of records was being dated by whatever
    non-compilation happened to share a word with it.
    """
    responses = [
        _response(_groups(
            ("A música brasileira deste século por seus autores e intérpretes: "
             "Chico Buarque", 55, "Album", ["Live"], "2000"),
            ("Nova História da Música Popular Brasileira: Chico Buarque",
             100, "Album", ["Compilation"], "1976"))),
        _response(ARTIST),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz(
            "Chico Buarque", "Nova História da Música Popular Brasileira")

    assert candidates[0]["year"] == "1976"


def test_a_self_titled_album_survives_the_relevance_check():
    """The title is the artist's name, so stripping the artist out of it before
    comparing leaves nothing to compare. Cartola's 1974 "Cartola" is the real
    case; it must not be gated away as irrelevant to the query "Cartola"."""
    responses = [
        _response(_groups(("Cartola", 100, "Album", None, "1974"))),
        _response(ARTIST),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("Cartola", "Cartola")

    assert candidates[0]["year"] == "1974"


@pytest.mark.parametrize("album, title", [
    ("Kind of Blue [Mono]", "Kind of Blue"),
    ("Space Is the Place (Reissue)", "Space Is the Place"),
    ("Racional", "Racional (Vol 1)"),
    ("Clube da Esquina (50th Anniversary Edition)", "Clube da Esquina"),
])
def test_an_edition_or_volume_suffix_does_not_fail_the_relevance_check(album, title):
    """A parenthesised or bracketed suffix is on the sleeve or in the database,
    rarely both. It must not count against the match on either side."""
    responses = [
        _response(_groups((title, 100, "Album", None, "1970"))),
        _response(ARTIST),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("Some Artist", album)

    assert candidates and candidates[0]["album_name"] == title


def test_a_dated_release_wins_a_tie_with_an_undated_one():
    """The year is the point of the lookup, and it is read from the first
    candidate only. Where nothing else separates two hits, the one that can
    actually answer the question is the better first."""
    responses = [
        _response(_groups(
            ("Some Album", 100, "Album", None, ""),
            ("Some Album", 100, "Album", None, "1975"))),
        _response(ARTIST),
    ]
    with patch.object(scan.requests, "get", side_effect=responses):
        candidates = scan.lookup_musicbrainz("Some Artist", "Some Album")

    assert candidates[0]["year"] == "1975"
