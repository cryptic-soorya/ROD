"""
mcp_server/tools/sales.py
OWNER: Teammate D

TOOL 1: get_sales_data
    Required scope: read:sales
    DB: mcp_server/db/sales.db
    Input:  { store_id: str (required), period: str (optional, default last_30_days) }
    Output: { store_id, period, revenue_current_period, revenue_previous_period, change_pct }
    Error:  { error: STORE_NOT_FOUND, message, tool } — structured dict, never raise exception

    change_pct formula: ((current - previous) / previous) × 100, rounded to 1 decimal
"""
