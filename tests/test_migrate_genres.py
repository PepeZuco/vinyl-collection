"""scripts/migrate_genres.py: moves each record's genre to the new taxonomy.

Every test builds its own small SQLite file and mapping CSV, so nothing here
touches the session database the rest of the suite shares.
"""
import csv
import sqlite3

import pytest

from scripts import migrate_genres as mg

COLUMNS = ["id", "artist", "album_name", "year", "genre", "my_rating", "wife_rating",
           "play_count", "play_dates", "bought_date", "cover_data", "notes"]


def make_db(tmp_path, rows):
    path = tmp_path / "vinyl.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE record (id INTEGER PRIMARY KEY, artist VARCHAR(200), "
                 "album_name VARCHAR(200), year VARCHAR(10), genre VARCHAR(100), "
                 "my_rating FLOAT, wife_rating FLOAT, play_count INTEGER, play_dates TEXT, "
                 "bought_date VARCHAR(50), cover_data TEXT, notes TEXT)")
    for r in rows:
        full = {"year": "1970", "my_rating": 4.5, "wife_rating": 3.0, "play_count": 7,
                "play_dates": '["2026-01-01"]', "bought_date": "2025-05-05",
                "cover_data": "data:image/jpeg;base64,AAAA", "notes": "a note", **r}
        conn.execute(f"INSERT INTO record ({','.join(COLUMNS)}) VALUES ({','.join('?' * len(COLUMNS))})",
                     [full[c] for c in COLUMNS])
    conn.commit()
    conn.close()
    return path


def make_mapping(tmp_path, rows):
    path = tmp_path / "genre_mapping.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "artist", "album_name", "year", "old_genre", "new_genre"])
        w.writeheader()
        for r in rows:
            w.writerow({"year": "1970", "old_genre": "", **r})
    return path


def dump(path):
    conn = sqlite3.connect(path)
    rows = {r[0]: r for r in conn.execute(f"SELECT {','.join(COLUMNS)} FROM record")}
    conn.close()
    return rows


def genres(path):
    return {rid: row[COLUMNS.index("genre")] for rid, row in dump(path).items()}


def run(*args):
    return mg.main([str(a) for a in args])


@pytest.fixture
def basic(tmp_path):
    db = make_db(tmp_path, [
        {"id": 1, "artist": "Cartola", "album_name": "Cartola", "genre": "MPB & Samba"},
        {"id": 2, "artist": "Tim Maia", "album_name": "Racional", "genre": "Soul & Funk"},
        {"id": 3, "artist": "Nirvana", "album_name": "Nevermind", "genre": "Rock"},
    ])
    mapping = make_mapping(tmp_path, [
        {"id": 1, "artist": "Cartola", "album_name": "Cartola", "new_genre": "Samba"},
        {"id": 2, "artist": "Tim Maia", "album_name": "Racional", "new_genre": "Soul & Funk"},
        {"id": 3, "artist": "Nirvana", "album_name": "Nevermind", "new_genre": "Alternative & Indie"},
    ])
    return db, mapping


def test_dry_run_writes_nothing(basic, capsys):
    db, mapping = basic
    before = db.read_bytes()

    assert run(mapping, "--db", db, "--dry-run") == 0

    assert db.read_bytes() == before
    out = capsys.readouterr().out
    assert "MPB & Samba -> Samba" in out
    assert "Rock -> Alternative & Indie" in out
    assert not list(db.parent.glob("*.pre-genre-migration-*"))


def test_apply_changes_only_the_genre_column(basic):
    db, mapping = basic
    before = dump(db)

    assert run(mapping, "--db", db, "--apply") == 0

    after = dump(db)
    assert genres(db) == {1: "Samba", 2: "Soul & Funk", 3: "Alternative & Indie"}
    g = COLUMNS.index("genre")
    for rid in before:
        assert before[rid][:g] + before[rid][g + 1:] == after[rid][:g] + after[rid][g + 1:]


def test_apply_backs_up_the_database_first(basic):
    db, mapping = basic
    original = genres(db)

    run(mapping, "--db", db, "--apply")

    backups = list(db.parent.glob("vinyl.db.pre-genre-migration-*"))
    assert len(backups) == 1
    assert genres(backups[0]) == original


def test_rerunning_apply_changes_nothing(basic, capsys):
    db, mapping = basic
    run(mapping, "--db", db, "--apply")
    once = db.read_bytes()
    capsys.readouterr()

    assert run(mapping, "--db", db, "--apply", "--no-backup") == 0

    assert db.read_bytes() == once
    assert "records to change:        0" in capsys.readouterr().out
    assert genres(db) == {1: "Samba", 2: "Soul & Funk", 3: "Alternative & Indie"}


def test_match_ignores_case_and_whitespace(tmp_path):
    db = make_db(tmp_path, [{"id": 1, "artist": "  tim   MAIA ", "album_name": "racional", "genre": "Pop"}])
    mapping = make_mapping(tmp_path, [{"id": 1, "artist": "Tim Maia", "album_name": "Racional ",
                                       "new_genre": "Soul & Funk"}])

    run(mapping, "--db", db, "--apply", "--no-backup")

    assert genres(db) == {1: "Soul & Funk"}


def test_an_id_whose_artist_or_album_differs_is_reported_not_updated(tmp_path, capsys):
    db = make_db(tmp_path, [
        {"id": 1, "artist": "ABBA", "album_name": "Dez Anos", "genre": "Pop"},
        {"id": 2, "artist": "Adele", "album_name": "21", "genre": "Pop"},
    ])
    mapping = make_mapping(tmp_path, [
        {"id": 1, "artist": "Adele", "album_name": "19", "new_genre": "R&B & Neo-Soul"},
        {"id": 2, "artist": "Adele", "album_name": "25", "new_genre": "R&B & Neo-Soul"},
    ])

    run(mapping, "--db", db, "--apply", "--no-backup")

    assert genres(db) == {1: "Pop", 2: "Pop"}
    out = capsys.readouterr().out
    assert "Mismatch report (2)" in out
    assert "Adele — 19" in out and "ABBA — Dez Anos" in out


def test_a_missing_id_is_reported(tmp_path, capsys):
    db = make_db(tmp_path, [{"id": 1, "artist": "A", "album_name": "B", "genre": "Pop"}])
    mapping = make_mapping(tmp_path, [
        {"id": 1, "artist": "A", "album_name": "B", "new_genre": "Rock"},
        {"id": 99, "artist": "Ghost", "album_name": "Gone", "new_genre": "Jazz"},
    ])

    run(mapping, "--db", db, "--apply", "--no-backup")

    assert genres(db) == {1: "Rock"}
    out = capsys.readouterr().out
    assert "Mismatch report (1)" in out and "id 99 not in the database" in out


def test_shifted_ids_match_by_name_only_with_the_fallback(tmp_path, capsys):
    rows = [{"id": 1, "artist": "Adele", "album_name": "19", "genre": "Pop"},
            {"id": 2, "artist": "Adele", "album_name": "21", "genre": "Pop"}]
    mapping = make_mapping(tmp_path, [
        {"id": 7, "artist": "Adele", "album_name": "21", "new_genre": "R&B & Neo-Soul"},
        {"id": 1, "artist": "Adele", "album_name": "21 (Deluxe)", "new_genre": "Jazz"},
        {"id": 8, "artist": "adele", "album_name": "19", "new_genre": "Soul & Funk"},
    ])
    db = make_db(tmp_path, rows)

    run(mapping, "--db", db, "--apply", "--no-backup")
    assert genres(db) == {1: "Pop", 2: "Pop"}

    capsys.readouterr()
    run(mapping, "--db", db, "--apply", "--no-backup", "--fallback-by-name")
    assert genres(db) == {1: "Soul & Funk", 2: "R&B & Neo-Soul"}
    out = capsys.readouterr().out
    assert "matched by artist+album:  2" in out
    assert "Mismatch report (1)" in out and "21 (Deluxe)" in out


def test_fallback_pairs_duplicate_albums_by_year(tmp_path):
    db = make_db(tmp_path, [
        {"id": 1, "artist": "Tim Maia", "album_name": "Tim Maia", "year": "1970", "genre": "MPB & Samba"},
        {"id": 2, "artist": "Tim Maia", "album_name": "Tim Maia", "year": "1973", "genre": "MPB & Samba"},
    ])
    mapping = make_mapping(tmp_path, [
        {"id": 50, "artist": "Tim Maia", "album_name": "Tim Maia", "year": "1973", "new_genre": "Samba"},
        {"id": 51, "artist": "Tim Maia", "album_name": "Tim Maia", "year": "1970", "new_genre": "Soul & Funk"},
    ])

    run(mapping, "--db", db, "--apply", "--no-backup", "--fallback-by-name")

    assert genres(db) == {1: "Soul & Funk", 2: "Samba"}


def test_fallback_takes_identical_duplicates_when_they_agree_on_the_genre(tmp_path):
    same = {"artist": "Lee Perry", "album_name": "Super Ape", "year": "1976", "genre": ""}
    db = make_db(tmp_path, [{"id": 1, **same}, {"id": 2, **same}])
    mapping = make_mapping(tmp_path, [
        {"id": 10, "artist": "Lee Perry", "album_name": "Super Ape", "year": "1976", "new_genre": "Reggae"},
        {"id": 11, "artist": "Lee Perry", "album_name": "Super Ape", "year": "1976", "new_genre": "Reggae"},
    ])

    run(mapping, "--db", db, "--apply", "--no-backup", "--fallback-by-name")

    assert genres(db) == {1: "Reggae", 2: "Reggae"}


def test_fallback_refuses_duplicates_it_cannot_tell_apart(tmp_path, capsys):
    same = {"artist": "Evinha", "album_name": "Evinha", "year": "1970", "genre": "Pop"}
    db = make_db(tmp_path, [{"id": 1, **same}, {"id": 2, **same}])
    mapping = make_mapping(tmp_path, [
        {"id": 10, "artist": "Evinha", "album_name": "Evinha", "year": "1970", "new_genre": "Pop"},
        {"id": 11, "artist": "Evinha", "album_name": "Evinha", "year": "1970", "new_genre": "Soft Rock"},
    ])

    run(mapping, "--db", db, "--apply", "--no-backup", "--fallback-by-name")

    assert genres(db) == {1: "Pop", 2: "Pop"}
    assert "Mismatch report (2)" in capsys.readouterr().out


def test_an_id_match_is_never_claimed_again_by_the_fallback(tmp_path):
    db = make_db(tmp_path, [{"id": 1, "artist": "A", "album_name": "B", "genre": "Pop"}])
    mapping = make_mapping(tmp_path, [
        {"id": 1, "artist": "A", "album_name": "B", "new_genre": "Rock"},
        {"id": 2, "artist": "A", "album_name": "B", "new_genre": "Jazz"},
    ])

    run(mapping, "--db", db, "--apply", "--no-backup", "--fallback-by-name")

    assert genres(db) == {1: "Rock"}


def test_a_record_edited_after_the_plan_aborts_the_whole_transaction(basic, monkeypatch):
    db, mapping = basic
    real_plan = mg.build_plan

    def plan_then_edit(conn, *a, **kw):
        plan = real_plan(conn, *a, **kw)
        other = sqlite3.connect(db)
        other.execute("UPDATE record SET genre = 'Jazz' WHERE id = 3")
        other.commit()
        other.close()
        return plan

    monkeypatch.setattr(mg, "build_plan", plan_then_edit)

    assert run(mapping, "--db", db, "--apply", "--no-backup") != 0
    assert genres(db) == {1: "MPB & Samba", 2: "Soul & Funk", 3: "Jazz"}


def test_a_mapping_genre_off_the_list_is_refused(tmp_path):
    db = make_db(tmp_path, [{"id": 1, "artist": "A", "album_name": "B", "genre": "Pop"}])
    mapping = make_mapping(tmp_path, [{"id": 1, "artist": "A", "album_name": "B", "new_genre": "MPB & Samba"}])

    with pytest.raises(SystemExit, match="MPB & Samba"):
        run(mapping, "--db", db, "--apply", "--no-backup")
    assert genres(db) == {1: "Pop"}


def test_dry_run_or_apply_is_required(basic):
    db, mapping = basic
    with pytest.raises(SystemExit):
        run(mapping, "--db", db)


def test_records_outside_the_mapping_are_listed_and_kept(tmp_path, capsys):
    db = make_db(tmp_path, [
        {"id": 1, "artist": "A", "album_name": "B", "genre": "Pop"},
        {"id": 2, "artist": "New", "album_name": "Buy", "genre": "MPB & Samba"},
    ])
    mapping = make_mapping(tmp_path, [{"id": 1, "artist": "A", "album_name": "B", "new_genre": "Rock"}])

    run(mapping, "--db", db, "--apply", "--no-backup")

    assert genres(db) == {1: "Rock", 2: "MPB & Samba"}
    out = capsys.readouterr().out
    assert "not in the mapping (1)" in out and "New — Buy" in out
    assert "off the new list" in out
