"""
seeds/seed_anomaly_returns.py

Injects one deliberate, coherent RETURN_SURGE anomaly, following the same
convention as seed_anomaly.py (SUP07/S036/P0108 -> supplier_delay). The base
random seed data has no engineered return_surge signal — see CLAUDE.md's
"Seeded anomalies" section.

Scenario: product P0030 (a real product already present in returns.db's
random seed data — organically has 152/344 = 44% of its historical returns
coded wrong_size, so this is a plausible product to have a fit/sizing
problem, not an arbitrary pick).

    A listing edit to P0030's description ~12 days ago silently dropped its
    sizing guidance. Customers have been ordering their usual size and
    getting a mis-fit, so wrong_size returns have spiked since.

Evidence this leaves for the agent's tools to find:
  - get_product_listing_changes("P0030", since=<~30 days ago>)
        -> most recent change is field_changed="description", dated ~12
           days ago, old_value referencing accurate sizing guidance,
           new_value with that guidance removed.
  - get_return_reasons("P0030", days=14 or 30)
        -> reason_code="wrong_size" now totals ~180 units across ~25 return
           records in the last 10 days alone (organic baseline for this
           window was only 8 units — see investigation notes), so
           wrong_size dominates the reasons breakdown for the period,
           easily clearing low_sample_warning (total_returns >> 10).

Root cause / confidence rationale: two independently-confirming signals
(a listing edit that predates the spike, and a reason-code breakdown that
is overwhelmingly wrong_size after that edit) support return_surge at
confidence 0.85-1.0 per agent/prompts.py's rubric ("multiple independent
pieces of evidence directly confirm the cause").

NOTE: get_return_reasons and get_product_listing_changes take a sku/since
but no store_id — this is a product-wide signal, not scoped to one store,
matching how the live tool contracts actually work.

Run from the rod/ directory, same convention as the other seeds/*.py:
    python seeds/seed_anomaly_returns.py

Safe to re-run: deletes-then-reinserts only the specific rows it owns
(scoped by product_id + reason_code / field_changed, and a recent date
window) rather than touching anything else.
"""
import sqlite3
from datetime import date, timedelta

PRODUCT_ID = "P0030"

RETURNS_DB = "mcp_server/db/returns.db"

TODAY = date.today()


def seed_listing_change(conn: sqlite3.Connection) -> None:
    """Insert the description edit that removed sizing guidance, ~12 days ago."""
    window_start = (TODAY - timedelta(days=20)).isoformat()
    conn.execute(
        "DELETE FROM product_listing_changes WHERE product_id = ? AND field_changed = 'description' AND change_date >= ?",
        (PRODUCT_ID, window_start),
    )
    change_date = (TODAY - timedelta(days=12)).isoformat()
    conn.execute(
        "INSERT INTO product_listing_changes (product_id, change_date, field_changed, old_value, new_value, changed_by) "
        "VALUES (?, ?, 'description', ?, ?, ?)",
        (
            PRODUCT_ID,
            change_date,
            "Fits true to size — see size chart for details.",
            "Updated product description; size chart guidance removed pending revision.",
            "content_team",
        ),
    )
    print(f"product_listing_changes: inserted description edit for {PRODUCT_ID} on {change_date} (sizing guidance removed)")


def seed_return_spike(conn: sqlite3.Connection) -> None:
    """Insert ~25 wrong_size return records in the 10 days after the listing edit,
    dominating the reason breakdown for any 14- or 30-day lookback window."""
    window_start = (TODAY - timedelta(days=11)).isoformat()
    conn.execute(
        "DELETE FROM return_reasons WHERE product_id = ? AND reason_code = 'wrong_size' AND return_date >= ?",
        (PRODUCT_ID, window_start),
    )
    rows = []
    total_units = 0
    for i in range(25):
        return_date = (TODAY - timedelta(days=10 - (i % 10))).isoformat()
        units_returned = 5 + (i % 4)  # 5-8 units per record
        sample_size = 60
        total_units += units_returned
        rows.append((
            PRODUCT_ID, return_date, "wrong_size",
            "Customer said sizing ran small/large vs chart", units_returned, sample_size,
        ))
    conn.executemany(
        "INSERT INTO return_reasons (product_id, return_date, reason_code, reason_text, units_returned, sample_size) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    print(f"return_reasons: inserted {len(rows)} wrong_size records for {PRODUCT_ID} totaling {total_units} units over the last 10 days")


def main() -> None:
    conn = sqlite3.connect(RETURNS_DB)
    try:
        seed_listing_change(conn)
        seed_return_spike(conn)
        conn.commit()
    finally:
        conn.close()

    print(f"\nDone. Investigate with sku='{PRODUCT_ID}' to exercise this return_surge case.")


if __name__ == "__main__":
    main()
