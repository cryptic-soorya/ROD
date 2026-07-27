"""
agent/orchestrator.py

Persistence/report-compilation glue that sits between the LangGraph engine
(agent/graph.py) and the investigations/reports services. investigations/
router.py calls run() below as its background task entry point; run() calls
agent.graph.run_investigation() to get an engine-agnostic result dict, then
converts it into the two shapes the rest of the system persists:
  - investigations.models.Report (investigations.service.update_status)
  - the canonical FRS report dict (reports.service.save_report, via
    reports.generator.compile_report)

Termination contract (enforced inside agent/graph.py):
    (a) LLM returns a text-only final turn, OR
    (b) 10 iterations reached (hard cap — never infinite loops)

After termination:
    - confidence >= 0.7  → status = completed, report generated
    - confidence < 0.7   → status = escalated, partial evidence preserved
    - loop exhausted without a final answer → status = escalated,
      confidence forced to 0.0 (see agent/graph.py's finalize_node)

SCHEMA NOTE (2026-07-20): investigations.service.update_status() no longer
takes an iteration_count kwarg — investigations dropped that column
entirely. total_iterations is still read out of run_investigation()'s
result (agent_summary still carries it, for compile_report's FRS report),
it's just not written back to investigations.service anymore.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional

from agent.graph import run_investigation
from agent.graph import GraphCallError
from investigations import service
from investigations.models import InvestigationStatus, AnomalyCategory, Report

from reports.generator import compile_report, ReportValidationError
from reports import service as reports_service
from logging_config import get_logger

logger = get_logger("agent.orchestrator")


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
    not run_investigation()'s raw dict tool output. This mirrors the same
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


def _flatten_recommendation_strings(raw) -> list[str]:
    """
    Recursively flattens list/dict nesting down to plain strings, so a
    stray nested list or dict value (e.g. an older/malformed
    {"immediate": [...], "customer_recovery": "..."} shape) never leaks
    into the output as a stringified Python repr like "['a', 'b']".
    """
    if isinstance(raw, str):
        return [raw] if raw else []
    if isinstance(raw, list):
        out: list[str] = []
        for item in raw:
            out.extend(_flatten_recommendation_strings(item))
        return out
    if isinstance(raw, dict):
        out = []
        for v in raw.values():
            out.extend(_flatten_recommendation_strings(v))
        return out
    return [str(raw)] if raw else []


def _coerce_recommendations(raw) -> list[str]:
    """
    Report.recommendations is List[str]. The LLM's JSON output isn't
    guaranteed to match that shape exactly (it might return a dict, a
    single string, or omit the field) — coerce defensively rather than
    letting a malformed-but-plausible response blow up report persistence.
    """
    return _flatten_recommendation_strings(raw)


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
    GraphCallError handling: never let a report failure vanish silently,
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
    Async wrapper around agent.graph.run_investigation() that matches the
    router's call signature. Compiles a canonical FRS-shaped report via
    reports.generator.compile_report(), persists it via
    reports.service.save_report(), and also persists the existing
    investigations.models.Report used by the investigations pipeline — so
    both consumers (the reports API and the investigations service) see
    consistent data.
    """
    anomaly_description = query
    if context:
        context_str = "\n".join(f"{k}: {v}" for k, v in context.items())
        anomaly_description = f"{query}\n\nContext:\n{context_str}"


    try:
        # run_investigation() is synchronous end-to-end (LangGraph's sync
        # .invoke(), sync Gemini calls, sync psycopg2 tool calls) — running it
        # directly on the event loop would block every other request (even
        # GET /health) for the full duration of the investigation. Offload
        # to a thread so the event loop stays free for concurrent requests.
        result = await asyncio.to_thread(
            run_investigation,
            anomaly_description=anomaly_description,
            investigation_id=str(investigation_id),
        )
    except GraphCallError as e:
        # The Gemini API call failed after all retries. Don't let this crash
        # the background task silently — persist a failed/escalated report so
        # the investigation is visible and actionable instead of just vanishing.
        # NOTE: assumes InvestigationStatus has no dedicated FAILED state;
        # one exists in investigations.models, prefer it over ESCALATED here.
        logger.error(
            f"investigation {investigation_id} could not complete — Gemini call failed",
            extra={"event": "investigation_failed", "investigation_id": str(investigation_id), "error_type": "GraphCallError"},
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

    # ── Query rejected before any tool call ─────────────────────────────────
    # agent/classifier.py (called from agent/graph.py's run_investigation)
    # short-circuits gibberish / non-anomaly queries with zero tool calls and
    # zero evidence, by design — there is nothing to investigate. That
    # correctly produces an empty evidence_trail, but compile_report() below
    # unconditionally rejects empty evidence as a traceability violation and
    # replaces root_cause with a generic "Report could not be generated"
    # message — appropriate for a genuine investigation that failed to
    # gather evidence, wrong for a query that was never investigable in the
    # first place. Route this case around compile_report() entirely so the
    # real rejection reason (and the "please resubmit" recommendation)
    # reaches the user instead of being clobbered.
    if not result.get("evidence"):
        logger.info(
            f"investigation {investigation_id} rejected before any tool call — "
            "query did not describe an investigable anomaly",
            extra={"event": "query_rejected", "investigation_id": str(investigation_id)},
        )
        recs = list(result.get("recommendations", []))
        report = Report(
            root_cause=result.get("root_cause", ""),
            evidence_trail=[],
            confidence_score=0.0,
            anomaly_category="unknown",
            recommendations=recs,
            estimated_impact=None,
            generated_at=datetime.now(timezone.utc),
        )
        service.update_status(investigation_id, InvestigationStatus.ESCALATED, report)
        reports_service.save_report({
            "investigation_id": str(investigation_id),
            "root_cause": result.get("root_cause", ""),
            "confidence_score": 0.0,
            "status": "escalated",
            "anomaly_category": "unknown",
            "evidence": [],
            "recommendations": {"immediate": recs, "customer_recovery": [], "process_improvement": []},
            "estimated_impact": "",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_iterations": 0,
        })
        return

    # ── Persist the raw evidence trail as individual tool_calls rows ───────
    # otherwise investigations.service never hears about it (tool_calls
    # stays empty forever), even though run_investigation() gathered real
    # evidence. The frontend's progress view reads this field, not
    # report.evidence_trail, so without this it looks like nothing happened.
    # total_iterations is still pulled out for the FRS report below — it's
    # just no longer written back to investigations.service (that column's
    # gone).
    total_iterations = result.get("total_iterations")
    _log_evidence_trail(investigation_id, result.get("evidence", []))

    # ── Surface grounding check results ─────────────────────────────────────
    # agent/grounding.py already capped confidence_score if root_cause named
    # an entity or entity-link the evidence doesn't support (see
    # agent/graph.py's finalize_node). Append the warnings as visible
    # evidence entries too, rather than letting them only affect the score
    # silently — a human reading the report should see *why* confidence was
    # capped, not just that it was.
    evidence_with_grounding = list(result.get("evidence", []))
    for warning in result.get("grounding_warnings", []):
        evidence_with_grounding.append({
            "step": "grounding_check",
            "tool": "grounding_check",
            "args": {},
            "finding": f"UNSUPPORTED CLAIM: {warning}",
        })

    # ── Compile the canonical FRS report ───────────────────────────────────
    compile_evidence = _evidence_for_compile_report(evidence_with_grounding)
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
            evidence_trail=_evidence_to_human_readable(evidence_with_grounding),
            confidence_score=0.0,
            anomaly_category="unknown",
            recommendations=[],
            estimated_impact=None,
            generated_at=datetime.now(timezone.utc),
        )
        service.update_status(investigation_id, status, report)
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
        evidence_trail=_evidence_to_human_readable(evidence_with_grounding),
        confidence_score=compiled_report["confidence_score"],
        anomaly_category=compiled_report["anomaly_category"],
        recommendations=_coerce_recommendations(result.get("recommendations", [])),
        estimated_impact=compiled_report.get("estimated_impact") or None,
        generated_at=compiled_report["generated_at"],
    )

    service.update_status(investigation_id, status, report)

    # ── Persist the identified root cause ──────────────────────────────────
    # log_root_cause() exists in investigations.service but nothing called
    # it before this fix. Only log a root_causes row when the investigation
    # actually reached a completed conclusion — an escalated/inconclusive
    # result (see agent/graph.py's finalize_node) doesn't represent an
    # identified cause, so it isn't logged here.
    if status == InvestigationStatus.COMPLETED:
        service.log_root_cause(
            investigation_id,
            cause_category=compiled_report.get("anomaly_category"),
            cause_description=compiled_report.get("root_cause"),
            confidence=compiled_report.get("confidence_score"),
        )