"""Daily snapshots of the SQLite database, kept for five days.

The collection lives in one file on the Railway volume, so a backup is a
snapshot of that file — taken while gunicorn is serving, which is why these
tests care about consistency and not just that a file appeared.
"""
import datetime
import importlib
import os
import pathlib
import sqlite3
import threading
import time

import pytest

import backup


def _make_db(path, artists):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE record (artist TEXT)")
    conn.executemany("INSERT INTO record VALUES (?)", [(a,) for a in artists])
    conn.commit()
    conn.close()


def _artists(path):
    conn = sqlite3.connect(path)
    try:
        return [row[0] for row in conn.execute("SELECT artist FROM record")]
    finally:
        conn.close()


def test_snapshot_copies_the_live_rows(tmp_path):
    source = tmp_path / "vinyl.db"
    _make_db(source, ["Tim Maia"])
    backups = tmp_path / "backups"

    written = backup.run_backup(str(source), str(backups), today=datetime.date(2026, 9, 20))

    assert written == str(backups / "vinyl-2026-09-20.db")
    assert _artists(written) == ["Tim Maia"]


def test_a_second_run_on_the_same_day_leaves_the_first_snapshot_alone(tmp_path):
    """The date-stamped name is the idempotency: two gunicorn workers, a
    redeploy, an hourly tick — all of them must land on one file per day."""
    source = tmp_path / "vinyl.db"
    _make_db(source, ["Tim Maia"])
    backups = tmp_path / "backups"
    day = datetime.date(2026, 9, 20)
    first = backup.run_backup(str(source), str(backups), today=day)
    # Mark the snapshot so a rewrite would be visible.
    conn = sqlite3.connect(first)
    conn.execute("INSERT INTO record VALUES ('marker')")
    conn.commit()
    conn.close()

    again = backup.run_backup(str(source), str(backups), today=day)

    assert again is None
    assert "marker" in _artists(first)


def test_a_snapshot_that_fails_leaves_no_file_behind(tmp_path):
    """Half a database under a dated name is worse than no backup at all: it
    reads as a good day to restore from until you try it."""
    source = tmp_path / "vinyl.db"
    source.write_text("this is not a database")
    backups = tmp_path / "backups"

    with pytest.raises(sqlite3.DatabaseError):
        backup.run_backup(str(source), str(backups), today=datetime.date(2026, 9, 20))

    assert list(backups.glob("vinyl-*.db")) == []


def test_no_snapshot_when_there_is_no_database_yet(tmp_path):
    """sqlite3.connect() creates whatever path it is given, so an unguarded
    snapshot of a missing database writes a valid, empty one — and it would
    hold today's slot, so the real data arriving an hour later gets no backup
    until tomorrow."""
    source = tmp_path / "vinyl.db"
    backups = tmp_path / "backups"

    assert backup.run_backup(str(source), str(backups), today=datetime.date(2026, 9, 20)) is None

    assert not source.exists(), "the backup created the database it was meant to copy"
    assert not list(backups.glob("vinyl-*.db"))


def test_prune_keeps_the_five_newest_days(tmp_path):
    backups = tmp_path / "backups"
    backups.mkdir()
    for day in range(10, 19):
        (backups / f"vinyl-2026-09-{day}.db").write_text("x")

    deleted = backup.prune(str(backups), keep=5)

    assert sorted(deleted) == [f"vinyl-2026-09-{day}.db" for day in range(10, 14)]
    assert sorted(p.name for p in backups.iterdir()) == [
        f"vinyl-2026-09-{day}.db" for day in range(14, 19)]


def test_prune_only_touches_its_own_snapshots(tmp_path):
    """The backup folder is on the same volume as everything else; a prune that
    globbed too widely would delete the live database."""
    backups = tmp_path / "backups"
    backups.mkdir()
    (backups / "vinyl.db").write_text("live")
    (backups / "notes.txt").write_text("keep me")
    for day in range(10, 19):
        (backups / f"vinyl-2026-09-{day}.db").write_text("x")

    backup.prune(str(backups), keep=5)

    assert (backups / "vinyl.db").exists()
    assert (backups / "notes.txt").exists()



def test_prune_clears_partials_left_by_a_killed_process(tmp_path):
    """A redeploy SIGKILLs the app; a snapshot caught mid-write leaves its temp
    file behind. Nothing else ever deletes those, so without this the volume
    grows by a whole database every time that happens."""
    backups = tmp_path / "backups"
    backups.mkdir()
    abandoned = backups / "vinyl-2026-09-20.db.4242.part"
    abandoned.write_text("half a database")
    os.utime(abandoned, (time.time() - 7200, time.time() - 7200))
    in_flight = backups / "vinyl-2026-09-20.db.4243.part"
    in_flight.write_text("another worker, still writing")

    backup.prune(str(backups), keep=5)

    assert not abandoned.exists()
    assert in_flight.exists(), "deleted a snapshot another worker was still writing"

def test_list_backups_reports_newest_first_with_sizes(tmp_path):
    backups = tmp_path / "backups"
    backups.mkdir()
    (backups / "vinyl-2026-09-17.db").write_bytes(b"x" * 10)
    (backups / "vinyl-2026-09-19.db").write_bytes(b"x" * 20)
    (backups / "notes.txt").write_text("ignored")

    listed = backup.list_backups(str(backups))

    assert listed == [
        {"name": "vinyl-2026-09-19.db", "date": "2026-09-19", "bytes": 20},
        {"name": "vinyl-2026-09-17.db", "date": "2026-09-17", "bytes": 10},
    ]


def test_listing_a_folder_that_does_not_exist_yet_is_empty(tmp_path):
    """The first boot on a fresh volume opens the menu before the first tick."""
    assert backup.list_backups(str(tmp_path / "nope")) == []


def test_a_tick_snapshots_and_prunes_in_one_pass(tmp_path):
    source = tmp_path / "vinyl.db"
    _make_db(source, ["Tim Maia"])
    backups = tmp_path / "backups"
    backups.mkdir()
    for day in range(10, 19):
        (backups / f"vinyl-2026-09-{day}.db").write_text("x")

    backup.daily_tick(str(source), str(backups), today=datetime.date(2026, 9, 20))

    assert sorted(p.name for p in backups.iterdir()) == [
        "vinyl-2026-09-15.db", "vinyl-2026-09-16.db", "vinyl-2026-09-17.db",
        "vinyl-2026-09-18.db", "vinyl-2026-09-20.db"]
    assert _artists(backups / "vinyl-2026-09-20.db") == ["Tim Maia"]


def test_a_tick_that_fails_does_not_raise(tmp_path):
    """The tick runs on a thread inside the web process. A backup that throws
    must not be able to take the site down with it."""
    source = tmp_path / "vinyl.db"
    source.write_text("this is not a database")

    backup.daily_tick(str(source), str(tmp_path / "backups"), today=datetime.date(2026, 9, 20))


def test_the_scheduler_snapshots_at_boot_and_stops_when_asked(tmp_path):
    """Waiting a whole interval before the first tick would mean a deploy late
    in the day silently skips that day."""
    source = tmp_path / "vinyl.db"
    _make_db(source, ["Tim Maia"])
    backups = tmp_path / "backups"
    stop = threading.Event()

    thread = backup.start_scheduler(str(source), str(backups), interval_seconds=3600, stop=stop)
    try:
        assert thread.daemon, "a non-daemon thread would hold the process open on shutdown"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not list(backups.glob("vinyl-*.db")):
            time.sleep(0.02)
        assert list(backups.glob("vinyl-*.db")), "no snapshot within 5s of boot"
    finally:
        stop.set()
        thread.join(timeout=5)
    assert not thread.is_alive()


# ── the API ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def vinyl_app(tmp_path_factory):
    """A fresh app bound to a throwaway sqlite file. Same guard as test_import."""
    data_dir = tmp_path_factory.mktemp("data")
    previous = {name: os.environ.get(name) for name in ("DATA_DIR", "DATABASE_URL")}
    os.environ["DATA_DIR"] = str(data_dir)
    os.environ.pop("DATABASE_URL", None)
    try:
        module = importlib.reload(importlib.import_module("app"))
        uri = module.app.config["SQLALCHEMY_DATABASE_URI"]
        assert uri == f"sqlite:///{data_dir}/vinyl.db", (
            f"test database escaped the tmp dir, refusing to use it: {uri}")
        with module.app.app_context():
            module.db.create_all()
        yield module
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        importlib.reload(importlib.import_module("app"))


@pytest.fixture
def snapshots(vinyl_app):
    """Two snapshots sitting in the app's backup folder."""
    folder = pathlib.Path(vinyl_app.BACKUP_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.iterdir():
        old.unlink()
    _make_db(folder / "vinyl-2026-09-19.db", ["Tim Maia"])
    _make_db(folder / "vinyl-2026-09-17.db", ["Jorge Ben"])
    return folder


@pytest.fixture
def authed(vinyl_app):
    c = vinyl_app.app.test_client()
    assert c.post("/api/auth/login", json={"password": vinyl_app.EDIT_PASSWORD}).status_code == 200
    return c


def test_listing_snapshots_needs_edit_mode(vinyl_app, snapshots):
    """A snapshot is the whole collection — covers, note photos, private notes.
    It sits behind the same door as /api/export."""
    visitor = vinyl_app.app.test_client()

    assert visitor.get("/api/backups").status_code == 401


def test_downloading_a_snapshot_needs_edit_mode(vinyl_app, snapshots):
    visitor = vinyl_app.app.test_client()

    assert visitor.get("/api/backups/vinyl-2026-09-19.db").status_code == 401


def test_listing_snapshots_reports_them_newest_first(authed, snapshots):
    body = authed.get("/api/backups").get_json()

    assert [b["date"] for b in body["backups"]] == ["2026-09-19", "2026-09-17"]
    assert body["backups"][0]["bytes"] > 0


def test_downloading_a_snapshot_returns_the_database(authed, snapshots, tmp_path):
    resp = authed.get("/api/backups/vinyl-2026-09-19.db")

    assert resp.status_code == 200
    downloaded = tmp_path / "downloaded.db"
    downloaded.write_bytes(resp.get_data())
    assert _artists(downloaded) == ["Tim Maia"]


@pytest.mark.parametrize("name", [
    "vinyl.db",                    # the live database, one folder up in spirit
    "vinyl-2026-09-19.db.part",    # a snapshot still being written
    "..%2F..%2Fetc%2Fpasswd",
])
def test_download_serves_nothing_but_a_dated_snapshot(authed, snapshots, name):
    resp = authed.get(f"/api/backups/{name}")

    assert resp.status_code == 404


# ── wiring the scheduler into the app ─────────────────────────────────────────

def test_the_scheduler_runs_against_the_live_sqlite_file(vinyl_app, monkeypatch):
    monkeypatch.delenv("BACKUP_ENABLED", raising=False)
    stop = threading.Event()

    thread = vinyl_app.start_backups(stop=stop)
    try:
        assert thread is not None
        # Wait for *today's* snapshot by name: the folder may already hold
        # older ones from the tests above, so "any vinyl-*.db" would pass
        # before the thread had done anything.
        folder = pathlib.Path(vinyl_app.BACKUP_DIR)
        today = folder / f"vinyl-{datetime.date.today().isoformat()}.db"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not today.exists():
            time.sleep(0.02)
        assert today.exists(), "no snapshot of the live database within 5s"
    finally:
        stop.set()
        thread.join(timeout=5)


def test_the_switch_turns_the_scheduler_off(vinyl_app, monkeypatch):
    monkeypatch.setenv("BACKUP_ENABLED", "0")

    assert vinyl_app.start_backups() is None


def test_no_scheduler_when_the_database_is_not_sqlite(vinyl_app, monkeypatch):
    """There is no file to snapshot on Postgres, and Railway injects a
    DATABASE_URL by default — a backup loop quietly copying nothing, or worse
    an empty file over a good one, is the failure to avoid here."""
    monkeypatch.delenv("BACKUP_ENABLED", raising=False)
    monkeypatch.setitem(vinyl_app.app.config, "SQLALCHEMY_DATABASE_URI",
                        "postgresql://user:pw@host/db")

    assert vinyl_app.start_backups() is None
