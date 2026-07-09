"""
Tests for agent/react_loop.py

MIGRATED 2026-07-09: the ReAct engine itself (loop, tool dispatch, Gemini
client pool, retry) moved to agent/graph.py — see tests/test_graph.py for
coverage of that. What's left here is react_loop.py's own remaining
surface:
  1. _extract_json_report — re-exported from agent.report_parsing for
     backward compat, still exercised directly via react_loop's name.
  2. run() — the async wrapper that maps a run_investigation()-shaped dict
     onto investigations.service / reports.service persistence. This is
     pure glue code independent of whichever engine produced the dict, so
     it's tested here by mocking react_loop.run_investigation() itself
     (a black box) rather than anything inside agent/graph.py.
"""
import asyncio
from unittest.mock import patch

from agent import react_loop


# ── 1. _extract_json_report (re-exported from agent.report_parsing) ──────────

class TestExtractJsonReport:
    def test_plain_json(self):
        text = '{"root_cause": "stockout", "confidence_score": 0.8}'
        assert react_loop._extract_json_report(text) == {
            "root_cause": "stockout",
            "confidence_score": 0.8,
        }

    def test_fenced_json_preferred(self):
        text = 'Reasoning...\n```json\n{"root_cause": "listing change", "confidence_score": 0.9}\n```\nDone.'
        result = react_loop._extract_json_report(text)
        assert result["root_cause"] == "listing change"

    def test_trailing_prose_after_json(self):
        text = '{"root_cause": "promo underperformance", "confidence_score": 0.6} — let me know if needed.'
        result = react_loop._extract_json_report(text)
        assert result["confidence_score"] == 0.6

    def test_example_json_before_real_json_uses_last(self):
        text = (
            'Format looks like {"example": true} but here is my answer: '
            '{"root_cause": "stockout", "confidence_score": 0.8}'
        )
        result = react_loop._extract_json_report(text)
        assert result == {"root_cause": "stockout", "confidence_score": 0.8}

    def test_no_json_returns_none(self):
        assert react_loop._extract_json_report("no json here at all") is None

    def test_nested_braces(self):
        text = 'aside: {"a": {"b": 1}} final: {"root_cause": "x", "confidence_score": 0.75}'
        result = react_loop._extract_json_report(text)
        assert result["root_cause"] == "x"


# ── 2. run() — the async router-facing wrapper ────────────────────────────────

class TestAsyncRun:
    def test_completed_status_persisted(self):
        fake_result = {
            "status": "completed",
            "root_cause": "cause",
            "evidence": [
                {"step": 1, "tool": "get_sales_data", "args": {"store_id": "STORE-001"},
                 "finding": {"change_pct": -20.0}},
            ],
            "confidence_score": 0.9,
            "anomaly_category": "sales_drop",  # real AnomalyCategory enum value
            "recommendations": ["Restock STORE-001", "Notify regional manager"],
            "estimated_impact": "$5k lost revenue over 7 days",
            "generated_at": "2026-07-03T12:00:00+00:00",
            "total_iterations": 3,
        }
        with patch.object(
            react_loop, "run_investigation", return_value=fake_result
        ), patch.object(
            react_loop.service, "update_status"
        ) as mock_update, patch.object(
            react_loop.service, "log_tool_call"
        ) as mock_log, patch.object(
            react_loop.reports_service, "save_report"
        ):
            asyncio.run(react_loop.run(investigation_id=1, query="anomaly"))

        args, _ = mock_update.call_args
        report = args[2]
        assert args[0] == 1
        assert args[1] == react_loop.InvestigationStatus.COMPLETED
        assert report.root_cause == "cause"
        assert report.anomaly_category == react_loop.AnomalyCategory.SALES_DROP
        assert report.recommendations == ["Restock STORE-001", "Notify regional manager"]
        # evidence dicts get converted to human-readable strings, not passed through raw
        assert isinstance(report.evidence_trail, list)
        assert all(isinstance(line, str) for line in report.evidence_trail)
        assert "get_sales_data" in report.evidence_trail[0]
        # previously silently dropped fields are now actually persisted
        assert report.estimated_impact == "$5k lost revenue over 7 days"
        assert report.generated_at is not None
        # the real iteration count and each evidence entry must reach the
        # investigations service, not just the compiled report's evidence_trail —
        # this is what the frontend's progress view actually reads
        assert mock_update.call_args.kwargs["iteration_count"] == 3
        mock_log.assert_called_once_with(
            1,
            tool_name="get_sales_data",
            input_args={"store_id": "STORE-001"},
            output={"change_pct": -20.0},
            error=None,
        )

    def test_escalated_status_persisted(self):
        fake_result = {"status": "escalated", "root_cause": "unclear", "evidence": []}
        with patch.object(
            react_loop, "run_investigation", return_value=fake_result
        ), patch.object(
            react_loop.service, "update_status"
        ) as mock_update, patch.object(
            react_loop.service, "log_tool_call"
        ), patch.object(
            react_loop.reports_service, "save_report"
        ):
            asyncio.run(react_loop.run(investigation_id=2, query="anomaly"))

        args, _ = mock_update.call_args
        assert args[1] == react_loop.InvestigationStatus.ESCALATED
        assert args[2].recommendations == []  # missing field defaults to empty list, not {}

    def test_context_merged_into_anomaly_description(self):
        captured = {}

        def fake_run_investigation(anomaly_description, investigation_id):
            captured["description"] = anomaly_description
            return {"status": "completed", "root_cause": "x", "evidence": []}

        with patch.object(
            react_loop, "run_investigation", side_effect=fake_run_investigation
        ), patch.object(react_loop.service, "update_status"), patch.object(
            react_loop.service, "log_tool_call"
        ), patch.object(
            react_loop.reports_service, "save_report"
        ):
            asyncio.run(
                react_loop.run(
                    investigation_id=3,
                    query="Sales dropped",
                    context={"store_id": "STORE-001", "region": "west"},
                )
            )

        assert "Sales dropped" in captured["description"]
        assert "store_id: STORE-001" in captured["description"]
        assert "region: west" in captured["description"]

    def test_gemini_call_error_persists_escalated_failure_report(self):
        with patch.object(
            react_loop,
            "run_investigation",
            side_effect=react_loop.GeminiCallError("API down after retries"),
        ), patch.object(react_loop.service, "update_status") as mock_update, patch.object(
            react_loop.reports_service, "save_report"
        ):
            asyncio.run(react_loop.run(investigation_id=4, query="anomaly"))

        args, _ = mock_update.call_args
        assert args[1] == react_loop.InvestigationStatus.ESCALATED
        assert "API down after retries" in args[2].root_cause
        assert args[2].confidence_score == 0.0
        assert args[2].recommendations == []
        assert args[2].generated_at is not None
