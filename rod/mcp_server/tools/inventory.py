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

TOOL 4: get_low_stock_items_for_store
    Required scope: read:inventory
    DB: PostgreSQL (table: inventory.inventory)
    Input:  { store_id: str (required), limit: int (optional, 1-50, default 10) }
    Output: { store_id, items: [{ sku, units_available, reorder_point, stockout_flag, last_snapshot }, ...] }
 
RBAC : all three tools enforce store-scoped access via
auth_middleware.require_store_access (store_id is a required arg on each — a manager naming
another store is rejected outright). Admins are unrestricted. 
"""
import os
from datetime import date, datetime
from decimal import Decimal
import psycopg2

from mcp_server.auth_middleware import check_scope, get_token_payload, require_store_access
from logging_config import get_logger
from db_pool import get_conn, put_conn

logger = get_logger("mcp.inventory")

DB_DSN = os.getenv("INVENTORY_DB_URL", os.getenv("DATABASE_URL"))


def _serialize(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _rows(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [{k: _serialize(v) for k, v in dict(r).items()} for r in cur.fetchall()]


def get_inventory_levels(sku: str, store_id: str) -> dict:
    err = check_scope(get_token_payload(), "read:inventory", tool_name="get_inventory_levels")
    if err:
        return err
    err = require_store_access(store_id, tool_name="get_inventory_levels")
    if err:
        return err

    conn = get_conn(DB_DSN)
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
        put_conn(DB_DSN, conn)


def get_replenishment_history(sku: str, store_id: str, days: int = 30) -> dict:
    err = check_scope(get_token_payload(), "read:inventory", tool_name="get_replenishment_history")
    if err:
        return err
    err = require_store_access(store_id, tool_name="get_replenishment_history")
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

    conn = get_conn(DB_DSN)
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
        put_conn(DB_DSN, conn)


def get_low_stock_items_for_store(store_id: str, limit: int = 10) -> dict:
    """
    Returns the SKUs at a store currently at or below their reorder point
    (worst first — most negative stock_on_hand - reorder_point first), plus
    any full stockouts. Use this when a stockout or low-stock issue is
    suspected at a store but the specific SKU isn't known yet — it's the
    entry point that get_inventory_levels needs a SKU for.
    limit: max number of SKUs to return (1-50, default 10).
    """
    err = check_scope(get_token_payload(), "read:inventory", tool_name="get_low_stock_items_for_store")
    if err:
        return err
    err = require_store_access(store_id, tool_name="get_low_stock_items_for_store")
    if err:
        return err

    limit = min(max(limit, 1), 50)

    conn = get_conn(DB_DSN)
    try:
        rows = _rows(conn, """
            SELECT
                sku_id,
                store_id,
                stock_on_hand,
                reorder_point,
                last_audited
            FROM inventory.inventory
            WHERE store_id = %s
              AND stock_on_hand <= reorder_point
            ORDER BY (stock_on_hand - reorder_point) ASC
            LIMIT %s
        """, (store_id, limit))

        return {
            "store_id": store_id,
            "items": [
                {
                    "sku": r["sku_id"],
                    "units_available": r["stock_on_hand"],
                    "reorder_point": r["reorder_point"],
                    "stockout_flag": r["stock_on_hand"] <= 0,
                    "last_snapshot": r["last_audited"],
                }
                for r in rows
            ],
            "tool": "get_low_stock_items_for_store",
        }
    except psycopg2.Error as e:
        logger.error(
            "low stock scan failed",
            extra={"event": "db_error", "error_type": type(e).__name__},
        )
        return {"error": "DB_ERROR", "message": str(e), "tool": "get_low_stock_items_for_store"}
    finally:
        put_conn(DB_DSN, conn)