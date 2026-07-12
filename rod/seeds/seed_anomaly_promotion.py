"""
seeds/seed_anomaly_promotion.py

Injects one deliberate, coherent promotion_underperform anomaly.

UPDATED: product_id -> sku_id. Targets P0022-SKU01 (size XXL, colour
Blue) -- confirmed via common.py to actually exist in your local sku
table.

Scenario: a new, steeply-discounted promotion (50% off) for this SKU
barely moved units at all -- it looks like the discount was applied to
inventory nobody wanted rather than genuine new demand.

Evidence this leaves for the agent's tools to find:
  - get_promotion_performance("PROMO-ANOM-P0022")
        -> discount_pct=50.0, baseline_units=150, units_sold=160
           -> actual_uplift_pct ~= 6.7%, projected_uplift_pct = 100.0
           -> underperformance_flag = True (6.7% << 0.5 x 100% = 50%)
           -> margin_impact is negative.
  - get_promotion_performance() called again against any of this SKU's
    other organic promo_ids shows a healthy uplift at a comparable
    discount tier, ruling out "this SKU just doesn't respond to
    promotions" as an alternative explanation.

Root cause / confidence rationale: the flagged promo's own
underperformance_flag plus the same-SKU historical contrast are two
independent pieces of evidence supporting promotion_underperform at
confidence 0.85-1.0.

Run from the rod/ directory:
    python seeds/seed_anomaly_promotion.py

Safe to re-run: deletes-then-reinserts only the one engineered promo_id
it owns (a dedicated "PROMO-ANOM-" prefix that can't collide with the
organic 5-digit "PROMOxxxxx" ids).
"""
import sqlite3
from datetime import date, timedelta

SKU_ID = "P0022-SKU01"
PROMO_ID = "PROMO-ANOM-P0022"

PROMOTIONS_DB = "../mcp_server/db/promotions.db"

TODAY = date.today()


def seed_underperforming_promo(conn: sqlite3.Connection) -> None:
    """Insert one steeply-discounted, barely-lifted promo for this SKU.
    underperformance_flag = actual_uplift_pct < 0.5 x projected_uplift_pct;
    projected_uplift_pct = discount_pct x 2 (per promotions.py's rule)."""
    conn.execute("DELETE FROM promotion_performance WHERE promo_id = ?", (PROMO_ID,))

    start_date = (TODAY - timedelta(days=20)).isoformat()
    end_date = (TODAY - timedelta(days=5)).isoformat()
    discount_pct = 50.0
    baseline_units = 150
    units_sold = 160  # actual_uplift_pct ~= 6.7%, projected = 100.0 -> flag True
    price = 45.0
    revenue = round(units_sold * price * (1 - discount_pct / 100), 2)
    cost_per_unit = round(price * 0.55, 2)
    margin_impact = round(revenue - (units_sold * cost_per_unit), 2)  # negative

    conn.execute(
        "INSERT INTO promotion_performance "
        "(promo_id, sku_id, start_date, end_date, discount_pct, units_sold, revenue, baseline_units, margin_impact) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (PROMO_ID, SKU_ID, start_date, end_date, discount_pct, units_sold, revenue, baseline_units, margin_impact),
    )
    print(
        f"promotion_performance: inserted {PROMO_ID} for {SKU_ID} "
        f"({discount_pct}% off, {baseline_units}->{units_sold} units, margin_impact={margin_impact})"
    )


def main() -> None:
    conn = sqlite3.connect(PROMOTIONS_DB)
    try:
        seed_underperforming_promo(conn)
        conn.commit()
    finally:
        conn.close()

    print(f"\nDone. Investigate promo_id='{PROMO_ID}' (sku {SKU_ID}) to exercise this promotion_underperform case.")


if __name__ == "__main__":
    main()
