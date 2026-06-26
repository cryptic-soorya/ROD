"""
mcp_server/server.py
OWNER: Team Lead

FastMCP server setup:
- Reads MCP_AUTH_TOKEN from environment at startup. Refuses to start if missing/malformed/expired.
- Registers all 9 tools (imported from tools/).
- Runs on stdio transport (NOT a TCP port).

IMPORTANT: This is a separate process from the FastAPI HTTP server (main.py).
The agent spawns this as a subprocess when an investigation begins.

Registered tools:
    From tools/sales.py:        get_sales_data
    From tools/inventory.py:    get_inventory_levels, get_replenishment_history
    From tools/returns.py:      get_return_reasons, get_product_listing_changes
    From tools/customers.py:    get_customer_complaints
    From tools/promotions.py:   get_promotion_performance
    From tools/suppliers.py:    get_delivery_performance         (SOORYA — DO NOT EDIT)
    From tools/knowledge.py:    knowledge_search                  (SOORYA — DO NOT EDIT)
"""
