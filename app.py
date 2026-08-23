import os, io, base64, csv, json
csv.field_size_limit(10 * 1024 * 1024)
from flask import Flask, request, jsonify, send_file, session, render_template
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from datetime import datetime
from functools import wraps

import scan

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")

_default_sqlite_path = os.path.join(os.environ.get("DATA_DIR", "."), "vinyl.db")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", f"sqlite:///{_default_sqlite_path}")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
def _upload_ceiling_bytes():
    """Upload ceiling in bytes, from MAX_UPLOAD_MB.

    Covers ride along in the CSV as base64, so a collection export runs far
    larger than the record count suggests and the old fixed 32MB cap rejected
    it. A malformed value falls back to the default instead of raising: this
    runs at import time, so a typo in the Railway variable would otherwise be
    a boot loop rather than a legible error.

    Note the ceiling is not free capacity. The import reads the whole body,
    decodes it, and builds every row in memory before committing, costing
    roughly 8x the file size in RSS (a 120MB CSV peaks near 950MB). Raise this
    past ~64MB only if the process has the memory to match.
    """
    try:
        return max(1, int(os.environ.get("MAX_UPLOAD_MB", "128"))) * 1024 * 1024
    except ValueError:
        return 128 * 1024 * 1024

app.config["MAX_CONTENT_LENGTH"] = _upload_ceiling_bytes()

EDIT_PASSWORD = os.environ.get("EDIT_PASSWORD", "vinyl123")

db = SQLAlchemy(app)

# Every dated field on a record — bought_date, play_dates, cleaned_dates and a
# note's date — holds the same two shapes, and the app only ever reads them, never
# computes on them, so they stay opaque strings here:
#
#   'YYYY-MM-DD'            recorded before times were kept. Ordered as midnight,
#                           but never shown with a clock — the collection does not
#                           know when in the day it happened.
#   'YYYY-MM-DDTHH:MM:SS'   a LOCAL wall clock, no zone suffix. What is written
#                           now, so the collection keeps the order things happened
#                           in. Deliberately not UTC: everything downstream reads
#                           the first 10 characters as the calendar day, and a UTC
#                           stamp files an evening event on the following day.
#
# static/grouping.js momentOf() is the one reader of these, and also converts the
# UTC stamps the play buttons wrote before this.
class Record(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    artist      = db.Column(db.String(200))
    album_name  = db.Column(db.String(200))
    year        = db.Column(db.String(10))
    genre       = db.Column(db.String(100))
    bought_date = db.Column(db.String(50))  # a stamp — see the note above
    bought_where= db.Column(db.String(200))
    bought_by   = db.Column(db.String(100))
    my_rating   = db.Column(db.Float, default=0)
    wife_rating = db.Column(db.Float, default=0)
    have_it     = db.Column(db.Boolean, default=True)
    play_count  = db.Column(db.Integer, default=0)
    play_dates  = db.Column(db.Text)      # JSON array of stamps, one per play
    last_cleaned= db.Column(db.String(50))  # deprecated: superseded by cleaned_dates, kept for migration only
    cleaned_dates = db.Column(db.Text)    # JSON array of stamps, one per cleaning
    cover_data  = db.Column(db.Text)      # base64 data URI
    notes       = db.Column(db.Text)      # JSON array of {date: stamp, text: markdown}
    country     = db.Column(db.String(2)) # ISO 3166-1 alpha-2 country code, e.g. "BR", "US"

    def to_dict(self):
        return {
            "id": self.id,
            "artist": self.artist or "",
            "album_name": self.album_name or "",
            "year": self.year or "",
            "genre": self.genre or "",
            "bought_date": self.bought_date or "",
            "bought_where": self.bought_where or "",
            "bought_by": self.bought_by or "",
            "my_rating": self.my_rating or 0,
            "wife_rating": self.wife_rating or 0,
            "have_it": bool(self.have_it),
            "play_count": self.play_count or 0,
            "play_dates": self.play_dates or "",
            "cleaned_dates": self.cleaned_dates or "",
            "cover_data": self.cover_data or "",
            "notes": self.notes or "",
            "country": self.country or "",
        }

with app.app_context():
    db.create_all()
    # lightweight auto-migration: db.create_all() only creates missing tables,
    # it won't add new columns to a table that already exists (e.g. on Railway's
    # persisted Postgres/SQLite). Add any columns that are missing.
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    existing_cols = [c["name"] for c in inspector.get_columns("record")]
    missing_cols = {
        "country": "VARCHAR(2)",
        "play_dates": "TEXT",
        "cleaned_dates": "TEXT",
    }
    added_cleaned_dates = "cleaned_dates" not in existing_cols
    for col, ddl_type in missing_cols.items():
        if col not in existing_cols:
            with db.engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE record ADD COLUMN {col} {ddl_type}"))
                conn.commit()

    # one-time backfill: seed cleaned_dates from the old single-value last_cleaned
    # column for any row that hasn't been migrated yet
    if added_cleaned_dates:
        stale = Record.query.filter(
            Record.last_cleaned.isnot(None), Record.last_cleaned != "",
            (Record.cleaned_dates.is_(None)) | (Record.cleaned_dates == "")
        ).all()
        for r in stale:
            r.cleaned_dates = json.dumps([r.last_cleaned])
        if stale:
            db.session.commit()

# ── auth helpers ──────────────────────────────────────────────────────────────

def is_authed():
    return session.get("authed") is True

def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_authed():
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper

# ── pages ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

# ── auth endpoints ────────────────────────────────────────────────────────────

@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    if data.get("password") == EDIT_PASSWORD:
        session["authed"] = True
        return jsonify({"ok": True})
    return jsonify({"error": "Wrong password"}), 403

@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/api/auth/status")
def auth_status():
    return jsonify({"authed": is_authed()})

# ── records API ───────────────────────────────────────────────────────────────

@app.route("/api/records")
def list_records():
    recs = Record.query.order_by(Record.artist).all()
    return jsonify([r.to_dict() for r in recs])

@app.route("/api/records", methods=["POST"])
@require_auth
def create_record():
    d = request.get_json(silent=True) or {}
    r = Record(
        artist      = d.get("artist",""),
        album_name  = d.get("album_name",""),
        year        = d.get("year",""),
        genre       = d.get("genre",""),
        bought_date = d.get("bought_date",""),
        bought_where= d.get("bought_where",""),
        bought_by   = d.get("bought_by",""),
        my_rating   = float(d.get("my_rating") or 0),
        wife_rating = float(d.get("wife_rating") or 0),
        have_it     = bool(d.get("have_it", True)),
        play_count  = int(d.get("play_count") or 0),
        play_dates  = d.get("play_dates",""),
        cleaned_dates = d.get("cleaned_dates",""),
        cover_data  = d.get("cover_data",""),
        notes       = d.get("notes",""),
        country     = (d.get("country") or "").strip().upper()[:2],
    )
    db.session.add(r)
    db.session.commit()
    return jsonify(r.to_dict()), 201

@app.route("/api/records/<int:rid>", methods=["PUT"])
@require_auth
def update_record(rid):
    r = Record.query.get_or_404(rid)
    d = request.get_json(silent=True) or {}
    for field in ["artist","album_name","year","genre","bought_date","bought_where","bought_by"]:
        if field in d:
            setattr(r, field, d[field])
    if "my_rating"   in d: r.my_rating   = float(d["my_rating"] or 0)
    if "wife_rating" in d: r.wife_rating  = float(d["wife_rating"] or 0)
    if "have_it"     in d: r.have_it      = bool(d["have_it"])
    if "play_count"  in d: r.play_count   = int(d["play_count"] or 0)
    if "play_dates"  in d: r.play_dates   = d["play_dates"]
    if "cleaned_dates" in d: r.cleaned_dates = d["cleaned_dates"]
    if "cover_data"  in d: r.cover_data   = d["cover_data"]
    if "notes"       in d: r.notes        = d["notes"]
    if "country"     in d: r.country      = (d["country"] or "").strip().upper()[:2]
    db.session.commit()
    return jsonify(r.to_dict())

@app.route("/api/records/<int:rid>", methods=["DELETE"])
@require_auth
def delete_record(rid):
    r = Record.query.get_or_404(rid)
    db.session.delete(r)
    db.session.commit()
    return jsonify({"ok": True})

# ── scan (photo / Spotify autofill) ───────────────────────────────────────────

@app.route("/api/scan", methods=["POST"])
@require_auth
def scan_record():
    d = request.get_json(silent=True) or {}
    image = d.get("image")
    spotify_url = d.get("spotify_url")
    if bool(image) == bool(spotify_url):
        return jsonify({"error": "Provide exactly one of image or spotify_url"}), 400

    # Load only the four columns needed. Record.query.all() would pull every
    # cover_data blob — ~31MB across the collection — on every scan.
    rows = db.session.query(
        Record.id, Record.artist, Record.album_name, Record.genre
    ).all()
    genres = sorted({r.genre for r in rows if r.genre})

    # The whole pipeline runs inside one try/except: lookup_musicbrainz,
    # fetch_cover and find_duplicate are documented never to raise, but that
    # contract isn't airtight (e.g. a 200 with an unexpected JSON shape can
    # still blow up a caller). The route doesn't trust it absolutely — any
    # escape here must still degrade to a JSON error, never a 500 HTML page.
    try:
        if image:
            source = "photo"
            fields = scan.extract_from_image(image, genres)
            spotify_image = None
        else:
            source = "spotify"
            resolved = scan.extract_from_spotify(spotify_url)
            spotify_image = resolved.get("image_url")
            fields = {
                "artist": resolved["artist"],
                "album_name": resolved["album_name"],
                "genre": scan.classify_genre(
                    resolved["artist"], resolved["album_name"], genres),
                "label": None,
                "catalog_number": None,
            }

        artist = fields.get("artist") or ""
        album = fields.get("album_name") or ""

        candidates = scan.lookup_musicbrainz(artist, album)
        for candidate in candidates:
            candidate["cover_data"] = scan.fetch_cover(candidate, spotify_image)

        existing = [{"id": r.id, "artist": r.artist or "",
                     "album_name": r.album_name or ""} for r in rows]
        duplicate = scan.find_duplicate(artist, album, existing)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        message = str(e)
        status = 503 if "not set" in message else 502
        return jsonify({"error": message}), status
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    year = candidates[0]["year"] if candidates else ""

    return jsonify({
        "source": source,
        "artist": artist,
        "album_name": album,
        "genre": fields.get("genre") or "",
        "candidates": candidates,
        "duplicate_of": {"id": duplicate["id"], "artist": duplicate["artist"],
                         "album_name": duplicate["album_name"]} if duplicate else None,
        "search_string": " ".join(p for p in [artist, album, year, "vinyl cover"] if p),
    })

# ── CSV import / export ───────────────────────────────────────────────────────

@app.route("/api/export")
def export_csv():
    recs = Record.query.order_by(Record.artist).all()
    cols = ["id","artist","album_name","year","genre","bought_date","bought_where",
            "bought_by","my_rating","wife_rating","have_it","play_count","play_dates","cleaned_dates","cover_image_base64","notes","country"]

    def generate():
        yield ",".join(cols) + "\n"
        for r in recs:
            d = r.to_dict()
            d["cover_image_base64"] = d.pop("cover_data","")
            row = []
            for c in cols:
                v = str(d.get(c,""))
                if "," in v or '"' in v or "\n" in v:
                    v = '"' + v.replace('"','""') + '"'
                row.append(v)
            yield ",".join(row) + "\n"

    return app.response_class(generate(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=vinyl_collection.csv"})

# Rows are inserted in batches so a large restore never holds the whole
# collection on the heap at once. Covers are base64 data URIs, so a few hundred
# rows is already tens of MB — this is the knob that bounds it.
_IMPORT_BATCH_ROWS = 500


def _record_mapping(row):
    """Turn one CSV row into a Record column mapping."""
    cover = row.get("cover_image_base64","") or row.get("cover_data","")
    if cover and not cover.startswith("data:"):
        cover = "data:image/jpeg;base64," + cover
    cleaned_dates = row.get("cleaned_dates","")
    if not cleaned_dates and row.get("last_cleaned",""):
        cleaned_dates = json.dumps([row["last_cleaned"]])
    return {
        "artist":      row.get("artist",""),
        "album_name":  row.get("album_name",""),
        "year":        row.get("year",""),
        "genre":       row.get("genre",""),
        "bought_date": row.get("bought_date",""),
        "bought_where":row.get("bought_where",""),
        "bought_by":   row.get("bought_by",""),
        "my_rating":   float(row.get("my_rating") or 0),
        "wife_rating": float(row.get("wife_rating") or 0),
        "have_it":     row.get("have_it","").lower() in ("true","1","yes"),
        "play_count":  int(row.get("play_count") or 0),
        "play_dates":  row.get("play_dates",""),
        "cleaned_dates": cleaned_dates,
        "cover_data":  cover,
        "notes":       row.get("notes",""),
        "country":     (row.get("country","") or "").strip().upper()[:2],
    }


def import_records_from_csv_rows(rows):
    """Replace the whole collection from an iterable of CSV row dicts.

    Inserted in batches to bound memory, but still ONE transaction: the delete
    and every batch commit together at the end. A failure part-way therefore
    rolls back to the existing collection rather than leaving it half-replaced
    — this wipes the table first, so a partial import would be data loss.
    """
    Record.query.delete()
    count = 0
    batch = []
    for row in rows:
        batch.append(_record_mapping(row))
        count += 1
        if len(batch) >= _IMPORT_BATCH_ROWS:
            db.session.execute(db.insert(Record), batch)
            batch.clear()
    if batch:
        db.session.execute(db.insert(Record), batch)
    db.session.commit()
    return count


def import_records_from_csv_text(text):
    """Import from a CSV already held in memory. Prefer the streaming path."""
    return import_records_from_csv_rows(csv.DictReader(io.StringIO(text)))


@app.route("/api/import", methods=["POST"])
@require_auth
def import_csv():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file"}), 400
    try:
        # Read the upload as a stream. Werkzeug spools anything large to a temp
        # file, so this stays off the heap; file.read().decode() used to make
        # three full-size copies of the CSV before parsing even began, which is
        # most of why a 120MB import peaked near 950MB of RSS.
        stream = io.TextIOWrapper(file.stream, encoding="utf-8",
                                  errors="replace", newline="")
        count = import_records_from_csv_rows(csv.DictReader(stream))
        return jsonify({"imported": count})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

#
