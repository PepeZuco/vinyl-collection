"""Daily snapshots of the SQLite collection, kept for the last few days."""

import datetime
import logging
import os
import re
import sqlite3
import threading
import time

log = logging.getLogger(__name__)

KEEP_DAYS = 5
INTERVAL_SECONDS = 3600
# How long a .part file may sit before it counts as abandoned rather than
# in flight. A snapshot takes a second; an hour is only about being sure.
PARTIAL_MAX_AGE_SECONDS = 3600

# The one shape prune deletes and the download endpoint serves. Anything else
# in the folder is somebody else's file.
NAME_RE = re.compile(r"^vinyl-\d{4}-\d{2}-\d{2}\.db$")


def snapshot_names(backup_dir):
    """Snapshot filenames in the folder, newest day first."""
    try:
        entries = os.listdir(backup_dir)
    except FileNotFoundError:
        return []
    # ISO dates sort chronologically as text, so no parsing is needed here.
    return sorted((n for n in entries if NAME_RE.match(n)), reverse=True)


def prune(backup_dir, keep=KEEP_DAYS, now=None):
    """Delete all but the `keep` newest snapshots, return the names removed.

    Also sweeps up temp files abandoned by a process that was killed mid-write
    — a redeploy in the wrong second — since nothing else ever would, and each
    one is the size of a whole database.
    """
    deleted = []
    deleted += _sweep_partials(backup_dir, now=now)
    for name in snapshot_names(backup_dir)[keep:]:
        try:
            os.remove(os.path.join(backup_dir, name))
        except OSError:
            continue
        deleted.append(name)
    return deleted


def run_backup(source_path, backup_dir, today=None):
    """Write today's snapshot of source_path into backup_dir, return its path.

    Returns None when today's snapshot is already there, or when there is no
    database to copy yet.

    The copy goes through SQLite's online backup API rather than a file copy:
    gunicorn is serving while this runs, and `cp` of a database mid-transaction
    can capture a torn write — a file that looks like a backup and restores as
    a corrupt database. It lands on a temp name first and is renamed into place,
    so a snapshot that dies halfway never occupies the dated name.
    """
    # sqlite3.connect() would happily create a missing source and copy the
    # empty result into today's slot, locking out the real snapshot until
    # tomorrow. No database yet means nothing to back up.
    if not os.path.isfile(source_path):
        return None

    day = today or datetime.date.today()
    os.makedirs(backup_dir, exist_ok=True)
    dest = os.path.join(backup_dir, f"vinyl-{day.isoformat()}.db")
    if os.path.exists(dest):
        return None

    # The pid keeps two workers that start in the same second off each other's
    # temp file; whichever finishes last renames a complete snapshot into place.
    partial = f"{dest}.{os.getpid()}.part"
    try:
        source = sqlite3.connect(source_path)
        try:
            target = sqlite3.connect(partial)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
        os.replace(partial, dest)
    except BaseException:
        for leftover in (partial, f"{partial}-journal", f"{partial}-wal"):
            try:
                os.remove(leftover)
            except OSError:
                pass
        raise
    return dest


def _sweep_partials(backup_dir, now=None):
    """Remove temp files old enough that no live writer could still own them."""
    cutoff = (now or time.time()) - PARTIAL_MAX_AGE_SECONDS
    removed = []
    try:
        entries = os.listdir(backup_dir)
    except FileNotFoundError:
        return removed
    for name in entries:
        if not name.endswith(".part"):
            continue
        path = os.path.join(backup_dir, name)
        try:
            if os.path.getmtime(path) > cutoff:
                continue
            os.remove(path)
        except OSError:
            continue
        removed.append(name)
    return removed


def list_backups(backup_dir):
    """Snapshots on disk, newest first, as plain dicts for the API."""
    listed = []
    for name in snapshot_names(backup_dir):
        try:
            size = os.path.getsize(os.path.join(backup_dir, name))
        except OSError:
            continue
        listed.append({"name": name, "date": name[len("vinyl-"):-len(".db")], "bytes": size})
    return listed


def daily_tick(source_path, backup_dir, today=None, keep=KEEP_DAYS):
    """One day's work: snapshot if needed, then prune. Never raises.

    This runs on a thread inside the web process, so a failure here — a full
    volume, a locked database — is logged and dropped rather than allowed to
    kill the app that is still serving the collection fine without it.
    """
    try:
        written = run_backup(source_path, backup_dir, today=today)
        if written:
            log.info("backup: wrote %s", written)
        for name in prune(backup_dir, keep=keep):
            log.info("backup: pruned %s", name)
    except Exception:
        log.exception("backup: snapshot failed")


def start_scheduler(source_path, backup_dir, interval_seconds=INTERVAL_SECONDS, stop=None):
    """Run daily_tick now and every interval after, on a daemon thread.

    Hourly rather than "once a day at 03:00": the process restarts on every
    deploy, so a fixed wall-clock alarm is one badly-timed redeploy away from
    missing a day. Ticking often and keying the snapshot on today's date gets
    the same one-file-a-day result without a clock to miss.
    """
    stop = stop or threading.Event()

    def loop():
        while not stop.is_set():
            daily_tick(source_path, backup_dir)
            stop.wait(interval_seconds)

    thread = threading.Thread(target=loop, name="vinyl-backup", daemon=True)
    thread.start()
    return thread
