"""
mcp_server/tools/sales.py
OWNER: Teammate D

TOOL 1: get_sales_data
    Required scope: read:sales
    DB: mcp_server/db/sales.db
    Input:  { store_id: str (required), period: str (optional, default last_30_days) }
    Output: { store_id, period, revenue_current_period, revenue_previous_period, change_pct }
    Error:  { error: STORE_NOT_FOUND, message, tool } — structured dict, never raise exception

    change_pct formula: ((current - previous) / previous) × 100, rounded to 1 decimal
"""

import os
import sqlite3
from pathlib import Path
from fastmcp import FastMCP

mcp = FastMCP("retail-sales")

BASE_DIR = Path(__file__).resolve().parent.parent
DB = os.getenv("SALES_DB_PATH", str(BASE_DIR / "db" / "sales.db"))


def _connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def _rows(conn, sql, params=()):
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


@mcp.tool()
def get_sales_data(store_id: str, period: str = "last_30_days") -> dict:
    """
    Returns sales revenue for a store in the requested period.
    change_pct is rounded to 1 decimal and uses the requested business formula.
    """
    try:
        conn = _connect()
        rows = _rows(conn, """
            SELECT
                store_id,
                period,
                revenue_current_period,
                revenue_previous_period
            FROM store_sales
            WHERE store_id = ?
              AND period = ?
        """, (store_id, period))

        if not rows:
            return {
                "error": "STORE_NOT_FOUND",
                "message": f"No sales data found for store '{store_id}' and period '{period}'.",
                "tool": "get_sales_data",
            }

        row = rows[0]
        current = row["revenue_current_period"]
        previous = row["revenue_previous_period"]
        change_pct = None if previous in (None, 0) else round(((current - previous) / previous) * 100, 1)

        return {
            "store_id": row["store_id"],
            "period": row["period"],
            "revenue_current_period": current,
            "revenue_previous_period": previous,
            "change_pct": change_pct,
        }
    except sqlite3.Error as e:
        return {
            "error": "DB_ERROR",
            "message": str(e),
            "tool": "get_sales_data",
        }


if __name__ == "__main__":
    mcp.run()
