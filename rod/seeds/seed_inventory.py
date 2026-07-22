"""
seeds/seed_inventory.py
"""

import random
from datetime import date, timedelta
from db import get_conn, bulk_insert, fetch_ids

random.seed(45)

SAMPLE_SKUS = 80
SAMPLE_STORES = 15
N_REPLENISHMENTS = 3000

def seed_inventory(conn, sku_ids, store_ids, promo_ids):
    sample_skus = random.sample(sku_ids, min(SAMPLE_SKUS, len(sku_ids)))
    sample_stores = random.sample(store_ids, min(SAMPLE_STORES, len(store_ids)))

    rows = []
    for sku_id in sample_skus:
        for store_id in sample_stores:
            stock = random.randint(0, 300)
            reorder = random.randint(20, 60)
            last_audited = date.today() - timedelta(days=random.randint(0, 14))
            rows.append((sku_id, store_id, stock, reorder, last_audited))

    bulk_insert(conn, "inventory.inventory",
                ["sku_id", "store_id", "stock_on_hand", "reorder_point", "last_audited"],
                rows)
    print(f"inventory.inventory seeded -> {len(rows)} rows")
    return sample_skus, sample_stores

def seed_replenishment(conn, sku_ids, store_ids, supplier_ids):
    rows = []
    for _ in range(N_REPLENISHMENTS):
        sku_id = random.choice(sku_ids)
        store_id = random.choice(store_ids)
        supplier_id = random.choice(supplier_ids)
        order_day = date.today() - timedelta(days=random.randint(0, 550))
        lead_days = max(1, int(random.gauss(5, 3)))
        received_day = order_day + timedelta(days=lead_days)
        units_ordered = random.randint(20, 500)
        units_received = units_ordered if random.random() > 0.1 else int(units_ordered * random.uniform(0.5, 0.95))
        rows.append((sku_id, store_id, order_day.isoformat(), received_day.isoformat(),
                      units_ordered, units_received, supplier_id))

    bulk_insert(conn, "inventory.replenishment_history",
                ["sku_id", "store_id", "order_date", "received_date",
                 "units_ordered", "units_received", "supplier_id"],
                rows)
    print(f"inventory.replenishment_history seeded -> {len(rows)} rows")

def main():
    conn = get_conn()
    try:
        sku_ids = fetch_ids(conn, "SELECT sku_id FROM reference.sku")
        store_ids = fetch_ids(conn, "SELECT store_id FROM reference.stores")
        supplier_ids = fetch_ids(conn, "SELECT supplier_id FROM reference.suppliers")
        promo_ids = fetch_ids(conn, "SELECT promo_id FROM promotions.promotions")

        if not sku_ids or not store_ids or not supplier_ids:
            raise RuntimeError("reference tables are empty -- run seed_reference.py first")

        sample_skus, sample_stores = seed_inventory(conn, sku_ids, store_ids, promo_ids)
        seed_replenishment(conn, sample_skus, sample_stores, supplier_ids)
        conn.commit()
        print("\ninventory seeding complete.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    main()