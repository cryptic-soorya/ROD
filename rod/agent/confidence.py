"""
agent/confidence.py
Maps a self-reported confidence score to an investigation status.
evaluate_confidence(score: float, iteration_count: int) -> str
    Returns "completed" if score >= 0.7, else "escalated".
Confidence score is self-reported by the LLM (0.0 to 1.0).
"""

COMPLETION_THRESHOLD = 0.7


def evaluate_confidence(score: float, iteration_count: int) -> str:
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(1.0, score))

    return "completed" if score >= COMPLETION_THRESHOLD else "escalated"
