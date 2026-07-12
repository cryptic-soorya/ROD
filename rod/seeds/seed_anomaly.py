"""
seeds/seed_anomaly.py

Injects one deliberate, coherent supplier_delay anomaly.

UPDATED: product_id -> sku_id. Same store/supplier triple as before
(S036 / SUP07), but now targeting a specific SKU variant of P0108 --
P0108-SKU01 (size S, colour Blue) -- rather than the bare product code,
since inventory_levels/replenishment_history/supplier_delivery are all
keyed by sku_id now. Confirmed via common.py (same random seed) that this
sku_id actually exists in your local sku table.

Scenario: store S036, SKU P0108-SKU01, supplier SUP07. Supplier SUP07 has
been chronically late shipping this SKU to S036 for the last month, so
S036 has been stocked out on it for weeks.

Evidence this leaves for the agent's tools to find:
  - get_inventory_levels("P0108-SKU01", "S036")
        -> stock_on_hand = 0, stockout_flag = True, below_reorder_point = True
  - get_replenishment_history("P0108-SKU01", "S036", days=30)
        -> one order received ~23 days late and badly short-shipped, one
           order still outstanding past its expected delivery window
  - get_delivery_performance("SUP07", period=...)
        -> degradation_flag = True for last_7_days/last_30_days (severe),
           and true (barely) for last_quarter (problem is recent-onset)

NOTE: get_sales_data has no SKU parameter -- it only aggregates revenue at
the whole-store level. Skipped deliberately, same reasoning as the
original version of this script.

Run from the rod/ directory:
    python seeds/seed_anomaly.py

Safe to re-run: deletes-then-reinserts only the specific rows it owns.
"""
import sqlite3
from datetime import date, timedelta

STORE_ID = "S036"
SKU_ID = "P0108-SKU01"
SUPPLIER_ID = "SUP07"

TODAY = date.today()

INVENTORY_DB = "../mcp_server/db/inventory.db"
SUPPLIERS_DB = "../mcp_server/db/suppliers.db"


def seed_inventory_snapshot(conn: sqlite3.Connection) -> None:
    """Force the latest snapshot for SKU_ID/STORE_ID to an unambiguous stockout."""
    latest_date = conn.execute(
        "SELECT MAX(snapshot_date) FROM inventory_levels WHERE sku_id = ? AND store_id = ?",
        (SKU_ID, STORE_ID),
    ).fetchone()[0]

    if latest_date is None:
        conn.execute(
            "INSERT INTO inventory_levels (sku_id, store_id, snapshot_date, stock_on_hand, reorder_point, stockout_flag) "
            "VALUES (?, ?, ?, 0, 40, 1)",
            (SKU_ID, STORE_ID, TODAY.isoformat()),
        )
    else:
        conn.execute(
            "UPDATE inventory_levels SET stock_on_hand = 0, stockout_flag = 1 "
            "WHERE sku_id = ? AND store_id = ? AND snapshot_date = ?",
            (SKU_ID, STORE_ID, latest_date),
        )
    print(f"inventory_levels: latest snapshot for {SKU_ID}/{STORE_ID} ({latest_date or TODAY.isoformat()}) forced to stock_on_hand=0, stockout_flag=1")


def seed_replenishment_delay(conn: sqlite3.Connection) -> None:
    """Insert two recent, badly-delayed orders from SUP07 for this SKU/store."""
    window_start = (TODAY - timedelta(days=40)).isoformat()
    conn.execute(
        "DELETE FROM replenishment_history WHERE sku_id = ? AND store_id = ? AND supplier_id = ? AND order_date >= ?",
        (SKU_ID, STORE_ID, SUPPLIER_ID, window_start),
    )

    order_a = TODAY - timedelta(days=25)
    received_a = TODAY - timedelta(days=2)   # 23-day lead time vs historical ~4 days
    order_b = TODAY - timedelta(days=10)      # still outstanding -- no received_date at all

    conn.execute(
        "INSERT INTO replenishment_history (sku_id, store_id, order_date, received_date, units_ordered, units_received, supplier_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (SKU_ID, STORE_ID, order_a.isoformat(), received_a.isoformat(), 300, 180, SUPPLIER_ID),
    )
    conn.execute(
        "INSERT INTO replenishment_history (sku_id, store_id, order_date, received_date, units_ordered, units_received, supplier_id) "
        "VALUES (?, ?, ?, NULL, ?, NULL, ?)",
        (SKU_ID, STORE_ID, order_b.isoformat(), 280, SUPPLIER_ID),
    )
    print(f"replenishment_history: inserted 2 delayed/outstanding orders for {SKU_ID}/{STORE_ID} from {SUPPLIER_ID}")


def seed_supplier_degradation(conn: sqlite3.Connection) -> None:
    """91 daily supplier_delivery rows so degradation_flag comes out True
    regardless of which period the tool filters on."""
    window_start = (TODAY - timedelta(days=90)).isoformat()
    conn.execute(
        "DELETE FROM supplier_delivery WHERE supplier_id = ? AND delivery_date >= ?",
        (SUPPLIER_ID, window_start),
    )
    for age in range(0, 91):
        d = (TODAY - timedelta(days=age)).isoformat()
        if age <= 6:
            current, baseline, defect_rate = 12.0, 4.5, 0.06
        elif age <= 29:
            current, baseline, defect_rate = 10.5, 4.3, 0.055
        else:
            current, baseline, defect_rate = 6.8, 4.5, 0.045
        degradation_flag = 1 if current > 1.5 * baseline else 0
        conn.execute(
            "INSERT INTO supplier_delivery "
            "(supplier_id, sku_id, delivery_date, avg_delivery_days_current, avg_delivery_days_baseline, defect_rate, degradation_flag) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (SUPPLIER_ID, SKU_ID, d, current, baseline, defect_rate, degradation_flag),
        )
    print(f"supplier_delivery: inserted 91 daily rows for {SUPPLIER_ID} spanning {window_start} to {TODAY.isoformat()}")


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

    print(f"\nDone. Investigate with store_id='{STORE_ID}', sku='{SKU_ID}' to exercise this case.")


if __name__ == "__main__":
    main()
