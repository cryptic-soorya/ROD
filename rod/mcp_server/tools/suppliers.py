"""
mcp_server/tools/suppliers.py

TOOL 8: get_delivery_performance
    Required scope: read:suppliers
    DB: PostgreSQL (table: suppliers.supplier_delivery)
    Input:  { supplier_id: str (required), period: str (optional, default last_30_days) }
    Output: { supplier_id, period, avg_delivery_days_current, avg_delivery_days_baseline,
              defect_rate, degradation_flag }
    Flag:   degradation_flag: true when avg_delivery_days_current > 1.5 × avg_delivery_days_baseline
"""

import os
from datetime import date, datetime, timedelta
from decimal import Decimal
import psycopg2
from fastmcp import FastMCP

from mcp_server.auth_middleware import check_scope, get_token_payload
from logging_config import get_logger
from db_pool import get_conn, put_conn

logger = get_logger("mcp.suppliers")

mcp = FastMCP("retail-suppliers")

DB_DSN = os.getenv("SUPPLIERS_DB_URL", os.getenv("DATABASE_URL"))

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
        return [{k: _serialize(v) for k, v in dict(r).items()} for r in cur.fetchall()]


@mcp.tool()
def get_delivery_performance(supplier_id: str, period: str = "last_30_days") -> dict:
    """
    Returns delivery performance for a supplier vs their baseline from suppliers.supplier_delivery.
    period: last_7_days | last_30_days | last_quarter (default: last_30_days).
    degradation_flag true when the aggregated avg_delivery_days_current > 1.5 × the aggregated baseline.
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

    days = VALID_PERIODS[period]
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    conn = get_conn(DB_DSN)
    try:
        rows = _rows(conn, """
            SELECT
                AVG(avg_delivery_days_current)  AS current_days,
                AVG(avg_delivery_days_baseline) AS baseline_days,
                AVG(defect_rate)                AS defect_rate
            FROM suppliers.supplier_delivery
            WHERE supplier_id = %s
              AND delivery_date::date >= %s
        """, (supplier_id, cutoff))

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

    except psycopg2.Error as e:
        logger.error(
            "delivery query failed",
            extra={"event": "db_error", "error_type": type(e).__name__},
        )
        return {"error": "DB_ERROR", "message": str(e), "tool": "get_delivery_performance"}
    finally:
        put_conn(DB_DSN, conn)


if __name__ == "__main__":
    mcp.run()