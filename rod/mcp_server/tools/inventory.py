"""
mcp_server/tools/inventory.py
OWNER: Teammate D

TOOL 2: get_inventory_levels
    Required scope: read:inventory
    DB: mcp_server/db/inventory.db
    Input:  { sku: str (required), store_id: str (required) }
    Output: { sku, store_id, units_available, units_reserved, reorder_point, last_updated }
    Flag:   below_reorder_point: true when units_available <= reorder_point

TOOL 3: get_replenishment_history
    Required scope: read:inventory
    DB: mcp_server/db/inventory.db
    Input:  { sku: str (required), store_id: str (required), days: int (optional, default 30) }
    Output: { sku, store_id, period_days, replenishments: [{date, quantity}] }
    NOTE:   Empty list is VALID — signals procurement gap. Do NOT return an error for empty.
"""
