"""The import-time startup block: run once per gunicorn worker, so twice at once.

Production starts two workers without --preload, and each imports app.py. The
schema work, the column migrations and the seeds must hold when both race.
"""

import os
import pathlib
import sqlite3
import subprocess
import time
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SEEDED = "spotify_playlists_seeded"


@pytest.fixture
def app_module():
    import app as app_module
    with app_module.app.app_context():
        app_module.SpotifyPlaylist.query.delete()
        app_module.AppFlag.query.delete()
        app_module.db.session.commit()
    yield app_module


def test_without_the_flag_the_seed_adds_both_rows_and_the_flag(app_module):
    with app_module.app.app_context():
        app_module._seed_legacy_playlists_once()
        assert app_module.SpotifyPlaylist.query.count() == 2
        assert app_module.db.session.get(app_module.AppFlag, SEEDED) is not None


def test_with_the_flag_deleted_legacy_rows_stay_deleted(app_module):
    with app_module.app.app_context():
        app_module._seed_legacy_playlists_once()
        app_module.SpotifyPlaylist.query.delete()
        app_module.db.session.commit()
        app_module._seed_legacy_playlists_once()
        assert app_module.SpotifyPlaylist.query.count() == 0


def test_two_workers_booting_at_once_both_start_and_seed_once(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env.update(DATA_DIR=str(tmp_path), BACKUP_ENABLED="0")
    # Everything app.py imports is loaded first, then both wait for the same
    # instant: what is left to race is the startup block itself, not two
    # interpreters warming up at different speeds.
    go = time.time() + 5
    boot = ("import flask, flask_sqlalchemy, sqlalchemy, requests, backup, pricing, scan, "
            f"playlist_filters, spotify_sync, time; time.sleep(max(0, {go} - time.time())); "
            "import app")
    procs = [subprocess.Popen([sys.executable, "-c", boot], cwd=REPO_ROOT, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for _ in range(2)]
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err

    with sqlite3.connect(tmp_path / "vinyl.db") as conn:
        names = [n for (n,) in conn.execute("SELECT name FROM spotify_playlist ORDER BY id")]
        flags = conn.execute("SELECT key FROM app_flag").fetchall()
    assert names == ["Zucoloto Vinyl Collection", "Zucoloto Vinyl Collection — Liked"]
    assert flags == [(SEEDED,)]
