"""
Tests for agent/report_parsing.py's extract_json_report — shared by
agent/graph.py's finalize_node to pull the final-answer JSON report out of
the model's closing text turn.
"""

from agent.report_parsing import extract_json_report


class TestExtractJsonReport:
    def test_plain_json(self):
        text = '{"root_cause": "stockout", "confidence_score": 0.8}'
        assert extract_json_report(text) == {
            "root_cause": "stockout",
            "confidence_score": 0.8,
        }

    def test_fenced_json_preferred(self):
        text = 'Reasoning...\n```json\n{"root_cause": "listing change", "confidence_score": 0.9}\n```\nDone.'
        result = extract_json_report(text)
        assert result["root_cause"] == "listing change"

    def test_trailing_prose_after_json(self):
        text = '{"root_cause": "promo underperformance", "confidence_score": 0.6} — let me know if needed.'
        result = extract_json_report(text)
        assert result["confidence_score"] == 0.6

    def test_example_json_before_real_json_uses_last(self):
        text = (
            'Format looks like {"example": true} but here is my answer: '
            '{"root_cause": "stockout", "confidence_score": 0.8}'
        )
        result = extract_json_report(text)
        assert result == {"root_cause": "stockout", "confidence_score": 0.8}

    def test_no_json_returns_none(self):
        assert extract_json_report("no json here at all") is None

    def test_nested_braces(self):
        text = 'aside: {"a": {"b": 1}} final: {"root_cause": "x", "confidence_score": 0.75}'
        result = extract_json_report(text)
        assert result["root_cause"] == "x"
