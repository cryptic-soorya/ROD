"""
mcp_server/tools/customers.py
OWNER: Teammate D

TOOL 6: get_customer_complaints
    Required scope: read:customers
    DB: mcp_server/db/customers.db
    Input:  { date_range: str (required, "YYYY-MM-DD,YYYY-MM-DD"), category: str (optional) }
    Output (with category):    { date_range, category_filter, complaints: [{complaint_id, category, date, description}] }
    Output (without category): { date_range, grouped_by_category: {category_name: count} }
    NOTE:   No category = grouped view helps agent spot dominant complaint type quickly.
"""

import os
import sqlite3
from pathlib import Path
from typing import Optional
from fastmcp import FastMCP

from mcp_server.auth_middleware import check_scope, get_token_payload

mcp = FastMCP("retail-complaints")

BASE_DIR = Path(__file__).resolve().parent.parent
DB = os.getenv("CUSTOMERS_DB_PATH", str(BASE_DIR / "db" / "customers.db"))

def _connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def _rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]

def _parse_date_range(date_range: str) -> tuple[str, str]:
    parts = date_range.strip().split(",")
    if len(parts) != 2:
        raise ValueError("date_range must be in format 'YYYY-MM-DD,YYYY-MM-DD'")
    return parts[0].strip(), parts[1].strip()


@mcp.tool()
def get_customer_complaints(
    date_range: str,
    category: Optional[str] = None,
) -> dict:
    """
    Returns customer complaint data from customer_complaints table.
    date_range is required — format: 'YYYY-MM-DD,YYYY-MM-DD'.
    Without category: returns grouped_by_category count so dominant type is instantly visible.
    With category: returns individual complaint records filtered to that category.
    """
    err = check_scope(get_token_payload(), "read:customers", tool_name="get_customer_complaints")
    if err:
        return err

    conn = _connect()

    try:
        start_date, end_date = _parse_date_range(date_range)
    except ValueError as e:
        return {"error": str(e)}

    if category is None:
        rows = _rows(conn, """
            SELECT
                category,
                COUNT(*) AS count
            FROM customer_complaints
            WHERE DATE(complaint_date) BETWEEN ? AND ?
            GROUP BY category
            ORDER BY count DESC
        """, (start_date, end_date))

        grouped = {r["category"]: r["count"] for r in rows}
        dominant = rows[0] if rows else None

        return {
            "date_range": date_range,
            "grouped_by_category": grouped,
            "dominant_category": dominant["category"] if dominant else None,
            "total_complaints": sum(r["count"] for r in rows),
        }

    rows = _rows(conn, """
        SELECT
            id            AS complaint_id,
            category,
            complaint_date AS date,
            complaint_text AS description
        FROM customer_complaints
        WHERE DATE(complaint_date) BETWEEN ? AND ?
          AND category = ?
        ORDER BY complaint_date DESC
    """, (start_date, end_date, category))

    return {
        "date_range": date_range,
        "category_filter": category,
        "total": len(rows),
        "complaints": rows,
    }


if __name__ == "__main__":
    mcp.run()