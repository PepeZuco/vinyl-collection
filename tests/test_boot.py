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

    # A collection built here rather than read from the database. conftest
    # binds the app to an empty throwaway one, and a developer's real
    # collection would make this test's outcome depend on whose machine it is.
    # It has to be varied enough for every assertion below to bite: records to
    # navigate between, both ownerships, a blank genre, cleaned and never
    # cleaned, played recently and long ago.
    def rec(n, **over):
        base = dict(
            id=n, artist=f"Artist {n}", album_name=f"Album {n}", year="1975",
            genre="Rock", bought_date=f"2026-08-{n:02d}", bought_where="Benedito Calixto",
            bought_by="", condition="used", my_rating=3, wife_rating=4, have_it=True,
            play_count=2, play_dates='["2026-08-20T20:00:00"]',
            cleaned_dates='["2026-08-02"]', cover_url="", notes="", country="BR",
        )
        base.update(over)
        return base

    rows = [
        rec(1), rec(2, genre="Jazz", year="1968", country="US"),
        rec(3, genre="", condition="new", cleaned_dates=""),
        rec(4, genre="Pop", year="1985", cleaned_dates="", play_dates=""),
        rec(5, genre="Jazz", play_dates='["2024-01-05"]'),
        rec(6, genre="Soul & Funk", year="1993", country="US", cleaned_dates="[]"),
        rec(7, genre="Rock", condition="new"),
        rec(8, genre="Pop", year="2020", bought_where="Amazon"),
        rec(9, have_it=False, bought_date="", cleaned_dates="", play_dates="",
            play_count=0, condition="", my_rating=0, wife_rating=0),
        rec(10, have_it=False, bought_date="", genre="Jazz", cleaned_dates="",
            play_dates="", play_count=0, condition=""),
        rec(11, have_it=False, bought_date="", genre="", cleaned_dates="",
            play_dates="", play_count=0, condition=""),
        rec(12, genre="Rock", notes='[{"date": "2026-08-23", "text": "clicky side B"}]'),
    ]
    records = tmp_path / "records.json"
    records.write_text(json.dumps(rows), encoding="utf-8")

    env = dict(os.environ,
               VINYL_JSDOM_PATH=str(modules),
               VINYL_PAGE_HTML=str(page),
               VINYL_RECORDS_JSON=str(records))
    result = subprocess.run(["node", "--test", "tests/test_boot.js"],
                            cwd=REPO_ROOT, capture_output=True, text=True,
                            timeout=300, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
