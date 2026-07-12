"""
seeds/seed_anomaly_returns.py

Injects one deliberate, coherent return_surge anomaly.

UPDATED:
    - product_id -> sku_id. Targets P0030-SKU01 (size XXL, colour Black) --
      confirmed via common.py to actually exist in your local sku table --
      rather than the bare product code.
    - product_listing_changes was renamed catalog_changes and relocated
      from returns.db into the merged investigations/orchestration.db.
      This script now writes to TWO separate db files instead of one:
      returns.db for return_reasons, orchestration.db for catalog_changes.

Scenario: SKU P0030-SKU01 (a real SKU whose parent product, P0030, already
has an organic wrong_size skew in returns.db's random seed data). A
listing edit to its description ~12 days ago silently dropped its sizing
guidance. Customers have been ordering their usual size and getting a
mis-fit, so wrong_size returns have spiked since.

Evidence this leaves for the agent's tools to find:
  - get_product_listing_changes("P0030-SKU01", since=<~30 days ago>)
        -> most recent change is field_changed="description", dated ~12
           days ago, sizing guidance removed.
  - get_return_reasons("P0030-SKU01", days=14 or 30)
        -> reason_code="wrong_size" totals ~180 units across ~25 return
           records in the last 10 days, easily clearing low_sample_warning.

Root cause / confidence rationale: two independently-confirming signals
(a listing edit predating the spike, and a reason-code breakdown
overwhelmingly wrong_size after that edit) support return_surge at
confidence 0.85-1.0.

Run from the rod/ directory:
    python seeds/seed_anomaly_returns.py

Safe to re-run: deletes-then-reinserts only the specific rows it owns.
"""
import sqlite3
from datetime import date, timedelta

SKU_ID = "P0030-SKU01"

RETURNS_DB = "../mcp_server/db/returns.db"
ORCHESTRATION_DB = "../investigations/orchestration.db"

TODAY = date.today()


def seed_listing_change(conn: sqlite3.Connection) -> None:
    """Insert the description edit that removed sizing guidance, ~12 days ago.
    Writes to catalog_changes in the merged orchestration.db now, not returns.db."""
    window_start = (TODAY - timedelta(days=20)).isoformat()
    conn.execute(
        "DELETE FROM catalog_changes WHERE sku_id = ? AND field_changed = 'description' AND change_date >= ?",
        (SKU_ID, window_start),
    )
    change_date = (TODAY - timedelta(days=12)).isoformat()
    conn.execute(
        "INSERT INTO catalog_changes (sku_id, change_date, field_changed, old_value, new_value, changed_by) "
        "VALUES (?, ?, 'description', ?, ?, ?)",
        (
            SKU_ID,
            change_date,
            "Fits true to size — see size chart for details.",
            "Updated product description; size chart guidance removed pending revision.",
            "content_team",
        ),
    )
    print(f"catalog_changes: inserted description edit for {SKU_ID} on {change_date} (sizing guidance removed)")


def seed_return_spike(conn: sqlite3.Connection) -> None:
    """Insert ~25 wrong_size return records in the 10 days after the listing edit."""
    window_start = (TODAY - timedelta(days=11)).isoformat()
    conn.execute(
        "DELETE FROM return_reasons WHERE sku_id = ? AND reason_code = 'wrong_size' AND return_date >= ?",
        (SKU_ID, window_start),
    )
    rows = []
    total_units = 0
    for i in range(25):
        return_date = (TODAY - timedelta(days=10 - (i % 10))).isoformat()
        units_returned = 5 + (i % 4)  # 5-8 units per record
        sample_size = 60
        total_units += units_returned
        rows.append((
            SKU_ID, return_date, "wrong_size",
            "Customer said sizing ran small/large vs chart", units_returned, sample_size,
        ))
    conn.executemany(
        "INSERT INTO return_reasons (sku_id, return_date, reason_code, reason_text, units_returned, sample_size) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    print(f"return_reasons: inserted {len(rows)} wrong_size records for {SKU_ID} totaling {total_units} units over the last 10 days")


def main() -> None:
    orch_conn = sqlite3.connect(ORCHESTRATION_DB)
    try:
        seed_listing_change(orch_conn)
        orch_conn.commit()
    finally:
        orch_conn.close()

    ret_conn = sqlite3.connect(RETURNS_DB)
    try:
        seed_return_spike(ret_conn)
        ret_conn.commit()
    finally:
        ret_conn.close()

    print(f"\nDone. Investigate with sku='{SKU_ID}' to exercise this return_surge case.")


if __name__ == "__main__":
    main()
