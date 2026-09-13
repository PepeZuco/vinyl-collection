"""Run the JavaScript carousel rules under pytest.

Mirrors tests/test_health.py: the gesture and centring maths are pure functions
in static/carousel.js, so they need a JS runtime, and shelling out to node's
test runner keeps `pytest` as the one command.
"""

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_carousel_js():
    result = subprocess.run(
        ["node", "--test", "tests/test_carousel.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
