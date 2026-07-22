"""
mcp_server/server.py
OWNER: Team Lead

Optional standalone MCP server (stdio transport) for external MCP clients
(e.g. Claude Desktop) that want to talk to ROD's tools directly.

NOTE: The live investigation path does NOT use this process. agent/react_loop.py
imports the tool functions from mcp_server/tools/*.py directly and calls them
in-process — there is no subprocess spawn and no stdio round-trip in that path.
Scope enforcement therefore lives in the tool functions themselves (each calls
check_scope()/get_token_payload() from mcp_server/auth_middleware.py at the top
of its body), not in this file — that way it applies identically whether a tool
is invoked in-process by the agent or via this stdio server.

This file just registers the same 10 tool functions on a FastMCP instance so
they're also reachable over stdio, and performs the one-time startup_check()
so get_token_payload() has something to return when those tools run here.

Registered tools:
    From tools/sales.py:        get_sales_data, get_stores_with_sales_decline,
                                 get_stores_with_sku_decline
    From tools/inventory.py:    get_inventory_levels, get_replenishment_history
    From tools/returns.py:      get_return_reasons, get_product_listing_changes
    From tools/customers.py:    get_customer_complaints
    From tools/promotions.py:   get_promotion_performance
    From tools/suppliers.py:    get_delivery_performance         (SOORYA — DO NOT EDIT)
    From tools/knowledge.py:    knowledge_search                  (SOORYA — DO NOT EDIT)
"""

import os

from fastmcp import FastMCP

from logging_config import get_logger

from .tools.sales import (
    get_sales_data,
    get_stores_with_sales_decline,
    get_stores_with_sku_decline,
)
from .tools.inventory import get_inventory_levels, get_replenishment_history
from .tools.returns import get_return_reasons, get_product_listing_changes
from .tools.customers import get_customer_complaints
from .tools.promotions import get_promotion_performance
from .tools.suppliers import get_delivery_performance
from .tools.knowledge import knowledge_search
from . import auth_middleware

logger = get_logger("mcp.server")

mcp = FastMCP("ROD MCP Server")

mcp.tool()(get_sales_data)
mcp.tool()(get_stores_with_sales_decline)
mcp.tool()(get_stores_with_sku_decline)
mcp.tool()(get_inventory_levels)
mcp.tool()(get_replenishment_history)
mcp.tool()(get_return_reasons)
mcp.tool()(get_product_listing_changes)
mcp.tool()(get_customer_complaints)
mcp.tool()(get_promotion_performance)
mcp.tool()(get_delivery_performance)
mcp.tool()(knowledge_search)


if __name__ == "__main__":
    # Validates MCP_AUTH_TOKEN once at startup and caches its payload so the
    # check_scope() calls inside each tool function have something to check
    # against. Exits the process if the token is missing/malformed/expired.
    auth_middleware.startup_check(os.environ.get("MCP_AUTH_TOKEN", ""))

    logger.info("ROD MCP stdio server starting", extra={"event": "mcp_server_start"})
    print("ROD MCP Server starting — 10 tools registered, scope-checked per call")
    mcp.run(transport="stdio")
