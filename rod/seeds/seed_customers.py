"""
seed_customers.py
Generates bulk fake rows into customers.db -> table `customer_complaints`.
Run: python seeds/seed_customers.py

CORRECTED: the schema below previously had id/sku_id/store_id/severity/
complaint_text/resolved, carried over from the original screenshot. That
never matched what mcp_server/tools/customers.py (the real, live tool)
actually queries -- its category-filtered SELECT reads columns
`complaint_id` and `description`, which didn't exist under the old
schema, and would fail with `no such column` the moment anyone called
get_customer_complaints(category=...). Confirmed by actually running it
(see seed_anomaly_customer.py's schema note). Fixed here to match the
real, working schema: no sku_id/store_id/severity/resolved at all --
this table is genuinely just complaint_id/category/complaint_date/
description.
"""
import os
import sqlite3
import random
from common import random_date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DB_PATH = os.path.join(PROJECT_ROOT, "mcp_server", "db", "customers.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS customer_complaints (
    complaint_id    TEXT PRIMARY KEY,
    category        TEXT NOT NULL,
    complaint_date  TEXT NOT NULL,
    description     TEXT
);
CREATE INDEX IF NOT EXISTS idx_complaints_category_date ON customer_complaints(category, complaint_date);
"""

CATEGORIES = ["quality", "shipping", "service", "billing"]
TEXT_TEMPLATES = {
    "quality": "Product felt cheap / broke faster than expected",
    "shipping": "Package arrived late or to wrong address",
    "service": "Support team was slow or unhelpful",
    "billing": "Charged wrong amount or double charged",
}


def generate_complaints(n=5000):
    rows = []
    for i in range(n):
        category = random.choice(CATEGORIES)
        rows.append((f"CMP-{i+1:05d}", category, random_date(), TEXT_TEMPLATES[category]))
    return rows


def main():
    db_dir = os.path.dirname(DB_PATH)
    os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    rows = generate_complaints()
    conn.executemany(
        "INSERT OR IGNORE INTO customer_complaints (complaint_id, category, complaint_date, description) VALUES (?,?,?,?)",
        rows,
    )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM customer_complaints").fetchone()[0]
    print(f"customers.db seeded -> {count} rows total")
    conn.close()


if __name__ == "__main__":
    main()



if __name__ == "__main__":
    main()
