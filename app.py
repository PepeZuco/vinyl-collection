import os, io, base64, csv, json
from flask import Flask, request, jsonify, send_file, session, render_template
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///vinyl.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32MB

EDIT_PASSWORD = os.environ.get("EDIT_PASSWORD", "vinyl123")

db = SQLAlchemy(app)

class Record(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    artist      = db.Column(db.String(200))
    album_name  = db.Column(db.String(200))
    year        = db.Column(db.String(10))
    genre       = db.Column(db.String(100))
    bought_date = db.Column(db.String(50))
    bought_where= db.Column(db.String(200))
    bought_by   = db.Column(db.String(100))
    my_rating   = db.Column(db.Float, default=0)
    wife_rating = db.Column(db.Float, default=0)
    have_it     = db.Column(db.Boolean, default=True)
    play_count  = db.Column(db.Integer, default=0)
    last_cleaned= db.Column(db.String(50))
    cover_data  = db.Column(db.Text)      # base64 data URI
    notes       = db.Column(db.Text)      # markdown notes

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
            "last_cleaned": self.last_cleaned or "",
            "cover_data": self.cover_data or "",
            "notes": self.notes or "",
        }

with app.app_context():
    db.create_all()

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
        last_cleaned= d.get("last_cleaned",""),
        cover_data  = d.get("cover_data",""),
        notes       = d.get("notes",""),
    )
    db.session.add(r)
    db.session.commit()
    return jsonify(r.to_dict()), 201

@app.route("/api/records/<int:rid>", methods=["PUT"])
@require_auth
def update_record(rid):
    r = Record.query.get_or_404(rid)
    d = request.get_json(silent=True) or {}
    for field in ["artist","album_name","year","genre","bought_date","bought_where","bought_by","last_cleaned"]:
        if field in d:
            setattr(r, field, d[field])
    if "my_rating"   in d: r.my_rating   = float(d["my_rating"] or 0)
    if "wife_rating" in d: r.wife_rating  = float(d["wife_rating"] or 0)
    if "have_it"     in d: r.have_it      = bool(d["have_it"])
    if "play_count"  in d: r.play_count   = int(d["play_count"] or 0)
    if "cover_data"  in d: r.cover_data   = d["cover_data"]
    if "notes"       in d: r.notes        = d["notes"]
    db.session.commit()
    return jsonify(r.to_dict())

@app.route("/api/records/<int:rid>", methods=["DELETE"])
@require_auth
def delete_record(rid):
    r = Record.query.get_or_404(rid)
    db.session.delete(r)
    db.session.commit()
    return jsonify({"ok": True})

# ── CSV import / export ───────────────────────────────────────────────────────

@app.route("/api/export")
def export_csv():
    recs = Record.query.order_by(Record.artist).all()
    cols = ["id","artist","album_name","year","genre","bought_date","bought_where",
            "bought_by","my_rating","wife_rating","have_it","play_count","last_cleaned","cover_image_base64","notes"]

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

@app.route("/api/import", methods=["POST"])
@require_auth
def import_csv():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file"}), 400
    try:
        text = file.read().decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        Record.query.delete()
        count = 0
        for row in reader:
            cover = row.get("cover_image_base64","") or row.get("cover_data","")
            if cover and not cover.startswith("data:"):
                cover = "data:image/jpeg;base64," + cover
            r = Record(
                artist      = row.get("artist",""),
                album_name  = row.get("album_name",""),
                year        = row.get("year",""),
                genre       = row.get("genre",""),
                bought_date = row.get("bought_date",""),
                bought_where= row.get("bought_where",""),
                bought_by   = row.get("bought_by",""),
                my_rating   = float(row.get("my_rating") or 0),
                wife_rating = float(row.get("wife_rating") or 0),
                have_it     = row.get("have_it","").lower() in ("true","1","yes"),
                play_count  = int(row.get("play_count") or 0),
                last_cleaned= row.get("last_cleaned",""),
                cover_data  = cover,
                notes       = row.get("notes",""),
            )
            db.session.add(r)
            count += 1
        db.session.commit()
        return jsonify({"imported": count})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
