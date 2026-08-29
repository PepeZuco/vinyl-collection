import os, io, base64, csv, json, uuid, hashlib
csv.field_size_limit(10 * 1024 * 1024)
from flask import Flask, request, jsonify, send_file, session, render_template
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from sqlalchemy.orm import defer
from werkzeug.utils import secure_filename
from datetime import datetime
from functools import wraps

import pricing
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


def _cover_hash(cover):
    """Short content hash of a stored cover, used as its ETag and cache buster.

    Not a security boundary — it only has to change when the bytes change, so
    a truncated digest is plenty and keeps the URL readable.
    """
    return hashlib.sha256((cover or "").encode("utf-8")).hexdigest()[:16]

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
    condition   = db.Column(db.String(10))  # '' | 'new' | 'used'
    my_rating   = db.Column(db.Float, default=0)
    wife_rating = db.Column(db.Float, default=0)
    have_it     = db.Column(db.Boolean, default=True)
    play_count  = db.Column(db.Integer, default=0)
    play_dates  = db.Column(db.Text)      # JSON array of stamps, one per play
    last_cleaned= db.Column(db.String(50))  # deprecated: superseded by cleaned_dates, kept for migration only
    cleaned_dates = db.Column(db.Text)    # JSON array of stamps, one per cleaning
    cover_data  = db.Column(db.Text)      # base64 data URI
    # Content hash of cover_data, maintained on every write. It exists so a
    # record can advertise its cover's URL without the blob being loaded:
    # to_dict() runs on a query that defers cover_data, and reading that column
    # there would lazy-load one ~155KB blob per row — the very cost this whole
    # arrangement removes. Also the cache buster; see record_cover().
    cover_hash  = db.Column(db.String(64))
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
            "condition": self.condition or "",
            "my_rating": self.my_rating or 0,
            "wife_rating": self.wife_rating or 0,
            "have_it": bool(self.have_it),
            "play_count": self.play_count or 0,
            "play_dates": self.play_dates or "",
            "cleaned_dates": self.cleaned_dates or "",
            # Deliberately a URL, not the bytes. Inlining every cover as base64
            # made this endpoint a 45MB response that blocked the first paint.
            "cover_url": f"/api/records/{self.id}/cover?v={self.cover_hash}" if self.cover_hash else "",
            "notes": self.notes or "",
            "country": self.country or "",
        }

# One row per Claude API call a scan made. Anthropic publishes no balance or
# remaining-credits endpoint, so what this app spends is only knowable if this
# app writes it down — hence a ledger rather than a lookup.
class ScanSpend(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    scan_id       = db.Column(db.String(32))  # groups the calls of one scan
    at            = db.Column(db.String(50))  # a stamp — see the note above
    source        = db.Column(db.String(10))  # 'photo' | 'spotify'
    model         = db.Column(db.String(60))
    input_tokens  = db.Column(db.Integer, default=0)
    output_tokens = db.Column(db.Integer, default=0)
    cost_usd      = db.Column(db.Float, default=0.0)


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
        "condition": "VARCHAR(10)",
        "cover_hash": "VARCHAR(64)",
    }
    added_cleaned_dates = "cleaned_dates" not in existing_cols
    added_cover_hash = "cover_hash" not in existing_cols
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

    # one-time backfill: hash every existing cover, so rows written before this
    # column existed still advertise a cover_url. Done in batches by id rather
    # than with one .all(): the whole point of the column is that the blobs are
    # expensive, and loading all of them at boot to compute their hashes would
    # reproduce the very spike this avoids.
    if added_cover_hash:
        BATCH = 50
        last_id = 0
        while True:
            rows = (db.session.query(Record.id, Record.cover_data)
                    .filter(Record.id > last_id,
                            Record.cover_data.isnot(None), Record.cover_data != "")
                    .order_by(Record.id).limit(BATCH).all())
            if not rows:
                break
            db.session.bulk_update_mappings(Record, [
                {"id": rid, "cover_hash": _cover_hash(cover)} for rid, cover in rows])
            db.session.commit()
            last_id = rows[-1][0]

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
    # defer(cover_data) is the load-bearing part: without it this query pulls
    # ~45MB of base64 through the process on every page load. to_dict() must
    # therefore never touch cover_data, or each row lazy-loads it right back.
    recs = (Record.query.options(defer(Record.cover_data))
            .order_by(Record.artist).all())
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
        condition   = d.get("condition",""),
        my_rating   = float(d.get("my_rating") or 0),
        wife_rating = float(d.get("wife_rating") or 0),
        have_it     = bool(d.get("have_it", True)),
        play_count  = int(d.get("play_count") or 0),
        play_dates  = d.get("play_dates",""),
        cleaned_dates = d.get("cleaned_dates",""),
        cover_data  = d.get("cover_data",""),
        cover_hash  = _cover_hash(d.get("cover_data","")) if d.get("cover_data") else None,
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
    for field in ["artist","album_name","year","genre","bought_date","bought_where","bought_by","condition"]:
        if field in d:
            setattr(r, field, d[field])
    if "my_rating"   in d: r.my_rating   = float(d["my_rating"] or 0)
    if "wife_rating" in d: r.wife_rating  = float(d["wife_rating"] or 0)
    if "have_it"     in d: r.have_it      = bool(d["have_it"])
    if "play_count"  in d: r.play_count   = int(d["play_count"] or 0)
    if "play_dates"  in d: r.play_dates   = d["play_dates"]
    if "cleaned_dates" in d: r.cleaned_dates = d["cleaned_dates"]
    if "cover_data"  in d:
        r.cover_data = d["cover_data"]
        r.cover_hash = _cover_hash(d["cover_data"]) if d["cover_data"] else None
    if "notes"       in d: r.notes        = d["notes"]
    if "country"     in d: r.country      = (d["country"] or "").strip().upper()[:2]
    db.session.commit()
    return jsonify(r.to_dict())

def _decode_cover(cover):
    """(bytes, mimetype) for a stored cover, or None if there is nothing to serve.

    Covers are stored as `data:<mime>;base64,<payload>` data URIs. A row whose
    payload is malformed is treated as having no cover rather than raising: a
    single bad import should 404 one image, not 500 the page around it.
    """
    if not cover or not cover.startswith("data:"):
        return None
    header, _, payload = cover.partition(",")
    if not payload:
        return None
    mime = header[len("data:"):].split(";")[0] or "image/jpeg"
    try:
        return base64.b64decode(payload), mime
    except Exception:
        return None


@app.route("/api/records/<int:rid>/cover")
def record_cover(rid):
    """Serve one record's cover as its own cacheable resource.

    Immutable caching is safe because the URL carries a content hash (see
    cover_url in Record.to_dict): editing a cover changes the hash, which
    changes the URL, which is a fresh cache entry. The `v` parameter is never
    read here — it only has to differ.
    """
    row = db.session.query(Record.cover_data).filter(Record.id == rid).first()
    decoded = _decode_cover(row[0]) if row else None
    if decoded is None:
        return jsonify({"error": "No cover"}), 404
    data, mime = decoded
    resp = app.response_class(data, mimetype=mime)
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    resp.set_etag(_cover_hash(row[0]))
    return resp.make_conditional(request)


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

    source = "photo" if image else "spotify"
    # Filled by the Claude calls below and banked in the finally, so a scan
    # that dies after the API answered still records what it spent — the call
    # was billed the moment it returned, and nothing downstream refunds it.
    spent = []

    # The whole pipeline runs inside one try/except: lookup_musicbrainz,
    # fetch_cover and find_duplicate are documented never to raise, but that
    # contract isn't airtight (e.g. a 200 with an unexpected JSON shape can
    # still blow up a caller). The route doesn't trust it absolutely — any
    # escape here must still degrade to a JSON error, never a 500 HTML page.
    try:
        if image:
            fields = scan.extract_from_image(image, genres, usage_out=spent)
            spotify_image = None
        else:
            resolved = scan.extract_from_spotify(spotify_url)
            spotify_image = resolved.get("image_url")
            fields = {
                "artist": resolved["artist"],
                "album_name": resolved["album_name"],
                "genre": scan.classify_genre(
                    resolved["artist"], resolved["album_name"], genres,
                    usage_out=spent),
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
    finally:
        _record_scan_spend(source, spent)

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

# ── scan spend ────────────────────────────────────────────────────────────────

# What one scan costs before any has been measured. Both are replaced by the
# running average as soon as the ledger has a scan of that source in it, so
# these only ever show on a fresh collection.
SEED_ESTIMATE_USD = {"photo": 0.006, "spotify": 0.0004}

# How many past scans the estimate averages. Short enough that switching model
# or photo size shows up in the number within a few scans.
ESTIMATE_WINDOW = 20


def _record_scan_spend(source, spent):
    """Write one ledger row per API call the scan made.

    Never raises: this runs in the scan route's finally, and a bookkeeping
    failure must not turn a scan the user already paid for into an error.
    """
    if not spent:
        return
    scan_id = uuid.uuid4().hex
    at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    try:
        db.session.execute(db.insert(ScanSpend), [{
            "scan_id": scan_id,
            "at": at,
            "source": source,
            "model": call["model"],
            "input_tokens": call["input_tokens"],
            "output_tokens": call["output_tokens"],
            "cost_usd": pricing.cost_usd(
                call["model"], call["input_tokens"], call["output_tokens"]),
        } for call in spent])
        db.session.commit()
    except Exception:
        app.logger.warning("Could not record scan spend", exc_info=True)
        db.session.rollback()


def _scan_estimate(source):
    """Mean cost of the last ESTIMATE_WINDOW scans from this source.

    Grouped by scan_id, not by row: a scan is one or more API calls, and the
    form is quoting the price of a scan.
    """
    recent = (db.session.query(func.sum(ScanSpend.cost_usd))
              .filter(ScanSpend.source == source)
              .group_by(ScanSpend.scan_id)
              .order_by(func.max(ScanSpend.id).desc())
              .limit(ESTIMATE_WINDOW).all())
    if not recent:
        return SEED_ESTIMATE_USD[source]
    return sum(total for (total,) in recent) / len(recent)


def _spend_over(query):
    """(dollars, scans) for a ScanSpend query — scans counted, not calls."""
    cost, scans = query.with_entities(
        func.coalesce(func.sum(ScanSpend.cost_usd), 0.0),
        func.count(func.distinct(ScanSpend.scan_id)),
    ).one()
    return float(cost or 0.0), int(scans or 0)


@app.route("/api/scan/usage")
@require_auth
def scan_usage():
    """What scanning has cost. There is no credits balance to read — Anthropic
    publishes no such endpoint — so this reports spend from our own ledger."""
    month = datetime.now().strftime("%Y-%m")
    month_usd, month_scans = _spend_over(
        ScanSpend.query.filter(ScanSpend.at.startswith(month)))
    total_usd, total_scans = _spend_over(ScanSpend.query)
    return jsonify({
        "month": month,
        "month_usd": month_usd,
        "month_scans": month_scans,
        "total_usd": total_usd,
        "total_scans": total_scans,
        "estimate": {"photo": _scan_estimate("photo"),
                     "spotify": _scan_estimate("spotify")},
    })

# ── CSV import / export ───────────────────────────────────────────────────────

@app.route("/api/export")
def export_csv():
    recs = Record.query.order_by(Record.artist).all()
    cols = ["id","artist","album_name","year","genre","bought_date","bought_where",
            "bought_by","condition","my_rating","wife_rating","have_it","play_count","play_dates","cleaned_dates","cover_image_base64","notes","country"]

    def generate():
        yield ",".join(cols) + "\n"
        for r in recs:
            d = r.to_dict()
            # to_dict() reports a URL now, but a backup has to carry the bytes.
            d["cover_image_base64"] = r.cover_data or ""
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
        "condition":   row.get("condition",""),
        "my_rating":   float(row.get("my_rating") or 0),
        "wife_rating": float(row.get("wife_rating") or 0),
        "have_it":     row.get("have_it","").lower() in ("true","1","yes"),
        "play_count":  int(row.get("play_count") or 0),
        "play_dates":  row.get("play_dates",""),
        "cleaned_dates": cleaned_dates,
        "cover_data":  cover,
        "cover_hash":  _cover_hash(cover) if cover else None,
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
