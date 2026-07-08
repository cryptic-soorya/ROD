"""
seeds/seed_anomaly.py

Injects one deliberate, coherent anomaly into the otherwise-random seed data,
for testing the ReAct agent end-to-end with a case designed to be resolvable
with HIGH confidence (unlike the base random data, which has no engineered
signal anywhere — see investigation notes from 2026-07-08).

Scenario: store S036, SKU P0108, supplier SUP07 (this exact
product/store/supplier triple already exists together in inventory.db's
replenishment_history, so it's not a made-up link).

    Supplier SUP07 has been chronically late shipping P0108 to S036 for the
    last month, so S036 has been stocked out on P0108 for weeks.

Evidence this leaves for the agent's tools to find:
  - get_inventory_levels("P0108", "S036")
        -> stock_on_hand = 0, stockout_flag = True, below_reorder_point = True
  - get_replenishment_history("P0108", "S036", days=30)
        -> one order received ~23 days late and badly short-shipped, one
           order still outstanding past its expected delivery window
  - get_delivery_performance("SUP07", period=...)
        -> degradation_flag = True for last_7_days/last_30_days (severe),
           and true (barely) for last_quarter (problem is recent-onset)

NOTE: get_sales_data has no SKU parameter — it only aggregates revenue at
the whole-store level (see mcp_server/tools/sales.py). P0108 is one of
~40 products sold at S036, so suppressing its sales alone wouldn't move
the store-wide number enough to be a legible signal, and doing that to a
meaningful fraction of the store's other ~40 products just to force a
store-level dip would no longer be "one clean anomaly" — it'd be
overwriting most of the store's data. Skipped deliberately; the
inventory/replenishment/supplier chain alone is enough for a confident
supplier_delay root cause, per agent/prompts.py's own confidence rubric
(multiple independent confirming signals -> 0.85-1.0).

Run from the rod/ directory, same convention as the other seeds/*.py:
    python seeds/seed_anomaly.py

Safe to re-run: deletes-then-reinserts only the specific rows it owns
(scoped by product_id/store_id/supplier_id, and for replenishment_history
also by a recent order_date window) rather than touching anything else.
"""
import sqlite3
from datetime import date, timedelta

STORE_ID = "S036"
SKU = "P0108"
SUPPLIER_ID = "SUP07"

TODAY = date.today()

INVENTORY_DB = "mcp_server/db/inventory.db"
SUPPLIERS_DB = "mcp_server/db/suppliers.db"


def seed_inventory_snapshot(conn: sqlite3.Connection) -> None:
    """Force the latest snapshot for P0108/S036 to an unambiguous stockout.
    get_inventory_levels only ever reads the single most recent row (ORDER BY
    snapshot_date DESC LIMIT 1), so that's the only row that matters here."""
    latest_date = conn.execute(
        "SELECT MAX(snapshot_date) FROM inventory_levels WHERE product_id = ? AND store_id = ?",
        (SKU, STORE_ID),
    ).fetchone()[0]

    if latest_date is None:
        # no snapshot exists at all yet for this pair (only happens if
        # inventory.db was reseeded without this product/store combo) — insert one
        conn.execute(
            "INSERT INTO inventory_levels (product_id, store_id, snapshot_date, stock_on_hand, reorder_point, stockout_flag) "
            "VALUES (?, ?, ?, 0, 40, 1)",
            (SKU, STORE_ID, TODAY.isoformat()),
        )
    else:
        conn.execute(
            "UPDATE inventory_levels SET stock_on_hand = 0, stockout_flag = 1 "
            "WHERE product_id = ? AND store_id = ? AND snapshot_date = ?",
            (SKU, STORE_ID, latest_date),
        )
    print(f"inventory_levels: latest snapshot for {SKU}/{STORE_ID} ({latest_date or TODAY.isoformat()}) forced to stock_on_hand=0, stockout_flag=1")


def seed_replenishment_delay(conn: sqlite3.Connection) -> None:
    """Insert two recent, badly-delayed orders from SUP07 for P0108/S036 —
    one that arrived ~23 days late and short-shipped, one still outstanding.
    Uses TODAY-relative dates so this stays inside get_replenishment_history's
    default 30-day lookback regardless of when this script actually runs."""
    window_start = (TODAY - timedelta(days=40)).isoformat()
    conn.execute(
        "DELETE FROM replenishment_history WHERE product_id = ? AND store_id = ? AND supplier_id = ? AND order_date >= ?",
        (SKU, STORE_ID, SUPPLIER_ID, window_start),
    )

    order_a = TODAY - timedelta(days=25)
    received_a = TODAY - timedelta(days=2)   # 23-day lead time vs this pair's historical ~4 days
    order_b = TODAY - timedelta(days=10)      # still outstanding — no received_date at all

    conn.execute(
        "INSERT INTO replenishment_history (product_id, store_id, order_date, received_date, units_ordered, units_received, supplier_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (SKU, STORE_ID, order_a.isoformat(), received_a.isoformat(), 300, 180, SUPPLIER_ID),
    )
    conn.execute(
        "INSERT INTO replenishment_history (product_id, store_id, order_date, received_date, units_ordered, units_received, supplier_id) "
        "VALUES (?, ?, ?, NULL, ?, NULL, ?)",
        (SKU, STORE_ID, order_b.isoformat(), 280, SUPPLIER_ID),
    )
    print(f"replenishment_history: inserted 2 delayed/outstanding orders for {SKU}/{STORE_ID} from {SUPPLIER_ID}")


def seed_supplier_degradation(conn: sqlite3.Connection) -> None:
    """SUP07 degradation_flag = current > 1.5 x baseline (mcp_server/tools/suppliers.py).
    Severe in the short term, still true (barely) at the quarter view, reflecting
    a problem that started partway through the quarter rather than always existing."""
    rows = [
        (SUPPLIER_ID, "last_7_days",  12.0, 4.5, 0.06),
        (SUPPLIER_ID, "last_30_days", 10.5, 4.3, 0.055),
        (SUPPLIER_ID, "last_quarter",  6.8, 4.5, 0.045),
    ]
    for supplier_id, period, current, baseline, defect_rate in rows:
        conn.execute(
            "INSERT OR REPLACE INTO supplier_deliveries "
            "(supplier_id, period, avg_delivery_days_current, avg_delivery_days_baseline, defect_rate) "
            "VALUES (?, ?, ?, ?, ?)",
            (supplier_id, period, current, baseline, defect_rate),
        )
    print(f"supplier_deliveries: {SUPPLIER_ID} degraded across all 3 periods (current > 1.5x baseline)")


def main() -> None:
    inv_conn = sqlite3.connect(INVENTORY_DB)
    try:
        seed_inventory_snapshot(inv_conn)
        seed_replenishment_delay(inv_conn)
        inv_conn.commit()
    finally:
        inv_conn.close()

    sup_conn = sqlite3.connect(SUPPLIERS_DB)
    try:
        seed_supplier_degradation(sup_conn)
        sup_conn.commit()
    finally:
        sup_conn.close()

    print(f"\nDone. Investigate with store_id='{STORE_ID}', sku='{SKU}' to exercise this case.")


if __name__ == "__main__":
    main()
