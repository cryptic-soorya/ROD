"""
seeds/seed_customers.py
"""

import random
from datetime import date, timedelta
from db import get_conn, bulk_insert, fetch_ids

random.seed(48)

N_COMPLAINTS = 5000
CATEGORIES = ["quality", "shipping", "service", "billing", "wrong_item"]
TEXT_TEMPLATES = {
    "quality": "Product felt cheap / broke faster than expected",
    "shipping": "Package arrived late or to wrong address",
    "service": "Support team was slow or unhelpful",
    "billing": "Charged wrong amount or double charged",
    "wrong_item": "Received a different item than ordered",
}

def seed_complaints(conn, sku_ids, store_ids, sales_rows):
    rows = []
    for i in range(1, N_COMPLAINTS + 1):
        complaint_id = f"CMP-{i:05d}"
        category = random.choice(CATEGORIES)

        if sales_rows and random.random() < 0.5:
            sale_id, sku_id, store_id, sale_date_str = random.choice(sales_rows)
            # Ensure complaint date is not in the future if sale was recent
            projected_date = date.fromisoformat(sale_date_str) + timedelta(days=random.randint(1, 21))
            complaint_date = min(date.today(), projected_date).isoformat()
        else:
            sale_id = None
            sku_id = random.choice(sku_ids)
            store_id = random.choice(store_ids)
            complaint_date = (date.today() - timedelta(days=random.randint(0, 550))).isoformat()

        rows.append((complaint_id, complaint_date, store_id, sku_id, sale_id,
                      category, TEXT_TEMPLATES[category]))

    bulk_insert(conn, "customers.customer_complaints",
                ["complaint_id", "complaint_date", "store_id", "sku_id",
                 "sale_id", "category", "description"],
                rows)
    print(f"customers.customer_complaints seeded -> {len(rows)} rows")

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

        seed_complaints(conn, sku_ids, store_ids, sales_rows)
        conn.commit()
        print("\ncustomers seeding complete.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    main()