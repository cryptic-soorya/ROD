"""
mcp_server/tools/inventory.py
OWNER: Teammate D

TOOL 2: get_inventory_levels
    Required scope: read:inventory
    DB: mcp_server/db/inventory.db
    Input:  { sku: str (required), store_id: str (required) }
    Output: { sku, store_id, units_available, units_reserved, reorder_point, last_updated }
    Flag:   below_reorder_point: true when units_available <= reorder_point

TOOL 3: get_replenishment_history
    Required scope: read:inventory
    DB: mcp_server/db/inventory.db
    Input:  { sku: str (required), store_id: str (required), days: int (optional, default 30) }
    Output: { sku, store_id, period_days, replenishments: [{date, quantity}] }
    NOTE:   Empty list is VALID — signals procurement gap. Do NOT return an error for empty.
"""
import os
import sqlite3
from pathlib import Path
from fastmcp import FastMCP

mcp = FastMCP("retail-inventory")

BASE_DIR = Path(__file__).resolve().parent.parent
DB = os.getenv("INVENTORY_DB_PATH", str(BASE_DIR / "db" / "inventory.db"))


def _connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def _rows(conn, sql, params=()):
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _format_replenishments(rows: list[dict]) -> list[dict]:
    return [
        {
            "date": row["replenishment_date"],
            "quantity": row["quantity"],
        }
        for row in rows
    ]


@mcp.tool()
def get_inventory_levels(sku: str, store_id: str) -> dict:
    """
    Returns current inventory metrics for a SKU at a specific store.
    below_reorder_point is true when units_available <= reorder_point.
    """
    try:
        conn = _connect()
        rows = _rows(conn, """
            SELECT
                sku,
                store_id,
                units_available,
                units_reserved,
                reorder_point,
                last_updated
            FROM inventory_levels
            WHERE sku = ?
              AND store_id = ?
        """, (sku, store_id))

        if not rows:
            return {
                "sku": sku,
                "store_id": store_id,
                "error": f"No inventory record found for sku '{sku}' at store '{store_id}'.",
            }

        row = rows[0]
        return {
            "sku": row["sku"],
            "store_id": row["store_id"],
            "units_available": row["units_available"],
            "units_reserved": row["units_reserved"],
            "reorder_point": row["reorder_point"],
            "last_updated": row["last_updated"],
            "below_reorder_point": row["units_available"] <= row["reorder_point"],
        }
    except sqlite3.Error as e:
        return {
            "error": "DB_ERROR",
            "message": str(e),
            "tool": "get_inventory_levels",
        }


@mcp.tool()
def get_replenishment_history(
    sku: str,
    store_id: str,
    days: int = 30,
) -> dict:
    """
    Returns replenishment records for a SKU/store over the last `days` days.
    An empty replenishments list is valid and does not return an error.
    """
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
                replenishment_date,
                quantity
            FROM replenishment_history
            WHERE sku = ?
              AND store_id = ?
              AND DATE(replenishment_date) >= DATE('now', ?)
            ORDER BY replenishment_date DESC
        """, (sku, store_id, f"-{days} days"))

        return {
            "sku": sku,
            "store_id": store_id,
            "period_days": days,
            "replenishments": _format_replenishments(rows),
        }
    except sqlite3.Error as e:
        return {
            "error": "DB_ERROR",
            "message": str(e),
            "tool": "get_replenishment_history",
        }


if __name__ == "__main__":
    mcp.run()
