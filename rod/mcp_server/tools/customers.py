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
