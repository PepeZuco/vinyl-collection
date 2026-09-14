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
