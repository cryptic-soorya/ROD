"""
seed_promotions.py
Generates bulk fake rows into promotions.db -> table `promotion_performance`.
Run: python seeds/seed_promotions.py
"""
import os
import sqlite3
import random
from datetime import timedelta
from common import PRODUCTS, random_date
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)  # Assuming it lives inside 'rod' alongside 'seeds'
DB_PATH = os.path.join(PROJECT_ROOT, "mcp_server/db/promotions.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS promotion_performance (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    promo_id        TEXT NOT NULL,
    product_id      TEXT NOT NULL,
    start_date      TEXT NOT NULL,
    end_date        TEXT NOT NULL,
    discount_pct    REAL NOT NULL,
    units_sold      INTEGER NOT NULL,
    revenue         REAL NOT NULL,
    baseline_units  INTEGER NOT NULL,
    margin_impact   REAL
);
CREATE INDEX IF NOT EXISTS idx_promo_product ON promotion_performance(product_id, start_date);
"""

def generate_promotions(n=3000):
    rows = []
    for i in range(n):
        promo_id = f"PROMO{str(i+1).zfill(5)}"
        product_id = random.choice(PRODUCTS)
        start = random_date()
        from datetime import date as _date
        start_date = _date.fromisoformat(start)
        duration = random.randint(3, 21)
        end_date = start_date + timedelta(days=duration)
        discount_pct = random.choice([10, 15, 20, 25, 30, 40, 50])
        baseline_units = random.randint(10, 200)
        lift_factor = random.uniform(1.0, 4.0)  # promo boosts units by this multiple
        units_sold = int(baseline_units * lift_factor)
        price = round(random.uniform(5, 200), 2)
        revenue = round(units_sold * price * (1 - discount_pct / 100), 2)
        cost_per_unit = round(price * random.uniform(0.4, 0.7), 2)  # rough COGS
        margin_impact = round(revenue - (units_sold * cost_per_unit), 2)
        rows.append((promo_id, product_id, start_date.isoformat(), end_date.isoformat(), discount_pct, units_sold, revenue, baseline_units, margin_impact))
    return rows

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    rows = generate_promotions()
    conn.executemany(
        "INSERT INTO promotion_performance (promo_id, product_id, start_date, end_date, discount_pct, units_sold, revenue, baseline_units, margin_impact) VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM promotion_performance").fetchone()[0]
    print(f"promotions.db seeded -> {count} rows total")
    conn.close()

if __name__ == "__main__":
    main()