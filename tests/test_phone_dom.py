"""Run tests/test_phone_dom.js under pytest.

Mirrors tests/test_boot.py's setup (render the real page, write a fixture
collection, point node at a scratch jsdom install) but targets a different JS
file on purpose. tests/test_boot.js boots its JSDOM with pretendToBeVisual:true
and never closes any of the windows it creates, so every one of its tests
leaves a live requestAnimationFrame timer behind; the file finishes but the
node process then hangs forever. test_phone_dom.js closes every window it
opens, which is what lets this test actually return.

jsdom is not a dependency of this project and must not become one: there is no
package.json and adding one would put a node toolchain in a Flask repo. It is
installed into the same scratch directory tests/test_boot.py uses, and this
test skips when that is not possible — offline, or with no npm — rather than
failing.
"""

import json
import os
import pathlib
import shutil
import subprocess
import tempfile

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
# Shared with tests/test_boot.py so the install cost is paid once, not per file.
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
def test_phone_dom_js(tmp_path):
    modules = _jsdom_path()
    if modules is None:
        pytest.skip("jsdom is unavailable (no npm, or no network to install it)")

    # The page as Flask actually renders it, and a collection to fill it with.
    import app as app_module

    page = tmp_path / "index.html"
    page.write_text(app_module.app.test_client().get("/").get_data(as_text=True),
                    encoding="utf-8")

    # A small fixture is enough here: these tests only need the form overlay
    # to open and one record to exist, not the full variety test_boot.py's
    # fixture carries for its much larger surface.
    def rec(n, **over):
        base = dict(
            id=n, artist=f"Artist {n}", album_name=f"Album {n}", year="1975",
            genre="Rock", bought_date=f"2026-08-{n:02d}", bought_where="Benedito Calixto",
            bought_by="", condition="used", my_rating=3, wife_rating=4, have_it=True,
            play_count=2, play_dates='["2026-08-20T20:00:00"]',
            cleaned_dates='["2026-08-02"]', notes="", country="BR",
            cover_url=f"/api/records/{n}/cover?v=hash{n}",
        )
        base.update(over)
        return base

    # 11 records at "Benedito Calixto" (1-11) and one at "Amazon" (12), for
    # task 6's place-chip ranking test — the same shape tests/test_boot.py's
    # own fixture uses for that assertion, in the file this module's
    # docstring explains is never run. rec(1) keeps its default play date,
    # which the log-collapse "a section with entries starts open" test below
    # also relies on.
    #
    # Task 8's edit root needs two more distinct shapes: record 4 with no
    # play dates yet (so a logged play is a visible change, not one entry
    # among several), and record 9 as a wishlist entry (have_it:False), so
    # the purchase row can be checked against a record that never had one.
    # Neither is referenced by any test above this comment.
    overrides = {
        4: dict(play_count=0, play_dates="[]"),
        9: dict(have_it=False, bought_date="", bought_where="", condition="",
                play_count=0, play_dates="[]", cleaned_dates="[]"),
    }
    rows = ([rec(n, **overrides.get(n, {})) for n in range(1, 12)]
            + [rec(12, bought_where="Amazon")])
    records = tmp_path / "records.json"
    records.write_text(json.dumps(rows), encoding="utf-8")

    env = dict(os.environ,
               VINYL_JSDOM_PATH=str(modules),
               VINYL_PAGE_HTML=str(page),
               VINYL_RECORDS_JSON=str(records))
    result = subprocess.run(["node", "--test", "tests/test_phone_dom.js"],
                            cwd=REPO_ROOT, capture_output=True, text=True,
                            timeout=60, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
