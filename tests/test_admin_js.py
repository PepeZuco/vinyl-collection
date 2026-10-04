"""Run the admin review-list rules (tests/test_admin.js) under pytest.

Same shape as tests/test_places_js.py: pure functions in static/admin.js,
node's test runner, and a skip when node is not installed.
"""

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_admin_js():
    result = subprocess.run(["node", "--test", "tests/test_admin.js"],
                            cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
