import json
import pathlib
import socket

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    """Load a recorded API response by filename stem."""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """Fail loudly if any test opens a real socket.

    Every external call in scan.py is meant to be mocked. Without this guard a
    forgotten patch turns into a silent live request to MusicBrainz, iTunes,
    Spotify or the Claude API — slow, flaky, and billable.
    """
    def _blocked(self, address, *args, **kwargs):
        raise AssertionError(f"test attempted a real network connection to {address!r}")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
