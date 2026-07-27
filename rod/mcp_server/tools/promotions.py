"""
mcp_server/tools/promotions.py

TOOL 7: get_promotion_performance
    Required scope: read:promotions
    DB: PostgreSQL (tables: promotions.promotions, promotions.promotion_performance)
    Input:  { promo_id: str (required) }
    Output: { promo_id, sku_id, start_date, end_date, discount_pct,
              units_sold, baseline_units, actual_uplift_pct, projected_uplift_pct,
              underperformance_flag, revenue, margin_impact }
    Flag:   underperformance_flag: true when actual_uplift_pct < 0.5 × projected_uplift_pct
"""

import os
from datetime import date, datetime
from decimal import Decimal
import psycopg2
from fastmcp import FastMCP

from mcp_server.auth_middleware import check_scope, get_token_payload
from logging_config import get_logger
from db_pool import get_conn, put_conn

logger = get_logger("mcp.promotions")

mcp = FastMCP("retail-promotions")

DB_DSN = os.getenv("PROMOTIONS_DB_URL", os.getenv("DATABASE_URL"))


def _serialize(value):
    """Postgres DATE/TIMESTAMP -> ISO string, NUMERIC -> float, so every
    tool output is JSON-safe (json.dumps chokes on date/Decimal)."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _rows(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [{k: _serialize(v) for k, v in dict(r).items()} for r in cur.fetchall()]


@mcp.tool()
def get_promotion_performance(promo_id: str) -> dict:
    """
    Returns promotion performance for a given promo_id, joining the
    promotions.promotions table (schedule/discount) with promotions.promotion_performance (results).
    actual_uplift_pct = (units_sold - baseline_units) / baseline_units * 100.
    projected_uplift_pct derived from discount_pct (10% discount ~ 20% uplift assumed).
    underperformance_flag true when actual_uplift_pct < 0.5 × projected_uplift_pct.
    """
    err = check_scope(get_token_payload(), "read:promotions", tool_name="get_promotion_performance")
    if err:
        return err

    conn = get_conn(DB_DSN)
    try:
        rows = _rows(conn, """
            SELECT
                p.promo_id,
                p.sku_id,
                p.start_date,
                p.end_date,
                p.dsct_pct AS discount_pct,
                pp.units_sold,
                pp.baseline_units,
                pp.revenue,
                pp.margin_impact
            FROM promotions.promotions p
            JOIN promotions.promotion_performance pp ON pp.promo_id = p.promo_id
            WHERE p.promo_id = %s
        """, (promo_id,))
    except psycopg2.Error as e:
        logger.error(
            "promotion query failed",
            extra={"event": "db_error", "error_type": type(e).__name__},
        )
        return {"error": "DB_ERROR", "message": str(e), "tool": "get_promotion_performance"}
    finally:
        put_conn(DB_DSN, conn)

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
        "sku_id":                 r["sku_id"],
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