"""
mcp_server/server.py
OWNER: Team Lead

Optional standalone MCP server (stdio transport) for external MCP clients
(e.g. Claude Desktop) that want to talk to ROD's tools directly.

NOTE: The live investigation path does NOT use this process. agent/tools.py
(used by agent/graph.py's LangGraph nodes) imports the tool functions from
mcp_server/tools/*.py directly and calls them in-process — there is no
subprocess spawn and no stdio round-trip in that path.
Scope enforcement therefore lives in the tool functions themselves (each calls
check_scope()/get_token_payload() from mcp_server/auth_middleware.py at the top
of its body), not in this file — that way it applies identically whether a tool
is invoked in-process by the agent or via this stdio server.

This file just registers the 13 tool functions on a FastMCP instance so
they're also reachable over stdio, and performs the one-time startup_check()
so get_token_payload() has something to return when those tools run here.

NOTE on store-scoped RBAC: the manager/store restrictions added to the tool
functions (mcp_server/auth_middleware.py's require_store_access /
resolve_scoped_store_id / filter_store_ids_for_caller, keyed off a
contextvars.ContextVar set per-investigation) are driven by a CallerContext
that agent/orchestrator.run() sets per-investigation on the live investigation
path. This stdio server never goes through that path — an external MCP
client here authenticates with the single service token via startup_check(),
with no per-request manager/admin distinction, same as check_scope's
_token_payload. So this file sets one admin/unrestricted CallerContext for
the whole process at startup (see below) rather than leaving it unset, which
would otherwise make every store-scoped tool call fail closed here. If this
stdio path ever needs manager-style restriction per external client, it needs
its own way to establish a CallerContext per connection — out of scope here.

Registered tools:
    From tools/sales.py:        get_sales_data, get_stores_with_sales_decline,
                                 get_stores_with_sku_decline,
                                 get_top_declining_skus_for_store
    From tools/inventory.py:    get_inventory_levels, get_replenishment_history,
                                 get_low_stock_items_for_store
    From tools/returns.py:      get_return_reasons, get_product_listing_changes
    From tools/customers.py:    get_customer_complaints
    From tools/promotions.py:   get_promotion_performance, get_underperforming_promotions
    From tools/suppliers.py:    get_delivery_performance         (was SOORYA — DO NOT EDIT, edited with approval)
    From tools/knowledge.py:    knowledge_search                  (SOORYA — DO NOT EDIT)
"""

import os

from fastmcp import FastMCP

from logging_config import get_logger

from .tools.sales import (
    get_sales_data,
    get_stores_with_sales_decline,
    get_stores_with_sku_decline,
    get_top_declining_skus_for_store,
)
from .tools.inventory import (
    get_inventory_levels,
    get_replenishment_history,
    get_low_stock_items_for_store,
)
from .tools.returns import get_return_reasons, get_product_listing_changes
from .tools.customers import get_customer_complaints
from .tools.promotions import get_promotion_performance, get_underperforming_promotions
from .tools.suppliers import get_delivery_performance
from .tools.knowledge import knowledge_search
from . import auth_middleware

logger = get_logger("mcp.server")

mcp = FastMCP("ROD MCP Server")

mcp.tool()(get_sales_data)
mcp.tool()(get_stores_with_sales_decline)
mcp.tool()(get_stores_with_sku_decline)
mcp.tool()(get_top_declining_skus_for_store)
mcp.tool()(get_inventory_levels)
mcp.tool()(get_replenishment_history)
mcp.tool()(get_low_stock_items_for_store)
mcp.tool()(get_return_reasons)
mcp.tool()(get_product_listing_changes)
mcp.tool()(get_customer_complaints)
mcp.tool()(get_promotion_performance)
mcp.tool()(get_underperforming_promotions)
mcp.tool()(get_delivery_performance)
mcp.tool()(knowledge_search)


if __name__ == "__main__":
    # Validates MCP_AUTH_TOKEN once at startup and caches its payload so the
    # check_scope() calls inside each tool function have something to check
    # against. Exits the process if the token is missing/malformed/expired.
    auth_middleware.startup_check(os.environ.get("MCP_AUTH_TOKEN", ""))

    # This process has no per-investigation caller (see NOTE above) — only
    # the one service token for its whole lifetime, same as check_scope's
    # _token_payload. Set an admin/unrestricted CallerContext once so the
    # new store-scope checks (require_store_access / resolve_scoped_store_id)
    # behave the way this server always did — rather than failing closed with
    # NO_CALLER_CONTEXT on every store-scoped tool call, which would be a
    # regression for existing external clients, not a security improvement.
    auth_middleware.set_caller_context(role="admin", store_id=None)

    logger.info("ROD MCP stdio server starting", extra={"event": "mcp_server_start"})
    print("ROD MCP Server starting — 13 tools registered, scope-checked per call")
    mcp.run(transport="stdio")