"""
mcp_server/tools/returns.py
OWNER: Teammate D

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
    Rule:   gap_days = last_updated − supplier_change_date. Positive = listing is stale.
"""
