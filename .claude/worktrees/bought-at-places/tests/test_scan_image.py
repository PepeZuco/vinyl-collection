import json
from unittest.mock import patch, Mock

import jsonschema
import pytest

import scan

GENRES = ["Rock", "MPB & Samba", "Jazz", "Soul & Funk"]
DATA_URI = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="


def _claude_response(payload: dict):
    block = Mock()
    block.type = "text"
    block.text = json.dumps(payload)
    message = Mock()
    message.content = [block]
    return message


def test_returns_extracted_fields():
    payload = {"artist": "Bill Withers", "album_name": "Live at Carnegie Hall",
               "genre": "Soul & Funk", "label": "Sussex", "catalog_number": "SXBS 7025"}
    client = Mock()
    client.messages.create.return_value = _claude_response(payload)

    with patch.object(scan, "_anthropic_client", return_value=client):
        result = scan.extract_from_image(DATA_URI, GENRES)

    assert result["artist"] == "Bill Withers"
    assert result["genre"] == "Soul & Funk"
    assert result["catalog_number"] == "SXBS 7025"
    assert result["label"] == "Sussex"
    assert set(result) == {"artist", "album_name", "genre", "label", "catalog_number"}


def test_genre_enum_is_built_from_supplied_genres():
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"artist": "X", "album_name": "Y", "genre": None,
         "label": None, "catalog_number": None}
    )

    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.extract_from_image(DATA_URI, GENRES)

    schema = client.messages.create.call_args.kwargs["output_config"]["format"]["schema"]
    genre_schema = schema["properties"]["genre"]
    assert genre_schema["anyOf"][0]["enum"] == GENRES


def test_genre_schema_permits_null_and_rejects_unknown_genres():
    """The model must be able to say 'not legible' — and must not invent a genre."""
    schema = scan._sleeve_schema(GENRES)
    genre_schema = schema["properties"]["genre"]

    jsonschema.validate(None, genre_schema)          # must not raise
    jsonschema.validate("Jazz", genre_schema)        # must not raise
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate("Polka", genre_schema)   # outside the vocabulary


def test_uses_sonnet_5_at_low_effort():
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"artist": "X", "album_name": "Y", "genre": None,
         "label": None, "catalog_number": None}
    )

    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.extract_from_image(DATA_URI, GENRES)

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-5"
    assert kwargs["output_config"]["effort"] == "low"


def test_prompt_forbids_inferring_year_and_country():
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"artist": "X", "album_name": "Y", "genre": None,
         "label": None, "catalog_number": None}
    )

    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.extract_from_image(DATA_URI, GENRES)

    system = client.messages.create.call_args.kwargs["system"].lower()
    # Assert the whole prohibition in one phrase, so inverting EITHER half
    # (year or country) breaks the test. Checking only "year in system and
    # country in system" would pass a rule reworded to demand them.
    assert "never infer or recall the release year or the country" in system
    assert "pressing" in system   # the clause that closes the "but it's printed" loophole


def test_illegible_fields_stay_none():
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"artist": "Bill Withers", "album_name": None, "genre": None,
         "label": None, "catalog_number": None}
    )

    with patch.object(scan, "_anthropic_client", return_value=client):
        result = scan.extract_from_image(DATA_URI, GENRES)

    assert result["album_name"] is None
    assert result["genre"] is None


def test_missing_api_key_raises_runtime_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        scan.extract_from_image(DATA_URI, GENRES)


def test_no_text_block_raises_runtime_error():
    block = Mock()
    block.type = "image"
    message = Mock()
    message.content = [block]
    client = Mock()
    client.messages.create.return_value = message

    with patch.object(scan, "_anthropic_client", return_value=client):
        with pytest.raises(RuntimeError):
            scan.extract_from_image(DATA_URI, GENRES)


def test_invalid_json_raises_runtime_error():
    block = Mock()
    block.type = "text"
    block.text = "not valid json"
    message = Mock()
    message.content = [block]
    client = Mock()
    client.messages.create.return_value = message

    with patch.object(scan, "_anthropic_client", return_value=client):
        with pytest.raises(RuntimeError):
            scan.extract_from_image(DATA_URI, GENRES)


def test_max_tokens_leaves_room_for_adaptive_thinking():
    """Sonnet 5 thinks adaptively when `thinking` is omitted, and those tokens
    come out of max_tokens. At 1024 a busy sleeve could spend the whole budget
    thinking and return no text block at all, which surfaced as an opaque 502.
    max_tokens is a ceiling, not a spend, so a generous one costs nothing.
    """
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"artist": "X", "album_name": "Y", "genre": None,
         "label": None, "catalog_number": None}
    )

    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.extract_from_image(DATA_URI, GENRES)

    assert client.messages.create.call_args.kwargs["max_tokens"] >= 16000
