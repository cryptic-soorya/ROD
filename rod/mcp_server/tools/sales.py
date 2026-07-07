"""
mcp_server/tools/sales.py
OWNER: Teammate D

TOOL 1: get_sales_data
    Required scope: read:sales
    DB: mcp_server/db/sales.db
    Input:  { store_id: str (required), period: str (optional, default last_30_days) }
    Output: { store_id, period, revenue_current_period, revenue_previous_period, change_pct }
    Error:  { error: STORE_NOT_FOUND, message, tool }
    change_pct formula: ((current - previous) / previous) × 100, rounded to 1 decimal
"""

import os
import sqlite3
from pathlib import Path
from fastmcp import FastMCP

from mcp_server.auth_middleware import check_scope, get_token_payload
from logging_config import get_logger

logger = get_logger("mcp.sales")

mcp = FastMCP("retail-sales")

BASE_DIR = Path(__file__).resolve().parent.parent
DB = os.getenv("SALES_DB_PATH", str(BASE_DIR / "db" / "sales.db"))

VALID_PERIODS = {"last_7_days": 7, "last_30_days": 30, "last_quarter": 90}

def _connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def _rows(conn, sql, params=()):
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


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

    try:
        conn = _connect()

        # current period
        current_rows = _rows(conn, """
            SELECT COALESCE(SUM(revenue), 0) AS revenue
            FROM sales
            WHERE store_id = ?
              AND DATE(sale_date) >= DATE('now', ?)
        """, (store_id, f"-{days} days"))

        # previous period (same length, immediately before current)
        previous_rows = _rows(conn, """
            SELECT COALESCE(SUM(revenue), 0) AS revenue
            FROM sales
            WHERE store_id = ?
              AND DATE(sale_date) >= DATE('now', ?)
              AND DATE(sale_date) <  DATE('now', ?)
        """, (store_id, f"-{days * 2} days", f"-{days} days"))

        current  = current_rows[0]["revenue"]
        previous = previous_rows[0]["revenue"]

        # check store exists at all
        exists = _rows(conn, "SELECT 1 FROM sales WHERE store_id = ? LIMIT 1", (store_id,))
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

    except sqlite3.Error as e:
        logger.error(
            "sales query failed",
            extra={"event": "db_error", "error_type": type(e).__name__},
        )
        return {"error": "DB_ERROR", "message": str(e), "tool": "get_sales_data"}


if __name__ == "__main__":
    mcp.run()