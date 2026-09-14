"""Run the JavaScript SSE frame-parser tests under pytest.

Same arrangement as tests/test_spend.py: the parsing is pure, so it lives in
static/scanstream.js where a JS runtime can reach it, and pytest shells out.
"""

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_scanstream_js():
    result = subprocess.run(
        ["node", "--test", "tests/test_scanstream.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
