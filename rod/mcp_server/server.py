"""
mcp_server/server.py
OWNER: Team Lead

THE single MCP server for all 14 tools across mcp_server/tools/*.py. There
is exactly one `mcp` FastMCP instance in this whole app — this one — and it
is used by BOTH of the following, over two different transports:

  1. LIVE INVESTIGATION PATH (in-memory transport, no subprocess, no
     sockets): agent/tools.py builds a single shared `fastmcp.Client(mcp)`
     wrapping this exact `mcp` object and calls tools via the real MCP
     protocol (`tools/list`, `tools/call` — actual request/response
     serialization), just over an in-process anyio memory stream instead of
     a network/stdio round trip. See agent/tools.py's module docstring for
     why this is a genuine MCP call and not a disguised function call.
  2. STANDALONE STDIO SERVER (`python -m mcp_server.server`, see __main__
     below): for external MCP clients (e.g. Claude Desktop) that want to
     talk to ROD's tools directly, over real stdio.

Scope enforcement (check_scope()/get_token_payload()) and store-scoped RBAC
(require_store_access()/resolve_scoped_store_id()/filter_store_ids_for_caller())
both live inside the tool functions themselves (mcp_server/tools/*.py,
mcp_server/auth_middleware.py) — NOT in this file, and NOT in either
transport. That's deliberate: the exact same checks run identically no
matter which of the two paths above reached the tool, because the tool
function body is the one thing both paths have in common.

NOTE on store-scoped RBAC / CallerContext per path:
  - Live path: agent/orchestrator.run() calls
    auth_middleware.set_caller_context(role, store_id) once per
    investigation, read off the human manager's own verified JWT. That
    value lives in a contextvars.ContextVar. Verified (see ctx_test.py
    during development) that this propagates correctly through an
    in-memory fastmcp.Client(mcp).call_tool() — each concurrent
    investigation's context stays isolated to its own asyncio task, the
    same as it did with the old asyncio.to_thread approach, so managers
    still can't see each other's store even under concurrent
    investigations.
  - Stdio path (__main__ below): there is no per-investigation human caller
    here at all — one external MCP client authenticates with the single
    service token via startup_check(), same as check_scope's
    _token_payload. This process sets ONE admin/unrestricted CallerContext
    for its whole lifetime (see below) rather than leaving it unset, which
    would otherwise fail every store-scoped tool call closed with
    NO_CALLER_CONTEXT. If the stdio path ever needs manager-style
    restriction per external client, it needs its own way to establish a
    CallerContext per connection — out of scope here.

Registered tools:
    From tools/sales.py:        get_sales_data, get_stores_with_sales_decline,
                                 get_stores_with_sku_decline,
                                 get_top_declining_skus_for_store
    From tools/inventory.py:    get_inventory_levels, get_replenishment_history,
                                 get_low_stock_items_for_store
    From tools/returns.py:      get_return_reasons, get_product_listing_changes
    From tools/customers.py:    get_customer_complaints
    From tools/promotions.py:   get_promotion_performance, get_underperforming_promotions
    From tools/suppliers.py:    get_delivery_performance
    From tools/knowledge.py:    knowledge_search
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

TOOL_COUNT = 14  # keep in sync with the registration block above


if __name__ == "__main__":
    # Validates MCP_AUTH_TOKEN once at startup and caches its payload so the
    # check_scope() calls inside each tool function have something to check
    # against. Exits the process if the token is missing/malformed/expired.
    #
    # NOTE: this is the STDIO path's own startup check, independent of
    # main.py's startup_check() call for the live app (see main.py's
    # @app.on_event("startup")) — the two never run in the same process,
    # since this file is only executed as `python -m mcp_server.server`,
    # never imported and run by main.py.
    auth_middleware.startup_check(os.environ.get("MCP_AUTH_TOKEN", ""))

    # This process has no per-investigation caller (see module docstring
    # above) — only the one service token for its whole lifetime, same as
    # check_scope's _token_payload. Set an admin/unrestricted CallerContext
    # once so the store-scope checks (require_store_access /
    # resolve_scoped_store_id) don't fail closed with NO_CALLER_CONTEXT on
    # every call from an external stdio client.
    auth_middleware.set_caller_context(role="admin", store_id=None)

    logger.info("ROD MCP stdio server starting", extra={"event": "mcp_server_start"})
    print(f"ROD MCP Server starting — {TOOL_COUNT} tools registered, scope-checked per call")
    mcp.run(transport="stdio")