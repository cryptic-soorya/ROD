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
