"""
reports/generator.py
OWNER: Teammate E

Internal function — called by agent/react_loop.py when end_turn is returned.
compile_report(investigation_id, evidence_trail, agent_summary, confidence_score) -> dict

Output structure (FRS Section 6.1):
{
    investigation_id, root_cause, confidence_score, status,
    anomaly_category, evidence: [{step, tool, finding}],
    recommendations: { immediate, customer_recovery, process_improvement },
    estimated_impact, generated_at, total_iterations
}

Rules:
    - Every claim in root_cause must trace to at least one evidence entry.
    - Report is IMMUTABLE once generated. No PUT/PATCH ever.
    - Corrections = new investigation.

ASSUMPTIONS (not fully specified upstream — confirm with whoever owns
agent/react_loop.py and adjust if the real shapes differ):

    evidence_trail: list[dict], each shaped like
        {"step": int, "tool": str, "finding": str}
        (matches the output "evidence" field directly, so it is passed
        through with light validation rather than reshaped)

    agent_summary: dict, expected to contain
        {
            "root_cause": str,
            "anomaly_category": str,
            "estimated_impact": str,
            "status": str,                 # e.g. "completed" | "escalated"
            "recommendations": {
                "immediate": list[str],
                "customer_recovery": list[str],
                "process_improvement": list[str],
            },
        }

    total_iterations is derived from len(evidence_trail) unless
    agent_summary explicitly provides "total_iterations" (react_loop may
    track retries/failed tool calls that don't produce evidence entries,
    in which case its own count is more accurate than ours).
"""

from datetime import datetime, timezone


class ReportValidationError(Exception):
    """Raised when compile_report() receives data that violates the
    evidence-traceability rule or is missing required fields."""
    pass


REQUIRED_AGENT_SUMMARY_FIELDS = (
    "root_cause",
    "anomaly_category",
    "estimated_impact",
    "status",
    "recommendations",
)

REQUIRED_RECOMMENDATION_KEYS = ("immediate", "customer_recovery", "process_improvement")


def _validate_evidence_trail(evidence_trail: list) -> list[dict]:
    if not evidence_trail:
        raise ReportValidationError(
            "evidence_trail is empty — a report cannot be generated with zero "
            "supporting evidence (violates traceability rule)."
        )

    validated = []
    for i, entry in enumerate(evidence_trail):
        if not isinstance(entry, dict):
            raise ReportValidationError(f"evidence_trail[{i}] is not a dict: {entry!r}")
        missing = [k for k in ("step", "tool", "finding") if k not in entry]
        if missing:
            raise ReportValidationError(
                f"evidence_trail[{i}] missing required keys: {missing}"
            )
        validated.append({
            "step": entry["step"],
            "tool": entry["tool"],
            "finding": entry["finding"],
        })
    return validated


def _validate_agent_summary(agent_summary: dict) -> None:
    missing = [f for f in REQUIRED_AGENT_SUMMARY_FIELDS if f not in agent_summary]
    if missing:
        raise ReportValidationError(f"agent_summary missing required fields: {missing}")

    recs = agent_summary["recommendations"]
    if not isinstance(recs, dict):
        raise ReportValidationError("agent_summary['recommendations'] must be a dict")

    missing_rec_keys = [k for k in REQUIRED_RECOMMENDATION_KEYS if k not in recs]
    if missing_rec_keys:
        raise ReportValidationError(
            f"agent_summary['recommendations'] missing keys: {missing_rec_keys}"
        )


def _check_root_cause_traceability(root_cause: str, evidence: list[dict]) -> None:
    """
    Enforces: 'Every claim in root_cause must trace to at least one evidence
    entry.' We cannot do true NLP claim-extraction here, so this is a
    best-effort structural check: root_cause must be non-trivial text, and
    there must be at least one evidence entry with a non-empty finding.
    A stronger check (e.g. keyword overlap or an LLM-based verifier) belongs
    in agent/confidence.py or react_loop.py, upstream of this function,
    since compile_report() only assembles what it's given — it doesn't
    re-derive conclusions from raw tool output.
    """
    if not root_cause or not root_cause.strip():
        raise ReportValidationError("root_cause is empty — cannot generate a report with no conclusion.")

    if not any(e["finding"].strip() for e in evidence):
        raise ReportValidationError(
            "root_cause is present but no evidence entry has a non-empty "
            "finding to support it — traceability rule violated."
        )


def compile_report(
    investigation_id: str,
    evidence_trail: list[dict],
    agent_summary: dict,
    confidence_score: float,
) -> dict:
    """
    Assembles the final, immutable report dict for a completed or escalated
    investigation. Raises ReportValidationError if the inputs violate the
    traceability or completeness rules — callers (react_loop.py) should
    treat that as a signal to escalate the investigation rather than silently
    swallow the error, since a report that can't be validated shouldn't be
    persisted either.
    """
    if not investigation_id:
        raise ReportValidationError("investigation_id is required.")

    if not (0.0 <= confidence_score <= 1.0):
        raise ReportValidationError(
            f"confidence_score must be between 0.0 and 1.0, got {confidence_score}"
        )

    evidence = _validate_evidence_trail(evidence_trail)
    _validate_agent_summary(agent_summary)
    _check_root_cause_traceability(agent_summary["root_cause"], evidence)

    total_iterations = agent_summary.get("total_iterations", len(evidence))

    report = {
        "investigation_id": investigation_id,
        "root_cause": agent_summary["root_cause"],
        "confidence_score": round(float(confidence_score), 4),
        "status": agent_summary["status"],
        "anomaly_category": agent_summary["anomaly_category"],
        "evidence": evidence,
        "recommendations": {
            "immediate": list(agent_summary["recommendations"].get("immediate", [])),
            "customer_recovery": list(agent_summary["recommendations"].get("customer_recovery", [])),
            "process_improvement": list(agent_summary["recommendations"].get("process_improvement", [])),
        },
        "estimated_impact": agent_summary["estimated_impact"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_iterations": total_iterations,
    }

    return report