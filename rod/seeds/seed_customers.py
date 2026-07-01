"""
seed_customers.py
Generates bulk fake rows into customers.db -> table `customer_complaints`.
Run: python seeds/seed_customers.py
"""
import sqlite3
import random
from common import PRODUCTS, STORES, random_date

DB_PATH = "mcp_server/db/customers.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS customer_complaints (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      TEXT,
    store_id        TEXT,
    complaint_date  TEXT NOT NULL,
    category        TEXT NOT NULL,
    severity        TEXT CHECK (severity IN ('low','medium','high')),
    complaint_text  TEXT,
    resolved        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_complaints_product_date ON customer_complaints(product_id, complaint_date);
"""

CATEGORIES = ["quality", "shipping", "service", "billing"]
SEVERITIES = ["low", "medium", "high"]
TEXT_TEMPLATES = {
    "quality": "Product felt cheap / broke faster than expected",
    "shipping": "Package arrived late or to wrong address",
    "service": "Support team was slow or unhelpful",
    "billing": "Charged wrong amount or double charged",
}

def generate_complaints(n=5000):
    rows = []
    for _ in range(n):
        product_id = random.choice(PRODUCTS) if random.random() > 0.1 else None
        store_id = random.choice(STORES) if random.random() > 0.4 else None
        category = random.choice(CATEGORIES)
        severity = random.choices(SEVERITIES, weights=[0.5, 0.35, 0.15])[0]
        resolved = random.choices([1, 0], weights=[0.8, 0.2])[0]
        rows.append((product_id, store_id, random_date(), category, severity, TEXT_TEMPLATES[category], resolved))
    return rows

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    rows = generate_complaints()
    conn.executemany(
        "INSERT INTO customer_complaints (product_id, store_id, complaint_date, category, severity, complaint_text, resolved) VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM customer_complaints").fetchone()[0]
    print(f"customers.db seeded -> {count} rows total")
    conn.close()

if __name__ == "__main__":
    main()