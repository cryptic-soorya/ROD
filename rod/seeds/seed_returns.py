"""
seed_returns.py
Generates bulk fake rows into returns.db -> tables `return_reasons`, `product_listing_changes`.
Run: python seeds/seed_returns.py
"""
import os
import sqlite3
import random
from common import PRODUCTS, random_date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DB_PATH = os.path.join(PROJECT_ROOT, "mcp_server/db/returns.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS return_reasons (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      TEXT NOT NULL,
    return_date     TEXT NOT NULL,
    reason_code     TEXT NOT NULL,
    reason_text     TEXT,
    units_returned  INTEGER NOT NULL,
    sample_size     INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS product_listing_changes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      TEXT NOT NULL,
    change_date     TEXT NOT NULL,
    field_changed   TEXT NOT NULL,
    old_value       TEXT,
    new_value       TEXT,
    changed_by      TEXT
);
CREATE INDEX IF NOT EXISTS idx_returns_product_date ON return_reasons(product_id, return_date);
CREATE INDEX IF NOT EXISTS idx_listing_product_date ON product_listing_changes(product_id, change_date);
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
FIELDS = ["title", "description", "images", "price", "category"]
EDITORS = ["merchandising_bot", "alice.k", "raj.p", "content_team", "auto_sync"]

def generate_returns(n=6000):
    rows = []
    for _ in range(n):
        product_id = random.choice(PRODUCTS)
        reason = random.choice(REASON_CODES)
        units_returned = random.randint(1, 25)
        sample_size = random.randint(5, 500)  # sometimes low -> triggers low_sample_warning downstream
        rows.append((product_id, random_date(), reason, REASON_TEXT[reason], units_returned, sample_size))
    return rows

def generate_listing_changes(n=2500):
    rows = []
    for _ in range(n):
        product_id = random.choice(PRODUCTS)
        field = random.choice(FIELDS)
        if field == "price":
            old_v, new_v = str(round(random.uniform(5, 200), 2)), str(round(random.uniform(5, 200), 2))
        else:
            old_v, new_v = f"old_{field}_v{random.randint(1,9)}", f"new_{field}_v{random.randint(1,9)}"
        rows.append((product_id, random_date(), field, old_v, new_v, random.choice(EDITORS)))
    return rows

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    conn.executemany(
        "INSERT INTO return_reasons (product_id, return_date, reason_code, reason_text, units_returned, sample_size) VALUES (?,?,?,?,?,?)",
        generate_returns(),
    )
    conn.executemany(
        "INSERT INTO product_listing_changes (product_id, change_date, field_changed, old_value, new_value, changed_by) VALUES (?,?,?,?,?,?)",
        generate_listing_changes(),
    )

    conn.commit()
    c1 = conn.execute("SELECT COUNT(*) FROM return_reasons").fetchone()[0]
    c2 = conn.execute("SELECT COUNT(*) FROM product_listing_changes").fetchone()[0]
    print(f"returns.db seeded -> return_reasons: {c1}, product_listing_changes: {c2}")
    conn.close()

if __name__ == "__main__":
    main()