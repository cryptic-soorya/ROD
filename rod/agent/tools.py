"""
agent/tools.py

LangChain tool wrappers that call the real MCP server (mcp_server/http_server.py)
via an actual fastmcp.Client, for use by the LangGraph ReAct agent
(agent/graph.py).

THIS IS A REAL MCP TOOL CALL OVER A REAL NETWORK CONNECTION, NOT A FUNCTION
CALL WEARING AN MCP COSTUME: each wrapper below does
`await client.call_tool(name, args)` against MCP_SERVER_URL — a genuine HTTP
loopback connection to mcp_server/http_server.py, a SEPARATE PROCESS from
this app. Request goes through a real TCP/HTTP round trip -> tools/call ->
JSON-serializable arguments -> the server's dispatch/schema validation -> the
tool function body -> a CallToolResult response parsed back out. Compare to
before this change, when this file used fastmcp's in-memory ClientTransport
(same process, no socket at all) — and before that, when it imported and
called `_get_inventory_levels(...)` etc. directly as plain Python functions
with no protocol involved at all.

Why a real HTTP connection now (not in-memory): the MCP server is meant to
be reachable as its own service — not just from this app's process — so the
client/server boundary needs to be a real one. The tradeoff versus the old
in-memory transport is real: every tool call now costs an actual network
round trip (still loopback by default, see mcp_server/http_server.py), and
the server being its own process means it needs its own lifecycle
(started/stopped/health-checked independently of main.py).

Business logic — DB access, scope checks (check_scope/get_token_payload),
store-scoped RBAC (require_store_access/resolve_scoped_store_id), and error
shapes — all still lives entirely in mcp_server/tools/*.py, owned by their
respective teammates, and is untouched by this change: the MCP server calls
the exact same tool function bodies either way. In particular
mcp_server/tools/suppliers.py and mcp_server/tools/knowledge.py are marked
"SOORYA — DO NOT EDIT", and this file still never modifies them — it just
calls them through the server instead of importing them directly.

RBAC across the client/server boundary, NOW A REAL PROCESS BOUNDARY:
contextvars.ContextVar (the old mechanism) cannot cross a network hop, so
agent/orchestrator.run() no longer sets the server's CallerContext directly.
Instead `set_caller_headers()` below stores the human caller's role/store_id
(read off their own verified JWT — see agent/orchestrator.py) in a
ContextVar *on this side*, and _call_tool() reads it back and sends it as
X-Caller-Role / X-Caller-Store-Id headers on every MCP HTTP request.
mcp_server/auth_middleware.py's CallerContextMiddleware reads those headers
server-side and sets ITS OWN CallerContext ContextVar for the duration of
that single tool call — same require_store_access()/resolve_scoped_store_id()
contract as before, just carried over the wire instead of shared process
memory. Isolation across concurrent investigations still holds: this side's
ContextVar is set once per investigation's own asyncio task (same as
before), and the server sets its copy fresh per incoming HTTP request/task,
so two concurrent investigations' headers never cross-contaminate either
side.

ASYNC: every wrapper below is `async def`, calling `await client.call_tool()`
— fastmcp's Client is async-only. This is why agent/graph.py's tools_node,
agent_node, and agent/orchestrator.run() all became async in this same
change (LangChain's @tool auto-generates an async `.ainvoke()` coroutine
from an `async def` function, so no extra wrapping is needed there).

Tool names, descriptions, and per-arg descriptions are carried over
verbatim from the previous google.genai FunctionDeclaration definitions in
agent/react_loop.py (_TOOL_DECLARATIONS) so tool-selection behavior does not
regress just because the framework/transport changed — with three
deliberate exceptions, unchanged from before this migration:
  1. get_customer_complaints: date_range uses the comma-separated format
     ('YYYY-MM-DD,YYYY-MM-DD') that customers.py's _parse_date_range() actually
     parses.
  2. get_customer_complaints: product_id, store_id, date_range, and category
     are now all optional and combinable, with a docstring that says
     explicitly when to call this tool vs. skip it.
  3. get_stores_with_sku_decline is new (no react_loop.py precedent).
"""

import contextvars
import os
from typing import Any, Optional

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from langchain_core.tools import tool

from mcp_server.auth_middleware import CALLER_ROLE_HEADER, CALLER_STORE_HEADER

# The real MCP server process (mcp_server/http_server.py) this app now talks
# to over the network — a separate deployable, not something main.py spawns.
# Defaults to loopback since http_server.py binds to 127.0.0.1 by default too.
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8765/mcp")

# The human caller's role/store_id for the investigation currently running
# in this asyncio task — set once per investigation by set_caller_headers()
# (called from agent/orchestrator.run(), same place that used to call
# mcp_server.auth_middleware.set_caller_context() directly back when the
# server shared this process). A ContextVar, not a plain module global, for
# the same reason auth_middleware.py's own CallerContext is one: concurrent
# investigations under FastAPI BackgroundTasks must not leak each other's
# store scope, and contextvars.Context is inherited per-asyncio-task, not
# shared across them.
_caller_headers: "contextvars.ContextVar[dict[str, str]]" = contextvars.ContextVar(
    "caller_headers", default={}
)


def set_caller_headers(role: str, store_id: Optional[str]) -> None:
    """
    Called once per investigation, before any tool call happens — mirrors
    the old set_caller_context() call site in agent/orchestrator.run(), but
    stores the value here (client-side) instead of writing directly into
    the server's CallerContext, since that's now a different process.
    role/store_id must come from the human caller's own verified JWT, never
    from `context`/`query` or any LLM-suppliable tool argument.
    """
    headers = {CALLER_ROLE_HEADER: role}
    if store_id is not None:
        headers[CALLER_STORE_HEADER] = store_id
    _caller_headers.set(headers)


async def _call_tool(name: str, arguments: dict[str, Any]) -> dict:
    """
    Calls `name` on the standalone MCP HTTP server and returns a plain
    JSON-safe dict, in the same shape mcp_server/tools/*.py functions have
    always returned directly — so report_parsing.py, grounding.py,
    confidence.py, and agent/graph.py's evidence trail / grounding checks
    don't need to know or care that a real network round trip happened in
    between.

    A fresh `async with Client(...)` is opened per call rather than one
    long-lived session for the whole app: a fastmcp Client's session is
    meant to be entered/exited per logical unit of work, and this also
    means a fresh TCP connection (or one drawn from httpx's own connection
    pool) is used per call rather than holding one connection open across
    unrelated, possibly-concurrent investigations.

    raise_on_error=False so a tool-side exception comes back as a
    CallToolResult with is_error=True instead of raising a ToolError here —
    converted to the same {"error", "message", "tool"} shape
    agent/graph.py's tools_node already used for its own exception-handling
    branch, so callers don't need two different failure shapes to handle.
    """
    transport = StreamableHttpTransport(MCP_SERVER_URL, headers=_caller_headers.get())
    async with Client(transport) as client:
        result = await client.call_tool(name, arguments, raise_on_error=False)

    if result.is_error:
        # result.content is a list of TextContent blocks; fastmcp puts the
        # error message in the first one (see ctx_test.py-style probing
        # during development — never a raw exception object here).
        message = (
            result.content[0].text
            if result.content and hasattr(result.content[0], "text")
            else "MCP tool call failed with no further detail."
        )
        return {"error": "TOOL_EXCEPTION", "message": message, "tool": name}

    # result.data is the structured return value FastMCP parsed back out of
    # the tool's declared output schema (a plain dict here, since every
    # tool in mcp_server/tools/*.py returns dict). Tools already return
    # their own {"error": ...} dicts for expected failure cases (DB errors,
    # validation, RBAC denials) — those pass through unchanged as
    # result.data, not as result.is_error, exactly as before this change.
    return result.data


@tool(parse_docstring=True)
async def get_sales_data(store_id: str, period: str = "last_30_days") -> dict:
    """Returns sales revenue for a store in the requested period. Use this to check if revenue dropped around the time of the anomaly.

    Args:
        store_id: Store identifier e.g. 'STORE-001'.
        period: 'last_7_days' | 'last_30_days' | 'last_quarter'.
    """
    return await _call_tool("get_sales_data", {"store_id": store_id, "period": period})


@tool(parse_docstring=True)
async def get_stores_with_sales_decline(period: str = "last_30_days", limit: int = 5) -> dict:
    """Scans ALL stores and returns the ones with the largest revenue decline, worst first. Call this FIRST when the anomaly description does not name a specific store AND does not name a specific SKU — it has no required identifier. If a SKU is already known, call get_stores_with_sku_decline instead, since this tool has no awareness of any particular product and may surface stores that don't even carry it. Use its results to pick which store_id to investigate further with the other tools.

    Args:
        period: 'last_7_days' | 'last_30_days' | 'last_quarter'.
        limit: Max stores to return, 1-15 (default 5).
    """
    return await _call_tool("get_stores_with_sales_decline", {"period": period, "limit": limit})


@tool(parse_docstring=True)
async def get_stores_with_sku_decline(
    sku_id: str, period: str = "last_30_days", limit: Optional[int] = None
) -> dict:
    """Finds EVERY store that carries the given SKU and returns revenue current-vs-previous for each, worst decline first — not just a top-N of decliners. Call this FIRST instead of get_stores_with_sales_decline whenever the anomaly already names a SKU: since the SKU is already known, checking only a handful of stores would ignore ones you were explicitly given. It scopes the scan to stores confirmed to stock that SKU (via inventory records), so you don't waste a get_inventory_levels call on a store that never carried it. Stores with no prior-period revenue still appear, with change_pct as null. Use its results to pick which store_id(s) to investigate further.

    Args:
        sku_id: SKU identifier e.g. 'SKU-7782'.
        period: 'last_7_days' | 'last_30_days' | 'last_quarter'.
        limit: Optional cap on number of stores returned, 1-50. Omit to get all stores that carry the SKU — do this by default so no affected store is missed.
    """
    return await _call_tool(
        "get_stores_with_sku_decline", {"sku_id": sku_id, "period": period, "limit": limit}
    )


@tool(parse_docstring=True)
async def get_top_declining_skus_for_store(store_id: str, period: str = "last_30_days", limit: int = 5) -> dict:
    """Given a store already known to have a revenue decline (e.g. from get_stores_with_sales_decline), breaks that decline down by SKU and returns the worst-declining SKUs at that store, worst first. Call this to go from "this store is down" to "this SKU is why" instead of guessing a SKU.

    Args:
        store_id: Store identifier e.g. 'STORE-001'.
        period: 'last_7_days' | 'last_30_days' | 'last_quarter'.
        limit: Max SKUs to return, 1-15 (default 5).
    """
    return await _call_tool(
        "get_top_declining_skus_for_store", {"store_id": store_id, "period": period, "limit": limit}
    )


@tool(parse_docstring=True)
async def get_inventory_levels(sku: str, store_id: str) -> dict:
    """Returns current inventory metrics for a SKU at a specific store. Use when investigating stockouts or low stock.

    Args:
        sku: SKU identifier e.g. 'SKU-7782'.
        store_id: Store identifier e.g. 'STORE-001'.
    """
    return await _call_tool("get_inventory_levels", {"sku": sku, "store_id": store_id})


@tool(parse_docstring=True)
async def get_replenishment_history(sku: str, store_id: str, days: int = 30) -> dict:
    """Returns replenishment order history for a SKU at a store. Use to check if restocking orders were placed and fulfilled on time.

    Args:
        sku: SKU identifier.
        store_id: Store identifier.
        days: How many days back to look (default 30).
    """
    return await _call_tool(
        "get_replenishment_history", {"sku": sku, "store_id": store_id, "days": days}
    )


@tool(parse_docstring=True)
async def get_low_stock_items_for_store(store_id: str, limit: int = 10) -> dict:
    """Returns the SKUs at a store currently at or below their reorder point (worst first), plus any full stockouts. Call this FIRST when a stockout or low-stock issue is suspected at a store but the specific SKU isn't known yet — get_inventory_levels needs a SKU this tool can supply.

    Args:
        store_id: Store identifier e.g. 'STORE-001'.
        limit: Max SKUs to return, 1-50 (default 10).
    """
    return await _call_tool("get_low_stock_items_for_store", {"store_id": store_id, "limit": limit})


@tool(parse_docstring=True)
async def get_return_reasons(sku: str, days: int = 14, store_id: Optional[str] = None) -> dict:
    """Returns a breakdown of return reasons for a SKU. Use when investigating return spikes to find what customers are complaining about. Pass store_id to isolate returns from a single store (e.g. a suspected bad batch or store-specific handling issue) instead of aggregating across every store that returned this SKU.

    Args:
        sku: SKU identifier.
        days: How many days back to analyze (default 14, max 365).
        store_id: Optional store identifier to isolate to, e.g. 'STORE-001'. Omit to aggregate across all stores.
    """
    return await _call_tool(
        "get_return_reasons", {"sku": sku, "days": days, "store_id": store_id}
    )


@tool(parse_docstring=True)
async def get_product_listing_changes(sku: str, since: str) -> dict:
    """Returns listing change history for a SKU (size charts, descriptions, images). Use when returns spike to check if a listing change caused customer confusion.

    Args:
        sku: SKU identifier.
        since: ISO date string e.g. '2026-06-01'. Must not be a future date.
    """
    return await _call_tool("get_product_listing_changes", {"sku": sku, "since": since})


@tool(parse_docstring=True)
async def get_customer_complaints(
    sku_id: Optional[str] = None,
    store_id: Optional[str] = None,
    date_range: Optional[str] = None,
    category: Optional[str] = None,
) -> dict:
    """Returns customer complaint data, optionally filtered by sku, store, date range, and/or category, in any combination. Useful whenever customer sentiment could plausibly explain the anomaly — return/complaint spikes, sizing or quality issues, AND sales decline investigations (complaints are a common root cause behind a store or SKU losing revenue). Narrow with store_id/product_id/date_range to the anomaly's own scope rather than pulling the whole table. Skip only when the anomaly is purely operational/supply-side with no plausible customer-facing angle (e.g. a supplier delivery delay or a pure inventory-replenishment miscount) — don't call it reflexively on every investigation regardless of what the other tools already showed. All args are optional; call with no args only if you genuinely need the full unscoped picture.

    Args:
        sku_id: Optional sku identifier to filter to, e.g. 'SKU-7782'.
        store_id: Optional store identifier to filter to, e.g. 'STORE-001'.
        date_range: Optional date range, format 'YYYY-MM-DD,YYYY-MM-DD' e.g. '2026-06-01,2026-06-30'.
        category: Optional filter: 'sizing' | 'quality' | 'delivery' | 'listing'.
    """
    return await _call_tool(
        "get_customer_complaints",
        {"sku_id": sku_id, "store_id": store_id, "date_range": date_range, "category": category},
    )


@tool(parse_docstring=True)
async def get_promotion_performance(promo_id: str) -> dict:
    """Returns promotion performance metrics. Use when investigating why a promotion underperformed its projected uplift.

    Args:
        promo_id: Promotion identifier e.g. 'PROMO-2026-01'.
    """
    return await _call_tool("get_promotion_performance", {"promo_id": promo_id})


@tool(parse_docstring=True)
async def get_underperforming_promotions(
    store_id: Optional[str] = None, period_days: int = 30, limit: int = 5
) -> dict:
    """Scans promotions that ended within the last period_days and returns the ones flagged as underperforming, worst shortfall first. Call this FIRST instead of get_promotion_performance when investigating a promotion underperformance anomaly but the specific promo_id isn't known yet.

    Args:
        store_id: Optional store identifier to scan, e.g. 'STORE-001'. Omit to scan every store's promotions.
        period_days: How many days back a promotion must have ended to be included (default 30).
        limit: Max promotions to return, 1-15 (default 5).
    """
    return await _call_tool(
        "get_underperforming_promotions",
        {"store_id": store_id, "period_days": period_days, "limit": limit},
    )


@tool(parse_docstring=True)
async def get_delivery_performance(
    supplier_id: str, period: str = "last_30_days", store_id: Optional[str] = None
) -> dict:
    """Returns supplier delivery performance vs their historical baseline. degradation_flag=True means current delivery time exceeds 150% of baseline. Use when investigating supply chain issues or stockouts. Pass store_id to isolate deliveries to a single store instead of aggregating across every store this supplier serves — a supplier can serve many stores while only one is actually affected.

    Args:
        supplier_id: Supplier identifier e.g. 'SUP-019'.
        period: 'last_7_days' | 'last_30_days' | 'last_quarter'.
        store_id: Optional store identifier to isolate to, e.g. 'STORE-001'. Omit to aggregate across all stores this supplier serves.
    """
    return await _call_tool(
        "get_delivery_performance",
        {"supplier_id": supplier_id, "period": period, "store_id": store_id},
    )


@tool(parse_docstring=True)
async def knowledge_search(query: str, n_results: int = 2) -> dict:
    """Semantic search over SOPs and past investigation cases. Call this to find relevant procedures or historical patterns that match the current anomaly. Can be called multiple times with different queries as you learn more.

    Args:
        query: Natural language description of what you're looking for.
        n_results: Number of results to return, 1-5 (default 2).
    """
    return await _call_tool("knowledge_search", {"query": query, "n_results": n_results})


# Same intent as react_loop.py's TOOL_REGISTRY: a name -> tool lookup, plus
# the ordered list agent/graph.py binds to the model.
ALL_TOOLS = [
    get_sales_data,
    get_stores_with_sales_decline,
    get_stores_with_sku_decline,
    get_top_declining_skus_for_store,
    get_inventory_levels,
    get_replenishment_history,
    get_low_stock_items_for_store,
    get_return_reasons,
    get_product_listing_changes,
    get_customer_complaints,
    get_promotion_performance,
    get_underperforming_promotions,
    get_delivery_performance,
    knowledge_search,
]

TOOL_MAP = {t.name: t for t in ALL_TOOLS}