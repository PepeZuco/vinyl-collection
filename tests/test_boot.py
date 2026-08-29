"""Boot the real page in a DOM and drive it, under pytest.

Every other JS test here exercises a model in isolation. This one renders the
actual template, runs its scripts, and presses things — the only check in the
suite that would notice a deleted function still being called, or an id the
markup no longer has. Neither shows up until a browser reaches it.

jsdom is not a dependency of this project and must not become one: there is no
package.json and adding one would put a node toolchain in a Flask repo. It is
installed into a scratch directory instead, and the test skips when that is not
possible — offline, or with no npm — rather than failing.
"""

import json
import os
import pathlib
import shutil
import subprocess
import tempfile

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
# Reused across runs so the install cost is paid once, not per test session.
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
def test_page_boots_and_responds(tmp_path):
    modules = _jsdom_path()
    if modules is None:
        pytest.skip("jsdom is unavailable (no npm, or no network to install it)")

    # The page as Flask actually renders it, and a collection to fill it with.
    import app as app_module

    page = tmp_path / "index.html"
    page.write_text(app_module.app.test_client().get("/").get_data(as_text=True),
                    encoding="utf-8")

    records = tmp_path / "records.json"
    with app_module.app.app_context():
        rows = [r.to_dict() for r in app_module.Record.query.limit(60).all()]
    # A collection with nothing in it would let every assertion pass vacuously.
    if not rows:
        rows = [{
            "id": 1, "artist": "Tim Maia", "album_name": "Uma Onda", "year": "1993",
            "genre": "Soul & Funk", "bought_date": "2026-08-01", "bought_where": "Unique",
            "bought_by": "", "condition": "used", "my_rating": 5, "wife_rating": 5,
            "have_it": True, "play_count": 3, "play_dates": '["2026-08-20"]',
            "cleaned_dates": "", "cover_url": "", "notes": "", "country": "BR",
        }, {
            "id": 2, "artist": "Wanted", "album_name": "Not Bought", "year": "1980",
            "genre": "", "bought_date": "", "bought_where": "", "bought_by": "",
            "condition": "", "my_rating": 0, "wife_rating": 0, "have_it": False,
            "play_count": 0, "play_dates": "", "cleaned_dates": "", "cover_url": "",
            "notes": "", "country": "",
        }]
    records.write_text(json.dumps(rows), encoding="utf-8")

    env = dict(os.environ,
               VINYL_JSDOM_PATH=str(modules),
               VINYL_PAGE_HTML=str(page),
               VINYL_RECORDS_JSON=str(records))
    result = subprocess.run(["node", "--test", "tests/test_boot.js"],
                            cwd=REPO_ROOT, capture_output=True, text=True,
                            timeout=300, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
