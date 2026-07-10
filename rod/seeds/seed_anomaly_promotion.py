"""
seeds/seed_anomaly_promotion.py

Injects one deliberate, coherent PROMOTION_UNDERPERFORM anomaly, following
the same convention as seed_anomaly.py (SUP07/S036/P0108 -> supplier_delay).
The base random seed data has no engineered promotion_underperform signal —
see CLAUDE.md's "Seeded anomalies" section.

Scenario: product P0022 (a real product already present in promotions.db's
random seed data — it organically has 27 prior promotions, several of them
healthy: e.g. PROMO01778 ran a 25% discount and hit ~58% actual uplift
against a ~50% projected uplift, i.e. it did NOT trip underperformance_flag.
That existing history is the "vs. its own track record" contrast — this
script does not touch or fabricate it).

    A new, steeply-discounted promotion (50% off) for P0022 barely moved
    units at all — it looks like the discount was applied to inventory
    nobody wanted rather than genuine new demand.

Evidence this leaves for the agent's tools to find:
  - get_promotion_performance("PROMO-ANOM-P0022")
        -> discount_pct=50.0, baseline_units=150, units_sold=160
           -> actual_uplift_pct ~= 6.7%, projected_uplift_pct = 100.0
              (per mcp_server/tools/promotions.py's discount_pct * 2 rule)
           -> underperformance_flag = True (6.7% << 0.5 x 100% = 50%)
           -> margin_impact is negative: the discount cost more than the
              (nearly nonexistent) extra units sold recovered.
  - get_promotion_performance() called again against any of P0022's other,
    organic promo_ids (e.g. "PROMO01778") shows a healthy uplift for the
    same product at a comparable discount tier, ruling out "P0022 just
    doesn't respond to promotions" as an alternative explanation.

Root cause / confidence rationale: the flagged promo's own
underperformance_flag plus the same-product historical contrast are two
independent pieces of evidence (one promo_id's numbers, and a comparison
across promo_ids for the same product) supporting promotion_underperform
at confidence 0.85-1.0 per agent/prompts.py's rubric.

NOTE: promotion_performance has no store_id column, and get_sales_data is
store-level only with no SKU parameter (see seed_anomaly.py's own note on
this same constraint) — there is no way to cross-reference a specific promo
against store-level sales data with the current schema, so this scenario
relies on get_promotion_performance alone, called against multiple promo_ids
for the same product, rather than a second tool.

Run from the rod/ directory, same convention as the other seeds/*.py:
    python seeds/seed_anomaly_promotion.py

Safe to re-run: deletes-then-reinserts only the one engineered promo_id it
owns (a dedicated "PROMO-ANOM-" prefix that can't collide with the
organic 5-digit "PROMOxxxxx" ids) rather than touching anything else.
"""
import sqlite3
from datetime import date, timedelta

PRODUCT_ID = "P0022"
PROMO_ID = "PROMO-ANOM-P0022"

PROMOTIONS_DB = "mcp_server/db/promotions.db"

TODAY = date.today()


def seed_underperforming_promo(conn: sqlite3.Connection) -> None:
    """Insert one steeply-discounted, barely-lifted promo for P0022.
    underperformance_flag = actual_uplift_pct < 0.5 x projected_uplift_pct
    (mcp_server/tools/promotions.py); projected_uplift_pct = discount_pct x 2."""
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
        "(promo_id, product_id, start_date, end_date, discount_pct, units_sold, revenue, baseline_units, margin_impact) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (PROMO_ID, PRODUCT_ID, start_date, end_date, discount_pct, units_sold, revenue, baseline_units, margin_impact),
    )
    print(
        f"promotion_performance: inserted {PROMO_ID} for {PRODUCT_ID} "
        f"({discount_pct}% off, {baseline_units}->{units_sold} units, margin_impact={margin_impact})"
    )


def main() -> None:
    conn = sqlite3.connect(PROMOTIONS_DB)
    try:
        seed_underperforming_promo(conn)
        conn.commit()
    finally:
        conn.close()

    print(f"\nDone. Investigate promo_id='{PROMO_ID}' (product {PRODUCT_ID}) to exercise this promotion_underperform case.")


if __name__ == "__main__":
    main()
