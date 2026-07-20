"""
mcp_server/tools/customers.py

TOOL 6: get_customer_complaints
    Required scope: read:customers
    DB: PostgreSQL (table: customers.customer_complaints)
    Input:  { date_range: str (required, "YYYY-MM-DD,YYYY-MM-DD"), category: str (optional) }
    Output (with category):    { date_range, category_filter, complaints: [{complaint_id, category, date, description}] }
    Output (without category): { date_range, grouped_by_category: {category_name: count} }
    NOTE:   No category = grouped view helps agent spot dominant complaint type quickly.
"""

import os
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
import psycopg2
import psycopg2.extras
from fastmcp import FastMCP

from mcp_server.auth_middleware import check_scope, get_token_payload

mcp = FastMCP("retail-complaints")

DB_DSN = os.getenv("CUSTOMERS_DB_URL", os.getenv("DATABASE_URL"))


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
    Returns customer complaint data from the customers.customer_complaints table.
    date_range is required — format: 'YYYY-MM-DD,YYYY-MM-DD'.
    Without category: returns grouped_by_category count so dominant type is instantly visible.
    With category: returns individual complaint records filtered to that category.
    """
    err = check_scope(get_token_payload(), "read:customers", tool_name="get_customer_complaints")
    if err:
        return err

    try:
        start_date, end_date = _parse_date_range(date_range)
    except ValueError as e:
        return {"error": str(e)}

    conn = _connect()
    try:
        if category is None:
            rows = _rows(conn, """
                SELECT
                    category,
                    COUNT(*) AS count
                FROM customers.customer_complaints
                WHERE complaint_date BETWEEN %s AND %s
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
                complaint_id,
                category,
                complaint_date AS date,
                description
            FROM customers.customer_complaints
            WHERE complaint_date BETWEEN %s AND %s
              AND category = %s
            ORDER BY complaint_date DESC
        """, (start_date, end_date, category))

        return {
            "date_range": date_range,
            "category_filter": category,
            "total": len(rows),
            "complaints": rows,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    mcp.run()