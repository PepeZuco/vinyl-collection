import json
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
