#!/usr/bin/env python3
"""Move every record's genre to the new style-based taxonomy.

Reads genre_mapping.csv (id, artist, album_name, year, old_genre, new_genre),
made by build_genre_prompt.py from a full /api/export, and rewrites ONLY the
record.genre column. Nothing else on a record is read for writing — covers,
ratings, plays, dates and notes are never in an UPDATE.

  python scripts/migrate_genres.py genre_mapping.csv --dry-run
  python scripts/migrate_genres.py genre_mapping.csv --apply

Matching is by id, and a row is only taken when the database's artist and
album agree with the mapping's (case-, accent-form- and whitespace-
insensitive). A missing id or a disagreeing artist/album is left alone and
listed in the mismatch report. --fallback-by-name additionally matches those
leftovers on artist + album (narrowed by year when an album is there twice),
for a database whose ids were renumbered — /api/import assigns fresh ids, so
any copy restored from a CSV will not share the export's.

--apply first copies the database to <db>.pre-genre-migration-<timestamp>
(skip with --no-backup), then writes everything in one transaction. Each
UPDATE also requires the genre to still be what the plan read, so a record
edited in between aborts the whole run instead of being overwritten. Rows
already on their new genre are not touched, so re-running is a no-op.

The database defaults to the app's own: $DATABASE_URL when it is sqlite,
else $DATA_DIR/vinyl.db, else instance/vinyl.db.
"""
import argparse
import csv
import os
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from genres import GENRES  # noqa: E402

csv.field_size_limit(sys.maxsize)


def norm(value):
    """Comparison key: NFC, whitespace collapsed, case folded."""
    return unicodedata.normalize("NFC", " ".join((value or "").split())).casefold()


def default_db_path():
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("sqlite:///"):
        return Path(url[len("sqlite:///"):])
    data_dir = os.environ.get("DATA_DIR")
    # Flask-SQLAlchemy resolves a relative sqlite path against the instance
    # folder, which is where the app's default "./vinyl.db" really lives.
    if data_dir and os.path.isabs(data_dir):
        return Path(data_dir) / "vinyl.db"
    return REPO / "instance" / (Path(data_dir or ".") / "vinyl.db")


def load_mapping(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    missing = {"id", "artist", "album_name", "new_genre"} - set(rows[0] if rows else {})
    if missing:
        raise SystemExit(f"{path}: missing column(s) {', '.join(sorted(missing))}")
    off_list = sorted({r["new_genre"] for r in rows} - set(GENRES))
    if off_list:
        raise SystemExit(f"{path}: new_genre values not in genres.GENRES: {off_list}")
    ids = Counter(r["id"] for r in rows)
    dup = [i for i, n in ids.items() if n > 1]
    if dup:
        raise SystemExit(f"{path}: duplicate ids {dup}")
    return rows


@dataclass
class Plan:
    db_rows: dict                                  # id -> (artist, album, year, genre)
    matches: list = field(default_factory=list)    # (db_id, mapping row, how)
    mismatches: list = field(default_factory=list) # (mapping row, reason)

    @property
    def changes(self):
        return [(rid, self.db_rows[rid][3] or "", row["new_genre"])
                for rid, row, _ in self.matches
                if (self.db_rows[rid][3] or "") != row["new_genre"]]

    @property
    def uncovered(self):
        claimed = {rid for rid, _, _ in self.matches}
        return sorted(rid for rid in self.db_rows if rid not in claimed)

    def genres_after(self):
        after = {rid: (r[3] or "") for rid, r in self.db_rows.items()}
        for rid, _, new in self.changes:
            after[rid] = new
        return after


def describe(artist, album):
    return f"{artist} — {album}"


def build_plan(conn, mapping, fallback_by_name=False):
    db_rows = {rid: (a or "", al or "", y or "", g)
               for rid, a, al, y, g in conn.execute(
                   "SELECT id, artist, album_name, year, genre FROM record")}
    plan = Plan(db_rows)
    claimed = set()
    leftovers = []

    for row in mapping:
        rid = int(row["id"])
        db = db_rows.get(rid)
        if db is None:
            leftovers.append((row, f"id {rid} not in the database"))
        elif (norm(db[0]), norm(db[1])) != (norm(row["artist"]), norm(row["album_name"])):
            leftovers.append((row, f"id {rid} is {describe(db[0], db[1])} in the database"))
        else:
            plan.matches.append((rid, row, "id"))
            claimed.add(rid)

    if not fallback_by_name:
        plan.mismatches = leftovers
        return plan

    by_key = defaultdict(list)
    for rid, (a, al, _, _) in db_rows.items():
        if rid not in claimed:
            by_key[(norm(a), norm(al))].append(rid)
    wanted = defaultdict(list)
    for row, reason in leftovers:
        wanted[(norm(row["artist"]), norm(row["album_name"]))].append((row, reason))

    for key, rows in wanted.items():
        candidates = by_key.get(key, [])
        if not candidates:
            plan.mismatches += [(row, reason + "; no record with that artist + album either")
                                for row, reason in rows]
            continue
        # An album in the collection twice (two Tim Maia "Tim Maia"s): pair by
        # year where that is unambiguous on both sides.
        if len(rows) > 1 or len(candidates) > 1:
            for row, reason in list(rows):
                same_year_db = [rid for rid in candidates if norm(db_rows[rid][2]) == norm(row.get("year"))]
                same_year_map = [r for r, _ in rows if norm(r.get("year")) == norm(row.get("year"))]
                if len(same_year_db) == 1 and len(same_year_map) == 1:
                    plan.matches.append((same_year_db[0], row, "artist+album+year"))
                    candidates.remove(same_year_db[0])
                    rows.remove((row, reason))
        if not rows:
            continue
        if len(rows) == len(candidates) and len({r["new_genre"] for r, _ in rows}) == 1:
            # Indistinguishable copies, but they all go to the same genre, so
            # which mapping row lands on which record cannot matter.
            for rid, (row, _) in zip(sorted(candidates), rows):
                plan.matches.append((rid, row, "artist+album"))
        else:
            plan.mismatches += [(row, f"{len(rows)} mapping row(s) and {len(candidates)} record(s) "
                                      f"share {describe(row['artist'], row['album_name'])} "
                                      "and cannot be paired")
                                for row, _ in rows]
    return plan


def backup(db_path):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = db_path.with_name(f"{db_path.name}.pre-genre-migration-{stamp}")
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return dest


class StaleRow(Exception):
    pass


def apply_plan(conn, plan):
    """Write plan.changes in ONE transaction; any stale row rolls all of it back."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        for rid, old, new in plan.changes:
            cur = conn.execute(
                "UPDATE record SET genre = ? WHERE id = ? AND COALESCE(genre, '') = ?",
                (new, rid, old))
            if cur.rowcount != 1:
                raise StaleRow(f"record {rid} changed since it was read (expected genre {old!r})")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def playlists_off_list(conn):
    """Saved Spotify playlists whose genre filter names a genre not on the list."""
    try:
        rows = conn.execute("SELECT id, name, filters FROM spotify_playlist").fetchall()
    except sqlite3.OperationalError:
        return []
    import json
    out = []
    for pid, name, filters in rows:
        try:
            gs = json.loads(filters or "{}").get("genres") or []
        except ValueError:
            continue
        bad = [g for g in gs if g not in GENRES]
        if bad:
            out.append((pid, name, bad))
    return out


def report(plan, mapping, conn):
    p = print
    by_how = Counter(how for _, _, how in plan.matches)
    changes = plan.changes
    p("\nMatching")
    for label, n in [("mapping rows:", len(mapping)),
                     ("records in database:", len(plan.db_rows)),
                     ("matched by id:", by_how["id"]),
                     ("matched by artist+album:", by_how["artist+album"] + by_how["artist+album+year"]),
                     ("mismatched (skipped):", len(plan.mismatches)),
                     ("records to change:", len(changes)),
                     ("already on new genre:", len(plan.matches) - len(changes))]:
        p(f"  {label:<26}{n}")

    p("\nChanges (old -> new)")
    if not changes:
        p("  (none)")
    for (old, new), n in sorted(Counter((o, nw) for _, o, nw in changes).items(),
                                key=lambda kv: (-kv[1], kv[0])):
        p(f"  {n:>4}  {old or '(no genre)'} -> {new}")

    before = Counter((r[3] or "") for r in plan.db_rows.values())
    after = Counter(plan.genres_after().values())
    expected = Counter(r["new_genre"] for r in mapping)
    p("\nGenre totals in the database")
    p(f"  {'genre':<28}{'before':>7}{'after':>7}{'expected':>10}")
    names = sorted(set(before) | set(after) | set(expected),
                   key=lambda g: (-expected.get(g, 0), -after.get(g, 0), g))
    for g in names:
        flag = "" if after.get(g, 0) == expected.get(g, 0) else "  <- differs"
        p(f"  {g or '(no genre)':<28}{before.get(g, 0):>7}{after.get(g, 0):>7}{expected.get(g, 0):>10}{flag}")
    p(f"  {'total':<28}{sum(before.values()):>7}{sum(after.values()):>7}{sum(expected.values()):>10}")
    p("  totals match the mapping" if after == expected else
      "  totals do NOT match the mapping")

    p(f"\nMismatch report ({len(plan.mismatches)})")
    for row, reason in sorted(plan.mismatches, key=lambda m: int(m[0]["id"])):
        p(f"  csv id {row['id']:>4}  {describe(row['artist'], row['album_name'])}"
          f"  ->  {row['new_genre']}  [{reason}]")

    uncovered = plan.uncovered
    after_genres = plan.genres_after()
    p(f"\nRecords not in the mapping ({len(uncovered)}) — genre left as is")
    for rid in uncovered:
        a, al, _, g = plan.db_rows[rid]
        tag = "" if (g or "") in GENRES or not g else "  (off the new list)"
        p(f"  db id {rid:>4}  {describe(a, al)}  [{g or 'no genre'}]{tag}")

    leftover = Counter(g for g in after_genres.values() if g and g not in GENRES)
    if leftover:
        p("\nGenres off the new list after this run: "
          + ", ".join(f"{g} ({n})" for g, n in leftover.most_common()))
    for pid, name, bad in playlists_off_list(conn):
        p(f"\nSaved playlist {pid} {name!r} filters on genre(s) off the new list: {bad}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("mapping", type=Path, help="genre_mapping.csv")
    ap.add_argument("--db", type=Path, default=None, help="SQLite file (default: the app's)")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    mode.add_argument("--apply", action="store_true", help="write the changes")
    ap.add_argument("--fallback-by-name", action="store_true",
                    help="match rows whose id fails on artist + album instead")
    ap.add_argument("--no-backup", action="store_true", help="skip the copy made before --apply")
    a = ap.parse_args(argv)

    db_path = a.db or default_db_path()
    if not db_path.is_file():
        raise SystemExit(f"no database at {db_path}")
    mapping = load_mapping(a.mapping)
    print(f"database: {db_path}\nmapping:  {a.mapping}\nmode:     "
          f"{'apply' if a.apply else 'dry run'}"
          f"{', fallback by artist+album' if a.fallback_by_name else ', match by id only'}")

    if a.dry_run:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            report(build_plan(conn, mapping, a.fallback_by_name), mapping, conn)
        finally:
            conn.close()
        print("\nDry run: nothing was written.")
        return 0

    if not a.no_backup:
        print(f"backup:   {backup(db_path)}")
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        plan = build_plan(conn, mapping, a.fallback_by_name)
        report(plan, mapping, conn)
        try:
            apply_plan(conn, plan)
        except StaleRow as e:
            print(f"\nABORTED, nothing written: {e}", file=sys.stderr)
            return 1
        print(f"\nApplied: {len(plan.changes)} genre(s) updated in one transaction.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
