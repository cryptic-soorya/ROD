"""
mcp_server/tools/suppliers.py
OWNER: SOORYA

TOOL 8: get_delivery_performance
    Required scope: read:suppliers
    DB: mcp_server/db/suppliers.db
    Input:  { supplier_id: str (required), period: str (optional, default last_30_days) }
    Output: { supplier_id, period, avg_delivery_days_current, avg_delivery_days_baseline,
              defect_rate, degradation_flag }
    Flag:   degradation_flag: true when avg_delivery_days_current > 1.5 × avg_delivery_days_baseline
"""

import os
import sqlite3
from pathlib import Path
from fastmcp import FastMCP

from mcp_server.auth_middleware import check_scope, get_token_payload
from logging_config import get_logger

logger = get_logger("mcp.suppliers")

mcp = FastMCP("retail-suppliers")

BASE_DIR = Path(__file__).resolve().parent.parent
DB = os.getenv("SUPPLIERS_DB_PATH", str(BASE_DIR / "db" / "suppliers.db"))

VALID_PERIODS = {"last_7_days": 7, "last_30_days": 30, "last_quarter": 90}

def _connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def _rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


@mcp.tool()
def get_delivery_performance(supplier_id: str, period: str = "last_30_days") -> dict:
    """
    Returns delivery performance for a supplier vs their baseline.
    period: last_7_days | last_30_days | last_quarter (default: last_30_days).
    degradation_flag true when avg_delivery_days_current > 1.5 × avg_delivery_days_baseline.
    """
    err = check_scope(get_token_payload(), "read:suppliers", tool_name="get_delivery_performance")
    if err:
        return err

    if period not in VALID_PERIODS:
        return {
            "error": "INVALID_PERIOD",
            "message": f"period must be one of: {', '.join(VALID_PERIODS)}",
            "tool": "get_delivery_performance",
        }

    try:
        conn = _connect()
        rows = _rows(conn, """
            SELECT
                avg_delivery_days_current  AS current_days,
                avg_delivery_days_baseline AS baseline_days,
                defect_rate                AS defect_rate
            FROM supplier_deliveries
            WHERE supplier_id = ?
              AND period = ?
        """, (supplier_id, period))

        row = rows[0] if rows else None

        if not row or row["current_days"] is None:
            return {
                "error": "SUPPLIER_NOT_FOUND",
                "message": f"supplier_id '{supplier_id}' not found for period '{period}'",
                "tool": "get_delivery_performance",
            }

        current  = round(row["current_days"], 2)
        baseline = round(row["baseline_days"], 2)
        defect   = round(row["defect_rate"], 4)

        return {
            "supplier_id":                  supplier_id,
            "period":                        period,
            "avg_delivery_days_current":     current,
            "avg_delivery_days_baseline":    baseline,
            "defect_rate":                   defect,
            "degradation_flag":              current > 1.5 * baseline,
        }

    except sqlite3.Error as e:
        logger.error(
            "delivery query failed",
            extra={"event": "db_error", "error_type": type(e).__name__},
        )
        return {"error": "DB_ERROR", "message": str(e), "tool": "get_delivery_performance"}


if __name__ == "__main__":
    mcp.run()