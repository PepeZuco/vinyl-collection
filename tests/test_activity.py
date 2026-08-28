"""Run the JavaScript activity-chart model tests under pytest.

The model rules are pure functions living in static/activity.js, so they are
testable — but only by a JS runtime. Shelling out to node's built-in test runner
keeps `pytest` as the one command that runs everything.
"""

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_activity_js():
    result = subprocess.run(
        ["node", "--test", "tests/test_activity.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
