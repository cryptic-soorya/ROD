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
"""

import os
from datetime import date, datetime
from decimal import Decimal
import psycopg2
import psycopg2.extras
from fastmcp import FastMCP

from mcp_server.auth_middleware import check_scope, get_token_payload
from logging_config import get_logger

logger = get_logger("mcp.sales")

mcp = FastMCP("retail-sales")

DB_DSN = os.getenv("SALES_DB_URL", os.getenv("DATABASE_URL"))

VALID_PERIODS = {"last_7_days": 7, "last_30_days": 30, "last_quarter": 90}


def _connect():
    return psycopg2.connect(DB_DSN, cursor_factory=psycopg2.extras.RealDictCursor)


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

    conn = _connect()
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
        conn.close()


@mcp.tool()
def get_stores_with_sales_decline(period: str = "last_30_days", limit: int = 5) -> dict:
    """
    Scans every store and returns the ones with the largest revenue decline, worst first.
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

    conn = _connect()
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
        conn.close()


if __name__ == "__main__":
    mcp.run()