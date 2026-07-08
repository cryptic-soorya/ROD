"""
seed_suppliers.py
Populates suppliers.db -> table `supplier_delivery`.
Run: python seeds/seed_suppliers.py
"""
import sqlite3
import random
from common import PRODUCTS, SUPPLIERS, random_date
import os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DB_PATH = os.path.join(PROJECT_ROOT, "mcp_server/db/suppliers.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS supplier_delivery (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id                 TEXT NOT NULL,
    product_id                  TEXT,
    delivery_date               TEXT NOT NULL,
    avg_delivery_days_current   REAL NOT NULL,
    avg_delivery_days_baseline  REAL NOT NULL,
    defect_rate                 REAL NOT NULL,
    degradation_flag            INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_supplier_date ON supplier_delivery(supplier_id, delivery_date);
"""

# each supplier has a baseline personality — some are reliably fast, some slow
SUPPLIER_PROFILE = {
    s: {
        "baseline": round(random.uniform(2.0, 8.0), 1),
        "defect_base": round(random.uniform(0.01, 0.08), 3),
    }
    for s in SUPPLIERS
}

def generate_rows(n=10000):
    rows = []
    for _ in range(n):
        supplier_id = random.choice(SUPPLIERS)
        product_id = random.choice(PRODUCTS) if random.random() > 0.1 else None
        profile = SUPPLIER_PROFILE[supplier_id]

        baseline = profile["baseline"]
        # current drifts around baseline; 15% chance supplier is degraded
        if random.random() < 0.15:
            current = round(baseline * random.uniform(1.5, 3.0), 2)  # degraded
        else:
            current = round(baseline * random.uniform(0.8, 1.3), 2)  # normal variance

        defect_rate = round(max(0.0, min(1.0, random.gauss(profile["defect_base"], 0.01))), 4)
        degradation_flag = 1 if current > 1.5 * baseline else 0

        rows.append((supplier_id, product_id, random_date(), current, baseline, defect_rate, degradation_flag))
    return rows

def main():
    db_dir = os.path.dirname(DB_PATH)
    os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO supplier_delivery (supplier_id, product_id, delivery_date, avg_delivery_days_current, avg_delivery_days_baseline, defect_rate, degradation_flag) VALUES (?,?,?,?,?,?,?)",
        generate_rows(),
    )
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM supplier_delivery").fetchone()[0]
    flagged = conn.execute("SELECT COUNT(*) FROM supplier_delivery WHERE degradation_flag=1").fetchone()[0]
    print(f"suppliers.db seeded -> {total} rows | {flagged} degraded")
    conn.close()

if __name__ == "__main__":
    main()
