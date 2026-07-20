"""
mcp_server/tools/inventory.py

TOOL 2: get_inventory_levels
    Required scope: read:inventory
    DB: PostgreSQL (table: inventory.inventory)
    Input:  { sku: str (required), store_id: str (required) }
    Output: { sku, store_id, units_available, reorder_point, stockout_flag, last_snapshot }
    Flag:   below_reorder_point: true when units_available <= reorder_point

TOOL 3: get_replenishment_history
    Required scope: read:inventory
    DB: PostgreSQL (table: inventory.replenishment_history)
    Input:  { sku: str (required), store_id: str (required), days: int (optional, default 30) }
    Output: { sku, store_id, period_days, replenishments: [{date, units_ordered, units_received, supplier_id}] }
    NOTE:   Empty list is VALID — signals procurement gap. Do NOT return an error for empty.
"""

import os
from datetime import date, datetime
from decimal import Decimal
import psycopg2
import psycopg2.extras
from fastmcp import FastMCP

from mcp_server.auth_middleware import check_scope, get_token_payload
from logging_config import get_logger

logger = get_logger("mcp.inventory")

mcp = FastMCP("retail-inventory")

DB_DSN = os.getenv("INVENTORY_DB_URL", os.getenv("DATABASE_URL"))


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
        return [{k: _serialize(v) for k, v in dict(r).items()} for r in cur.fetchall()]


@mcp.tool()
def get_inventory_levels(sku: str, store_id: str) -> dict:
    """
    Returns current inventory metrics for a SKU at a specific store.
    Uses the current state single-row representation per SKU/Store.
    below_reorder_point true when stock_on_hand <= reorder_point.
    stockout_flag is derived (stock_on_hand <= 0).
    """
    err = check_scope(get_token_payload(), "read:inventory", tool_name="get_inventory_levels")
    if err:
        return err

    conn = _connect()
    try:
        rows = _rows(conn, """
            SELECT
                sku_id,
                store_id,
                stock_on_hand,
                reorder_point,
                last_audited
            FROM inventory.inventory
            WHERE sku_id = %s
              AND store_id = %s
            LIMIT 1
        """, (sku, store_id))

        if not rows:
            return {
                "sku": sku,
                "store_id": store_id,
                "error": f"No inventory record found for sku '{sku}' at store '{store_id}'.",
            }

        row = rows[0]
        return {
            "sku": row["sku_id"],
            "store_id": row["store_id"],
            "units_available": row["stock_on_hand"],
            "reorder_point": row["reorder_point"],
            "stockout_flag": row["stock_on_hand"] <= 0,
            "below_reorder_point": row["stock_on_hand"] <= row["reorder_point"],
            "last_snapshot": row["last_audited"],
        }
    except psycopg2.Error as e:
        logger.error(
            "inventory query failed",
            extra={"event": "db_error", "error_type": type(e).__name__},
        )
        return {"error": "DB_ERROR", "message": str(e), "tool": "get_inventory_levels"}
    finally:
        conn.close()


@mcp.tool()
def get_replenishment_history(sku: str, store_id: str, days: int = 30) -> dict:
    """
    Returns replenishment records for a SKU/store over the last `days` days.
    An empty replenishments list is valid and signals a procurement gap.
    """
    err = check_scope(get_token_payload(), "read:inventory", tool_name="get_replenishment_history")
    if err:
        return err

    if days <= 0:
        return {
            "sku": sku,
            "store_id": store_id,
            "period_days": days,
            "error": "days must be a positive integer",
            "tool": "get_replenishment_history",
        }

    conn = _connect()
    try:
        rows = _rows(conn, """
            SELECT
                order_date,
                received_date,
                units_ordered,
                units_received,
                supplier_id
            FROM inventory.replenishment_history
            WHERE sku_id = %s
              AND store_id = %s
              AND order_date::date >= CURRENT_DATE - (%s || ' days')::interval
            ORDER BY order_date DESC
        """, (sku, store_id, days))

        return {
            "sku": sku,
            "store_id": store_id,
            "period_days": days,
            "replenishments": [
                {
                    "order_date": r["order_date"],
                    "received_date": r["received_date"],
                    "units_ordered": r["units_ordered"],
                    "units_received": r["units_received"],
                    "supplier_id": r["supplier_id"],
                }
                for r in rows
            ],
        }
    except psycopg2.Error as e:
        logger.error(
            "replenishment history query failed",
            extra={"event": "db_error", "error_type": type(e).__name__},
        )
        return {"error": "DB_ERROR", "message": str(e), "tool": "get_replenishment_history"}
    finally:
        conn.close()


if __name__ == "__main__":
    mcp.run()