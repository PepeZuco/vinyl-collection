import json
from unittest.mock import patch, Mock

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


def test_genre_enum_is_built_from_supplied_genres():
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"artist": "X", "album_name": "Y", "genre": None,
         "label": None, "catalog_number": None}
    )

    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.extract_from_image(DATA_URI, GENRES)

    schema = client.messages.create.call_args.kwargs["output_config"]["format"]["schema"]
    assert schema["properties"]["genre"]["enum"] == GENRES


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
    assert "year" in system and "country" in system


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
