"""
agent/report_parsing.py

Pulls the final-answer JSON report out of the model's closing text turn.
Shared by both the legacy react_loop.py loop and the LangGraph agent/graph.py
implementation so there's one copy of this logic, not two drifting in
parallel during the migration.
"""

import json
import re


# Takes Gemini's final answer (a block of text) and pulls out the JSON report
# object hiding inside it (the {"root_cause": ..., "confidence_score": ...} part).
def extract_json_report(text: str) -> dict | None:
    """
    Gemini is asked to output raw JSON at the end, but its surrounding prose
    or a ```json fence can itself contain braces (examples, nested quotes,
    etc.), so blindly slicing from the first '{' to the last '}' can grab
    the wrong span or fail to parse. Instead:
      1. Prefer an explicit ```json fenced block if present.
      2. Otherwise scan for '{' characters and use json.JSONDecoder.raw_decode
         at each candidate start — this finds the first *complete, valid*
         JSON object regardless of what comes after it, rather than assuming
         the last '}' in the text is the right closing brace.
    """
    # First, try the easy case: Gemini wrapped the JSON in a ```json ... ``` code block.
    fence_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass  # fall through to brace-scanning below

    # Gemini is instructed to put the JSON report at the END of its response,
    # so if multiple valid JSON objects appear (e.g. an example shown earlier
    # in its reasoning), we want the LAST one, not the first. We only want
    # the last *top-level* object though — once a candidate at position i
    # parses successfully, its own span (i..end) is consumed and skipped,
    # so a nested object value inside it (e.g. a "recommendations": {...}
    # field) is never re-considered as its own candidate and can't overwrite
    # the correct outer object.
    # Otherwise: scan the text for every '{' and try to parse a valid JSON
    # object starting there. Keep the LAST valid one found (Gemini is told to
    # put the real report at the end of its response).
    decoder = json.JSONDecoder()
    last_valid: dict | None = None
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        try:
            # Try parsing a complete JSON object starting at position i.
            obj, end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            i += 1
            continue
        if isinstance(obj, dict):
            last_valid = obj
            i = end  # skip past this object so nested objects inside it aren't re-matched
        else:
            i += 1
    return last_valid
