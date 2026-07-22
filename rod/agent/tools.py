"""
agent/tools.py

LangChain tool wrappers around the real MCP tool functions in
mcp_server/tools/*.py, for use by the LangGraph ReAct agent (agent/graph.py).

These wrap, never reimplement, the underlying business logic — DB access,
scope checks (check_scope/get_token_payload), and error shapes all still
live in mcp_server/tools/*.py, owned by their respective teammates. In
particular mcp_server/tools/suppliers.py and mcp_server/tools/knowledge.py
are marked "SOORYA — DO NOT EDIT", so this file only imports and decorates
them; it never modifies them.

Tool names, descriptions, and per-arg descriptions are carried over
verbatim from the previous google.genai FunctionDeclaration definitions in
agent/react_loop.py (_TOOL_DECLARATIONS) so tool-selection behavior does not
regress just because the framework changed — with three deliberate exceptions:
  1. get_customer_complaints: date_range uses the comma-separated format
     ('YYYY-MM-DD,YYYY-MM-DD') that customers.py's _parse_date_range() actually
     parses. The old react_loop.py declaration described a colon-separated
     example ('2026-06-01:2026-06-30') that does not match the real parser —
     that mismatch is not carried forward here.
  2. get_customer_complaints: product_id, store_id, date_range, and category
     are now all optional and combinable (mcp_server/tools/customers.py was
     updated to filter dynamically on whatever subset is passed), and the
     docstring now says explicitly when to call this tool vs. skip it — the
     agent was calling it on nearly every investigation regardless of anomaly
     type.
  3. get_stores_with_sku_decline is new (no react_loop.py precedent) — added
     alongside get_stores_with_sales_decline so the agent stops blindly
     scanning store-wide declines when it already has a SKU in hand and then
     burning an iteration on a store that never carried that SKU
     (see mcp_server/tools/sales.py TOOL 1c). get_stores_with_sales_decline's
     docstring is updated to point at it.
"""

from typing import Optional

from langchain_core.tools import tool

from mcp_server.tools.sales import (
    get_sales_data as _get_sales_data,
    get_stores_with_sales_decline as _get_stores_with_sales_decline,
    get_stores_with_sku_decline as _get_stores_with_sku_decline,
)
from mcp_server.tools.inventory import (
    get_inventory_levels as _get_inventory_levels,
    get_replenishment_history as _get_replenishment_history,
)
from mcp_server.tools.returns import (
    get_return_reasons as _get_return_reasons,
    get_product_listing_changes as _get_product_listing_changes,
)
from mcp_server.tools.customers import get_customer_complaints as _get_customer_complaints
from mcp_server.tools.promotions import get_promotion_performance as _get_promotion_performance
from mcp_server.tools.suppliers import get_delivery_performance as _get_delivery_performance
from mcp_server.tools.knowledge import knowledge_search as _knowledge_search


@tool(parse_docstring=True)
def get_sales_data(store_id: str, period: str = "last_30_days") -> dict:
    """Returns sales revenue for a store in the requested period. Use this to check if revenue dropped around the time of the anomaly.

    Args:
        store_id: Store identifier e.g. 'STORE-001'.
        period: 'last_7_days' | 'last_30_days' | 'last_quarter'.
    """
    return _get_sales_data(store_id=store_id, period=period)


@tool(parse_docstring=True)
def get_stores_with_sales_decline(period: str = "last_30_days", limit: int = 5) -> dict:
    """Scans ALL stores and returns the ones with the largest revenue decline, worst first. Call this FIRST when the anomaly description does not name a specific store AND does not name a specific SKU — it has no required identifier. If a SKU is already known, call get_stores_with_sku_decline instead, since this tool has no awareness of any particular product and may surface stores that don't even carry it. Use its results to pick which store_id to investigate further with the other tools.

    Args:
        period: 'last_7_days' | 'last_30_days' | 'last_quarter'.
        limit: Max stores to return, 1-15 (default 5).
    """
    return _get_stores_with_sales_decline(period=period, limit=limit)


@tool(parse_docstring=True)
def get_stores_with_sku_decline(
    sku_id: str, period: str = "last_30_days", limit: Optional[int] = None
) -> dict:
    """Finds EVERY store that carries the given SKU and returns revenue current-vs-previous for each, worst decline first — not just a top-N of decliners. Call this FIRST instead of get_stores_with_sales_decline whenever the anomaly already names a SKU: since the SKU is already known, checking only a handful of stores would ignore ones you were explicitly given. It scopes the scan to stores confirmed to stock that SKU (via inventory records), so you don't waste a get_inventory_levels call on a store that never carried it. Stores with no prior-period revenue still appear, with change_pct as null. Use its results to pick which store_id(s) to investigate further.

    Args:
        sku_id: SKU identifier e.g. 'SKU-7782'.
        period: 'last_7_days' | 'last_30_days' | 'last_quarter'.
        limit: Optional cap on number of stores returned, 1-50. Omit to get all stores that carry the SKU — do this by default so no affected store is missed.
    """
    return _get_stores_with_sku_decline(sku_id=sku_id, period=period, limit=limit)


@tool(parse_docstring=True)
def get_inventory_levels(sku: str, store_id: str) -> dict:
    """Returns current inventory metrics for a SKU at a specific store. Use when investigating stockouts or low stock.

    Args:
        sku: SKU identifier e.g. 'SKU-7782'.
        store_id: Store identifier e.g. 'STORE-001'.
    """
    return _get_inventory_levels(sku=sku, store_id=store_id)


@tool(parse_docstring=True)
def get_replenishment_history(sku: str, store_id: str, days: int = 30) -> dict:
    """Returns replenishment order history for a SKU at a store. Use to check if restocking orders were placed and fulfilled on time.

    Args:
        sku: SKU identifier.
        store_id: Store identifier.
        days: How many days back to look (default 30).
    """
    return _get_replenishment_history(sku=sku, store_id=store_id, days=days)


@tool(parse_docstring=True)
def get_return_reasons(sku: str, days: int = 14) -> dict:
    """Returns a breakdown of return reasons for a SKU. Use when investigating return spikes to find what customers are complaining about.

    Args:
        sku: SKU identifier.
        days: How many days back to analyze (default 14, max 365).
    """
    return _get_return_reasons(sku=sku, days=days)


@tool(parse_docstring=True)
def get_product_listing_changes(sku: str, since: str) -> dict:
    """Returns listing change history for a SKU (size charts, descriptions, images). Use when returns spike to check if a listing change caused customer confusion.

    Args:
        sku: SKU identifier.
        since: ISO date string e.g. '2026-06-01'. Must not be a future date.
    """
    return _get_product_listing_changes(sku=sku, since=since)


@tool(parse_docstring=True)
def get_customer_complaints(
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
    return _get_customer_complaints(
        sku_id=sku_id, store_id=store_id, date_range=date_range, category=category
    )


@tool(parse_docstring=True)
def get_promotion_performance(promo_id: str) -> dict:
    """Returns promotion performance metrics. Use when investigating why a promotion underperformed its projected uplift.

    Args:
        promo_id: Promotion identifier e.g. 'PROMO-2026-01'.
    """
    return _get_promotion_performance(promo_id=promo_id)


@tool(parse_docstring=True)
def get_delivery_performance(supplier_id: str, period: str = "last_30_days") -> dict:
    """Returns supplier delivery performance vs their historical baseline. degradation_flag=True means current delivery time exceeds 150% of baseline. Use when investigating supply chain issues or stockouts.

    Args:
        supplier_id: Supplier identifier e.g. 'SUP-019'.
        period: 'last_7_days' | 'last_30_days' | 'last_quarter'.
    """
    return _get_delivery_performance(supplier_id=supplier_id, period=period)


@tool(parse_docstring=True)
def knowledge_search(query: str, n_results: int = 2) -> dict:
    """Semantic search over SOPs and past investigation cases. Call this to find relevant procedures or historical patterns that match the current anomaly. Can be called multiple times with different queries as you learn more.

    Args:
        query: Natural language description of what you're looking for.
        n_results: Number of results to return, 1-5 (default 2).
    """
    return _knowledge_search(query=query, n_results=n_results)


# Same intent as react_loop.py's TOOL_REGISTRY: a name -> tool lookup, plus
# the ordered list agent/graph.py binds to the model.
ALL_TOOLS = [
    get_sales_data,
    get_stores_with_sales_decline,
    get_stores_with_sku_decline,
    get_inventory_levels,
    get_replenishment_history,
    get_return_reasons,
    get_product_listing_changes,
    get_customer_complaints,
    get_promotion_performance,
    get_delivery_performance,
    knowledge_search,
]

TOOL_MAP = {t.name: t for t in ALL_TOOLS}