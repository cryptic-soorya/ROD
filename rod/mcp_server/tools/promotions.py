"""
mcp_server/tools/promotions.py

TOOL 7: get_promotion_performance
    Required scope: read:promotions
    DB: mcp_server/db/promotions.db
    Input:  { promo_id: str (required) }
    Output: { promo_id, sku, target_segment, start_date, end_date,
              projected_uplift_pct, actual_uplift_pct, underperformance_flag }
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
    underperformance_flag is true when actual_uplift_pct < 0.5 × projected_uplift_pct.
    Uses uplift_percent from DB as actual_uplift_pct and derives projected from target_sales/actual_sales.
    """
    conn = _connect()

    rows = _rows(conn, """
        SELECT
            promo_id,
            promo_name,
            start_date,
            end_date,
            target_sales,
            actual_sales,
            uplift_percent                                              AS actual_uplift_pct,
            -- derive projected uplift pct from target vs actual sales
            CASE
                WHEN target_sales = 0 THEN NULL
                ELSE ROUND((target_sales - actual_sales) * 100.0 / target_sales, 2)
            END                                                         AS projected_uplift_pct,
            status
        FROM Promotion_Performance
        WHERE promo_id = ?
    """, (promo_id,))

    if not rows:
        return {
            "promo_id": promo_id,
            "error": f"No promotion found with promo_id '{promo_id}'",
        }

    r = rows[0]

    actual_uplift    = r["actual_uplift_pct"]
    projected_uplift = r["projected_uplift_pct"]

    underperformance_flag = (
        actual_uplift is not None and
        projected_uplift is not None and
        actual_uplift < 0.5 * projected_uplift
    )

    return {
        "promo_id":               r["promo_id"],
        "promo_name":             r["promo_name"],
        "start_date":             r["start_date"],
        "end_date":               r["end_date"],
        "target_sales":           r["target_sales"],
        "actual_sales":           r["actual_sales"],
        "projected_uplift_pct":   projected_uplift,
        "actual_uplift_pct":      actual_uplift,
        "underperformance_flag":  underperformance_flag,
        "status":                 r["status"],
    }


if __name__ == "__main__":
    mcp.run()
