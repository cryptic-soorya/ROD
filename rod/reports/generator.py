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
"""

from datetime import datetime, timezone
from typing import List
 
from investigations.models import Report, AnomalyCategory
 
 
def compile_report(react_output: dict) -> Report:
    """
    Takes the dict returned by agent/react_loop.py run()
    and returns a Report pydantic model.
 
    react_output keys (from react_loop.py return statement):
        investigation_id  : int
        status            : str
        root_cause        : str
        confidence_score  : float
        anomaly_category  : str
        evidence          : list of dicts  [{step, tool, args, finding}]
        recommendations   : dict or list
        estimated_impact  : str
        generated_at      : str
        total_iterations  : int
    """
 
    # ── Root Cause ────────────────────────────────────────
    root_cause = react_output.get("root_cause", "Root cause could not be determined.")
 
    # ── Confidence Score ──────────────────────────────────
    confidence_score = float(react_output.get("confidence_score", 0.0))
 
    # ── Anomaly Category → enum ───────────────────────────
    raw_category     = react_output.get("anomaly_category", "unknown")
    anomaly_category = _map_category(raw_category)
 
    # ── Evidence Trail → List[str] ────────────────────────
    # react_loop returns evidence as list of dicts
    # models.py defines evidence_trail as List[str]
    raw_evidence: list = react_output.get("evidence", [])
    evidence_trail: List[str] = []
    for item in raw_evidence:
        step    = item.get("step", "?")
        tool    = item.get("tool", "unknown")
        args    = item.get("args", {})
        finding = item.get("finding", {})
        evidence_trail.append(
            f"[Step {step}] Tool: {tool} | "
            f"Args: {args} | "
            f"Finding: {finding}"
        )
 
    # ── Recommendations → List[str] ───────────────────────
    # react_loop may return recommendations as dict or list
    # models.py defines recommendations as List[str]
    raw_recs = react_output.get("recommendations", {})
    if isinstance(raw_recs, dict):
        recommendations: List[str] = (
            raw_recs.get("immediate", []) +
            raw_recs.get("recovery",  []) +
            raw_recs.get("process",   [])
        )
        if not recommendations:
            recommendations = ["Review anomaly manually"]
    elif isinstance(raw_recs, list):
        recommendations = raw_recs
    else:
        recommendations = ["Review anomaly manually"]
 
    # ── Build Report (exactly matches investigations/models.py) ──
    report = Report(
        anomaly_category = anomaly_category,
        confidence_score = round(confidence_score, 3),
        root_cause       = root_cause,
        recommendations  = recommendations,
        evidence_trail   = evidence_trail,
        generated_at     = datetime.now(timezone.utc)
    )
 
    return report
 
 
# ── Map string → AnomalyCategory enum ────────────────────
def _map_category(raw: str) -> AnomalyCategory:
    mapping = {
        "sales":                   AnomalyCategory.SALES_DROP,
        "sales_drop":              AnomalyCategory.SALES_DROP,
        "inventory":               AnomalyCategory.INVENTORY_SPIKE,
        "inventory_spike":         AnomalyCategory.INVENTORY_SPIKE,
        "returns":                 AnomalyCategory.RETURN_SURGE,
        "return_surge":            AnomalyCategory.RETURN_SURGE,
        "supply_chain":            AnomalyCategory.SUPPLIER_DELAY,
        "supplier_delay":          AnomalyCategory.SUPPLIER_DELAY,
        "customer_behaviour":      AnomalyCategory.CUSTOMER_COMPLAINT,
        "customer_complaint":      AnomalyCategory.CUSTOMER_COMPLAINT,
        "promotion":               AnomalyCategory.PROMOTION_UNDERPERFORM,
        "promotion_underperform":  AnomalyCategory.PROMOTION_UNDERPERFORM,
    }
    return mapping.get(str(raw).lower(), AnomalyCategory.UNKNOWN)
 