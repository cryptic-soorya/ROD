"""
mcp_server/tools/promotions.py
OWNER: Teammate D

TOOL 7: get_promotion_performance
    Required scope: read:promotions
    DB: mcp_server/db/promotions.db
    Input:  { promo_id: str (required) }
    Output: { promo_id, sku, target_segment, start_date, end_date, projected_uplift_pct, actual_uplift_pct, underperformance_flag }
    Flag:   underperformance_flag: true when actual_uplift_pct < 0.5 × projected_uplift_pct
"""
