"""
mcp_server/tools/returns.py

TOOL 4: get_return_reasons
    Required scope: read:returns
    DB: mcp_server/db/returns.db
    Input:  { sku: str (required), days: int (optional, default 14, max 365) }
    Output: { sku, period_days, total_returns, low_sample_warning, reasons: {reason: float} }
    Rule:   All reason percentages MUST sum to 1.0 (± 0.01 tolerance)
    Flag:   low_sample_warning: true when total_returns < 10 (configurable via env)

TOOL 5: get_product_listing_changes
    Required scope: read:returns
    DB: mcp_server/db/returns.db
    Input:  { sku: str (required), since: str ISO date (required, must NOT be future date) }
    Output: { sku, last_updated, supplier_change_date, gap_days, fields_changed: [str] }
    Rule:   gap_days = last_updated - supplier_change_date. Positive = listing is stale.
"""

import os
import sqlite3
from datetime import datetime
from fastmcp import FastMCP

mcp = FastMCP("retail-returns")

DB = "../db/returns.db"
LOW_SAMPLE_THRESHOLD = int(os.environ.get("LOW_SAMPLE_THRESHOLD", 10))
MAX_DAYS = 365


# ── helpers ───────────────────────────────────────────────────────────────────

def _connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def _rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]

def _validate_since(since: str) -> str | None:
    try:
        dt = datetime.strptime(since, "%Y-%m-%d")
    except ValueError:
        return f"Invalid date format '{since}'. Expected ISO format YYYY-MM-DD."
    if dt.date() > datetime.now().date():
        return f"'since' date '{since}' is in the future. Must be today or earlier."
    return None


# ── Tool 4 ────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_return_reasons(sku: str, days: int = 14) -> dict:
    """
    Returns a breakdown of return reasons for a given SKU over a time period.
    days defaults to 14, max 365.
    low_sample_warning is true when total_returns < 10 (set LOW_SAMPLE_THRESHOLD env var to override).
    All reason percentages sum to 1.0 (± 0.01 tolerance).
    """
    days = max(1, min(days, MAX_DAYS))
    conn = _connect()

    rows = _rows(conn, """
        SELECT return_reason, COUNT(*) AS count
        FROM Returns
        WHERE sku_id = ?
          AND return_date >= DATE('now', ? || ' days')
        GROUP BY return_reason
        ORDER BY count DESC
    """, (sku, f"-{days}"))

    total_returns = sum(r["count"] for r in rows)

    if total_returns == 0:
        return {
            "sku": sku,
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
        reasons[r["return_reason"]] = pct

    total_pct = sum(reasons.values())
    assert abs(total_pct - 1.0) <= 0.01, f"Reason percentages sum to {total_pct}, expected 1.0"

    return {
        "sku": sku,
        "period_days": days,
        "total_returns": total_returns,
        "low_sample_warning": total_returns < LOW_SAMPLE_THRESHOLD,
        "reasons": reasons,
    }


# ── Tool 5 ────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_product_listing_changes(sku: str, since: str) -> dict:
    """
    Returns listing change history for a SKU since a given ISO date.
    since must not be a future date.
    gap_days = retailer_update_date - supplier_change_date. Positive means listing is stale.
    fields_changed lists every field that was modified in the period.
    """
    err = _validate_since(since)
    if err:
        return {"error": err}

    conn = _connect()

    rows = _rows(conn, """
        SELECT
            field_changed,
            supplier_change_date,
            retailer_update_date AS last_updated,
            CASE
                WHEN retailer_update_date IS NULL THEN NULL
                ELSE CAST(
                    julianday(retailer_update_date) - julianday(supplier_change_date)
                    AS INTEGER
                )
            END AS gap_days
        FROM Product_Listing_Changes
        WHERE sku_id = ?
          AND supplier_change_date >= ?
        ORDER BY supplier_change_date DESC
    """, (sku, since))

    if not rows:
        return {
            "sku": sku,
            "since": since,
            "last_updated": None,
            "supplier_change_date": None,
            "gap_days": None,
            "fields_changed": [],
            "note": "No listing changes found for this SKU since the given date.",
        }

    latest = rows[0]
    fields_changed = list(dict.fromkeys(r["field_changed"] for r in rows))

    return {
        "sku": sku,
        "since": since,
        "supplier_change_date": latest["supplier_change_date"],
        "last_updated": latest["last_updated"],
        "gap_days": latest["gap_days"],
        "fields_changed": fields_changed,
        "stale": latest["gap_days"] is not None and latest["gap_days"] > 0,
        "never_updated": latest["last_updated"] is None,
        "total_changes_in_period": len(rows),
    }


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
