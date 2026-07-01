"""
agent/react_loop.py
OWNER: Teammate C

The core ReAct engine loop. Pattern per iteration:
    Thought  → LLM reasons about what to do next
    Action   → LLM picks a tool + arguments
    Observation → Tool result returned, appended to evidence trail

Loop terminates when:
    (a) LLM returns end_turn with final answer, OR
    (b) 10 iterations reached (hard cap — never infinite loops)

After termination:
    - confidence >= 0.7  → status = completed, report generated
    - confidence < 0.7   → status = escalated, partial evidence preserved
"""

import os
import json
import re
from datetime import datetime, timezone

from google import genai
from google.genai import types

from mcp_server.tools.sales import get_sales_data
from mcp_server.tools.inventory import get_inventory_levels, get_replenishment_history
from mcp_server.tools.returns import get_return_reasons, get_product_listing_changes
from mcp_server.tools.customers import get_customer_complaints
from mcp_server.tools.promotions import get_promotion_performance
from mcp_server.tools.suppliers import get_delivery_performance
from mcp_server.tools.knowledge import knowledge_search

from agent.prompts import SYSTEM_PROMPT
from agent.confidence import evaluate_confidence

# ── Gemini client ─────────────────────────────────────────────────────────────
# Reads GEMINI_API_KEY from environment. Fails fast if missing.
_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
MODEL = "gemini-3.1-flash-lite"
MAX_ITERATIONS = 10

# ── Tool registry ─────────────────────────────────────────────────────────────
# Maps the tool name Gemini uses → the Python function to call.
# When Gemini says "call get_sales_data", we look it up here and execute it.
TOOL_REGISTRY = {
    "get_sales_data": get_sales_data,
    "get_inventory_levels": get_inventory_levels,
    "get_replenishment_history": get_replenishment_history,
    "get_return_reasons": get_return_reasons,
    "get_product_listing_changes": get_product_listing_changes,
    "get_customer_complaints": get_customer_complaints,
    "get_promotion_performance": get_promotion_performance,
    "get_delivery_performance": get_delivery_performance,
    "knowledge_search": knowledge_search,
}

# ── Tool schemas for Gemini ───────────────────────────────────────────────────
# Gemini needs to know each tool's name, what it does, and what args it takes.
# This is equivalent to the tool_use block in Anthropic's API.
# Gemini uses JSON Schema format for parameter definitions.
_TOOL_DECLARATIONS = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="get_sales_data",
        description="Returns sales revenue for a store in the requested period. Use this to check if revenue dropped around the time of the anomaly.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "store_id": types.Schema(type="STRING", description="Store identifier e.g. 'STORE-001'"),
                "period": types.Schema(type="STRING", description="'last_7_days' | 'last_30_days' | 'last_quarter'"),
            },
            required=["store_id"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_inventory_levels",
        description="Returns current inventory metrics for a SKU at a specific store. Use when investigating stockouts or low stock.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "sku": types.Schema(type="STRING", description="SKU identifier e.g. 'SKU-7782'"),
                "store_id": types.Schema(type="STRING", description="Store identifier e.g. 'STORE-001'"),
            },
            required=["sku", "store_id"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_replenishment_history",
        description="Returns replenishment order history for a SKU at a store. Use to check if restocking orders were placed and fulfilled on time.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "sku": types.Schema(type="STRING", description="SKU identifier"),
                "store_id": types.Schema(type="STRING", description="Store identifier"),
                "days": types.Schema(type="INTEGER", description="How many days back to look (default 30)"),
            },
            required=["sku", "store_id"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_return_reasons",
        description="Returns a breakdown of return reasons for a SKU. Use when investigating return spikes to find what customers are complaining about.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "sku": types.Schema(type="STRING", description="SKU identifier"),
                "days": types.Schema(type="INTEGER", description="How many days back to analyze (default 14, max 365)"),
            },
            required=["sku"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_product_listing_changes",
        description="Returns listing change history for a SKU (size charts, descriptions, images). Use when returns spike to check if a listing change caused customer confusion.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "sku": types.Schema(type="STRING", description="SKU identifier"),
                "since": types.Schema(type="STRING", description="ISO date string e.g. '2026-06-01'"),
            },
            required=["sku", "since"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_customer_complaints",
        description="Returns customer complaint data grouped by category. Use to understand what customers are upset about during the anomaly window.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "date_range": types.Schema(type="STRING", description="Date range string e.g. '2026-06-01:2026-06-30'"),
                "category": types.Schema(type="STRING", description="Optional filter: 'sizing' | 'quality' | 'delivery' | 'listing'"),
            },
            required=["date_range"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_promotion_performance",
        description="Returns promotion performance metrics. Use when investigating why a promotion underperformed its projected uplift.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "promo_id": types.Schema(type="STRING", description="Promotion identifier e.g. 'PROMO-2026-01'"),
            },
            required=["promo_id"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_delivery_performance",
        description="Returns supplier delivery performance vs their historical baseline. degradation_flag=True means current delivery time exceeds 150% of baseline. Use when investigating supply chain issues or stockouts.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "supplier_id": types.Schema(type="STRING", description="Supplier identifier e.g. 'SUP-019'"),
                "period": types.Schema(type="STRING", description="'last_7_days' | 'last_30_days' | 'last_quarter'"),
            },
            required=["supplier_id"],
        ),
    ),
    types.FunctionDeclaration(
        name="knowledge_search",
        description="Semantic search over SOPs and past investigation cases. Call this to find relevant procedures or historical patterns that match the current anomaly. Can be called multiple times with different queries as you learn more.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "query": types.Schema(type="STRING", description="Natural language description of what you're looking for"),
                "n_results": types.Schema(type="INTEGER", description="Number of results to return, 1-5 (default 2)"),
            },
            required=["query"],
        ),
    ),
])


def _execute_tool(name: str, args: dict) -> dict:
    """Looks up the tool by name and calls it with the args Gemini provided."""
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        return {"error": "UNKNOWN_TOOL", "message": f"No tool named '{name}'", "tool": name}
    try:
        return fn(**args)
    except Exception as e:
        return {"error": "TOOL_EXCEPTION", "message": str(e), "tool": name}


def _extract_json_report(text: str) -> dict | None:
    """
    Pulls the JSON block out of Gemini's final text response.
    Gemini is asked to output raw JSON at the end — this finds and parses it.
    """
    # Find the first '{' and last '}' to extract the JSON block
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        return None
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        return None


def run_investigation(anomaly_description: str, investigation_id: str) -> dict:
    """
    Entry point. Takes an anomaly description, runs the ReAct loop, returns a report dict.

    The conversation history (contents) grows each iteration:
      - User turn: the anomaly description (first message only)
      - Model turn: Gemini's response (text and/or function calls)
      - Tool turn: the result of each function call
    Gemini sees the full history on every call, so it knows what it already tried.
    """
    # conversation history — starts with the user describing the anomaly
    contents = [
        types.Content(
            role="user",
            parts=[types.Part(text=f"Investigate this anomaly:\n\n{anomaly_description}")]
        )
    ]

    evidence_trail = []   # every tool call + result, in order
    final_text = ""       # Gemini's written conclusion
    iterations = 0

    while iterations < MAX_ITERATIONS:
        iterations += 1

        # Send the full conversation to Gemini
        response = _client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                tools=[_TOOL_DECLARATIONS],
                system_instruction=SYSTEM_PROMPT,
            ),
        )

        candidate = response.candidates[0]
        model_parts = candidate.content.parts

        # Append Gemini's response to history so it's part of the next turn
        contents.append(types.Content(role="model", parts=model_parts))

        # Separate what Gemini returned: text parts and function call parts
        text_parts = [p for p in model_parts if p.text]
        call_parts = [p for p in model_parts if p.function_call]

        # No function calls = Gemini is done reasoning, this is the final answer
        if not call_parts:
            final_text = " ".join(p.text for p in text_parts)
            break

        # Execute each tool call Gemini requested and collect results
        tool_response_parts = []
        for part in call_parts:
            fc = part.function_call
            args = dict(fc.args)  # fc.args is a MapComposite, convert to plain dict

            result = _execute_tool(fc.name, args)

            # Record in the evidence trail (this becomes the report's evidence section)
            evidence_trail.append({
                "step": iterations,
                "tool": fc.name,
                "args": args,
                "finding": result,
            })

            # Wrap the result in a FunctionResponse so Gemini can read it next turn
            tool_response_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name,
                        response={"result": result},
                    )
                )
            )

        # Append tool results as a "tool" role turn so Gemini sees them next iteration
        contents.append(types.Content(role="user", parts=tool_response_parts))

    # ── Loop ended — build the report ─────────────────────────────────────────
    # Try to parse the structured JSON Gemini was asked to include in its final text
    parsed = _extract_json_report(final_text) or {}

    confidence_score = float(parsed.get("confidence_score", 0.5))
    status = evaluate_confidence(confidence_score, iterations)

    return {
        "investigation_id": investigation_id,
        "status": status,
        "root_cause": parsed.get("root_cause", final_text),
        "confidence_score": confidence_score,
        "anomaly_category": parsed.get("anomaly_category", "unknown"),
        "evidence": evidence_trail,
        "recommendations": parsed.get("recommendations", {}),
        "estimated_impact": parsed.get("estimated_impact", ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_iterations": iterations,
    }
