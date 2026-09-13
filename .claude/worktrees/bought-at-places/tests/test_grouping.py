"""Run the JavaScript crate-grouping tests under pytest.

The grouping rules are pure functions living in static/grouping.js, so they are
testable — but only by a JS runtime. Shelling out to node's built-in test runner
keeps `pytest` as the one command that runs everything.
"""

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_grouping_js():
    result = subprocess.run(
        ["node", "--test", "tests/test_grouping.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
