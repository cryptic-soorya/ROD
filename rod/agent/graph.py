# This file contains the core logic for an investigation system using a state graph approach. 
# It defines a state graph where each node represents a     
# state in the investigation process, and edges represent transitions
# between states. 
#  It also includes functions that manage the workflow of an investigation,
#  It manages the workflow of an investigation, including calling language models (LLMs) with retries, 
# handling tool calls, and finalizing the investigation based on the gathered evidence.
#
# The key components include:
# - StateGraph: Manages the nodes and edges representing different stages of the investigation process.
# - agent_node, tools_node, finalize_node: Functions that define the behavior at each stage of the investigation.
# - run_investigation: Entry point for running an investigation given an anomaly description.
#
# The system aims to handle multiple LLM keys for robustness and includes mechanisms for retrying API calls with exponential backoff.

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


def _find_store_denial(evidence_trail: list[dict]) -> dict | None:
    """
    Scans the evidence trail for a tool result shaped like
    {"error": "STORE_FORBIDDEN", "message": ..., "tool": ...} — the dict
    mcp_server/auth_middleware.py's require_store_access()/
    resolve_scoped_store_id() return when a manager's investigation
    requested a store outside their own. Returns the first one found, or
    None. Deliberately checks only STORE_FORBIDDEN, not NO_CALLER_CONTEXT —
    the latter signals a wiring bug (missing CallerContext), not a genuine
    access decision, and should surface as a normal escalation rather than
    being silently reframed as "you don't have access".
    """
    for item in evidence_trail:
        finding = item.get("finding")
        if isinstance(finding, dict) and finding.get("error") == "STORE_FORBIDDEN":
            return finding
    return None


class InvestigationState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    investigation_id: str
    iterations: int
    evidence_trail: list[dict]
    result: dict | None


def _turn_budget_message(iterations: int) -> HumanMessage:
    """
    A live, per-call reminder of how many turns are left — injected fresh
    into every agent_node call rather than relying solely on SYSTEM_PROMPT's
    static "aim for 4-6 turns" instruction, which is stated once at the start
    of what can become a 10+ turn tool-calling loop and reliably loses
    salience by turn 8-9 (see INV-72: solid negative evidence by iteration 6,
    but the model kept calling tools instead of concluding, then hit
    MAX_ITERATIONS with nothing to show for it).

    Deliberately NOT added to the persisted state["messages"] — see
    agent_node below — so it doesn't accumulate as repeated near-identical
    messages in the conversation history; it's rebuilt with fresh numbers
    each call instead.
    """
    used = iterations
    remaining = MAX_ITERATIONS - used
    urgency = (
        " You are close to the turn limit — stop calling tools now and give "
        "your best-supported answer from the evidence already gathered, even "
        "if it's only a partial or lower-confidence conclusion."
        if remaining <= 3 else ""
    )
    return HumanMessage(
        content=f"[Turn budget: {used}/{MAX_ITERATIONS} used, {remaining} remaining.]{urgency}"
    )


def agent_node(state: InvestigationState) -> dict:
    budget_note = _turn_budget_message(state["iterations"])
    response = _call_llm_with_retry(state["messages"] + [budget_note])
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


def _attempt_forced_conclusion(state: InvestigationState) -> AIMessage | None:
    """
    Issued only when MAX_ITERATIONS was hit without the model volunteering a
    final answer. Rather than discarding whatever evidence was already
    gathered (see INV-72: 8 solid tool calls' worth of negative evidence —
    inventory fine, no returns, no complaints, no listing changes, plus a
    knowledge_search lead the model correctly declined to chase without a
    real supplier_id — thrown away for a generic "ran out of iterations"
    message with confidence forced to 0.0), this makes one extra LLM call
    instructing the model to conclude using ONLY the evidence already in
    state["messages"], no new tool calls.

    This call does not consume additional MAX_ITERATIONS budget — it's a
    single uncounted wrap-up, not another turn of the normal loop. If the
    model still returns tool_calls here they're simply ignored by the caller
    (finalize_node) — there's no budget left to execute them regardless, and
    the point is a hard stop either way. Returns None (rather than raising)
    if the call fails after retries, so the caller can fall back to the
    original generic message instead of crashing the investigation.
    """
    wrap_up = HumanMessage(content=(
        "You have used all available tool-call turns for this investigation. "
        "Do not call any more tools — none will be executed even if you request "
        "them. Using ONLY the evidence already gathered above, produce your best "
        "final answer now, in the same JSON report format described in your "
        "instructions. If the evidence is inconclusive, say so honestly and give "
        "your best-supported partial hypothesis with an appropriately low "
        "confidence_score, rather than refusing to answer."
    ))
    try:
        return _call_llm_with_retry(state["messages"] + [wrap_up])
    except GraphCallError:
        logger.warning(
            f"investigation {state['investigation_id']} forced-conclusion call failed — "
            "falling back to generic exhausted-iterations message",
            extra={"event": "forced_conclusion_failed", "investigation_id": state["investigation_id"]},
        )
        return None


def route_after_agent(state: InvestigationState) -> str:
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else "finalize"


def route_after_tools(state: InvestigationState) -> str:
    # A store-scope denial short-circuits immediately — no point burning the
    # remaining iterations on tools that can't get the data the agent was
    # just denied. Checked before the iteration cap so it fires even on
    # iteration 1.
    if _find_store_denial(state["evidence_trail"]):
        return "finalize"
    # Tools from the MAX_ITERATIONS-th agent turn still execute (evidence
    # preserved) but we never call the model an 11th time — matches
    # react_loop.run_investigation()'s `while iterations < MAX_ITERATIONS`.
    return "finalize" if state["iterations"] >= MAX_ITERATIONS else "agent"


def finalize_node(state: InvestigationState) -> dict:
    denial = _find_store_denial(state["evidence_trail"])
    if denial:
        logger.info(
            f"investigation {state['investigation_id']} terminated early — "
            "cross-store access denied, no further tool calls attempted",
            extra={"event": "investigation_access_denied", "investigation_id": state["investigation_id"]},
        )
        result = {
            "investigation_id": state["investigation_id"],
            "status": "escalated",
            "root_cause": (
                "This investigation was stopped because it required data from a "
                "store you don't have access to. "
                f"{denial.get('message', 'Access to that store was denied.')} "
                "Resubmit the investigation scoped to your own store if you'd "
                "like to continue."
            ),
            "confidence_score": 0.0,
            "anomaly_category": "unknown",
            "evidence": state["evidence_trail"],
            "recommendations": [
                "Resubmit this investigation without referencing a store outside your access."
            ],
            "estimated_impact": "",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_iterations": state["iterations"],
            "reached_final_answer": True,
            "grounding_warnings": [],
        }
        return {"result": result}

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
        forced_response = _attempt_forced_conclusion(state)
        forced_text = _message_text(forced_response) if forced_response is not None else ""
        forced_parsed = extract_json_report(forced_text) if forced_text else None

        if forced_parsed and forced_parsed.get("root_cause"):
            # Forced conclusion succeeded — use it, but treat it as inherently
            # less reliable than a naturally-reached answer: cap confidence,
            # still run it through the same grounding check as a normal
            # answer, and mark reached_final_answer True since we did get an
            # actual conclusion, just a forced one.
            parsed = forced_parsed
            reached_final_answer = True
            confidence_score = min(float(parsed.get("confidence_score", 0.5)), 0.6)
            root_cause = (
                f"[Forced conclusion after exhausting {MAX_ITERATIONS} iterations — "
                "based only on evidence already gathered, not further investigated.] "
                + parsed["root_cause"]
            )

            grounding_warnings = check_grounding(root_cause, state["evidence_trail"])
            if grounding_warnings:
                confidence_score = min(confidence_score, 0.4)
                logger.warning(
                    f"investigation {state['investigation_id']} forced-conclusion root_cause "
                    f"failed grounding check ({len(grounding_warnings)} warning(s)) — "
                    f"confidence capped at {confidence_score}",
                    extra={"event": "grounding_check_failed", "investigation_id": state["investigation_id"]},
                )

            status = evaluate_confidence(confidence_score, state["iterations"])
            logger.info(
                f"investigation {state['investigation_id']} exhausted {MAX_ITERATIONS} iterations "
                f"but produced a forced conclusion from existing evidence (confidence={confidence_score})",
                extra={"event": "investigation_forced_conclusion", "investigation_id": state["investigation_id"]},
            )
        else:
            # Forced pass produced nothing usable either — fall back to the
            # original generic message rather than fabricating anything.
            parsed = {}
            confidence_score = 0.0
            status = "escalated"
            root_cause = (
                f"Investigation did not reach a conclusion within {MAX_ITERATIONS} "
                "iterations. Partial evidence was collected but no final answer "
                "was produced — see evidence trail for what was gathered so far."
            )
            logger.warning(
                f"investigation {state['investigation_id']} exhausted {MAX_ITERATIONS} iterations "
                "without a final answer, and the forced-conclusion pass also produced nothing usable",
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