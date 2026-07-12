"""
seed_sales.py
Generates bulk fake rows into sales.db -> table `sales`.
Run: python seeds/seed_sales.py

UPDATED: product_id -> sku_id. Sampling now happens at the SKU level
(common.SKUS), not the product level, since sku is now the real grain of
every operational table.
"""
import sqlite3
import random
from common import SKUS, STORES, daterange
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DB_PATH = os.path.join(PROJECT_ROOT, "mcp_server/db/sales.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sales (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sku_id          TEXT NOT NULL,
    store_id        TEXT NOT NULL,
    sale_date       TEXT NOT NULL,
    units_sold      INTEGER NOT NULL,
    revenue         REAL NOT NULL,
    discount_pct    REAL DEFAULT 0,
    channel         TEXT CHECK (channel IN ('online','in_store'))
);
CREATE INDEX IF NOT EXISTS idx_sales_sku_date ON sales(sku_id, sale_date);
CREATE INDEX IF NOT EXISTS idx_sales_store_date ON sales(store_id, sale_date);
"""

# every SKU gets a base price + base daily demand so numbers look real, not random noise
SKU_PROFILE = {s: {"price": round(random.uniform(5, 200), 2), "base_units": random.randint(1, 40)} for s in SKUS}


def generate_rows(sample_skus=80, sample_stores=15):
    """Full cartesian sku/store/day = way too many rows. Sample a realistic
    subset of sku/store pairs instead, like a real chain would have."""
    rows = []
    chosen_skus = random.sample(SKUS, min(sample_skus, len(SKUS)))
    chosen_stores = random.sample(STORES, sample_stores)

    for day in daterange():
        for sku_id in chosen_skus:
            for store_id in chosen_stores:
                if random.random() < 0.7:  # not every sku sells in every store every day
                    profile = SKU_PROFILE[sku_id]
                    units = max(0, int(random.gauss(profile["base_units"], profile["base_units"] * 0.3)))
                    discount = random.choice([0, 0, 0, 5, 10, 15, 20])
                    revenue = round(units * profile["price"] * (1 - discount / 100), 2)
                    channel = random.choice(["online", "in_store"])
                    rows.append((sku_id, store_id, day.isoformat(), units, revenue, discount, channel))
    return rows


def main():
    db_dir = os.path.dirname(DB_PATH)
    os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    rows = generate_rows()
    conn.executemany(
        "INSERT INTO sales (sku_id, store_id, sale_date, units_sold, revenue, discount_pct, channel) VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
    print(f"sales.db seeded -> {count} rows total")
    conn.close()


if __name__ == "__main__":
    main()