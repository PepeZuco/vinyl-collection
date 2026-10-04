"""identify_albums: one Claude verdict per playlist song, batched, never raising."""

import json
import threading
from types import SimpleNamespace

import scan


def _song(i, artist="The Beatles", album="1 (Remastered)"):
    return {"title": f"Song {i}", "artists": [artist], "album": album,
            "release_year": "2000", "image_url": ""}


class FakeClaude:
    """Answers each batch from `answer(lines)`; records every call."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []
        self.lock = threading.Lock()
        self.messages = self

    def create(self, **kw):
        with self.lock:
            self.calls.append(kw)
        lines = kw["messages"][0]["content"].split("\n")
        body = self.answer(lines)
        if isinstance(body, Exception):
            raise body
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(body))],
            usage=SimpleNamespace(input_tokens=100, output_tokens=20))


def _patch(monkeypatch, fake):
    monkeypatch.setattr(scan, "_anthropic_client", lambda: fake)


def _studio(lines):
    return {"albums": [{"artist": "The Beatles", "album": "Abbey Road", "year": "1969"}
                       for _ in lines]}


def test_returns_one_answer_per_song_in_order(monkeypatch):
    _patch(monkeypatch, FakeClaude(_studio))
    out = scan.identify_albums([_song(1), _song(2)])
    assert out == [{"artist": "The Beatles", "album": "Abbey Road", "year": "1969",
                    "unverified": False}] * 2


def test_the_prompt_numbers_songs_with_artist_title_and_spotify_album(monkeypatch):
    fake = FakeClaude(_studio)
    _patch(monkeypatch, fake)
    scan.identify_albums([_song(1)])
    call = fake.calls[0]
    assert call["model"] == scan.IDENTIFY_MODEL == "claude-haiku-4-5"
    assert call["messages"][0]["content"] == "1. The Beatles — Song 1 — on Spotify: 1 (Remastered)"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "studio album" in call["system"].lower()


def test_120_songs_are_three_calls_and_three_usage_rows(monkeypatch):
    fake = FakeClaude(_studio)
    _patch(monkeypatch, fake)
    usage = []
    out = scan.identify_albums([_song(i) for i in range(120)], usage_out=usage)
    assert len(fake.calls) == 3
    assert sorted(len(c["messages"][0]["content"].split("\n")) for c in fake.calls) == [20, 50, 50]
    assert len(out) == 120
    assert len(usage) == 3 and all(u["model"] == "claude-haiku-4-5" for u in usage)


def test_a_null_album_is_kept_as_unplaced(monkeypatch):
    _patch(monkeypatch, FakeClaude(lambda lines: {"albums": [
        {"artist": "Unknown", "album": None, "year": None}]}))
    assert scan.identify_albums([_song(1)]) == [
        {"artist": "Unknown", "album": None, "year": None, "unverified": False}]


def test_a_failed_batch_falls_back_to_the_spotify_album(monkeypatch):
    _patch(monkeypatch, FakeClaude(lambda lines: RuntimeError("overloaded")))
    assert scan.identify_albums([_song(1, album="Menagerie")]) == [
        {"artist": "The Beatles", "album": "Menagerie", "year": "2000", "unverified": True}]


def test_fallback_strips_spotify_edition_tails(monkeypatch):
    _patch(monkeypatch, FakeClaude(lambda lines: RuntimeError("overloaded")))
    out = scan.identify_albums([_song(1, album="Abbey Road (Remastered 2009)"),
                                _song(2, album="Help! - Remastered 2009")])
    assert [(o["album"], o["unverified"]) for o in out] == [
        ("Abbey Road", True), ("Help!", True)]


def test_a_short_answer_falls_back_only_for_the_missing_songs(monkeypatch):
    _patch(monkeypatch, FakeClaude(lambda lines: {"albums": [
        {"artist": "The Beatles", "album": "Abbey Road", "year": "1969"}]}))
    out = scan.identify_albums([_song(1), _song(2, album="Help!")])
    assert out[0]["album"] == "Abbey Road" and out[0]["unverified"] is False
    assert out[1] == {"artist": "The Beatles", "album": "Help!", "year": "2000",
                      "unverified": True}


def test_no_api_key_falls_back_for_every_song(monkeypatch):
    def boom():
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    monkeypatch.setattr(scan, "_anthropic_client", boom)
    out = scan.identify_albums([_song(1)])
    assert out[0]["unverified"] is True


def test_no_songs_asks_nothing(monkeypatch):
    fake = FakeClaude(_studio)
    _patch(monkeypatch, fake)
    assert scan.identify_albums([]) == []
    assert fake.calls == []


def test_non_string_album_falls_back_to_spotify(monkeypatch):
    _patch(monkeypatch, FakeClaude(lambda lines: {"albums": [
        {"artist": "The Beatles", "album": 42, "year": "1969"}]}))
    out = scan.identify_albums([_song(1, album="Help!")])
    # Non-string album is invalid; should fall back to Spotify with unverified=True
    assert out == [{"artist": "The Beatles", "album": "Help!", "year": "2000",
                    "unverified": True}]


def test_non_string_year_becomes_none(monkeypatch):
    _patch(monkeypatch, FakeClaude(lambda lines: {"albums": [
        {"artist": "The Beatles", "album": "Abbey Road", "year": 1969}]}))
    out = scan.identify_albums([_song(1)])
    # Non-string year should become None, but album is valid so unverified=False
    assert out == [{"artist": "The Beatles", "album": "Abbey Road", "year": None,
                    "unverified": False}]
