"""
inject_test_anomalies.py
Injects a small number of GROUND-TRUTH anomalies into already-seeded ROD
databases, so you can point the ReAct agent at a real product and check
whether it recovers the correct root cause.

Run from repo root (same convention as seed_sales.py etc.):
    python seeds/inject_test_anomalies.py

Requires: the six domain dbs already seeded (sales, inventory, suppliers,
returns, customers) via the existing seed_*.py scripts. Safe to re-run —
it deletes its own previously-injected rows for the anomaly window before
re-inserting.

Produces two scenarios, applied to real product/supplier pairs pulled
straight out of your seeded replenishment_history (never invented IDs
outside what your data already uses, except the two new "bad manufacturer"
supplier ids created for Scenario B, which are intentionally new).

SCENARIO A — "Existing supplier degrades"
    product's current main supplier -> delivery days spike + degradation_flag=1
    -> inventory stockout for that product's stores
    -> sales.units_sold collapses to ~0 in the anomaly window
    Ground truth: supplier degradation -> stockout -> sales drop.

SCENARIO B — "Manufacturer swap"
    product's recent replenishment_history.supplier_id switched to a NEW
    supplier with a high defect_rate (delivery timing stays normal)
    -> return_reasons spike with reason_code='defective'
    -> customer_complaints spike with category='quality'
    -> sales.units_sold dips moderately (not a stockout)
    Ground truth: manufacturer switch -> quality defects -> returns/complaints.

Writes a full before/after change log to:
    seeds/anomaly_injection_log.json
    seeds/anomaly_injection_report.md
"""
import sqlite3
import random
import json
from datetime import date, timedelta
from seeds.common import STORES as ALL_STORES, SUPPLIERS as ALL_SUPPLIERS

random.seed(101)  # separate seed from the base seeders, so this is deterministic on its own

import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(SCRIPT_DIR, "..", "mcp_server", "db")

SALES_DB     = os.path.join(DB_DIR, "sales.db")
INVENTORY_DB = os.path.join(DB_DIR, "inventory.db")
SUPPLIERS_DB = os.path.join(DB_DIR, "suppliers.db")
RETURNS_DB   = os.path.join(DB_DIR, "returns.db")
CUSTOMERS_DB = os.path.join(DB_DIR, "customers.db")

ANOMALY_START = date(2026, 6, 16)
ANOMALY_END   = date(2026, 6, 30)  # last 14 days of the seeded date range

NUM_DEGRADE = 2
NUM_SWAP = 2

NEW_BAD_SUPPLIERS = ["SUP21", "SUP22"]  # intentionally outside SUP01-20, used only for Scenario B


def window_dates():
    days = (ANOMALY_END - ANOMALY_START).days
    return [(ANOMALY_START + timedelta(days=i)).isoformat() for i in range(days + 1)]


def connect(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = OFF")
    return conn


# ── Candidate selection ──────────────────────────────────────────────────

def pick_candidates(inv_conn, n_needed):
    """
    Pulls (product_id, main_supplier_id) pairs straight from replenishment_history:
    for each product that has enough order history, find its most frequent supplier.
    Only products with >= 5 replenishment orders are considered, so there's a real
    history to manipulate.
    """
    rows = inv_conn.execute(
        """
        SELECT product_id, supplier_id, COUNT(*) as cnt
        FROM replenishment_history
        GROUP BY product_id, supplier_id
        """
    ).fetchall()

    by_product = {}
    for product_id, supplier_id, cnt in rows:
        by_product.setdefault(product_id, []).append((supplier_id, cnt))

    candidates = []
    for product_id, supplier_counts in by_product.items():
        total = sum(c for _, c in supplier_counts)
        if total < 5:
            continue
        main_supplier = max(supplier_counts, key=lambda x: x[1])[0]
        candidates.append((product_id, main_supplier, total))

    random.shuffle(candidates)
    if len(candidates) < n_needed:
        raise RuntimeError(
            f"Only found {len(candidates)} eligible products with >=5 replenishment "
            f"orders. Re-run seed_inventory.py with more sample_products, or lower "
            f"the threshold in pick_candidates()."
        )
    selected = candidates[:n_needed]
    print(f"[pick_candidates] selected {len(selected)} product/supplier pairs:")
    for product_id, main_supplier, total in selected:
        print(f"    - product={product_id}  main_supplier={main_supplier}  replenishment_orders={total}")
    return selected


def product_stores(inv_conn, product_id):
    rows = inv_conn.execute(
        "SELECT DISTINCT store_id FROM inventory_levels WHERE product_id = ?",
        (product_id,),
    ).fetchall()
    stores = [r[0] for r in rows]
    if not stores:
        stores = random.sample(ALL_STORES, 3)
    return stores[:5]  # cap so we're not touching 50 stores per product


def product_avg_unit_price(sales_conn, product_id):
    row = sales_conn.execute(
        """
        SELECT AVG(revenue * 1.0 / units_sold)
        FROM sales
        WHERE product_id = ? AND units_sold > 0
        """,
        (product_id,),
    ).fetchone()
    return round(row[0], 2) if row and row[0] else round(random.uniform(10, 100), 2)


# ── Scenario A: existing supplier degrades ──────────────────────────────

def degrade_existing_supplier(product_id, supplier_id, sup_conn, inv_conn, sales_conn, log):
    print(f"\n=== SCENARIO A: degrading existing supplier ===")
    print(f"    product_id={product_id}  supplier_id={supplier_id}")

    dates = window_dates()
    entry = {
        "scenario": "A_supplier_degrades",
        "product_id": product_id,
        "supplier_id": supplier_id,
        "window": [dates[0], dates[-1]],
        "changes": [],
    }

    # 1. suppliers.db: baseline from existing history, then inject degraded rows
    base_row = sup_conn.execute(
        "SELECT AVG(avg_delivery_days_baseline), AVG(defect_rate) FROM supplier_delivery WHERE supplier_id = ?",
        (supplier_id,),
    ).fetchone()
    baseline_days = round(base_row[0], 2) if base_row and base_row[0] else round(random.uniform(3, 7), 2)
    baseline_defect = round(base_row[1], 4) if base_row and base_row[1] else 0.03

    sup_conn.execute(
        "DELETE FROM supplier_delivery WHERE supplier_id = ? AND product_id = ? AND delivery_date BETWEEN ? AND ?",
        (supplier_id, product_id, dates[0], dates[-1]),
    )
    inserted = 0
    for d in dates:
        current_days = round(baseline_days * random.uniform(2.5, 3.2), 2)
        defect_rate = round(min(0.2, baseline_defect * random.uniform(1.5, 2.2)), 4)
        sup_conn.execute(
            """INSERT INTO supplier_delivery
               (supplier_id, product_id, delivery_date, avg_delivery_days_current,
                avg_delivery_days_baseline, defect_rate, degradation_flag)
               VALUES (?,?,?,?,?,?,1)""",
            (supplier_id, product_id, d, current_days, baseline_days, defect_rate),
        )
        inserted += 1
    print(f"    [suppliers.db] product={product_id} supplier={supplier_id}: "
          f"inserted {inserted} degraded delivery rows (baseline={baseline_days}d -> ~{round(baseline_days*2.8,2)}d)")
    entry["changes"].append({
        "table": "suppliers.db:supplier_delivery",
        "action": f"inserted {inserted} rows for supplier {supplier_id} / product {product_id}",
        "before_baseline_days": baseline_days,
        "after_current_days": f"~{round(baseline_days*2.8,2)} (2.5-3.2x baseline)",
        "degradation_flag": 1,
    })

    # 2. inventory.db: stockout in this product's stores, ramping to 0
    stores = product_stores(inv_conn, product_id)
    inv_conn.execute(
        "DELETE FROM inventory_levels WHERE product_id = ? AND store_id IN ({}) AND snapshot_date BETWEEN ? AND ?".format(
            ",".join("?" * len(stores))
        ),
        [product_id, *stores, dates[0], dates[-1]],
    )
    reorder_pt = 30
    for store_id in stores:
        stock = random.randint(40, 80)
        for i, d in enumerate(dates):
            drop = max(5, stock // 4)
            stock = max(0, stock - drop) if i < 4 else 0
            stockout_flag = 1 if stock == 0 else 0
            inv_conn.execute(
                """INSERT INTO inventory_levels
                   (product_id, store_id, snapshot_date, stock_on_hand, reorder_point, stockout_flag)
                   VALUES (?,?,?,?,?,?)""",
                (product_id, store_id, d, stock, reorder_pt, stockout_flag),
            )
    print(f"    [inventory.db] product={product_id}: stockout ramp injected in stores {stores}")
    entry["changes"].append({
        "table": "inventory.db:inventory_levels",
        "action": f"stores {stores} ramp to stock_on_hand=0 by day 4, stockout_flag=1 for remainder of window",
    })

    # 3. inventory.db: mark the most recent replenishment order as stuck (never received)
    recent_order = inv_conn.execute(
        """SELECT id, order_date FROM replenishment_history
           WHERE product_id = ? AND supplier_id = ?
           ORDER BY order_date DESC LIMIT 1""",
        (product_id, supplier_id),
    ).fetchone()
    if recent_order:
        order_id, order_date = recent_order
        inv_conn.execute(
            "UPDATE replenishment_history SET received_date = NULL WHERE id = ?",
            (order_id,),
        )
        print(f"    [inventory.db] product={product_id}: replenishment order id={order_id} "
              f"(order_date={order_date}) marked as stuck (received_date=NULL)")
        entry["changes"].append({
            "table": "inventory.db:replenishment_history",
            "action": f"order id={order_id} (order_date={order_date}) set received_date=NULL — open order stuck with degraded supplier",
        })

    # 4. sales.db: collapse units_sold in the same stores/window
    price = product_avg_unit_price(sales_conn, product_id)
    sales_conn.execute(
        "DELETE FROM sales WHERE product_id = ? AND store_id IN ({}) AND sale_date BETWEEN ? AND ?".format(
            ",".join("?" * len(stores))
        ),
        [product_id, *stores, dates[0], dates[-1]],
    )
    total_units_before_est = 0
    for store_id in stores:
        for d in dates:
            units = random.choice([0, 0, 0, 1])  # near-zero, occasional trickle sale from remaining stock
            revenue = round(units * price, 2)
            channel = random.choice(["online", "in_store"])
            sales_conn.execute(
                """INSERT INTO sales (product_id, store_id, sale_date, units_sold, revenue, discount_pct, channel)
                   VALUES (?,?,?,?,?,0,?)""",
                (product_id, store_id, d, units, revenue, channel),
            )
    print(f"    [sales.db] product={product_id}: units_sold collapsed to 0-1/day across stores {stores}")
    entry["changes"].append({
        "table": "sales.db:sales",
        "action": f"units_sold collapsed to 0-1/day across stores {stores} for the full window (unit price ${price})",
    })

    entry["ground_truth"] = (
        f"Supplier {supplier_id} degraded (avg delivery ~2.5-3.2x baseline of {baseline_days} days, "
        f"degradation_flag=1) starting {dates[0]}. Its most recent open order for {product_id} never "
        f"arrived (received_date=NULL). This caused stockouts (stockout_flag=1) in stores {stores}, "
        f"which collapsed units_sold to near zero for the rest of the window."
    )
    print(f"    [DONE] product={product_id} fully injected (Scenario A)")
    log.append(entry)
    return entry


# ── Scenario B: manufacturer swap ────────────────────────────────────────

def swap_to_new_supplier(product_id, old_supplier_id, new_supplier_id, sup_conn, inv_conn,
                          ret_conn, cust_conn, sales_conn, log):
    print(f"\n=== SCENARIO B: manufacturer swap ===")
    print(f"    product_id={product_id}  old_supplier={old_supplier_id}  new_supplier={new_supplier_id}")

    dates = window_dates()
    entry = {
        "scenario": "B_manufacturer_swap",
        "product_id": product_id,
        "old_supplier_id": old_supplier_id,
        "new_supplier_id": new_supplier_id,
        "window": [dates[0], dates[-1]],
        "changes": [],
    }

    # 1. inventory.db: swap supplier_id on recent orders for this product
    recent_orders = inv_conn.execute(
        """SELECT id FROM replenishment_history
           WHERE product_id = ? AND supplier_id = ? AND order_date >= ?""",
        (product_id, old_supplier_id, (ANOMALY_START - timedelta(days=10)).isoformat()),
    ).fetchall()
    order_ids = [r[0] for r in recent_orders]
    if order_ids:
        inv_conn.executemany(
            "UPDATE replenishment_history SET supplier_id = ? WHERE id = ?",
            [(new_supplier_id, oid) for oid in order_ids],
        )
    print(f"    [inventory.db] product={product_id}: {len(order_ids)} orders switched "
          f"{old_supplier_id} -> {new_supplier_id} (order_ids={order_ids})")
    entry["changes"].append({
        "table": "inventory.db:replenishment_history",
        "action": f"{len(order_ids)} recent orders switched from supplier {old_supplier_id} -> {new_supplier_id}",
        "order_ids": order_ids,
    })

    # 2. suppliers.db: new supplier has normal delivery timing but a high defect rate
    sup_conn.execute(
        "DELETE FROM supplier_delivery WHERE supplier_id = ? AND product_id = ? AND delivery_date BETWEEN ? AND ?",
        (new_supplier_id, product_id, dates[0], dates[-1]),
    )
    baseline_days = round(random.uniform(3, 6), 2)
    for d in dates:
        current_days = round(baseline_days * random.uniform(0.9, 1.2), 2)  # NOT delayed, on purpose
        defect_rate = round(random.uniform(0.15, 0.25), 4)  # the actual problem
        sup_conn.execute(
            """INSERT INTO supplier_delivery
               (supplier_id, product_id, delivery_date, avg_delivery_days_current,
                avg_delivery_days_baseline, defect_rate, degradation_flag)
               VALUES (?,?,?,?,?,?,0)""",
            (new_supplier_id, product_id, d, current_days, baseline_days, defect_rate),
        )
    print(f"    [suppliers.db] product={product_id}: {len(dates)} rows inserted for new supplier "
          f"{new_supplier_id} (normal delivery, defect_rate 0.15-0.25)")
    entry["changes"].append({
        "table": "suppliers.db:supplier_delivery",
        "action": f"inserted {len(dates)} rows for NEW supplier {new_supplier_id}: normal delivery timing, defect_rate 0.15-0.25, degradation_flag=0",
        "note": "delivery timing deliberately normal so the agent has to distinguish this from Scenario A",
    })

    # 3. returns.db: defective returns spike
    ret_conn.execute(
        "DELETE FROM return_reasons WHERE product_id = ? AND return_date BETWEEN ? AND ?",
        (product_id, dates[0], dates[-1]),
    )
    inserted = 0
    for d in dates:
        if random.random() < 0.7:
            ret_conn.execute(
                """INSERT INTO return_reasons
                   (product_id, return_date, reason_code, reason_text, units_returned, sample_size)
                   VALUES (?,?,?,?,?,?)""",
                (product_id, d, "defective",
                 "Item stopped working / broke after few uses", random.randint(3, 10), random.randint(20, 60)),
            )
            inserted += 1
    print(f"    [returns.db] product={product_id}: {inserted} 'defective' return_reasons rows inserted")
    entry["changes"].append({
        "table": "returns.db:return_reasons",
        "action": f"inserted {inserted} rows with reason_code='defective', sample_size>=20 (avoids low_sample_warning)",
    })

    # 4. customers.db: quality complaints spike
    stores = product_stores(inv_conn, product_id)
    cust_conn.execute(
        "DELETE FROM customer_complaints WHERE product_id = ? AND complaint_date BETWEEN ? AND ?",
        (product_id, dates[0], dates[-1]),
    )
    inserted = 0
    for d in dates:
        if random.random() < 0.6:
            cust_conn.execute(
                """INSERT INTO customer_complaints
                   (product_id, store_id, complaint_date, category, severity, complaint_text, resolved)
                   VALUES (?,?,?,?,?,?,?)""",
                (product_id, random.choice(stores), d, "quality",
                 random.choices(["low", "medium", "high"], weights=[0.2, 0.4, 0.4])[0],
                 "Product felt cheap / broke faster than expected",
                 random.choices([1, 0], weights=[0.3, 0.7])[0]),  # mostly unresolved -> backlog signal
            )
            inserted += 1
    print(f"    [customers.db] product={product_id}: {inserted} 'quality' complaints inserted (stores={stores})")
    entry["changes"].append({
        "table": "customers.db:customer_complaints",
        "action": f"inserted {inserted} 'quality' complaints, weighted toward unresolved (backlog signal)",
    })

    # 5. sales.db: moderate dip, not a full stockout
    price = product_avg_unit_price(sales_conn, product_id)
    existing = sales_conn.execute(
        "SELECT id, units_sold FROM sales WHERE product_id = ? AND sale_date BETWEEN ? AND ?",
        (product_id, dates[0], dates[-1]),
    ).fetchall()
    for row_id, units in existing:
        new_units = max(0, int(units * random.uniform(0.4, 0.65)))
        new_revenue = round(new_units * price, 2)
        sales_conn.execute(
            "UPDATE sales SET units_sold = ?, revenue = ? WHERE id = ?",
            (new_units, new_revenue, row_id),
        )
    print(f"    [sales.db] product={product_id}: {len(existing)} rows dipped to ~40-65% of original units_sold")
    entry["changes"].append({
        "table": "sales.db:sales",
        "action": f"units_sold reduced to ~40-65% of original for {len(existing)} existing rows in window (moderate dip, not stockout)",
    })

    entry["ground_truth"] = (
        f"Product {product_id} was switched from supplier {old_supplier_id} to {new_supplier_id} on recent "
        f"replenishment orders. {new_supplier_id} has normal delivery timing (degradation_flag=0) but an "
        f"elevated defect_rate (0.15-0.25), which shows up as a 'defective' spike in return_reasons and a "
        f"'quality' complaint spike in customer_complaints, plus a moderate (not total) sales dip. The trap: "
        f"a naive check of degradation_flag alone will miss this — the agent needs get_delivery_performance's "
        f"defect_rate field specifically."
    )
    print(f"    [DONE] product={product_id} fully injected (Scenario B)")
    log.append(entry)
    return entry


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    sales_conn = connect(SALES_DB)
    inv_conn = connect(INVENTORY_DB)
    sup_conn = connect(SUPPLIERS_DB)
    ret_conn = connect(RETURNS_DB)
    cust_conn = connect(CUSTOMERS_DB)

    candidates = pick_candidates(inv_conn, NUM_DEGRADE + NUM_SWAP)
    degrade_candidates = candidates[:NUM_DEGRADE]
    swap_candidates = candidates[NUM_DEGRADE:NUM_DEGRADE + NUM_SWAP]

    log = []

    for product_id, supplier_id, _ in degrade_candidates:
        degrade_existing_supplier(product_id, supplier_id, sup_conn, inv_conn, sales_conn, log)

    for i, (product_id, old_supplier_id, _) in enumerate(swap_candidates):
        new_supplier_id = NEW_BAD_SUPPLIERS[i % len(NEW_BAD_SUPPLIERS)]
        swap_to_new_supplier(product_id, old_supplier_id, new_supplier_id,
                              sup_conn, inv_conn, ret_conn, cust_conn, sales_conn, log)

    for conn in (sales_conn, inv_conn, sup_conn, ret_conn, cust_conn):
        conn.commit()
        conn.close()

    with open("seeds/anomaly_injection_log.json", "w") as f:
        json.dump(log, f, indent=2)

    with open("seeds/anomaly_injection_report.md", "w") as f:
        f.write("# Injected Test Anomalies\n\n")
        f.write(f"Window: {ANOMALY_START.isoformat()} to {ANOMALY_END.isoformat()}\n\n")
        for entry in log:
            f.write(f"## {entry['product_id']} — {entry['scenario']}\n\n")
            f.write(f"**Ground truth:** {entry['ground_truth']}\n\n")
            f.write("**Changes made:**\n\n")
            for c in entry["changes"]:
                f.write(f"- `{c['table']}`: {c['action']}\n")
            f.write("\n")

    print(f"\n{'='*60}")
    print(f"SUMMARY: Injected {len(log)} anomalies into the following products:")
    print(f"{'='*60}")
    for entry in log:
        if entry["scenario"] == "A_supplier_degrades":
            print(f"- {entry['product_id']}  [{entry['scenario']}]  supplier={entry['supplier_id']}")
        else:
            print(f"- {entry['product_id']}  [{entry['scenario']}]  "
                  f"{entry['old_supplier_id']} -> {entry['new_supplier_id']}")
    print(f"\nFull log: seeds/anomaly_injection_log.json")
    print("Human-readable report: seeds/anomaly_injection_report.md")


if __name__ == "__main__":
    main()