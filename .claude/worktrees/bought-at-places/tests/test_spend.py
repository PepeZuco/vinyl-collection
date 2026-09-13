"""Run the JavaScript scan-spend formatting tests under pytest.

Same arrangement as tests/test_grouping.py: the formatting is pure, so it lives
in static/spend.js where a JS runtime can reach it, and pytest shells out.
"""

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_spend_js():
    result = subprocess.run(
        ["node", "--test", "tests/test_spend.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
