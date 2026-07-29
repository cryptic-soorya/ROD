"""
mcp_server/tools/returns.py
 
TOOL 8: get_return_reasons
    Required scope: read:returns
    DB: PostgreSQL (table: returns.return_reasons)
    Input:  { sku: str (required), days: int (optional, default 14, max 365), store_id: str (optional) }
    Output: { sku, store_id, period_days, total_returns, low_sample_warning, reasons: {reason: float} }
    Rule:   All reason percentages MUST sum to 1.0 (± 0.01 tolerance)
    Flag:   low_sample_warning: true when total_returns < 10 (configurable via env)
    NOTE:   store_id added 2026-07-28 — return_reasons had a store_id column that wasn't being
            used, meaning a store-specific bad batch or handling issue was getting diluted/masked
            by aggregating across every store carrying the SKU. Omit to keep that old aggregate
            behavior; pass a store to isolate it.
 
TOOL 9: get_product_listing_changes
    Required scope: read:returns
    DB: PostgreSQL (table: orchestration.catalog_changes)
    Input:  { sku: str (required), since: str ISO date (required, must NOT be future date) }
    Output: { sku, change_date, fields_changed: [str], gap_days }
    Rule:   gap_days not available in schema — returns None. Positive = listing is stale.
    NOTE:   No store_id here deliberately — orchestration.catalog_changes has no store column
            in the schema; a listing edit is SKU-wide, not store-specific, so there's nothing to
            RBAC-scope. Not touched in the 2026-07-28 RBAC pass for that reason.
 
RBAC (2026-07-28): get_return_reasons' store_id is resolved via
auth_middleware.resolve_scoped_store_id — same force-scope-on-omission /
reject-on-mismatch behavior as get_customer_complaints. See mcp_server/auth_middleware.py
for the CallerContext this is keyed off.
"""

import os
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
import psycopg2
from fastmcp import FastMCP

from mcp_server.auth_middleware import check_scope, get_token_payload, resolve_scoped_store_id
from logging_config import get_logger
from db_pool import get_conn, put_conn

logger = get_logger("mcp.returns")

mcp = FastMCP("retail-returns")

DB_DSN = os.getenv("RETURNS_DB_URL", os.getenv("DATABASE_URL"))

LOW_SAMPLE_THRESHOLD = int(os.environ.get("LOW_SAMPLE_THRESHOLD", 10))
MAX_DAYS = 365


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


def _validate_since(since: str) -> str | None:
    try:
        dt = datetime.strptime(since, "%Y-%m-%d")
    except ValueError:
        return f"Invalid date format '{since}'. Expected ISO format YYYY-MM-DD."
    if dt.date() > datetime.now().date():
        return f"'since' date '{since}' is in the future. Must be today or earlier."
    return None


@mcp.tool()
def get_return_reasons(sku: str, days: int = 14, store_id: Optional[str] = None) -> dict:
    """
    Returns a breakdown of return reasons for a given SKU over a time period from returns.return_reasons.
    days defaults to 14, max 365. store_id is optional — omit to aggregate across every store
    that returned this SKU, or pass a store to isolate returns from just that store (useful when
    a bad batch or store-specific handling issue is suspected rather than a SKU-wide problem).
    low_sample_warning is true when total_returns < 10.
    All reason percentages sum to 1.0 (± 0.01 tolerance).
    """
    err = check_scope(get_token_payload(), "read:returns", tool_name="get_return_reasons")
    if err:
        return err

    store_id, err = resolve_scoped_store_id(store_id, tool_name="get_return_reasons")
    if err:
        return err

    days = max(1, min(days, MAX_DAYS))

    conn = get_conn(DB_DSN)
    try:
        store_clause = "AND store_id = %s" if store_id is not None else ""
        params = (sku, days, store_id) if store_id is not None else (sku, days)
        rows = _rows(conn, f"""
            SELECT
                reason_code,
                reason_text,
                SUM(units_returned) AS count
            FROM returns.return_reasons
            WHERE sku_id = %s
              AND return_date::date >= CURRENT_DATE - (%s || ' days')::interval
              {store_clause}
            GROUP BY reason_code, reason_text
            ORDER BY count DESC
        """, params)
    except psycopg2.Error as e:
        logger.error(
            "return reasons query failed",
            extra={"event": "db_error", "error_type": type(e).__name__},
        )
        return {"error": "DB_ERROR", "message": str(e), "tool": "get_return_reasons"}
    finally:
        put_conn(DB_DSN, conn)

    total_returns = sum(r["count"] for r in rows)

    if total_returns == 0:
        return {
            "sku": sku,
            "store_id": store_id,
            "period_days": days,
            "total_returns": 0,
            "low_sample_warning": True,
            "reasons": {},
            "note": "No return records found for this SKU in the given period.",
        }

    reasons = {}
    running_total = 0.0
    for i, r in enumerate(rows):
        if i < len(rows) - 1:
            pct = round(r["count"] / total_returns, 4)
            running_total += pct
        else:
            pct = round(1.0 - running_total, 4)
        reasons[r["reason_code"]] = pct

    total_pct = sum(reasons.values())
    assert abs(total_pct - 1.0) <= 0.01, f"Reason percentages sum to {total_pct}, expected 1.0"

    return {
        "sku": sku,
        "store_id": store_id,
        "period_days": days,
        "total_returns": total_returns,
        "low_sample_warning": total_returns < LOW_SAMPLE_THRESHOLD,
        "reasons": reasons,
    }


@mcp.tool()
def get_product_listing_changes(sku: str, since: str) -> dict:
    """
    Returns listing change history for a SKU since a given ISO date from orchestration.catalog_changes.
    since must not be a future date.
    fields_changed lists every field modified in the period.
    """
    scope_err = check_scope(get_token_payload(), "read:returns", tool_name="get_product_listing_changes")
    if scope_err:
        return scope_err

    err = _validate_since(since)
    if err:
        return {"error": err}

    conn = get_conn(DB_DSN)
    try:
        rows = _rows(conn, """
            SELECT
                field_changed,
                old_value,
                new_value,
                change_date,
                changed_by
            FROM orchestration.catalog_changes
            WHERE sku_id = %s
              AND change_date::date >= %s
            ORDER BY change_date DESC
        """, (sku, since))
    except psycopg2.Error as e:
        logger.error(
            "catalog changes query failed",
            extra={"event": "db_error", "error_type": type(e).__name__},
        )
        return {"error": "DB_ERROR", "message": str(e), "tool": "get_product_listing_changes"}
    finally:
        put_conn(DB_DSN, conn)

    if not rows:
        return {
            "sku": sku,
            "since": since,
            "change_date": None,
            "fields_changed": [],
            "gap_days": None,
            "note": "No listing changes found for this SKU since the given date.",
        }

    latest = rows[0]
    fields_changed = list(dict.fromkeys(r["field_changed"] for r in rows))

    return {
        "sku": sku,
        "since": since,
        "change_date": latest["change_date"],
        "fields_changed": fields_changed,
        "gap_days": None,
        "total_changes_in_period": len(rows),
        "changes": [
            {
                "field": r["field_changed"],
                "old_value": r["old_value"],
                "new_value": r["new_value"],
                "date": r["change_date"],
                "changed_by": r["changed_by"],
            }
            for r in rows
        ],
    }


if __name__ == "__main__":
    mcp.run()