"""
seed_returns.py
Generates bulk fake rows into returns.db -> table `return_reasons`.
Run: python seeds/seed_returns.py

UPDATED:
    - product_id -> sku_id.
    - product_listing_changes REMOVED from this file entirely -- it's been
      renamed catalog_changes and relocated into seed_orchestration.py,
      since it's catalog/reference data, not a returns artifact. See that
      script for its generator.
"""
import os
import sqlite3
import random
from common import SKUS, random_date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DB_PATH = os.path.join(PROJECT_ROOT, "mcp_server/db/returns.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS return_reasons (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sku_id          TEXT NOT NULL,
    return_date     TEXT NOT NULL,
    reason_code     TEXT NOT NULL,
    reason_text     TEXT,
    units_returned  INTEGER NOT NULL,
    sample_size     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_returns_sku_date ON return_reasons(sku_id, return_date);
"""

REASON_CODES = ["wrong_size", "defective", "not_as_described", "changed_mind", "arrived_late", "damaged_in_transit"]
REASON_TEXT = {
    "wrong_size": "Customer said sizing ran small/large vs chart",
    "defective": "Item stopped working / broke after few uses",
    "not_as_described": "Color/material did not match listing photos",
    "changed_mind": "No longer needed, ordered by mistake",
    "arrived_late": "Took too long, customer already bought elsewhere",
    "damaged_in_transit": "Box crushed, item damaged on arrival",
}


def generate_returns(n=6000):
    rows = []
    for _ in range(n):
        sku_id = random.choice(SKUS)
        reason = random.choice(REASON_CODES)
        units_returned = random.randint(1, 25)
        sample_size = random.randint(5, 500)  # sometimes low -> triggers low_sample_warning downstream
        rows.append((sku_id, random_date(), reason, REASON_TEXT[reason], units_returned, sample_size))
    return rows


def main():
    db_dir = os.path.dirname(DB_PATH)
    os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    conn.executemany(
        "INSERT INTO return_reasons (sku_id, return_date, reason_code, reason_text, units_returned, sample_size) VALUES (?,?,?,?,?,?)",
        generate_returns(),
    )

    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM return_reasons").fetchone()[0]
    print(f"returns.db seeded -> return_reasons: {count}")
    print("product_listing_changes / catalog_changes is no longer seeded here -- see seed_orchestration.py")
    conn.close()


if __name__ == "__main__":
    main()
