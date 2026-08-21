import json
import pathlib

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    """Load a recorded API response by filename stem."""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
