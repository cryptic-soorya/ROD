"""
mcp_server/tools/customers.py


TOOL 6: get_customer_complaints
    Required scope: read:customers
    DB: PostgreSQL (table: customers.customer_complaints)
    Input:  { sku_id: str (optional), store_id: str (optional),
              date_range: str (optional, "YYYY-MM-DD,YYYY-MM-DD"), category: str (optional) }
            Any combination of the above can be passed together.
    Output (with category):    { filters, category_filter, complaints: [{complaint_id, category, date, description, sku_id, store_id}] }
    Output (without category): { filters, grouped_by_category: {category_name: count} }
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


def _build_filters(sku_id, store_id, date_range, category) -> tuple[list[str], list, dict]:
    """Turns whichever filters were passed into a WHERE clause + params.
    Returns (clauses, params, filters_echo) — filters_echo is just for the response."""
    clauses = []
    params = []
    filters_echo = {}

    if sku_id is not None:
        clauses.append("sku_id = %s")
        params.append(sku_id)
        filters_echo["sku_id"] = sku_id

    if store_id is not None:
        clauses.append("store_id = %s")
        params.append(store_id)
        filters_echo["store_id"] = store_id

    if date_range is not None:
        start_date, end_date = _parse_date_range(date_range)
        clauses.append("complaint_date BETWEEN %s AND %s")
        params.extend([start_date, end_date])
        filters_echo["date_range"] = date_range

    if category is not None:
        filters_echo["category"] = category  # applied separately per branch below

    return clauses, params, filters_echo


@mcp.tool()
def get_customer_complaints(
    sku_id: Optional[str] = None,
    store_id: Optional[str] = None,
    date_range: Optional[str] = None,
    category: Optional[str] = None,
) -> dict:
    """
    Returns customer complaint data from the customers.customer_complaints table.
    All filters are optional and combinable: sku_id, store_id, date_range
    ('YYYY-MM-DD,YYYY-MM-DD'), category. Pass none to get all complaints grouped.

    Without category: returns grouped_by_category count so dominant type is instantly visible.
    With category: returns individual complaint records matching all given filters.
    """
    err = check_scope(get_token_payload(), "read:customers", tool_name="get_customer_complaints")
    if err:
        return err

    try:
        clauses, params, filters_echo = _build_filters(sku_id, store_id, date_range, category)
    except ValueError as e:
        return {"error": str(e)}

    conn = _connect()
    try:
        if category is None:
            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = _rows(conn, f"""
                SELECT
                    category,
                    COUNT(*) AS count
                FROM customers.customer_complaints
                {where_sql}
                GROUP BY category
                ORDER BY count DESC
            """, tuple(params))

            grouped = {r["category"]: r["count"] for r in rows}
            dominant = rows[0] if rows else None

            return {
                "filters": filters_echo,
                "grouped_by_category": grouped,
                "dominant_category": dominant["category"] if dominant else None,
                "total_complaints": sum(r["count"] for r in rows),
            }

        # category given -> add it to the filter and return individual rows
        clauses.append("category = %s")
        params.append(category)
        where_sql = f"WHERE {' AND '.join(clauses)}"

        rows = _rows(conn, f"""
            SELECT
                complaint_id,
                category,
                complaint_date AS date,
                description,
                sku_id,
                store_id
            FROM customers.customer_complaints
            {where_sql}
            ORDER BY complaint_date DESC
        """, tuple(params))

        return {
            "filters": filters_echo,
            "category_filter": category,
            "total": len(rows),
            "complaints": rows,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    mcp.run()