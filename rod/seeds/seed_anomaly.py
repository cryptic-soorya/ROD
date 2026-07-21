"""
seeds/seed_anomaly.py

Injects ONE deliberate, coherent anomaly scenario across schemas so your
agent's MCP tools have something real to investigate -- as opposed to the
other seed_*.py scripts, which generate independent random data per schema
with no causal relationship between tables.

Run LAST, after every other seed_*.py script (including seed_sales.py,
seed_inventory.py, seed_suppliers.py, seed_returns.py, seed_customers.py).
It depends on all of them and will delete/rewrite a narrow slice of
sales.sales + sales.sale_items for the target sku/stores to make room for
the story.

THE STORY
---------
One supplier (TARGET_SUPPLIER) starts delivering late and with a higher
defect rate for one sku (TARGET_SKU) at three stores (TARGET_STORES),
starting ANOMALY_START (45 days ago) and continuing through today:

    1. suppliers.supplier_delivery  -- root cause: degraded lead times +
       elevated defect_rate for that supplier/sku/store combo.
    2. inventory.replenishment_history -- replenishment orders placed
       during the window take much longer and arrive partially fulfilled.
    3. inventory.inventory -- stock_on_hand is driven to near-zero at the
       three stores (visible stockout).
    4. sales.sales / sales.sale_items -- the 45 days BEFORE the window
       show normal sales frequency for that sku/store; the 45 days DURING
       the window show a sharp drop (lost sales due to stockout). This is
       a real, queryable decline, not just fewer random rows.
    5. returns.return_reasons -- of the sales that did go through during
       the window, an elevated share come back with reason "defective".
    6. customers.customer_complaints -- a spike of "quality" complaints
       for that sku/store during the window.

Nothing here touches orchestration.investigations/hypotheses/etc. -- per
seed_orchestration.py, those should be produced by your real agent as it
investigates this injected scenario, not faked.

Run: python seeds/seed_anomaly.py
"""

import random
from datetime import date, timedelta
from psycopg2.extras import execute_values
from db import get_conn, bulk_insert, fetch_ids

random.seed(99)

ANOMALY_END = date.today()
ANOMALY_START = ANOMALY_END - timedelta(days=45)
PRE_WINDOW_START = ANOMALY_START - timedelta(days=45)

BASELINE_DELIVERY_DAYS = 4.0
BASELINE_DEFECT_RATE = 0.03


def pick_targets(conn):
    sku_ids = fetch_ids(conn, "SELECT sku_id FROM reference.sku ORDER BY sku_id")
    store_ids = fetch_ids(conn, "SELECT store_id FROM reference.stores ORDER BY store_id")
    supplier_ids = fetch_ids(conn, "SELECT supplier_id FROM reference.suppliers ORDER BY supplier_id")

    if not sku_ids or not store_ids or not supplier_ids:
        raise RuntimeError("reference tables are empty -- run seed_reference.py first")
    if len(store_ids) < 3:
        raise RuntimeError("need at least 3 stores in reference.stores for this scenario")

    target_sku = sku_ids[len(sku_ids) // 3]
    target_stores = store_ids[:3]
    target_supplier = supplier_ids[0]
    return target_sku, target_stores, target_supplier


def seed_supplier_degradation(conn, supplier_id, sku_id, store_ids):
    rows = []
    idx = 1
    for store_id in store_ids:
        for _ in range(12):
            deli_id = f"DELIAN{idx:04d}"
            idx += 1
            delivery_date = ANOMALY_START + timedelta(days=random.randint(0, 45))
            current = round(BASELINE_DELIVERY_DAYS * random.uniform(2.2, 3.2), 2)
            defect_rate = round(max(0.0, min(1.0, random.gauss(0.18, 0.03))), 4)
            rows.append((deli_id, supplier_id, sku_id, store_id, delivery_date.isoformat(),
                         current, BASELINE_DELIVERY_DAYS, defect_rate, True))

    bulk_insert(conn, "suppliers.supplier_delivery",
                ["deli_id", "supplier_id", "sku_id", "store_id", "delivery_date",
                 "avg_delivery_days_current", "avg_delivery_days_baseline",
                 "defect_rate", "degradation_flag"],
                rows)
    print(f"suppliers.supplier_delivery: injected {len(rows)} degraded deliveries")


def seed_replenishment_gap(conn, sku_id, store_ids, supplier_id):
    rows = []
    for store_id in store_ids:
        for _ in range(4):
            order_day = ANOMALY_START + timedelta(days=random.randint(0, 35))
            lead_days = random.randint(12, 20)  # normal baseline is ~5 days
            received_day = order_day + timedelta(days=lead_days)
            units_ordered = random.randint(100, 400)
            units_received = int(units_ordered * random.uniform(0.4, 0.7))  # partial fulfillment
            rows.append((sku_id, store_id, order_day.isoformat(), received_day.isoformat(),
                         units_ordered, units_received, supplier_id))

    bulk_insert(conn, "inventory.replenishment_history",
                ["sku_id", "store_id", "order_date", "received_date",
                 "units_ordered", "units_received", "supplier_id"],
                rows)
    print(f"inventory.replenishment_history: injected {len(rows)} delayed/partial orders")


def seed_inventory_stockout(conn, sku_id, store_ids):
    with conn.cursor() as cur:
        for store_id in store_ids:
            cur.execute(
                """
                UPDATE inventory.inventory
                SET stock_on_hand = %s, last_audited = %s
                WHERE sku_id = %s AND store_id = %s
                """,
                (random.randint(0, 4), date.today().isoformat(), sku_id, store_id),
            )
            if cur.rowcount == 0:
                cur.execute(
                    """
                    INSERT INTO inventory.inventory
                        (sku_id, store_id, stock_on_hand, reorder_point, last_audited)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (sku_id, store_id, random.randint(0, 4), 30, date.today().isoformat()),
                )
    print(f"inventory.inventory: drove stock_on_hand to near-zero at {len(store_ids)} stores")


def reset_window_sales(conn, sku_id, store_ids):
    """Clear existing sales for the target sku/stores across the full
    90-day span (pre-window + anomaly window) so we can rewrite a clean,
    causally meaningful before/after pattern."""
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM sales.sale_items
            WHERE sale_id IN (
                SELECT sale_id FROM sales.sales
                WHERE sku_id = %s AND store_id = ANY(%s) AND sale_date >= %s
            )
            """,
            (sku_id, store_ids, PRE_WINDOW_START.isoformat()),
        )
        cur.execute(
            "DELETE FROM sales.sales WHERE sku_id = %s AND store_id = ANY(%s) AND sale_date >= %s",
            (sku_id, store_ids, PRE_WINDOW_START.isoformat()),
        )


def seed_sales_decline(conn, sku_id, store_ids, all_sku_ids):
    reset_window_sales(conn, sku_id, store_ids)

    sales_data = []
    for store_id in store_ids:
        # pre-window baseline: normal, frequent sales
        for d in range(45):
            day = PRE_WINDOW_START + timedelta(days=d)
            if random.random() < 0.6:
                total_price = round(random.uniform(15.0, 800.0), 2)
                sales_data.append((sku_id, store_id, day.isoformat(), total_price))
        # anomaly window: stockout starves sales
        for d in range(45):
            day = ANOMALY_START + timedelta(days=d)
            if random.random() < 0.15:
                total_price = round(random.uniform(15.0, 800.0), 2)
                sales_data.append((sku_id, store_id, day.isoformat(), total_price))

    with conn.cursor() as cur:
        generated = execute_values(
            cur,
            """
            INSERT INTO sales.sales (sku_id, store_id, sale_date, total_price)
            VALUES %s
            RETURNING sale_id, sale_date
            """,
            sales_data,
            fetch=True,
        )

        sale_items_data = []
        for sale_id, _sale_date in generated:
            for _ in range(random.randint(1, 4)):
                item_sku_id = random.choice(all_sku_ids)
                quantity = random.randint(1, 5)
                mrp = round(random.uniform(5.0, 150.0), 2)
                dscnt_applied = round(random.uniform(0.0, mrp * 0.2), 2)
                sale_items_data.append((sale_id, item_sku_id, quantity, mrp, dscnt_applied))

        execute_values(
            cur,
            """
            INSERT INTO sales.sale_items (sale_id, sku_id, quantity, mrp, dscnt_applied)
            VALUES %s
            """,
            sale_items_data,
        )

    n_pre = sum(1 for _id, d in generated if date.fromisoformat(d if isinstance(d, str) else d.isoformat()) < ANOMALY_START)
    n_during = len(generated) - n_pre
    print(f"sales.sales: rewrote window -> {n_pre} pre-window sales, {n_during} during-anomaly sales "
          f"({len(sale_items_data)} line items)")
    return generated


def seed_returns_spike(conn, sku_id, store_ids):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT sale_id, sale_date FROM sales.sales WHERE sku_id = %s AND store_id = ANY(%s) AND sale_date >= %s",
            (sku_id, store_ids, ANOMALY_START.isoformat()),
        )
        window_sales = cur.fetchall()

    rows = []
    for sale_id, sale_date_val in window_sales:
        if random.random() < 0.5:  # elevated defective-return rate during window
            sale_date_str = sale_date_val if isinstance(sale_date_val, str) else sale_date_val.isoformat()
            projected = date.fromisoformat(sale_date_str) + timedelta(days=random.randint(1, 10))
            return_date = min(date.today(), projected).isoformat()
            store_id = random.choice(store_ids)
            rows.append((sku_id, store_id, sale_id, return_date, "defective",
                        "Item stopped working / broke after few uses -- spike tied to bad supplier batch",
                        random.randint(1, 10)))

    bulk_insert(conn, "returns.return_reasons",
                ["sku_id", "store_id", "sale_id", "return_date", "reason_code",
                 "reason_text", "units_returned"],
                rows)
    print(f"returns.return_reasons: injected {len(rows)} defective returns tied to window sales")


def seed_complaints_spike(conn, sku_id, store_ids):
    rows = []
    for i in range(1, 121):
        complaint_id = f"CMP-AN{i:04d}"
        store_id = random.choice(store_ids)
        complaint_date = (ANOMALY_START + timedelta(days=random.randint(0, 45))).isoformat()
        rows.append((complaint_id, complaint_date, store_id, sku_id, None,
                    "quality", "Multiple customers reporting defective units this month"))

    bulk_insert(conn, "customers.customer_complaints",
                ["complaint_id", "complaint_date", "store_id", "sku_id",
                 "sale_id", "category", "description"],
                rows)
    print(f"customers.customer_complaints: injected {len(rows)} quality complaints")


def main():
    conn = get_conn()
    try:
        target_sku, target_stores, target_supplier = pick_targets(conn)
        all_sku_ids = fetch_ids(conn, "SELECT sku_id FROM reference.sku")

        print(f"\n{'='*60}\nInjecting anomaly scenario\n{'='*60}")
        print(f"sku:      {target_sku}")
        print(f"stores:   {target_stores}")
        print(f"supplier: {target_supplier}")
        print(f"window:   {ANOMALY_START.isoformat()} -> {ANOMALY_END.isoformat()} "
              f"(baseline compare: {PRE_WINDOW_START.isoformat()} -> {ANOMALY_START.isoformat()})")
        print(f"{'='*60}\n")

        seed_supplier_degradation(conn, target_supplier, target_sku, target_stores)
        seed_replenishment_gap(conn, target_sku, target_stores, target_supplier)
        seed_inventory_stockout(conn, target_sku, target_stores)
        seed_sales_decline(conn, target_sku, target_stores, all_sku_ids)
        seed_returns_spike(conn, target_sku, target_stores)
        seed_complaints_spike(conn, target_sku, target_stores)

        conn.commit()
        print(f"\n{'='*60}\nAnomaly injected & committed.\n"
              f"Query sku_id={target_sku}, store_id in {target_stores} "
              f"around {ANOMALY_START.isoformat()} to see the full chain:\n"
              f"supplier degradation -> replenishment gap -> stockout -> "
              f"sales decline -> returns/complaints spike.\n{'='*60}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()