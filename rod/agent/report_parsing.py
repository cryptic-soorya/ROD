"""
agent/report_parsing.py

Pulls the final-answer JSON report out of the model's closing text turn.
Shared by both the legacy react_loop.py loop and the LangGraph agent/graph.py
implementation so there's one copy of this logic, not two drifting in
parallel during the migration.
"""

import json
import re


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
    fence_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass  # fall through to brace-scanning below

    # Gemini is instructed to put the JSON report at the END of its response,
    # so if multiple valid JSON objects appear (e.g. an example shown earlier
    # in its reasoning), we want the LAST one, not the first.
    decoder = json.JSONDecoder()
    last_valid: dict | None = None
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            last_valid = obj
    return last_valid
