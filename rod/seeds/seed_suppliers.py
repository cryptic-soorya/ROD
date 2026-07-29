"""
seeds/seed_suppliers.py
"""

import random
from datetime import date, timedelta
from db import get_conn, bulk_insert, fetch_ids

random.seed(46)

N_DELIVERIES = 5000
END_DATE = date.today()
START_DATE = END_DATE - timedelta(days=550)

def random_date():
    delta = (END_DATE - START_DATE).days
    return (START_DATE + timedelta(days=random.randint(0, delta))).isoformat()

def seed_supplier_delivery(conn, supplier_ids, sku_ids, store_ids):
    profile = {
        s: {
            "baseline": round(random.uniform(2.0, 8.0), 1),
            "defect_base": round(random.uniform(0.01, 0.08), 3),
        }
        for s in supplier_ids
    }

    rows = []
    for i in range(1, N_DELIVERIES + 1):
        deli_id = f"DELI{i:05d}"
        supplier_id = random.choice(supplier_ids)
        sku_id = random.choice(sku_ids) if random.random() > 0.1 else None
        store_id = random.choice(store_ids) if random.random() > 0.1 else None
        p = profile[supplier_id]

        baseline = p["baseline"]
        if random.random() < 0.15:
            current = round(baseline * random.uniform(1.5, 3.0), 2)  # degraded
        else:
            current = round(baseline * random.uniform(0.8, 1.3), 2)  # normal variance

        defect_rate = round(max(0.0, min(1.0, random.gauss(p["defect_base"], 0.01))), 4)
        degradation_flag = current > 1.5 * baseline

        rows.append((deli_id, supplier_id, sku_id, store_id, random_date(),
                      current, baseline, defect_rate, degradation_flag))

    bulk_insert(conn, "suppliers.supplier_delivery",
                ["deli_id", "supplier_id", "sku_id", "store_id", "delivery_date",
                 "avg_delivery_days_current", "avg_delivery_days_baseline",
                 "defect_rate", "degradation_flag"],
                rows)
    flagged = sum(1 for r in rows if r[8])
    print(f"suppliers.supplier_delivery seeded -> {len(rows)} rows ({flagged} degraded)")

def main():
    conn = get_conn()
    try:
        supplier_ids = fetch_ids(conn, "SELECT supplier_id FROM reference.suppliers")
        sku_ids = fetch_ids(conn, "SELECT sku_id FROM reference.sku")
        store_ids = fetch_ids(conn, "SELECT store_id FROM reference.stores")

        if not supplier_ids or not sku_ids or not store_ids:
            raise RuntimeError("reference tables are empty -- run seed_reference.py first")

        seed_supplier_delivery(conn, supplier_ids, sku_ids, store_ids)
        conn.commit()
        print("\nsuppliers seeding complete.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    main()