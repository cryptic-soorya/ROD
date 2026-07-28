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

from typing import Optional

from mcp_server.auth_middleware import (
    check_scope,
    get_token_payload,
    require_store_access,
    resolve_scoped_store_id,
)
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
                p.store_id,
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

    err = require_store_access(r["store_id"], tool_name="get_promotion_performance")
    if err:
        return err

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
        "store_id":               r["store_id"],
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


@mcp.tool()
def get_underperforming_promotions(
    store_id: Optional[str] = None, period_days: int = 30, limit: int = 5
) -> dict:
    """
    Scans promotions ending within the last period_days and returns the ones
    flagged as underperforming (actual_uplift_pct < 0.5 x projected_uplift_pct),
    worst first. Use this to discover which promotion is behind an anomaly when
    the promo_id isn't already known — otherwise get_promotion_performance
    requires a promo_id you don't have yet.
    store_id: optional — omit to scan every store's promotions, or pass a
    store to scan just that store's.
    period_days: how many days back a promotion must have ended to be included (default 30).
    limit: max number of promotions to return (1-15, default 5).
    """
    err = check_scope(get_token_payload(), "read:promotions", tool_name="get_underperforming_promotions")
    if err:
        return err

    store_id, err = resolve_scoped_store_id(store_id, tool_name="get_underperforming_promotions")
    if err:
        return err

    limit = min(max(limit, 1), 15)
    period_days = max(1, min(period_days, 365))

    conn = get_conn(DB_DSN)
    try:
        store_clause = "AND p.store_id = %s" if store_id is not None else ""
        params = (period_days,) + ((store_id,) if store_id is not None else ())
        rows = _rows(conn, f"""
            SELECT
                p.promo_id,
                p.sku_id,
                p.store_id,
                p.end_date,
                p.dsct_pct AS discount_pct,
                pp.units_sold,
                pp.baseline_units
            FROM promotions.promotions p
            JOIN promotions.promotion_performance pp ON pp.promo_id = p.promo_id
            WHERE p.end_date::date >= CURRENT_DATE - (%s || ' days')::interval
              {store_clause}
        """, params)
    except psycopg2.Error as e:
        logger.error(
            "underperforming promotions scan failed",
            extra={"event": "db_error", "error_type": type(e).__name__},
        )
        return {"error": "DB_ERROR", "message": str(e), "tool": "get_underperforming_promotions"}
    finally:
        put_conn(DB_DSN, conn)

    underperforming = []
    for r in rows:
        baseline = r["baseline_units"]
        units_sold = r["units_sold"]
        discount_pct = r["discount_pct"]

        if not baseline or baseline <= 0 or discount_pct is None:
            continue

        actual_uplift_pct = round((units_sold - baseline) / baseline * 100, 2)
        projected_uplift_pct = round(discount_pct * 2, 2)

        if actual_uplift_pct < 0.5 * projected_uplift_pct:
            underperforming.append({
                "promo_id": r["promo_id"],
                "sku_id": r["sku_id"],
                "store_id": r["store_id"],
                "end_date": r["end_date"],
                "actual_uplift_pct": actual_uplift_pct,
                "projected_uplift_pct": projected_uplift_pct,
                "shortfall_pct": round(projected_uplift_pct - actual_uplift_pct, 2),
            })

    underperforming.sort(key=lambda p: p["shortfall_pct"], reverse=True)

    return {
        "store_id": store_id,
        "period_days": period_days,
        "promotions": underperforming[:limit],
        "tool": "get_underperforming_promotions",
    }


if __name__ == "__main__":
    mcp.run()