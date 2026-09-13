"""Run the JavaScript urlstate rules under pytest.

Mirrors tests/test_activity.py: the rules are pure functions in
static/urlstate.js, so they need a JS runtime, and shelling out to node's test
runner keeps `pytest` as the one command.
"""

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_urlstate_js():
    result = subprocess.run(
        ["node", "--test", "tests/test_urlstate.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
