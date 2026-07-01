"""
mcp_server/tools/promotions.py

TOOL 7: get_promotion_performance
    Required scope: read:promotions
    DB: mcp_server/db/promotions.db
    Input:  { promo_id: str (required) }
    Output: { promo_id, product_id, start_date, end_date, discount_pct,
              units_sold, baseline_units, actual_uplift_pct, projected_uplift_pct,
              underperformance_flag, revenue, margin_impact }
    Flag:   underperformance_flag: true when actual_uplift_pct < 0.5 × projected_uplift_pct
"""

import os
import sqlite3
from pathlib import Path
from fastmcp import FastMCP

mcp = FastMCP("retail-promotions")

BASE_DIR = Path(__file__).resolve().parent.parent
DB = os.getenv("PROMOTIONS_DB_PATH", str(BASE_DIR / "db" / "promotions.db"))

def _connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def _rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


@mcp.tool()
def get_promotion_performance(promo_id: str) -> dict:
    """
    Returns promotion performance for a given promo_id.
    actual_uplift_pct = (units_sold - baseline_units) / baseline_units * 100.
    projected_uplift_pct derived from discount_pct (10% discount ~ 20% uplift assumed).
    underperformance_flag true when actual_uplift_pct < 0.5 × projected_uplift_pct.
    """
    conn = _connect()

    rows = _rows(conn, """
        SELECT
            promo_id,
            product_id,
            start_date,
            end_date,
            discount_pct,
            units_sold,
            baseline_units,
            revenue,
            margin_impact
        FROM promotion_performance
        WHERE promo_id = ?
    """, (promo_id,))

    if not rows:
        return {
            "promo_id": promo_id,
            "error": f"No promotion found with promo_id '{promo_id}'",
        }

    r = rows[0]

    baseline = r["baseline_units"]
    units_sold = r["units_sold"]

    actual_uplift_pct = (
        round((units_sold - baseline) / baseline * 100, 2)
        if baseline and baseline > 0 else None
    )

    # projected uplift: industry rule of thumb — each 10% discount drives ~20% uplift
    projected_uplift_pct = (
        round(r["discount_pct"] * 2, 2)
        if r["discount_pct"] is not None else None
    )

    underperformance_flag = (
        actual_uplift_pct is not None and
        projected_uplift_pct is not None and
        actual_uplift_pct < 0.5 * projected_uplift_pct
    )

    return {
        "promo_id":               r["promo_id"],
        "product_id":             r["product_id"],
        "start_date":             r["start_date"],
        "end_date":               r["end_date"],
        "discount_pct":           r["discount_pct"],
        "units_sold":             units_sold,
        "baseline_units":         baseline,
        "revenue":                r["revenue"],
        "margin_impact":          r["margin_impact"],
        "actual_uplift_pct":      actual_uplift_pct,
        "projected_uplift_pct":   projected_uplift_pct,
        "underperformance_flag":  underperformance_flag,
    }


if __name__ == "__main__":
    mcp.run()