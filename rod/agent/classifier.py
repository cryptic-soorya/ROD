"""
agent/classifier.py

Checks if the anomaly_description contain any
recognizable text at all, or just gibberish. Runs before
agent/graph.py's run_investigation() ever calls the LLM.

The reason this exists as a separate, non-LLM check: agent/prompts.py's
SYSTEM_PROMPT already instructs the model to refuse gibberish before
calling tools, but that instruction is one paragraph inside a ~150-line
system prompt. 
This only catches unrecognisable "words". It deliberately
does NOT try to catch coherent-but-irrelevant input (greetings, unrelated
questions) that requires actual language understanding to do well, and is
left to SYSTEM_PROMPT's existing instruction, since false positives there
(rejecting a real but tersely-worded anomaly report) are worse than an
occasional missed greeting.
"""

import re

VOWELS = set("aeiouy")
WORD_RE = re.compile(r"[A-Za-z]+")

# A word is "gibberish-like" if it has no vowels, a character repeated 4+
# times in a row, or a run of 6+ consecutive consonants — patterns that
# essentially never occur in real English words but are common in keyboard
# mashing. Words under 3 letters are never flagged (too short to judge, and
# real short words/codes are common: "SKU", "the", "S036" -> "S").
def _is_gibberish_word(word: str) -> bool:
    w = word.lower()
    if len(w) < 3:
        return False
    if not any(c in VOWELS for c in w):
        return True
    if re.search(r"(.)\1{3,}", w):
        return True
    consonant_run = 0
    max_run = 0
    for c in w:
        if c in VOWELS:
            consonant_run = 0
        else:
            consonant_run += 1
            max_run = max(max_run, consonant_run)
    return max_run >= 6


def gibberish_rejection_reason(text: str) -> str | None:
    """
    Returns a human-readable rejection reason if `text` is empty or
    majority keyboard-mash gibberish, else None (proceed to investigate).
    """
    stripped = (text or "").strip()
    if not stripped:
        return "The submitted query was empty."

    words = WORD_RE.findall(stripped)
    if not words:
        return "The submitted query contains no recognizable text — nothing to investigate."

    evaluable = [w for w in words if len(w) >= 3]
    flagged = [w for w in evaluable if _is_gibberish_word(w)]
    if evaluable and (len(flagged) / len(evaluable)) > 0.5:
        return "The submitted query does not contain recognizable words and appears to be random input."

    return None
