"""
agent/grounding.py

Post-hoc check on the LLM's final root_cause text: does every entity ID it
names actually appear somewhere in the evidence this investigation
gathered, and — for claims that link two different entity types (e.g. "SUP-019
delayed deliveries to S036") — did any single tool call actually return
both of those entities together?

Why this exists: the system prompt already tells the model "every claim
must be traceable to a tool result you actually retrieved" (agent/prompts.py),
but nothing enforced it. In practice the model can independently confirm
two unrelated facts (a supplier is degraded; a store's sales declined) via
separate tool calls and then narrate them as causally connected in
root_cause even though no tool call ever returned both together. See the
2026-07-11 investigation of the SUP-019 / S036,S028,S038 report — none of
those entities ever co-occur in a single tool result anywhere in
suppliers.db, inventory.db, or customers.db (customer_complaints has no
store_id/product_id column at all, so complaint claims can never be
grounded to a store).

This module does not re-judge the model's reasoning — it only flags
identifiers that were asserted but never observed together, so an
over-confident but ungrounded narrative gets caught before a human trusts
its confidence_score.
"""

import json
import re
from itertools import combinations

# Structured ID shapes used across the seeded DBs (see CLAUDE.md's schema
# tables). Supplier IDs appear in two inconsistent formats in the data
# itself (SUP07 vs SUP-019) — match both.
ENTITY_PATTERNS: dict[str, re.Pattern] = {
    "store": re.compile(r"\bS0\d{2,3}\b"),
    "sku": re.compile(r"\bP0\d{2,3}\b"),
    "supplier": re.compile(r"\bSUP-?\d{2,3}\b"),
    "promo": re.compile(r"\bPROMO-[A-Z0-9-]+\b"),
}


def extract_entities(text: str) -> dict[str, set[str]]:
    """Returns {entity_type: {ids found in text}} for the known ID shapes."""
    found: dict[str, set[str]] = {}
    for etype, pattern in ENTITY_PATTERNS.items():
        matches = set(pattern.findall(text or ""))
        if matches:
            found[etype] = matches
    return found


def _step_text(item: dict) -> str:
    args = item.get("args", {})
    finding = item.get("finding", {})
    try:
        return json.dumps(args) + " " + json.dumps(finding)
    except TypeError:
        return f"{args} {finding}"


def check_grounding(root_cause: str, evidence_trail: list[dict]) -> list[str]:
    """
    Returns a list of human-readable warnings (empty if root_cause is fully
    grounded). Two checks:

    1. Every entity ID named in root_cause appeared in at least one tool
       call's args or output somewhere in evidence_trail.
    2. For every pair of *different-type* entities both named in root_cause
       (e.g. one store + one supplier), at least one single evidence_trail
       step contains both — i.e. some tool call actually returned them
       together, not just independently true facts from separate calls.
    """
    warnings: list[str] = []

    claimed = extract_entities(root_cause)
    if not claimed:
        return warnings

    step_texts = [_step_text(item) for item in evidence_trail]
    all_evidence_text = " ".join(step_texts)

    # Check 1: every claimed ID appeared somewhere in the evidence at all.
    for etype, ids in claimed.items():
        for entity_id in ids:
            if entity_id not in all_evidence_text:
                warnings.append(
                    f"root_cause references {etype} '{entity_id}', which never "
                    f"appeared in any tool call's arguments or result — this "
                    f"investigation never actually looked it up."
                )

    # Check 2: cross-type entity pairs — did any single step return both?
    flat_ids = [(etype, eid) for etype, ids in claimed.items() for eid in ids]
    for (type_a, id_a), (type_b, id_b) in combinations(flat_ids, 2):
        if type_a == type_b:
            continue  # only cross-type links (e.g. supplier<->store) imply causation
        co_occurs = any(id_a in step and id_b in step for step in step_texts)
        if not co_occurs:
            warnings.append(
                f"root_cause implies a link between {type_a} '{id_a}' and "
                f"{type_b} '{id_b}', but no single tool call ever returned "
                f"both together — each was only confirmed independently, "
                f"so this connection is not supported by evidence."
            )

    return warnings
