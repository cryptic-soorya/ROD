"""
seeds/seed_promotions.py
"""

import random
from datetime import date, timedelta
from db import get_conn, bulk_insert, fetch_ids

random.seed(43)

N_PROMOS = 500
END_DATE = date.today()
START_DATE = END_DATE - timedelta(days=550)

def random_date():
    delta = (END_DATE - START_DATE).days
    return START_DATE + timedelta(days=random.randint(0, delta))

def seed_promotions(conn, sku_ids, store_ids):
    promo_rows = []
    perf_rows = []

    for i in range(1, N_PROMOS + 1):
        promo_id = f"PROMO{i:05d}"
        sku_id = random.choice(sku_ids)
        store_id = random.choice(store_ids)
        start = random_date()
        end = start + timedelta(days=random.randint(3, 21))
        discount_pct = random.choice([10, 15, 20, 25, 30, 40, 50])
        promo_type = random.choice(["discount", "bogo", "clearance", "seasonal"])

        promo_rows.append((promo_id, store_id, promo_type, sku_id, discount_pct, start, end))

        baseline_units = random.randint(10, 200)
        lift_factor = random.uniform(1.0, 4.0)
        units_sold = int(baseline_units * lift_factor)
        price = random.uniform(5, 200)
        revenue = round(units_sold * price * (1 - discount_pct / 100), 2)
        cost_per_unit = price * random.uniform(0.4, 0.7)
        margin_impact = round(revenue - (units_sold * cost_per_unit), 2)

        perf_rows.append((promo_id, units_sold, revenue, baseline_units, margin_impact))

    bulk_insert(conn, "promotions.promotions",
                ["promo_id", "store_id", "type", "sku_id", "dsct_pct", "start_date", "end_date"],
                promo_rows)
    print(f"promotions.promotions seeded -> {len(promo_rows)} rows")

    bulk_insert(conn, "promotions.promotion_performance",
                ["promo_id", "units_sold", "revenue", "baseline_units", "margin_impact"],
                perf_rows)
    print(f"promotions.promotion_performance seeded -> {len(perf_rows)} rows")

def main():
    conn = get_conn()
    try:
        sku_ids = fetch_ids(conn, "SELECT sku_id FROM reference.sku")
        store_ids = fetch_ids(conn, "SELECT store_id FROM reference.stores")
        if not sku_ids or not store_ids:
            raise RuntimeError("reference.sku / reference.stores are empty -- run seed_reference.py first")

        seed_promotions(conn, sku_ids, store_ids)
        conn.commit()
        print("\npromotions seeding complete.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    main()