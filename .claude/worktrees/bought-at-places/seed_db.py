"""Seed the local dev DB from vinyl_collection.csv (gitignored, not deployed)."""
import os
from app import app, db, import_records_from_csv_text

CSV_PATH = os.environ.get("SEED_CSV", "vinyl_collection.csv")

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            text = f.read()
        count = import_records_from_csv_text(text)
        print(f"Imported {count} records from {CSV_PATH}")
