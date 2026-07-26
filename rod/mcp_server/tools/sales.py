"""
mcp_server/tools/sales.py

TOOL 1: get_sales_data
    Required scope: read:sales
    DB: PostgreSQL (table: sales.sales)
    Input:  { store_id: str (required), period: str (optional, default last_30_days) }
    Output: { store_id, period, revenue_current_period, revenue_previous_period, change_pct }
    Error:  { error: STORE_NOT_FOUND, message, tool }
    change_pct formula: ((current - previous) / previous) × 100, rounded to 1 decimal

TOOL 1b: get_stores_with_sales_decline
    Required scope: read:sales
    DB: PostgreSQL (table: sales.sales)
    Input:  { period: str (optional, default last_30_days), limit: int (optional, 1-15, default 5) }
    Output: { period, stores: [{ store_id, revenue_current_period, revenue_previous_period, change_pct }, ...] }

TOOL 1c: get_stores_with_sku_decline
    Required scopes: read:sales, read:inventory (cross-schema: sales.sales + inventory.inventory)
    Input:  { sku_id: str (required), period: str (optional, default last_30_days), limit: int (optional, 1-15, default 5) }
    Output: { sku, period, stores: [{ store_id, revenue_current_period, revenue_previous_period, change_pct }, ...] }
    Use this instead of get_stores_with_sales_decline when the SKU is already known — it scopes the
    scan to stores that actually carry the SKU (per inventory.inventory), so downstream
    get_inventory_levels calls don't waste an iteration on a store that never stocked it.
"""

import os
from datetime import date, datetime
from decimal import Decimal
import psycopg2
from fastmcp import FastMCP

from mcp_server.auth_middleware import check_scope, get_token_payload
from logging_config import get_logger
from db_pool import get_conn, put_conn

logger = get_logger("mcp.sales")

mcp = FastMCP("retail-sales")

DB_DSN = os.getenv("SALES_DB_URL", os.getenv("DATABASE_URL"))

VALID_PERIODS = {"last_7_days": 7, "last_30_days": 30, "last_quarter": 90}


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
        return [{k: _serialize(v) for k, v in dict(row).items()} for row in cur.fetchall()]


@mcp.tool()
def get_sales_data(store_id: str, period: str = "last_30_days") -> dict:
    """
    Returns sales revenue for a store comparing current vs previous period.
    period: last_7_days | last_30_days | last_quarter (default: last_30_days).
    change_pct = ((current - previous) / previous) × 100, rounded to 1 decimal.
    """
    err = check_scope(get_token_payload(), "read:sales", tool_name="get_sales_data")
    if err:
        return err

    if period not in VALID_PERIODS:
        return {
            "error": "INVALID_PERIOD",
            "message": f"period must be one of: {', '.join(VALID_PERIODS)}",
            "tool": "get_sales_data",
        }

    days = VALID_PERIODS[period]

    conn = get_conn(DB_DSN)
    try:
        # current period
        current_rows = _rows(conn, """
            SELECT COALESCE(SUM(total_price), 0) AS revenue
            FROM sales.sales
            WHERE store_id = %s
              AND sale_date::date >= CURRENT_DATE - (%s || ' days')::interval
        """, (store_id, days))

        # previous period (same length, immediately before current)
        previous_rows = _rows(conn, """
            SELECT COALESCE(SUM(total_price), 0) AS revenue
            FROM sales.sales
            WHERE store_id = %s
              AND sale_date::date >= CURRENT_DATE - (%s || ' days')::interval
              AND sale_date::date <  CURRENT_DATE - (%s || ' days')::interval
        """, (store_id, days * 2, days))

        current  = current_rows[0]["revenue"]
        previous = previous_rows[0]["revenue"]

        # check store exists at all
        exists = _rows(conn, "SELECT 1 FROM sales.sales WHERE store_id = %s LIMIT 1", (store_id,))
        if not exists:
            return {
                "error": "STORE_NOT_FOUND",
                "message": f"No sales data found for store '{store_id}'.",
                "tool": "get_sales_data",
            }

        change_pct = (
            None if previous in (None, 0)
            else round(((current - previous) / previous) * 100, 1)
        )

        return {
            "store_id": store_id,
            "period": period,
            "revenue_current_period": round(current, 2),
            "revenue_previous_period": round(previous, 2),
            "change_pct": change_pct,
        }

    except psycopg2.Error as e:
        logger.error(
            "sales query failed",
            extra={"event": "db_error", "error_type": type(e).__name__},
        )
        return {"error": "DB_ERROR", "message": str(e), "tool": "get_sales_data"}
    finally:
        put_conn(DB_DSN, conn)


@mcp.tool()
def get_stores_with_sales_decline(period: str = "last_30_days", limit: int = 5) -> dict:
    """
    Scans every store and returns the ones with the largest revenue decline, worst first.
    This is store-wide and has no knowledge of any particular SKU. If you already have a
    SKU in hand, use get_stores_with_sku_decline instead — it scopes the scan to stores
    that actually carry that SKU, which this tool cannot do.
    period: last_7_days | last_30_days | last_quarter (default: last_30_days).
    limit: max number of stores to return (1-15, default 5).
    """
    err = check_scope(get_token_payload(), "read:sales", tool_name="get_stores_with_sales_decline")
    if err:
        return err

    if period not in VALID_PERIODS:
        return {
            "error": "INVALID_PERIOD",
            "message": f"period must be one of: {', '.join(VALID_PERIODS)}",
            "tool": "get_stores_with_sales_decline",
        }

    limit = min(max(limit, 1), 15)
    days = VALID_PERIODS[period]

    conn = get_conn(DB_DSN)
    try:
        rows = _rows(conn, """
            SELECT store_id,
                   COALESCE(SUM(CASE
                       WHEN sale_date::date >= CURRENT_DATE - (%s || ' days')::interval
                       THEN total_price ELSE 0
                   END), 0) AS current,
                   COALESCE(SUM(CASE
                       WHEN sale_date::date >= CURRENT_DATE - (%s || ' days')::interval
                        AND sale_date::date <  CURRENT_DATE - (%s || ' days')::interval
                       THEN total_price ELSE 0
                   END), 0) AS previous
            FROM sales.sales
            GROUP BY store_id
        """, (days, days * 2, days))

        declines = []
        for row in rows:
            current, previous = row["current"], row["previous"]
            if not previous:
                continue
            change_pct = round(((current - previous) / previous) * 100, 1)
            if change_pct < 0:
                declines.append({
                    "store_id": row["store_id"],
                    "revenue_current_period": round(current, 2),
                    "revenue_previous_period": round(previous, 2),
                    "change_pct": change_pct,
                })

        declines.sort(key=lambda s: s["change_pct"])

        return {
            "period": period,
            "stores": declines[:limit],
            "tool": "get_stores_with_sales_decline",
        }

    except psycopg2.Error as e:
        logger.error(
            "sales decline scan failed",
            extra={"event": "db_error", "error_type": type(e).__name__},
        )
        return {"error": "DB_ERROR", "message": str(e), "tool": "get_stores_with_sales_decline"}
    finally:
        put_conn(DB_DSN, conn)


@mcp.tool()
def get_stores_with_sku_decline(sku_id: str, period: str = "last_30_days", limit: int = 5) -> dict:
    """
    Finds stores that currently carry the given SKU (per inventory.inventory) and returns
    the ones with the largest revenue decline for that SKU, worst first.

    Prefer this over get_stores_with_sales_decline when you already know the SKU — it
    scopes the scan to stores that actually stock it, so a subsequent get_inventory_levels
    call won't land on a store that returns "no inventory record found".

    period: last_7_days | last_30_days | last_quarter (default: last_30_days).
    limit: max number of stores to return (1-15, default 5).
    """
    payload = get_token_payload()
    err = check_scope(payload, "read:sales", tool_name="get_stores_with_sku_decline")
    if err:
        return err
    err = check_scope(payload, "read:inventory", tool_name="get_stores_with_sku_decline")
    if err:
        return err

    if period not in VALID_PERIODS:
        return {
            "error": "INVALID_PERIOD",
            "message": f"period must be one of: {', '.join(VALID_PERIODS)}",
            "tool": "get_stores_with_sku_decline",
        }

    limit = min(max(limit, 1), 15)
    days = VALID_PERIODS[period]

    conn = get_conn(DB_DSN)
    try:
        # Stores that actually carry this SKU, per inventory — this is the set
        # we scope the decline scan to, rather than blindly scanning every store.
        carrying = _rows(conn, """
            SELECT DISTINCT store_id
            FROM inventory.inventory
            WHERE sku_id = %s
        """, (sku_id,))
        store_ids = [r["store_id"] for r in carrying]

        if not store_ids:
            return {
                "sku": sku_id,
                "period": period,
                "stores": [],
                "message": f"No stores currently carry SKU '{sku_id}' per inventory records.",
                "tool": "get_stores_with_sku_decline",
            }

        rows = _rows(conn, """
            SELECT store_id,
                   COALESCE(SUM(CASE
                       WHEN sale_date::date >= CURRENT_DATE - (%s || ' days')::interval
                       THEN total_price ELSE 0
                   END), 0) AS current,
                   COALESCE(SUM(CASE
                       WHEN sale_date::date >= CURRENT_DATE - (%s || ' days')::interval
                        AND sale_date::date <  CURRENT_DATE - (%s || ' days')::interval
                       THEN total_price ELSE 0
                   END), 0) AS previous
            FROM sales.sales
            WHERE sku_id = %s
              AND store_id = ANY(%s)
            GROUP BY store_id
        """, (days, days * 2, days, sku_id, store_ids))

        declines = []
        for row in rows:
            current, previous = row["current"], row["previous"]
            if not previous:
                continue
            change_pct = round(((current - previous) / previous) * 100, 1)
            if change_pct < 0:
                declines.append({
                    "store_id": row["store_id"],
                    "revenue_current_period": round(current, 2),
                    "revenue_previous_period": round(previous, 2),
                    "change_pct": change_pct,
                })

        declines.sort(key=lambda s: s["change_pct"])

        return {
            "sku": sku_id,
            "period": period,
            "stores": declines[:limit],
            "tool": "get_stores_with_sku_decline",
        }

    except psycopg2.Error as e:
        logger.error(
            "sku decline scan failed",
            extra={"event": "db_error", "error_type": type(e).__name__},
        )
        return {"error": "DB_ERROR", "message": str(e), "tool": "get_stores_with_sku_decline"}
    finally:
        put_conn(DB_DSN, conn)


if __name__ == "__main__":
    mcp.run()