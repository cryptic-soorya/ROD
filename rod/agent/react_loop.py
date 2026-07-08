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
    - loop exhausted without a final answer → status = escalated,
      confidence forced to 0.0 (see run_investigation for details)
"""

import os
import json
import re
import time
from datetime import datetime, timezone

from google import genai
from google.genai import types

from mcp_server.tools.sales import get_sales_data, get_stores_with_sales_decline
from mcp_server.tools.inventory import get_inventory_levels, get_replenishment_history
from mcp_server.tools.returns import get_return_reasons, get_product_listing_changes
from mcp_server.tools.customers import get_customer_complaints
from mcp_server.tools.promotions import get_promotion_performance
from mcp_server.tools.suppliers import get_delivery_performance
from mcp_server.tools.knowledge import knowledge_search

from agent.prompts import SYSTEM_PROMPT
from agent.confidence import evaluate_confidence
from logging_config import get_logger

logger = get_logger("agent.react_loop")

# ── Gemini client pool ────────────────────────────────────────────────────────
# Reads GEMINI_API_KEY_1..GEMINI_API_KEY_5 from environment and builds one
# client per configured key, so _call_gemini_with_retry can rotate across them
# (spreads load, and lets a rate-limited key get bypassed by trying the next
# one instead of just backing off on the same key). Falls back to the single
# GEMINI_API_KEY for backward compatibility if none of the numbered vars are set.
def _load_gemini_keys() -> list[str]:
    keys = [
        key for i in range(1, 6)
        if (key := os.environ.get(f"GEMINI_API_KEY_{i}")) and not key.startswith("replace-with")
    ]
    if keys:
        return keys
    single = os.environ.get("GEMINI_API_KEY")
    if single and not single.startswith("replace-with"):
        return [single]
    raise RuntimeError(
        "No Gemini API key configured — set GEMINI_API_KEY_1..GEMINI_API_KEY_5 "
        "(or GEMINI_API_KEY as a single-key fallback)."
    )


_GEMINI_KEYS = _load_gemini_keys()
_CLIENTS = [genai.Client(api_key=key) for key in _GEMINI_KEYS]
_client_cursor = 0  # rotates which key each new investigation starts from
_client = _CLIENTS[0]  # back-compat alias — tests patch this single-client name directly
MODEL = "gemini-3.1-flash-lite"
MAX_ITERATIONS = 10

# Retry config for transient Gemini API failures (timeouts, 5xx, rate limits).
# We do NOT retry on the loop's normal control flow — only around the network call.
MAX_API_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2  # doubles each attempt: 2s, 4s, 8s

# ── Tool registry ─────────────────────────────────────────────────────────────
# Maps the tool name Gemini uses → the Python function to call.
# When Gemini says "call get_sales_data", we look it up here and execute it.
TOOL_REGISTRY = {
    "get_sales_data": get_sales_data,
    "get_stores_with_sales_decline": get_stores_with_sales_decline,
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
        name="get_stores_with_sales_decline",
        description="Scans ALL stores and returns the ones with the largest revenue decline, worst first. Call this FIRST when the anomaly description does not name a specific store — it has no required identifier. Use its results to pick which store_id to investigate further with the other tools.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "period": types.Schema(type="STRING", description="'last_7_days' | 'last_30_days' | 'last_quarter'"),
                "limit": types.Schema(type="INTEGER", description="Max stores to return, 1-15 (default 5)"),
            },
            required=[],
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


class GeminiCallError(Exception):
    """Raised when generate_content fails after exhausting all retries."""


def _execute_tool(name: str, args: dict, investigation_id: str | None = None) -> dict:
    """Looks up the tool by name and calls it with the args Gemini provided."""
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        logger.warning(
            f"unknown tool requested: {name}",
            extra={"event": "unknown_tool", "error_type": "UNKNOWN_TOOL", "investigation_id": investigation_id},
        )
        return {"error": "UNKNOWN_TOOL", "message": f"No tool named '{name}'", "tool": name}
    try:
        return fn(**args)
    except Exception as e:
        logger.error(
            f"tool '{name}' raised during execution",
            extra={"event": "tool_exception", "error_type": type(e).__name__, "investigation_id": investigation_id},
            exc_info=True,
        )
        return {"error": "TOOL_EXCEPTION", "message": str(e), "tool": name}


def _call_gemini_with_retry(contents: list) -> "types.GenerateContentResponse":
    """
    Calls generate_content, rotating across the Gemini client pool on each
    attempt so a rate-limited or failing key gets bypassed by the next one.
    Only backs off with the exponential delay once every key in the pool has
    been tried in the current call (i.e. we're about to hit the same key
    twice) — no point sleeping when there's an untried key to fall through to.
    Fails loudly with GeminiCallError after MAX_API_RETRIES so callers don't
    silently proceed on a half-formed response.
    """
    global _client_cursor
    last_error: Exception | None = None
    start = _client_cursor
    _client_cursor = (_client_cursor + 1) % len(_CLIENTS)  # next call starts on a different key

    for attempt in range(1, MAX_API_RETRIES + 1):
        key_idx = (start + attempt - 1) % len(_CLIENTS)
        try:
            return _CLIENTS[key_idx].models.generate_content(
                model=MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    tools=[_TOOL_DECLARATIONS],
                    system_instruction=SYSTEM_PROMPT,
                ),
            )
        except Exception as e:  # google.genai doesn't expose a narrow, stable
            # exception hierarchy we can rely on here, so we retry broadly and
            # let the caller decide what to do once retries are exhausted.
            last_error = e
            logger.warning(
                f"generate_content attempt {attempt}/{MAX_API_RETRIES} failed (key {key_idx + 1}/{len(_CLIENTS)})",
                extra={"event": "gemini_call_retry", "error_type": type(e).__name__},
            )
            if attempt < MAX_API_RETRIES:
                # Only back off once we've cycled through every key without success.
                if attempt % len(_CLIENTS) == 0:
                    time.sleep(RETRY_BACKOFF_SECONDS * (2 ** (attempt // len(_CLIENTS) - 1)))
    logger.error(
        f"generate_content failed after {MAX_API_RETRIES} attempts across {len(_CLIENTS)} key(s)",
        extra={"event": "gemini_call_exhausted", "error_type": type(last_error).__name__},
    )
    raise GeminiCallError(
        f"generate_content failed after {MAX_API_RETRIES} attempts: {last_error}"
    ) from last_error


def _extract_json_report(text: str) -> dict | None:
    """
    Pulls the JSON report block out of Gemini's final text response.

    Gemini is asked to output raw JSON at the end, but its surrounding prose
    or a ```json fence can itself contain braces (examples, nested quotes,
    etc.), so blindly slicing from the first '{' to the last '}' can grab
    the wrong span or fail to parse. Instead:
      1. Prefer an explicit ```json fenced block if present.
      2. Otherwise scan for '{' characters and use json.JSONDecoder.raw_decode
         at each candidate start — this finds the first *complete, valid*
         JSON object regardless of what comes after it, rather than assuming
         the last '}' in the text is the right closing brace.
    """
    fence_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass  # fall through to brace-scanning below

    # Gemini is instructed to put the JSON report at the END of its response,
    # so if multiple valid JSON objects appear (e.g. an example shown earlier
    # in its reasoning), we want the LAST one, not the first.
    decoder = json.JSONDecoder()
    last_valid: dict | None = None
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            last_valid = obj
    return last_valid


def run_investigation(anomaly_description: str, investigation_id: str) -> dict:
    """
    Entry point. Takes an anomaly description, runs the ReAct loop, returns a report dict.

    The conversation history (contents) grows each iteration:
      - User turn: the anomaly description (first message only)
      - Model turn: Gemini's response (text and/or function calls)
      - Tool turn: the result of each function call. Gemini's API expects tool
        results to come back as a "user" role turn (there's no separate "tool"
        role in the Gemini content schema, unlike Anthropic's) — the
        FunctionResponse part inside it is what tells Gemini this is a tool
        result rather than a new user message.
    Gemini sees the full history on every call, so it knows what it already tried.
    """
    contents = [
        types.Content(
            role="user",
            parts=[types.Part(text=f"Investigate this anomaly:\n\n{anomaly_description}")]
        )
    ]

    evidence_trail = []   # every tool call + result, in order
    final_text = ""       # Gemini's written conclusion
    iterations = 0
    reached_final_answer = False  # True only if Gemini returned a text-only turn

    while iterations < MAX_ITERATIONS:
        iterations += 1

        response = _call_gemini_with_retry(contents)

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
            reached_final_answer = True
            break

        # Execute each tool call Gemini requested and collect results
        tool_response_parts = []
        for part in call_parts:
            fc = part.function_call
            args = dict(fc.args)  # fc.args is a MapComposite, convert to plain dict

            result = _execute_tool(fc.name, args, investigation_id=investigation_id)

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

        # Append tool results as a "user" role turn so Gemini sees them next iteration
        contents.append(types.Content(role="user", parts=tool_response_parts))

    # ── Loop ended — build the report ─────────────────────────────────────────
    if reached_final_answer:
        parsed = _extract_json_report(final_text) or {}
        confidence_score = float(parsed.get("confidence_score", 0.5))
        status = evaluate_confidence(confidence_score, iterations)
        root_cause = parsed.get("root_cause", final_text)
    else:
        # Hit MAX_ITERATIONS without Gemini ever giving a text-only final turn.
        # Don't silently fall back to the 0.5 default confidence_score — that
        # would make an exhausted, inconclusive run look like a middling-but-
        # real finding. Force it to escalated with confidence 0.0 and say why.
        parsed = {}
        confidence_score = 0.0
        status = "escalated"
        root_cause = (
            f"Investigation did not reach a conclusion within {MAX_ITERATIONS} "
            "iterations. Partial evidence was collected but no final answer "
            "was produced — see evidence trail for what was gathered so far."
        )
        logger.warning(
            f"investigation {investigation_id} exhausted {MAX_ITERATIONS} iterations without a final answer",
            extra={"event": "investigation_exhausted", "investigation_id": investigation_id},
        )

    return {
        "investigation_id": investigation_id,
        "status": status,
        "root_cause": root_cause,
        "confidence_score": confidence_score,
        "anomaly_category": parsed.get("anomaly_category", "unknown"),
        "evidence": evidence_trail,
        "recommendations": parsed.get("recommendations", []),
        "estimated_impact": parsed.get("estimated_impact", ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_iterations": iterations,
        "reached_final_answer": reached_final_answer,
    }


# ── Router-compatible entry point ─────────────────────────────────────────────
# The investigations router calls:
#   await react_run(investigation_id, query, context)
# This wrapper bridges that signature to run_investigation().

from typing import Optional
from investigations import service
from investigations.models import InvestigationStatus, AnomalyCategory, Report

from reports.generator import compile_report, ReportValidationError
from reports import service as reports_service


def _evidence_to_human_readable(evidence_trail: list) -> list[str]:
    """
    run_investigation() builds a rich evidence trail (dicts with step/tool/
    args/finding) for internal use and future structured storage, but
    Report.evidence_trail is List[str] — human-readable steps. This converts
    one to the other rather than passing the raw dicts straight through
    (which is what caused the earlier pydantic ValidationError).
    """
    lines = []
    for item in evidence_trail:
        step = item.get("step")
        tool = item.get("tool")
        args = item.get("args")
        finding = item.get("finding")
        if isinstance(finding, dict) and finding.get("error"):
            summary = finding.get("message", finding.get("error"))
            lines.append(f"Step {step}: called {tool}({args}) — error: {summary}")
        else:
            lines.append(f"Step {step}: called {tool}({args}) → {finding}")
    return lines


def _log_evidence_trail(investigation_id: int, evidence_trail: list) -> None:
    """
    Persists each run_investigation() evidence entry as a tool_calls row via
    investigations.service.log_tool_call — this is what the investigations
    API's tool_calls field and the frontend's progress view actually read.
    Without this, an investigation's evidence only ever lived inside the
    compiled report's evidence_trail (a plain string list), so a completed
    investigation with real tool calls looked like "0 iterations, no
    evidence gathered" even when run_investigation() did real work.
    """
    for item in evidence_trail:
        finding = item.get("finding")
        error = None
        if isinstance(finding, dict) and finding.get("error"):
            error = str(finding.get("message", finding.get("error")))
        service.log_tool_call(
            investigation_id,
            tool_name=item.get("tool"),
            input_args=item.get("args") or {},
            output=finding,
            error=error,
        )


def _evidence_for_compile_report(evidence_trail: list) -> list[dict]:
    """
    reports.generator.compile_report expects evidence entries shaped like
    {"step": int, "tool": str, "finding": str} — a plain string finding,
    not react_loop's raw dict tool output. This mirrors the same
    stringification _evidence_to_human_readable uses, but keeps only the
    finding text (compile_report's evidence field doesn't carry the
    "called X(args)" framing — that's specific to the internal
    investigations.models.Report.evidence_trail representation).
    """
    compiled = []
    for item in evidence_trail:
        step = item.get("step")
        tool = item.get("tool")
        finding = item.get("finding")
        if isinstance(finding, dict) and finding.get("error"):
            finding_str = str(finding.get("message", finding.get("error")))
        else:
            finding_str = str(finding)
        compiled.append({"step": step, "tool": tool, "finding": finding_str})
    return compiled


def _coerce_recommendations(raw) -> list[str]:
    """
    Report.recommendations is List[str]. The LLM's JSON output isn't
    guaranteed to match that shape exactly (it might return a dict, a
    single string, or omit the field) — coerce defensively rather than
    letting a malformed-but-plausible response blow up report persistence.
    """
    if isinstance(raw, list):
        return [str(item) for item in raw if item]
    if isinstance(raw, dict):
        # tolerate an older/malformed {"key": "value"} shape by flattening values
        return [str(v) for v in raw.values() if v]
    if isinstance(raw, str) and raw:
        return [raw]
    return []


def _recommendations_for_compile_report(raw) -> dict:
    """
    reports.generator.compile_report expects recommendations split into
    immediate / customer_recovery / process_improvement buckets (FRS 6.1).
    agent/prompts.py currently only asks Gemini for a flat list, and
    investigations.models.Report.recommendations is List[str] — neither
    produces the three-way structure yet.

    KNOWN GAP: until agent/prompts.py is updated to elicit the structured
    breakdown from Gemini, everything gets bucketed under "immediate" here
    so compile_report doesn't reject an otherwise-valid response. This is a
    compatibility shim, not the real fix — flag to whoever owns prompts.py.
    """
    if isinstance(raw, dict) and any(
        k in raw for k in ("immediate", "customer_recovery", "process_improvement")
    ):
        return {
            "immediate": list(raw.get("immediate", [])),
            "customer_recovery": list(raw.get("customer_recovery", [])),
            "process_improvement": list(raw.get("process_improvement", [])),
        }
    return {
        "immediate": _coerce_recommendations(raw),
        "customer_recovery": [],
        "process_improvement": [],
    }


def _build_fallback_report(investigation_id: str, reason: str) -> dict:
    """
    Used when compile_report() itself raises ReportValidationError (e.g.
    empty evidence, blank root_cause) — same philosophy as the existing
    GeminiCallError handling: never let a report failure vanish silently,
    persist something escalated and visible instead.
    """
    return {
        "investigation_id": investigation_id,
        "root_cause": f"Report could not be generated: {reason}",
        "confidence_score": 0.0,
        "status": "escalated",
        "anomaly_category": "unknown",
        "evidence": [],
        "recommendations": {"immediate": [], "customer_recovery": [], "process_improvement": []},
        "estimated_impact": "",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_iterations": 0,
    }


async def run(
    investigation_id: int,
    query: str,
    context: Optional[dict] = None,
) -> None:
    """
    Async wrapper around run_investigation() that matches the router's call signature.
    Compiles a canonical FRS-shaped report via reports.generator.compile_report(),
    persists it via reports.service.save_report(), and also persists the existing
    investigations.models.Report used by the investigations pipeline — so both
    consumers (the reports API and the investigations service) see consistent data.
    """
    anomaly_description = query
    if context:
        context_str = "\n".join(f"{k}: {v}" for k, v in context.items())
        anomaly_description = f"{query}\n\nContext:\n{context_str}"

    try:
        result = run_investigation(
            anomaly_description=anomaly_description,
            investigation_id=str(investigation_id),
        )
    except GeminiCallError as e:
        # The Gemini API call failed after all retries. Don't let this crash
        # the background task silently — persist a failed/escalated report so
        # the investigation is visible and actionable instead of just vanishing.
        # NOTE: assumes InvestigationStatus has no dedicated FAILED state; if
        # one exists in investigations.models, prefer it over ESCALATED here.
        logger.error(
            f"investigation {investigation_id} could not complete — Gemini call failed",
            extra={"event": "investigation_failed", "investigation_id": str(investigation_id), "error_type": "GeminiCallError"},
            exc_info=True,
        )
        report = Report(
            root_cause=f"Investigation could not complete: {e}",
            evidence_trail=[],
            confidence_score=0.0,
            anomaly_category="unknown",
            recommendations=[],
            estimated_impact=None,
            generated_at=datetime.now(timezone.utc),
        )
        service.update_status(investigation_id, InvestigationStatus.ESCALATED, report)

        fallback = _build_fallback_report(str(investigation_id), str(e))
        reports_service.save_report(fallback)
        return

    # ── Persist the raw evidence trail as individual tool_calls rows, and
    # capture the real iteration count — otherwise investigations.service
    # never hears about either (its iteration_count stays 0 and tool_calls
    # stays empty forever), even though run_investigation() gathered real
    # evidence. The frontend's progress view reads these two fields, not
    # report.evidence_trail, so without this it looks like nothing happened.
    total_iterations = result.get("total_iterations")
    _log_evidence_trail(investigation_id, result.get("evidence", []))

    # ── Compile the canonical FRS report ───────────────────────────────────
    compile_evidence = _evidence_for_compile_report(result.get("evidence", []))
    agent_summary = {
        "root_cause": result.get("root_cause", ""),
        "anomaly_category": result.get("anomaly_category", "unknown"),
        "estimated_impact": result.get("estimated_impact", ""),
        "status": result.get("status", "escalated"),
        "recommendations": _recommendations_for_compile_report(result.get("recommendations", [])),
        "total_iterations": result.get("total_iterations"),
    }

    try:
        compiled_report = compile_report(
            investigation_id=str(investigation_id),
            evidence_trail=compile_evidence,
            agent_summary=agent_summary,
            confidence_score=result.get("confidence_score", 0.0),
        )
    except ReportValidationError as e:
        # compile_report rejected the inputs (e.g. empty evidence, blank
        # root_cause). Persist a visible escalated placeholder rather than
        # losing the failure silently.
        compiled_report = _build_fallback_report(str(investigation_id), str(e))
        status = InvestigationStatus.ESCALATED
        report = Report(
            root_cause=compiled_report["root_cause"],
            evidence_trail=_evidence_to_human_readable(result.get("evidence", [])),
            confidence_score=0.0,
            anomaly_category="unknown",
            recommendations=[],
            estimated_impact=None,
            generated_at=datetime.now(timezone.utc),
        )
        service.update_status(investigation_id, status, report, iteration_count=total_iterations)
        reports_service.save_report(compiled_report)
        return

    reports_service.save_report(compiled_report)

    # ── Persist to the existing investigations pipeline too ────────────────
    status = (
        InvestigationStatus.COMPLETED
        if compiled_report["status"] == "completed"
        else InvestigationStatus.ESCALATED
    )

    report = Report(
        root_cause=compiled_report["root_cause"],
        evidence_trail=_evidence_to_human_readable(result.get("evidence", [])),
        confidence_score=compiled_report["confidence_score"],
        anomaly_category=compiled_report["anomaly_category"],
        recommendations=_coerce_recommendations(result.get("recommendations", [])),
        estimated_impact=compiled_report.get("estimated_impact") or None,
        generated_at=compiled_report["generated_at"],
    )

    service.update_status(investigation_id, status, report, iteration_count=total_iterations)