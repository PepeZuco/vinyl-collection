"""Run the phone record screen's pure logic under pytest (mirrors test_covertilt.py)."""

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_phonedetail_js():
    result = subprocess.run(
        ["node", "--test", "tests/test_phonedetail.js"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
