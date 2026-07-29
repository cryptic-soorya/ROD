"""
agent/confidence.py
evaluate_confidence(score: float, iteration_count: int) -> str
    Returns "completed" if score >= 0.7, else "escalated".
    Called after every end_turn.

Confidence score is self-reported by the LLM (0.0 to 1.0).
Escalated investigations surface in filtered view via GET /investigations?status=escalated.
"""

COMPLETION_THRESHOLD = 0.7


def evaluate_confidence(score: float, iteration_count: int) -> str:
    """
    Maps a self-reported confidence score to an investigation status.

    iteration_count is accepted (and logged by callers via the report's
    total_iterations field) but does not currently affect the decision —
    the contract documented above is a pure threshold on score. It's kept
    as a parameter so this signature doesn't need to change if iteration-
    aware rules (e.g. penalizing investigations that used every available
    turn) are added later.

    score is self-reported by the LLM, so it isn't guaranteed to be a
    well-formed float in [0.0, 1.0] — clamp defensively rather than letting
    a malformed value silently produce a wrong status.
    """
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(1.0, score))

    return "completed" if score >= COMPLETION_THRESHOLD else "escalated"