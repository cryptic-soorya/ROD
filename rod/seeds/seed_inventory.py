"""
seed_inventory.py
Generates bulk fake rows into inventory.db -> tables `inventory_levels`, `replenishment_history`.
Run: python seeds/seed_inventory.py

UPDATED: product_id -> sku_id on both tables.
"""
import os
import sqlite3
import random
from datetime import timedelta
from common import SKUS, STORES, SUPPLIERS, daterange

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DB_PATH = os.path.join(PROJECT_ROOT, "mcp_server", "db", "inventory.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS inventory_levels (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sku_id          TEXT NOT NULL,
    store_id        TEXT NOT NULL,
    snapshot_date   TEXT NOT NULL,
    stock_on_hand   INTEGER NOT NULL,
    reorder_point   INTEGER NOT NULL,
    stockout_flag   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS replenishment_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sku_id          TEXT NOT NULL,
    store_id        TEXT NOT NULL,
    order_date      TEXT NOT NULL,
    received_date   TEXT,
    units_ordered   INTEGER NOT NULL,
    units_received  INTEGER,
    supplier_id     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inv_sku_store ON inventory_levels(sku_id, store_id);
CREATE INDEX IF NOT EXISTS idx_replen_sku_store ON replenishment_history(sku_id, store_id);
"""


def generate_inventory_levels(sample_skus=80, sample_stores=15):
    rows = []
    chosen_skus = random.sample(SKUS, min(sample_skus, len(SKUS)))
    chosen_stores = random.sample(STORES, sample_stores)
    stock = {(s, st): random.randint(50, 300) for s in chosen_skus for st in chosen_stores}
    reorder = {(s, st): random.randint(20, 60) for s in chosen_skus for st in chosen_stores}

    for day in daterange():
        for sku_id in chosen_skus:
            for store_id in chosen_stores:
                key = (sku_id, store_id)
                drift = random.randint(-15, 8)
                stock[key] = max(0, stock[key] + drift)
                stockout = 1 if stock[key] == 0 else 0
                rows.append((sku_id, store_id, day.isoformat(), stock[key], reorder[key], stockout))
    return rows


def generate_replenishment(n=8000, sample_skus=80, sample_stores=15):
    rows = []
    chosen_skus = random.sample(SKUS, min(sample_skus, len(SKUS)))
    chosen_stores = random.sample(STORES, sample_stores)
    for _ in range(n):
        sku_id = random.choice(chosen_skus)
        store_id = random.choice(chosen_stores)
        supplier_id = random.choice(SUPPLIERS)
        order_day = random.choice(list(daterange()))
        lead_days = max(1, int(random.gauss(5, 3)))
        received_day = order_day + timedelta(days=lead_days)
        units_ordered = random.randint(20, 500)
        units_received = units_ordered if random.random() > 0.1 else int(units_ordered * random.uniform(0.5, 0.95))
        rows.append((sku_id, store_id, order_day.isoformat(), received_day.isoformat(), units_ordered, units_received, supplier_id))
    return rows


def main():
    db_dir = os.path.dirname(DB_PATH)
    os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    inv_rows = generate_inventory_levels()
    conn.executemany(
        "INSERT INTO inventory_levels (sku_id, store_id, snapshot_date, stock_on_hand, reorder_point, stockout_flag) VALUES (?,?,?,?,?,?)",
        inv_rows,
    )

    replen_rows = generate_replenishment()
    conn.executemany(
        "INSERT INTO replenishment_history (sku_id, store_id, order_date, received_date, units_ordered, units_received, supplier_id) VALUES (?,?,?,?,?,?,?)",
        replen_rows,
    )

    conn.commit()
    c1 = conn.execute("SELECT COUNT(*) FROM inventory_levels").fetchone()[0]
    c2 = conn.execute("SELECT COUNT(*) FROM replenishment_history").fetchone()[0]
    print(f"inventory.db seeded -> inventory_levels: {c1}, replenishment_history: {c2}")
    conn.close()


if __name__ == "__main__":
    main()
