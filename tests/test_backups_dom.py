"""Run tests/test_backups_dom.js under pytest.

Same harness as tests/test_phone_dom.py — the real page rendered by Flask, a
scratch jsdom install shared with tests/test_boot.py, and a skip rather than a
failure when node or npm is missing. No records fixture here: the backups
panel does not read the collection, only /api/backups.
"""

import os
import pathlib
import shutil
import subprocess
import tempfile

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
JSDOM_HOME = pathlib.Path(tempfile.gettempdir()) / "vinyl-jsdom"


def _jsdom_path():
    """node_modules holding jsdom, installing it once if it is not there yet."""
    modules = JSDOM_HOME / "node_modules"
    if (modules / "jsdom").is_dir():
        return modules
    if shutil.which("npm") is None:
        return None
    JSDOM_HOME.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["npm", "init", "-y"], cwd=JSDOM_HOME, capture_output=True,
                       text=True, timeout=120, check=True)
        subprocess.run(["npm", "install", "--silent", "--no-audit", "--no-fund", "jsdom"],
                       cwd=JSDOM_HOME, capture_output=True, text=True, timeout=600, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return modules if (modules / "jsdom").is_dir() else None


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_backups_dom_js(tmp_path):
    modules = _jsdom_path()
    if modules is None:
        pytest.skip("jsdom is unavailable (no npm, or no network to install it)")

    import app as app_module

    page = tmp_path / "index.html"
    page.write_text(app_module.app.test_client().get("/").get_data(as_text=True),
                    encoding="utf-8")

    env = dict(os.environ, VINYL_JSDOM_PATH=str(modules), VINYL_PAGE_HTML=str(page))
    result = subprocess.run(["node", "--test", "tests/test_backups_dom.js"],
                            cwd=REPO_ROOT, capture_output=True, text=True,
                            timeout=60, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
