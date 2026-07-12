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
    DB: investigations/orchestration.db (catalog_changes table)
    Input:  { sku: str (required), since: str ISO date (required, must NOT be future date) }
    Output: { sku, change_date, fields_changed: [str], gap_days }
    Rule:   gap_days not available in schema — returns None. Positive = listing is stale.

UPDATED:
    - get_return_reasons: return_reasons is keyed by sku_id now, not
      product_id. Query updated accordingly.
    - get_product_listing_changes: the underlying table was renamed
      product_listing_changes -> catalog_changes AND relocated from
      returns.db into the merged investigations/orchestration.db (it's
      catalog/reference data, not returns data). Per team decision, this
      function stays in returns.py under read:returns scope rather than
      moving to a new tool/scope — only the DB connection changes, using
      a second DB_PATH/connect function since the two tools in this file
      now genuinely point at different physical files.
"""

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from fastmcp import FastMCP

from mcp_server.auth_middleware import check_scope, get_token_payload

mcp = FastMCP("retail-returns")

BASE_DIR = Path(__file__).resolve().parent.parent
DB = os.getenv("RETURNS_DB_PATH", str(BASE_DIR / "db" / "returns.db"))

# catalog_changes now lives in the merged orchestration.db, a sibling
# directory to mcp_server/, not inside mcp_server/db/ like the other
# retail dbs -- this path is intentionally different from DB above.
CATALOG_DB = os.getenv(
    "ORCHESTRATION_DB_PATH",
    str(BASE_DIR.parent / "investigations" / "orchestration.db"),
)

LOW_SAMPLE_THRESHOLD = int(os.environ.get("LOW_SAMPLE_THRESHOLD", 10))
MAX_DAYS = 365


def _connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def _connect_catalog():
    conn = sqlite3.connect(CATALOG_DB)
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


@mcp.tool()
def get_return_reasons(sku: str, days: int = 14) -> dict:
    """
    Returns a breakdown of return reasons for a given SKU over a time period.
    days defaults to 14, max 365.
    low_sample_warning is true when total_returns < 10.
    All reason percentages sum to 1.0 (± 0.01 tolerance).
    """
    err = check_scope(get_token_payload(), "read:returns", tool_name="get_return_reasons")
    if err:
        return err

    days = max(1, min(days, MAX_DAYS))
    conn = _connect()

    rows = _rows(conn, """
        SELECT
            reason_code,
            reason_text,
            SUM(units_returned) AS count
        FROM return_reasons
        WHERE sku_id = ?
          AND return_date >= DATE('now', ? || ' days')
        GROUP BY reason_code, reason_text
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
        reasons[r["reason_code"]] = pct

    total_pct = sum(reasons.values())
    assert abs(total_pct - 1.0) <= 0.01, f"Reason percentages sum to {total_pct}, expected 1.0"

    return {
        "sku": sku,
        "period_days": days,
        "total_returns": total_returns,
        "low_sample_warning": total_returns < LOW_SAMPLE_THRESHOLD,
        "reasons": reasons,
    }


@mcp.tool()
def get_product_listing_changes(sku: str, since: str) -> dict:
    """
    Returns listing change history for a SKU since a given ISO date.
    since must not be a future date.
    fields_changed lists every field modified in the period.
    NOTE: reads from catalog_changes in investigations/orchestration.db,
    not returns.db -- see module docstring.
    """
    scope_err = check_scope(get_token_payload(), "read:returns", tool_name="get_product_listing_changes")
    if scope_err:
        return scope_err

    err = _validate_since(since)
    if err:
        return {"error": err}

    conn = _connect_catalog()

    rows = _rows(conn, """
        SELECT
            field_changed,
            old_value,
            new_value,
            change_date,
            changed_by
        FROM catalog_changes
        WHERE sku_id = ?
          AND change_date >= ?
        ORDER BY change_date DESC
    """, (sku, since))

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
        "gap_days": None,   # not available in current schema
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
