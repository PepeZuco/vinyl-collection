"""Recording what each Claude call spent, without changing what the call returns."""
import json
from unittest.mock import patch, Mock

import scan

GENRES = ["Rock", "Jazz", "Soul & Funk"]
DATA_URI = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
SLEEVE = {"artist": "Bill Withers", "album_name": "Menagerie", "genre": "Soul & Funk",
          "label": None, "catalog_number": None}


def _claude_response(payload, input_tokens=1200, output_tokens=180):
    block = Mock()
    block.type = "text"
    block.text = json.dumps(payload)
    usage = Mock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    message = Mock()
    message.content = [block]
    message.usage = usage
    return message


def test_image_scan_records_its_model_and_tokens():
    client = Mock()
    client.messages.create.return_value = _claude_response(SLEEVE)
    spent = []

    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.extract_from_image(DATA_URI, GENRES, usage_out=spent)

    assert spent == [{"model": scan.VISION_MODEL,
                      "input_tokens": 1200, "output_tokens": 180}]


def test_genre_call_records_its_model_and_tokens():
    client = Mock()
    client.messages.create.return_value = _claude_response({"genre": "Jazz"}, 90, 12)
    spent = []

    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.classify_genre("Bill Evans", "Waltz for Debby", GENRES, usage_out=spent)

    assert spent == [{"model": scan.GENRE_MODEL,
                      "input_tokens": 90, "output_tokens": 12}]


def test_spend_is_recorded_even_when_the_response_cannot_be_parsed():
    """The call was billed the moment it returned — a parse failure after that
    does not refund it, so the ledger must not lose the row."""
    client = Mock()
    unparseable = _claude_response(SLEEVE)
    unparseable.content[0].text = "not json"
    client.messages.create.return_value = unparseable
    spent = []

    with patch.object(scan, "_anthropic_client", return_value=client):
        try:
            scan.extract_from_image(DATA_URI, GENRES, usage_out=spent)
        except RuntimeError:
            pass

    assert len(spent) == 1
    assert spent[0]["input_tokens"] == 1200


def test_a_response_without_countable_usage_records_nothing_and_still_works():
    """A bare Mock (and a real response missing usage) must not break a scan."""
    client = Mock()
    response = _claude_response(SLEEVE)
    response.usage = None
    client.messages.create.return_value = response
    spent = []

    with patch.object(scan, "_anthropic_client", return_value=client):
        result = scan.extract_from_image(DATA_URI, GENRES, usage_out=spent)

    assert result["artist"] == "Bill Withers"
    assert spent == []


def test_non_numeric_token_counts_are_ignored():
    client = Mock()
    response = _claude_response(SLEEVE)
    response.usage = Mock()  # .input_tokens is itself a Mock, not a number
    client.messages.create.return_value = response
    spent = []

    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.extract_from_image(DATA_URI, GENRES, usage_out=spent)

    assert spent == []


def test_a_failed_genre_call_records_no_spend():
    client = Mock()
    client.messages.create.side_effect = RuntimeError("boom")
    spent = []

    with patch.object(scan, "_anthropic_client", return_value=client):
        assert scan.classify_genre("X", "Y", GENRES, usage_out=spent) is None

    assert spent == []
