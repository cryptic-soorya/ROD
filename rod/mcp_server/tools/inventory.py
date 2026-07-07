"""
mcp_server/tools/inventory.py
OWNER: Teammate D

TOOL 2: get_inventory_levels
    Required scope: read:inventory
    DB: mcp_server/db/inventory.db
    Input:  { sku: str (required), store_id: str (required) }
    Output: { sku, store_id, units_available, reorder_point, stockout_flag, last_snapshot }
    Flag:   below_reorder_point: true when units_available <= reorder_point

TOOL 3: get_replenishment_history
    Required scope: read:inventory
    DB: mcp_server/db/inventory.db
    Input:  { sku: str (required), store_id: str (required), days: int (optional, default 30) }
    Output: { sku, store_id, period_days, replenishments: [{date, units_ordered, units_received, supplier_id}] }
    NOTE:   Empty list is VALID — signals procurement gap. Do NOT return an error for empty.
"""

import os
import sqlite3
from pathlib import Path
from fastmcp import FastMCP

from mcp_server.auth_middleware import check_scope, get_token_payload
from logging_config import get_logger

logger = get_logger("mcp.inventory")

mcp = FastMCP("retail-inventory")

BASE_DIR = Path(__file__).resolve().parent.parent
DB = os.getenv("INVENTORY_DB_PATH", str(BASE_DIR / "db" / "inventory.db"))


def _connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def _rows(conn, sql, params=()):
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


@mcp.tool()
def get_inventory_levels(sku: str, store_id: str) -> dict:
    """
    Returns current inventory metrics for a SKU at a specific store.
    Uses most recent snapshot. below_reorder_point true when stock_on_hand <= reorder_point.
    """
    err = check_scope(get_token_payload(), "read:inventory", tool_name="get_inventory_levels")
    if err:
        return err

    try:
        conn = _connect()
        rows = _rows(conn, """
            SELECT
                product_id,
                store_id,
                stock_on_hand,
                reorder_point,
                stockout_flag,
                snapshot_date
            FROM inventory_levels
            WHERE product_id = ?
              AND store_id = ?
            ORDER BY snapshot_date DESC
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
            "sku": row["product_id"],
            "store_id": row["store_id"],
            "units_available": row["stock_on_hand"],
            "reorder_point": row["reorder_point"],
            "stockout_flag": bool(row["stockout_flag"]),
            "below_reorder_point": row["stock_on_hand"] <= row["reorder_point"],
            "last_snapshot": row["snapshot_date"],
        }
    except sqlite3.Error as e:
        logger.error(
            "inventory query failed",
            extra={"event": "db_error", "error_type": type(e).__name__},
        )
        return {"error": "DB_ERROR", "message": str(e), "tool": "get_inventory_levels"}


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

    try:
        conn = _connect()
        rows = _rows(conn, """
            SELECT
                order_date,
                received_date,
                units_ordered,
                units_received,
                supplier_id
            FROM replenishment_history
            WHERE product_id = ?
              AND store_id = ?
              AND DATE(order_date) >= DATE('now', ?)
            ORDER BY order_date DESC
        """, (sku, store_id, f"-{days} days"))

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
    except sqlite3.Error as e:
        logger.error(
            "replenishment history query failed",
            extra={"event": "db_error", "error_type": type(e).__name__},
        )
        return {"error": "DB_ERROR", "message": str(e), "tool": "get_replenishment_history"}


if __name__ == "__main__":
    mcp.run()