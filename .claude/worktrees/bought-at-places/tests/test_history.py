"""Run the JavaScript race-chart timeline tests under pytest.

The timeline rules are pure functions living in static/history.js, so they are
testable — but only by a JS runtime. Shelling out to node's built-in test runner
keeps `pytest` as the one command that runs everything.
"""

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_history_js():
    result = subprocess.run(
        ["node", "--test", "tests/test_history.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
