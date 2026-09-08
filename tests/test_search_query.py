import json
from unittest.mock import patch, Mock

import pytest

import scan


def _claude_response(payload: dict):
    block = Mock()
    block.type = "text"
    block.text = json.dumps(payload)
    message = Mock()
    message.content = [block]
    return message


def test_an_artist_only_query_returns_no_album():
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"artist": "Jorge Ben", "album": None})

    with patch.object(scan, "_anthropic_client", return_value=client):
        assert scan.parse_search_query("jorge ben") == {
            "artist": "Jorge Ben", "album": None}


def test_a_query_naming_both_returns_both():
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"artist": "Milton Nascimento", "album": "Clube da Esquina"})

    with patch.object(scan, "_anthropic_client", return_value=client):
        assert scan.parse_search_query("clube da esquina") == {
            "artist": "Milton Nascimento", "album": "Clube da Esquina"}


def test_uses_haiku_and_sends_no_effort():
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"artist": "Rita Lee", "album": None})

    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.parse_search_query("rita lee")

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5"
    # output_config.effort 400s on Haiku 4.5 — see the comment at scan.py:645.
    assert "effort" not in kwargs["output_config"]


def test_records_usage_for_the_ledger():
    client = Mock()
    response = _claude_response({"artist": "Criolo", "album": None})
    response.usage = Mock(input_tokens=180, output_tokens=40)
    client.messages.create.return_value = response

    spent = []
    with patch.object(scan, "_anthropic_client", return_value=client):
        scan.parse_search_query("criolo", usage_out=spent)

    assert spent == [{"model": "claude-haiku-4-5",
                      "input_tokens": 180, "output_tokens": 40}]


def test_an_empty_query_is_rejected_without_calling_the_api():
    client = Mock()
    with patch.object(scan, "_anthropic_client", return_value=client):
        with pytest.raises(ValueError):
            scan.parse_search_query("   ")
    client.messages.create.assert_not_called()


def test_an_artistless_answer_is_rejected():
    """Nothing downstream can act on a parse with no artist in it."""
    client = Mock()
    client.messages.create.return_value = _claude_response(
        {"artist": None, "album": None})

    with patch.object(scan, "_anthropic_client", return_value=client):
        with pytest.raises(ValueError):
            scan.parse_search_query("asdfghjkl")
