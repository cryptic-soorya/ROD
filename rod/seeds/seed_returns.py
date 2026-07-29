"""
seeds/seed_returns.py
"""

import random
from datetime import date, timedelta
from db import get_conn, bulk_insert, fetch_ids

random.seed(47)

N_RETURNS = 6000
REASON_CODES = ["wrong_size", "defective", "not_as_described", "changed_mind",
                 "arrived_late", "damaged_in_transit"]
REASON_TEXT = {
    "wrong_size": "Customer said sizing ran small/large vs chart",
    "defective": "Item stopped working / broke after few uses",
    "not_as_described": "Color/material did not match listing photos",
    "changed_mind": "No longer needed, ordered by mistake",
    "arrived_late": "Took too long, customer already bought elsewhere",
    "damaged_in_transit": "Box crushed, item damaged on arrival",
}

def seed_returns(conn, sku_ids, store_ids, sales_rows):
    rows = []
    for _ in range(N_RETURNS):
        if sales_rows and random.random() < 0.6:
            sale_id, sku_id, store_id, sale_date_str = random.choice(sales_rows)
            # Ensure return date isn't pushed into the future if the sale was yesterday
            projected_return_date = date.fromisoformat(sale_date_str) + timedelta(days=random.randint(1, 30))
            return_date = min(date.today(), projected_return_date).isoformat()
        else:
            sale_id = None
            sku_id = random.choice(sku_ids)
            store_id = random.choice(store_ids)
            return_date = (date.today() - timedelta(days=random.randint(0, 550))).isoformat()

        reason = random.choice(REASON_CODES)
        units_returned = random.randint(1, 25)
        rows.append((sku_id, store_id, sale_id, return_date, reason,
                      REASON_TEXT[reason], units_returned))

    bulk_insert(conn, "returns.return_reasons",
                ["sku_id", "store_id", "sale_id", "return_date", "reason_code",
                 "reason_text", "units_returned"],
                rows)
    print(f"returns.return_reasons seeded -> {len(rows)} rows")

def main():
    conn = get_conn()
    try:
        sku_ids = fetch_ids(conn, "SELECT sku_id FROM reference.sku")
        store_ids = fetch_ids(conn, "SELECT store_id FROM reference.stores")

        with conn.cursor() as cur:
            cur.execute("SELECT sale_id, sku_id, store_id, sale_date FROM sales.sales")
            sales_rows = cur.fetchall()

        if not sku_ids or not store_ids:
            raise RuntimeError("reference tables are empty -- run seed_reference.py first")
        if not sales_rows:
            print("WARNING: sales.sales is empty -- run seed_sales.py first for realistic "
                  "sale_id links. Proceeding with standalone returns only.")

        seed_returns(conn, sku_ids, store_ids, sales_rows)
        conn.commit()
        print("\nreturns seeding complete.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    main()