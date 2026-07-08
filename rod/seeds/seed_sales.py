"""
seed_sales.py
Generates bulk fake rows into sales.db -> table `sales`.
Run: python seeds/seed_sales.py
"""
import sqlite3
import random
from common import PRODUCTS, STORES, daterange
import os
    
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DB_PATH = os.path.join(PROJECT_ROOT, "mcp_server/db/sales.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sales (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      TEXT NOT NULL,
    store_id        TEXT NOT NULL,
    sale_date       TEXT NOT NULL,
    units_sold      INTEGER NOT NULL,
    revenue         REAL NOT NULL,
    discount_pct    REAL DEFAULT 0,
    channel         TEXT CHECK (channel IN ('online','in_store'))
);
CREATE INDEX IF NOT EXISTS idx_sales_product_date ON sales(product_id, sale_date);
CREATE INDEX IF NOT EXISTS idx_sales_store_date ON sales(store_id, sale_date);
"""

# every product gets a base price + base daily demand so numbers look real, not random noise
PRODUCT_PROFILE = {p: {"price": round(random.uniform(5, 200), 2), "base_units": random.randint(1, 40)} for p in PRODUCTS}

def generate_rows(sample_products=40, sample_stores=15):
    """Full cartesian product/store/day = way too many rows (200*50*545 days).
    Sample a realistic subset of product/store pairs instead, like a real chain would have."""
    rows = []
    chosen_products = random.sample(PRODUCTS, sample_products)
    chosen_stores = random.sample(STORES, sample_stores)

    for day in daterange():
        for product_id in chosen_products:
            for store_id in chosen_stores:
                if random.random() < 0.7:  # not every product sells in every store every day
                    profile = PRODUCT_PROFILE[product_id]
                    units = max(0, int(random.gauss(profile["base_units"], profile["base_units"] * 0.3)))
                    discount = random.choice([0, 0, 0, 5, 10, 15, 20])
                    revenue = round(units * profile["price"] * (1 - discount / 100), 2)
                    channel = random.choice(["online", "in_store"])
                    rows.append((product_id, store_id, day.isoformat(), units, revenue, discount, channel))
    return rows

def main():
    db_dir = os.path.dirname(DB_PATH)
    os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    rows = generate_rows()
    conn.executemany(
        "INSERT INTO sales (product_id, store_id, sale_date, units_sold, revenue, discount_pct, channel) VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
    print(f"sales.db seeded -> {count} rows total")
    conn.close()

if __name__ == "__main__":
    main()
