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

import sqlite3
from typing import Optional
from fastmcp import FastMCP

mcp = FastMCP("retail-complaints")

DB = "../db/customers.db"

def _connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def _rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]

def _parse_date_range(date_range: str) -> tuple[str, str]:
    """Parse 'YYYY-MM-DD,YYYY-MM-DD' into (start, end)."""
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
    Returns customer complaint data from Customer_Queries table.
    date_range is required — format: 'YYYY-MM-DD,YYYY-MM-DD'.
    Without category: returns grouped_by_category count so dominant type is instantly visible.
    With category: returns individual complaint records filtered to that category.
    """
    conn = _connect()

    try:
        start_date, end_date = _parse_date_range(date_range)
    except ValueError as e:
        return {"error": str(e)}

    # ── no category → grouped view ────────────────────────────────────────────
    if category is None:
        rows = _rows(conn, """
            SELECT
                query_type          AS category,
                COUNT(*)            AS count
            FROM Customer_Queries
            WHERE DATE(created_at) BETWEEN ? AND ?
            GROUP BY query_type
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

    # ── with category → individual complaints ─────────────────────────────────
    rows = _rows(conn, """
        SELECT
            query_id        AS complaint_id,
            query_type      AS category,
            DATE(created_at) AS date,
            description
        FROM Customer_Queries
        WHERE DATE(created_at) BETWEEN ? AND ?
          AND query_type = ?
        ORDER BY created_at DESC
    """, (start_date, end_date, category))

    return {
        "date_range": date_range,
        "category_filter": category,
        "total": len(rows),
        "complaints": rows,
    }


if __name__ == "__main__":
    mcp.run()
