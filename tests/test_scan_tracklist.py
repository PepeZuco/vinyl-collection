"""scan.suggest_tracklist: Claude names a record's vinyl tracklist when the
record has none, so a stand-in playlist has songs to search for."""

import json
from unittest.mock import Mock, patch

import scan


def _claude(payload, usage=(100, 50)):
    block = Mock()
    block.type = "text"
    block.text = json.dumps(payload)
    message = Mock()
    message.content = [block]
    message.usage = Mock(input_tokens=usage[0], output_tokens=usage[1])
    return message


def _suggest(payload, **kw):
    client = Mock()
    client.messages.create.return_value = _claude(payload)
    with patch.object(scan, "_anthropic_client", return_value=client):
        return scan.suggest_tracklist("Elis Regina", "Elis", "1972", **kw), client


def test_returns_sides_and_titles_and_the_disc_count():
    out, _ = _suggest({"tracks": [{"side": "A", "title": "Bala com Bala"},
                                  {"side": "b", "title": " Atrás da Porta "},
                                  {"side": "C", "title": "Extra"}]})
    assert out == {"tracks": [{"side": "A", "title": "Bala com Bala"},
                              {"side": "B", "title": "Atrás da Porta"},
                              {"side": "C", "title": "Extra"}],
                   "disc_count": 2}


def test_uses_haiku_and_names_the_record():
    _, client = _suggest({"tracks": [{"side": "A", "title": "X"}]})
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5"
    assert "effort" not in json.dumps(kwargs.get("output_config"))
    assert "Elis Regina" in kwargs["messages"][0]["content"]


def test_records_what_the_call_cost():
    spent = []
    _suggest({"tracks": [{"side": "A", "title": "X"}]}, usage_out=spent)
    assert spent == [{"model": "claude-haiku-4-5", "input_tokens": 100, "output_tokens": 50}]


def test_an_unknown_record_is_none():
    out, _ = _suggest({"tracks": []})
    assert out is None


def test_untitled_rows_and_bad_sides_are_dropped():
    out, _ = _suggest({"tracks": [{"side": "A", "title": ""}, {"side": "?", "title": "Y"},
                                  {"side": "A", "title": "Z"}]})
    assert out == {"tracks": [{"side": "A", "title": "Z"}], "disc_count": 1}


def test_an_api_failure_is_none():
    client = Mock()
    client.messages.create.side_effect = RuntimeError("boom")
    with patch.object(scan, "_anthropic_client", return_value=client):
        assert scan.suggest_tracklist("A", "B", "") is None
