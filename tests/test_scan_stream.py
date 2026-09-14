"""The streaming half of /api/scan. The JSON half is covered by
tests/test_scan_endpoint.py and must keep behaving identically."""

import json
import pytest
from unittest.mock import patch
import app as app_module


def test_sse_frame_has_event_data_and_blank_line():
    frame = app_module._sse("step", {"id": "mb", "state": "run"})
    assert frame == 'event: step\ndata: {"id":"mb","state":"run"}\n\n'


def test_sse_payload_is_one_line_even_when_nested():
    """A newline inside the data would end the frame early and split one
    event into two unparseable halves."""
    frame = app_module._sse("done", {"candidates": [{"album_name": "A\nB"}]})
    body = [ln for ln in frame.split("\n") if ln.startswith("data: ")]
    assert len(body) == 1
    assert json.loads(body[0][6:])["candidates"][0]["album_name"] == "A\nB"


SSE = {"Accept": "text/event-stream"}


def frames(response):
    """Parse an SSE body into [(event, payload), …]."""
    out = []
    for block in response.get_data(as_text=True).split("\n\n"):
        if not block.strip():
            continue
        event = data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        out.append((event, data))
    return out


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        with test_client.session_transaction() as session:
            session["authed"] = True
        yield test_client


@pytest.fixture(autouse=True)
def _pipeline_offline():
    """Every outbound call stubbed; these tests are about the event sequence."""
    with patch.object(app_module.scan, "extract_from_image",
                      return_value={"artist": "Jorge Ben", "album_name": "Africa Brasil",
                                    "genre": "Samba", "label": None, "catalog_number": None}), \
         patch.object(app_module.scan, "lookup_musicbrainz",
                      return_value=[{"mbid": "rg1", "year": "1976", "country": "BR",
                                     "artist": "Jorge Ben", "album_name": "Africa Brasil",
                                     "type": "Album", "label": None}]), \
         patch.object(app_module.scan, "fetch_cover", return_value=None), \
         patch.object(app_module.scan, "flag_vinyl",
                      side_effect=lambda rows, **kw: [r.setdefault("vinyl", "yes") for r in rows]), \
         patch.object(app_module.scan, "find_duplicate", return_value=None):
        yield


def test_photo_scan_streams_its_stages_in_order(client):
    got = frames(client.post("/api/scan", headers=SSE,
                             json={"image": "data:image/jpeg;base64,x"}))
    assert [e for e, _ in got][-1] == "done"
    # Collect the order of DISTINCT stages entering "run", collapsing
    # consecutive repeats: the cover stage opens with a bare
    # {"id":"cover","state":"run"} and then emits one
    # {"id":"cover","state":"run","n":i+1,"of":N} per candidate, so "cover"
    # legitimately repeats and a naive collection would see it twice.
    ids = []
    for e, p in got:
        if e == "step" and p["state"] == "run" and (not ids or ids[-1] != p["id"]):
            ids.append(p["id"])
    assert ids == ["vision", "mb", "cover", "vinyl", "shelf"]


def test_spotify_scan_streams_spotify_then_genre_never_vision(client):
    """Spec: 'a Spotify scan emits spotify and genre where the photo path
    emits vision.' Pins SCAN_STAGES.spotify's ids and order in templates/
    index.html against what the server actually streams — nothing enforced
    that before this test existed."""
    with patch.object(app_module.scan, "extract_from_spotify",
                      return_value={"artist": "Jorge Ben", "album_name": "Africa Brasil",
                                    "image_url": None}), \
         patch.object(app_module.scan, "classify_genre", return_value="Samba"):
        got = frames(client.post("/api/scan", headers=SSE,
                                 json={"spotify_url": "https://open.spotify.com/album/x"}))
    assert [e for e, _ in got][-1] == "done"
    ids = []
    for e, p in got:
        if e == "step" and p["state"] == "run" and (not ids or ids[-1] != p["id"]):
            ids.append(p["id"])
    assert ids == ["spotify", "genre", "mb", "cover", "vinyl", "shelf"]
    assert "vision" not in [p["id"] for e, p in got if e == "step"]


def test_done_payload_matches_the_json_path(client):
    streamed = frames(client.post("/api/scan", headers=SSE,
                                  json={"image": "data:image/jpeg;base64,x"}))[-1][1]
    plain = client.post("/api/scan", json={"image": "data:image/jpeg;base64,x"}).get_json()
    assert streamed == plain


def test_json_path_is_untouched_without_the_accept_header(client):
    response = client.post("/api/scan", json={"image": "data:image/jpeg;base64,x"})
    assert response.status_code == 200
    assert response.mimetype == "application/json"


def test_unreachable_musicbrainz_is_a_skip_not_an_error(client):
    with patch.object(app_module.scan, "lookup_musicbrainz",
                      side_effect=app_module.scan.MusicBrainzUnavailable("down")):
        got = frames(client.post("/api/scan", headers=SSE,
                                 json={"image": "data:image/jpeg;base64,x"}))
    assert not [e for e, _ in got if e == "error"]
    assert ("step", {"id": "mb", "state": "skip",
                     "detail": "MusicBrainz unavailable — no year or alternates"}) in got
    assert got[-1][0] == "done"
    assert got[-1][1]["lookup_failed"] is True


def test_a_bad_input_becomes_an_error_event_carrying_its_status(client):
    with patch.object(app_module.scan, "extract_from_image",
                      side_effect=ValueError("that is not a sleeve")):
        got = frames(client.post("/api/scan", headers=SSE,
                                 json={"image": "data:image/jpeg;base64,x"}))
    assert got[-1] == ("error", {"error": "that is not a sleeve", "status": 400})


def test_spend_is_banked_even_when_the_client_never_reads_the_stream(client):
    """Cancel abandons the result but not the bill — the call was billed the
    moment it returned. The generator's finally is what guarantees this.

    The Flask test client normally drains the whole response before handing
    it back, so a naive post()-then-assert never actually disconnects — it
    only proves the ordinary completion path, which would pass even against
    a route that doesn't stream at all. To exercise a real client hang-up we
    have to reach past the helper and close the un-buffered app iterator
    ourselves after pulling just one frame, which is what drops the
    generator via GeneratorExit the way an abandoned request would.
    """
    with patch.object(app_module, "_record_scan_spend") as banked:
        response = client.post("/api/scan", headers=SSE,
                               json={"image": "data:image/jpeg;base64,x"},
                               buffered=False)
        iterator = iter(response.response)  # the un-drained stream
        next(iterator)                      # one frame only
        iterator.close()                    # the client hangs up here
    assert banked.called


def test_spend_lands_in_the_database_while_streaming():
    """stream_with_context exists so the generator can still touch db.session
    once it is running outside the view function's own request handling —
    without it, the request context Flask pushed for the view call is gone
    the instant the view returns a Response object, and _record_scan_spend's
    insert/commit (running inside the generator's `finally`, drained lazily
    as the client reads the stream) would hit "working outside of
    application context" the moment a real API call had billed anything.

    Deliberately NOT using the shared `client` fixture: that fixture opens
    the test client with `with app_module.app.test_client() as test_client:`,
    which pushes an ambient application context that stays alive for the
    whole test. Under that ambient context db.session stays legal on its own,
    regardless of stream_with_context — which would make this test pass even
    with stream_with_context deleted, guarding nothing. Building the client
    here without that `with` wrapper leaves no context bleeding in, so the
    generator's ability to touch db.session mid-stream depends on
    stream_with_context alone, the way it does in production.

    The other streaming tests never catch any of this: their stub
    extract_from_image leaves usage_out empty, so _record_scan_spend
    early-returns before touching the database at all. Here the stub
    actually appends a call, forcing a real ScanSpend row through the
    generator mid-stream.
    """
    def spending_extract(image, genres, usage_out=None):
        if usage_out is not None:
            usage_out.append({"model": "claude-sonnet-5",
                              "input_tokens": 1000, "output_tokens": 200})
        return {"artist": "Jorge Ben", "album_name": "Africa Brasil",
                "genre": "Samba", "label": None, "catalog_number": None}

    with app_module.app.app_context():
        app_module.ScanSpend.query.delete()
        app_module.db.session.commit()

    app_module.app.config["TESTING"] = True
    test_client = app_module.app.test_client()  # no `with` — no ambient context
    with test_client.session_transaction() as session:
        session["authed"] = True

    with patch.object(app_module.scan, "extract_from_image", side_effect=spending_extract):
        frames(test_client.post("/api/scan", headers=SSE,
                                json={"image": "data:image/jpeg;base64,x"}))

    with app_module.app.app_context():
        rows = app_module.ScanSpend.query.all()
    assert len(rows) == 1
    assert rows[0].source == "photo"
    assert rows[0].model == "claude-sonnet-5"


# ── the streaming half of /api/search ───────────────────────────────────────
#
# _pipeline_offline (above) is autouse for this whole module. It stubs
# scan.flag_vinyl (setdefault "yes") and scan.find_duplicate (None) — both
# used by the search pipeline too — so the tests below only need to patch the
# search-specific calls: parse_search_query, lookup_artist,
# lookup_discography, search_covers.

_SEARCH_DISCOGRAPHY = [
    {"mbid": "m1", "year": "1970", "country": "BR", "artist": "Jorge Ben",
     "credited": "Jorge Ben", "canonical": "Jorge Ben Jor",
     "album_name": "Força bruta", "type": "Album", "label": None},
    {"mbid": "m2", "year": "1976", "country": "BR", "artist": "Jorge Ben",
     "credited": "Jorge Ben", "canonical": "Jorge Ben Jor",
     "album_name": "África Brasil", "type": "Album", "label": None},
]


def _search_patches():
    return [
        patch.object(app_module.scan, "parse_search_query",
                     return_value={"artist": "Jorge Ben", "album": None}),
        patch.object(app_module.scan, "lookup_artist",
                     return_value={"mbid": "19499124", "name": "Jorge Ben Jor",
                                   "country": "BR"}),
        patch.object(app_module.scan, "lookup_discography",
                     return_value=[dict(r) for r in _SEARCH_DISCOGRAPHY]),
        patch.object(app_module.scan, "search_covers"),
    ]


def test_search_streams_its_stages_in_order(client):
    patches = _search_patches()
    for p in patches:
        p.start()
    try:
        got = frames(client.post("/api/search", headers=SSE,
                                 json={"query": "jorge ben"}))
    finally:
        for p in reversed(patches):
            p.stop()
    assert [e for e, _ in got][-1] == "done"
    ids = []
    for e, p in got:
        if e == "step" and p["state"] == "run" and (not ids or ids[-1] != p["id"]):
            ids.append(p["id"])
    assert ids == ["parse", "artist", "discography", "covers", "vinyl", "shelf"]


def test_search_done_payload_matches_the_json_path(client):
    patches = _search_patches()
    for p in patches:
        p.start()
    try:
        streamed = frames(client.post("/api/search", headers=SSE,
                                      json={"query": "jorge ben"}))[-1][1]
        plain = client.post("/api/search", json={"query": "jorge ben"}).get_json()
    finally:
        for p in reversed(patches):
            p.stop()
    assert streamed == plain


def test_search_json_path_is_untouched_without_the_accept_header(client):
    patches = _search_patches()
    for p in patches:
        p.start()
    try:
        response = client.post("/api/search", json={"query": "jorge ben"})
    finally:
        for p in reversed(patches):
            p.stop()
    assert response.status_code == 200
    assert response.mimetype == "application/json"


def test_search_unreachable_musicbrainz_is_an_error_not_a_skip(client):
    """Unlike /api/scan, an unreachable MusicBrainz is fatal for a search —
    there is no sleeve photo to fall back on, so this must be an "error"
    event carrying 502, and no stage may report "skip" on the way there."""
    with patch.object(app_module.scan, "parse_search_query",
                      return_value={"artist": "Jorge Ben", "album": None}), \
         patch.object(app_module.scan, "lookup_artist",
                      side_effect=app_module.scan.MusicBrainzUnavailable("down")):
        got = frames(client.post("/api/search", headers=SSE,
                                 json={"query": "jorge ben"}))
    assert not [e for e, p in got if e == "step" and p.get("state") == "skip"]
    assert got[-1] == ("error", {
        "error": "Couldn't reach MusicBrainz — try again in a moment",
        "status": 502})


def test_search_no_such_artist_skips_and_still_ends_with_done(client):
    """lookup_artist returning None is a legitimate empty result, not a
    failure: the artist stage (and everything downstream of it) reports
    "skip", but the stream still ends in a normal "done" with results: []."""
    with patch.object(app_module.scan, "parse_search_query",
                      return_value={"artist": "Zzz", "album": None}), \
         patch.object(app_module.scan, "lookup_artist", return_value=None):
        got = frames(client.post("/api/search", headers=SSE,
                                 json={"query": "zzzzz"}))
    assert not [e for e, _ in got if e == "error"]
    assert ("step", {"id": "artist", "state": "skip",
                     "detail": "no artist matched"}) in got
    assert got[-1][0] == "done"
    assert got[-1][1]["results"] == []


def test_search_spend_is_banked_even_when_the_client_never_reads_the_stream(client):
    """Same load-bearing rule as the scan route's version of this test: the
    Claude call inside parse_search_query is billed the moment it returns,
    so an abandoned request must not make that spend vanish. Confirmed (by
    hand, not by a test in this file) to fail when _record_scan_spend is
    moved out of the generator's finally — see the backend report for that
    evidence.
    """
    def spending_parse(query, usage_out=None):
        if usage_out is not None:
            usage_out.append({"model": "claude-haiku-4-5",
                              "input_tokens": 50, "output_tokens": 10})
        return {"artist": "Jorge Ben", "album": None}

    with patch.object(app_module, "_record_scan_spend") as banked, \
         patch.object(app_module.scan, "parse_search_query",
                      side_effect=spending_parse):
        response = client.post("/api/search", headers=SSE,
                               json={"query": "jorge ben"},
                               buffered=False)
        iterator = iter(response.response)  # the un-drained stream
        next(iterator)                      # one frame only ("parse" run)
        iterator.close()                    # the client hangs up here
    assert banked.called
    assert banked.call_args.args[0] == "search"
