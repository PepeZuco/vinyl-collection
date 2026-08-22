import json
import logging
from unittest.mock import patch, Mock

import jsonschema
import pytest

import scan

GENRES = ["Rock", "MPB & Samba", "Jazz", "Soul & Funk"]


def _claude_response(payload: dict):
    block = Mock()
    block.type = "text"
    block.text = json.dumps(payload)
    message = Mock()
    message.content = [block]
    return message


def test_returns_a_genre_from_the_enum():
    client = Mock()
    client.messages.create.return_value = _claude_response({"genre": "Soul & Funk"})

    with patch.object(scan, "_anthropic_client", return_value=client):
        assert scan.classify_genre("Bill Withers", "Menagerie", GENRES) == "Soul & Funk"


def test_uses_haiku():
    client = Mock()
    client.messages.create.return_value = _claude_response({"genre": "Jazz"})

    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.classify_genre("Bill Evans", "Waltz for Debby", GENRES)

    assert client.messages.create.call_args.kwargs["model"] == "claude-haiku-4-5"


def test_null_genre_returns_none():
    client = Mock()
    client.messages.create.return_value = _claude_response({"genre": None})

    with patch.object(scan, "_anthropic_client", return_value=client):
        assert scan.classify_genre("Unknown", "Unknown", GENRES) is None


def test_value_outside_enum_is_rejected():
    client = Mock()
    client.messages.create.return_value = _claude_response({"genre": "Polka"})

    with patch.object(scan, "_anthropic_client", return_value=client):
        assert scan.classify_genre("X", "Y", GENRES) is None


def test_api_failure_returns_none():
    client = Mock()
    client.messages.create.side_effect = RuntimeError("boom")

    with patch.object(scan, "_anthropic_client", return_value=client):
        assert scan.classify_genre("X", "Y", GENRES) is None


def test_genre_schema_permits_null_and_rejects_unknown_genres():
    """The model must be able to say 'none fit' — and must not invent a genre."""
    schema = scan._genre_schema(GENRES)
    genre_schema = schema["properties"]["genre"]

    jsonschema.validate(None, genre_schema)          # must not raise
    jsonschema.validate("Jazz", genre_schema)        # must not raise
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate("Polka", genre_schema)   # outside the vocabulary


def test_no_effort_in_output_config():
    """output_config.effort must NOT be sent on the genre call.

    GENRE_MODEL is claude-haiku-4-5, and `effort` errors on Haiku 4.5 (and
    Sonnet 4.5) — it only exists from Opus 4.5 / the 4.6+ family upwards.
    Sending it made every single genre call 400, which classify_genre's
    `except Exception` then swallowed into a permanently empty genre field.
    Structured outputs (output_config.format) are fine on every model, so the
    format key must stay.
    """
    client = Mock()
    client.messages.create.return_value = _claude_response({"genre": "Jazz"})

    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.classify_genre("Bill Evans", "Waltz for Debby", GENRES)

    output_config = client.messages.create.call_args.kwargs["output_config"]
    assert "effort" not in output_config
    assert output_config["format"]["type"] == "json_schema"


def test_api_failure_is_logged(caplog):
    """The never-raise contract must not also be a never-tell contract."""
    client = Mock()
    client.messages.create.side_effect = RuntimeError("boom")

    with caplog.at_level(logging.WARNING, logger="scan"):
        with patch.object(scan, "_anthropic_client", return_value=client):
            assert scan.classify_genre("Bill Withers", "Menagerie", GENRES) is None

    records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert records, "a swallowed genre failure must still leave a log record"
    assert records[0].exc_info is not None, "log the traceback, not just a message"
    assert "boom" in caplog.text or "RuntimeError" in caplog.text
