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


def test_spend_lands_in_the_database_while_streaming(client):
    """stream_with_context exists so the generator can still touch db.session
    once it is running outside the view function's own request handling —
    without it, _record_scan_spend's insert/commit would raise "working
    outside of application context" the moment a real API call had billed
    anything. The other streaming tests never catch this: their stub
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

    with patch.object(app_module.scan, "extract_from_image", side_effect=spending_extract):
        frames(client.post("/api/scan", headers=SSE,
                           json={"image": "data:image/jpeg;base64,x"}))

    with app_module.app.app_context():
        rows = app_module.ScanSpend.query.all()
    assert len(rows) == 1
    assert rows[0].source == "photo"
    assert rows[0].model == "claude-sonnet-5"
