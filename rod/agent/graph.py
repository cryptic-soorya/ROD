"""
agent/graph.py

LangGraph replacement for the manual while-loop in agent/react_loop.py.
Same contract as react_loop.run_investigation(): takes an anomaly
description + investigation_id, returns the same-shaped result dict
(status/root_cause/confidence_score/anomaly_category/evidence/
recommendations/estimated_impact/generated_at/total_iterations/
reached_final_answer), so callers don't need to change.

Graph shape:
    agent ──(tool_calls present)──> tools ──(iterations < cap)──> agent
      │                                │
      └──(no tool_calls)──> finalize <─┘──(iterations >= cap)──> finalize

Mirrors react_loop.run_investigation()'s exact termination semantics:
    - Model returns a text-only turn (no tool_calls)  → reached_final_answer=True
    - MAX_ITERATIONS agent turns used and the last one still requested
      tools → those tools still execute (evidence is preserved) but the
      graph does not call the model again → reached_final_answer=False,
      forced confidence 0.0 / status escalated (never a silent 0.5 default).
"""

import os
import time
from datetime import datetime, timezone
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, HumanMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from agent.tools import ALL_TOOLS, TOOL_MAP
from agent.prompts import SYSTEM_PROMPT
from agent.confidence import evaluate_confidence
from agent.classifier import gibberish_rejection_reason
from agent.grounding import check_grounding
from agent.report_parsing import extract_json_report
from logging_config import get_logger

logger = get_logger("agent.graph")

MODEL = "gemini-3.1-flash-lite"
MAX_ITERATIONS = 10

# Same retry/backoff shape as react_loop._call_gemini_with_retry — one
# ChatGoogleGenerativeAI client per configured key, rotate across them on
# failure, only sleep once every key in the pool has been tried once.
MAX_API_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2


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
_LLMS = [
    ChatGoogleGenerativeAI(model=MODEL, google_api_key=key).bind_tools(ALL_TOOLS)
    for key in _GEMINI_KEYS
]
_client_cursor = 0  # rotates which key each new investigation starts from


class GraphCallError(Exception):
    """Raised when the model call fails after exhausting all retries across all keys."""


def _call_llm_with_retry(messages: list) -> AIMessage:
    global _client_cursor
    last_error: Exception | None = None
    start = _client_cursor
    _client_cursor = (_client_cursor + 1) % len(_LLMS)

    for attempt in range(1, MAX_API_RETRIES + 1):
        key_idx = (start + attempt - 1) % len(_LLMS)
        try:
            return _LLMS[key_idx].invoke(messages)
        except Exception as e:
            last_error = e
            logger.warning(
                f"llm call attempt {attempt}/{MAX_API_RETRIES} failed (key {key_idx + 1}/{len(_LLMS)})",
                extra={"event": "gemini_call_retry", "error_type": type(e).__name__},
            )
            if attempt < MAX_API_RETRIES and attempt % len(_LLMS) == 0:
                time.sleep(RETRY_BACKOFF_SECONDS * (2 ** (attempt // len(_LLMS) - 1)))
    logger.error(
        f"llm call failed after {MAX_API_RETRIES} attempts across {len(_LLMS)} key(s)",
        extra={"event": "gemini_call_exhausted", "error_type": type(last_error).__name__},
    )
    raise GraphCallError(f"llm call failed after {MAX_API_RETRIES} attempts: {last_error}") from last_error


def _message_text(message: AIMessage) -> str:
    """
    ChatGoogleGenerativeAI's AIMessage.content is sometimes a plain string,
    sometimes a list of content-part dicts (e.g. [{"type": "text", "text":
    ..., "extras": {...}}]) — normalize to plain text the same way
    react_loop._extract_json_report expects.
    """
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "") for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return str(content)


class InvestigationState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    investigation_id: str
    iterations: int
    evidence_trail: list[dict]
    result: dict | None


def agent_node(state: InvestigationState) -> dict:
    response = _call_llm_with_retry(state["messages"])
    return {"messages": [response], "iterations": state["iterations"] + 1}


def tools_node(state: InvestigationState) -> dict:
    last = state["messages"][-1]
    tool_messages = []
    new_evidence = []

    for call in last.tool_calls:
        fn = TOOL_MAP.get(call["name"])
        if fn is None:
            logger.warning(
                f"unknown tool requested: {call['name']}",
                extra={"event": "unknown_tool", "error_type": "UNKNOWN_TOOL", "investigation_id": state["investigation_id"]},
            )
            result = {"error": "UNKNOWN_TOOL", "message": f"No tool named '{call['name']}'", "tool": call["name"]}
        else:
            try:
                result = fn.invoke(call["args"])
            except Exception as e:
                logger.error(
                    f"tool '{call['name']}' raised during execution",
                    extra={"event": "tool_exception", "error_type": type(e).__name__, "investigation_id": state["investigation_id"]},
                    exc_info=True,
                )
                result = {"error": "TOOL_EXCEPTION", "message": str(e), "tool": call["name"]}

        new_evidence.append({
            "step": state["iterations"],
            "tool": call["name"],
            "args": call["args"],
            "finding": result,
        })
        tool_messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))

    return {
        "messages": tool_messages,
        "evidence_trail": state["evidence_trail"] + new_evidence,
    }


def route_after_agent(state: InvestigationState) -> str:
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else "finalize"


def route_after_tools(state: InvestigationState) -> str:
    # Tools from the MAX_ITERATIONS-th agent turn still execute (evidence
    # preserved) but we never call the model an 11th time — matches
    # react_loop.run_investigation()'s `while iterations < MAX_ITERATIONS`.
    return "finalize" if state["iterations"] >= MAX_ITERATIONS else "agent"


def finalize_node(state: InvestigationState) -> dict:
    last_ai = next(
        (m for m in reversed(state["messages"]) if isinstance(m, AIMessage)),
        None,
    )
    reached_final_answer = bool(last_ai) and not getattr(last_ai, "tool_calls", None)

    grounding_warnings: list[str] = []

    if reached_final_answer:
        final_text = _message_text(last_ai)
        parsed = extract_json_report(final_text) or {}
        confidence_score = float(parsed.get("confidence_score", 0.5))
        root_cause = parsed.get("root_cause", final_text)

        # Don't let a narrative that stitches together independently-true
        # facts from separate tool calls (e.g. "supplier X delayed store Y")
        # auto-complete on the model's own self-reported confidence — check
        # that every entity it named, and every cross-entity link it implies,
        # actually appeared together in some tool result. See agent/grounding.py.
        grounding_warnings = check_grounding(root_cause, state["evidence_trail"])
        if grounding_warnings:
            confidence_score = min(confidence_score, 0.4)
            logger.warning(
                f"investigation {state['investigation_id']} root_cause failed grounding check "
                f"({len(grounding_warnings)} warning(s)) — confidence capped at {confidence_score}",
                extra={"event": "grounding_check_failed", "investigation_id": state["investigation_id"]},
            )

        status = evaluate_confidence(confidence_score, state["iterations"])
    else:
        parsed = {}
        confidence_score = 0.0
        status = "escalated"
        root_cause = (
            f"Investigation did not reach a conclusion within {MAX_ITERATIONS} "
            "iterations. Partial evidence was collected but no final answer "
            "was produced — see evidence trail for what was gathered so far."
        )
        logger.warning(
            f"investigation {state['investigation_id']} exhausted {MAX_ITERATIONS} iterations without a final answer",
            extra={"event": "investigation_exhausted", "investigation_id": state["investigation_id"]},
        )

    result = {
        "investigation_id": state["investigation_id"],
        "status": status,
        "root_cause": root_cause,
        "confidence_score": confidence_score,
        "anomaly_category": parsed.get("anomaly_category", "unknown"),
        "evidence": state["evidence_trail"],
        "recommendations": parsed.get("recommendations", []),
        "estimated_impact": parsed.get("estimated_impact", ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_iterations": state["iterations"],
        "reached_final_answer": reached_final_answer,
        "grounding_warnings": grounding_warnings,
    }
    return {"result": result}


def _build_graph():
    graph = StateGraph(InvestigationState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("finalize", finalize_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", route_after_agent, {"tools": "tools", "finalize": "finalize"})
    graph.add_conditional_edges("tools", route_after_tools, {"agent": "agent", "finalize": "finalize"})
    graph.add_edge("finalize", END)
    return graph.compile()


_GRAPH = _build_graph()

# Recursion limit: each (agent -> tools -> agent) round trip is 2 graph
# "supersteps", plus the final -> finalize hop. MAX_ITERATIONS agent turns
# means up to ~2*MAX_ITERATIONS+1 steps; pad generously so the graph's own
# limit is never what cuts a run short — MAX_ITERATIONS inside the nodes is
# the real, intentional cap.
_RECURSION_LIMIT = (MAX_ITERATIONS * 2) + 10


def run_investigation(anomaly_description: str, investigation_id: str) -> dict:
    """
    Entry point — same contract as react_loop.run_investigation(): takes an
    anomaly description, runs the graph, returns the same-shaped report dict.
    """
    # Deterministic gibberish gate — runs before any LLM call, so it can't
    # be skipped by the model ignoring SYSTEM_PROMPT's own instruction to
    # refuse gibberish (see agent/classifier.py for why that alone wasn't
    # reliable). react_loop.run() already special-cases a zero-evidence
    # result as "rejected before any tool call" and routes it around
    # compile_report(), so this only needs to produce that same shape.
    rejection_reason = gibberish_rejection_reason(anomaly_description)
    if rejection_reason:
        logger.info(
            f"investigation {investigation_id} rejected before any tool call: {rejection_reason}",
            extra={"event": "query_rejected_gibberish", "investigation_id": investigation_id},
        )
        return {
            "investigation_id": investigation_id,
            "status": "escalated",
            "root_cause": (
                f"{rejection_reason} This does not describe a recognizable "
                "retail anomaly and cannot be investigated."
            ),
            "confidence_score": 0.0,
            "anomaly_category": "unknown",
            "evidence": [],
            "recommendations": [
                "Resubmit with a specific description of the anomaly, "
                "including the affected store, SKU, or symptom."
            ],
            "estimated_impact": "",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_iterations": 0,
            "reached_final_answer": True,
            "grounding_warnings": [],
        }

    initial_state: InvestigationState = {
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=f"Investigate this anomaly:\n\n{anomaly_description}"),
        ],
        "investigation_id": investigation_id,
        "iterations": 0,
        "evidence_trail": [],
        "result": None,
    }
    final_state = _GRAPH.invoke(initial_state, config={"recursion_limit": _RECURSION_LIMIT})
    return final_state["result"]
