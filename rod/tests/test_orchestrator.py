"""
Tests for agent/orchestrator.py's run() — the async wrapper that maps an
agent.graph.run_investigation()-shaped dict onto investigations.service /
reports.service persistence. This is pure glue code independent of the
LangGraph engine that produced the dict, so it's tested here by mocking
agent.graph.run_investigation() itself (a black box) rather than anything
inside agent/graph.py — see tests/test_graph.py for engine coverage.
"""
import asyncio
from unittest.mock import patch

from agent import orchestrator


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
            orchestrator, "run_investigation", return_value=fake_result
        ), patch.object(
            orchestrator.service, "update_status"
        ) as mock_update, patch.object(
            orchestrator.service, "log_tool_call"
        ) as mock_log, patch.object(
            orchestrator.reports_service, "save_report"
        ):
            asyncio.run(orchestrator.run(investigation_id=1, query="anomaly"))

        args, _ = mock_update.call_args
        report = args[2]
        assert args[0] == 1
        assert args[1] == orchestrator.InvestigationStatus.COMPLETED
        assert report.root_cause == "cause"
        assert report.anomaly_category == orchestrator.AnomalyCategory.SALES_DROP
        assert report.recommendations == ["Restock STORE-001", "Notify regional manager"]
        # evidence dicts get converted to human-readable strings, not passed through raw
        assert isinstance(report.evidence_trail, list)
        assert all(isinstance(line, str) for line in report.evidence_trail)
        assert "get_sales_data" in report.evidence_trail[0]
        # previously silently dropped fields are now actually persisted
        assert report.estimated_impact == "$5k lost revenue over 7 days"
        assert report.generated_at is not None
        # each evidence entry must reach the investigations service via
        # log_tool_call, not just the compiled report's evidence_trail — this
        # is what the frontend's progress view actually reads. update_status()
        # itself no longer takes iteration_count (investigations dropped that
        # column — see investigations/service.py's update_status docstring).
        assert "iteration_count" not in mock_update.call_args.kwargs
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
            orchestrator, "run_investigation", return_value=fake_result
        ), patch.object(
            orchestrator.service, "update_status"
        ) as mock_update, patch.object(
            orchestrator.service, "log_tool_call"
        ), patch.object(
            orchestrator.reports_service, "save_report"
        ):
            asyncio.run(orchestrator.run(investigation_id=2, query="anomaly"))

        args, _ = mock_update.call_args
        assert args[1] == orchestrator.InvestigationStatus.ESCALATED
        assert args[2].recommendations == []  # missing field defaults to empty list, not {}

    def test_context_merged_into_anomaly_description(self):
        captured = {}

        def fake_run_investigation(anomaly_description, investigation_id):
            captured["description"] = anomaly_description
            return {"status": "completed", "root_cause": "x", "evidence": []}

        with patch.object(
            orchestrator, "run_investigation", side_effect=fake_run_investigation
        ), patch.object(orchestrator.service, "update_status"), patch.object(
            orchestrator.service, "log_tool_call"
        ), patch.object(
            orchestrator.reports_service, "save_report"
        ):
            asyncio.run(
                orchestrator.run(
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
            orchestrator,
            "run_investigation",
            side_effect=orchestrator.GraphCallError("API down after retries"),
        ), patch.object(orchestrator.service, "update_status") as mock_update, patch.object(
            orchestrator.reports_service, "save_report"
        ):
            asyncio.run(orchestrator.run(investigation_id=4, query="anomaly"))

        args, _ = mock_update.call_args
        assert args[1] == orchestrator.InvestigationStatus.ESCALATED
        assert "API down after retries" in args[2].root_cause
        assert args[2].confidence_score == 0.0
        assert args[2].recommendations == []
        assert args[2].generated_at is not None
