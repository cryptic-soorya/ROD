"""
agent/confidence.py
OWNER: Teammate C

evaluate_confidence(score: float, iteration_count: int) -> str
    Returns "completed" if score >= 0.7, else "escalated".
    Called after every end_turn.

Confidence score is self-reported by the LLM (0.0 to 1.0).
Escalated investigations surface in filtered view via GET /investigations?status=escalated.
"""
