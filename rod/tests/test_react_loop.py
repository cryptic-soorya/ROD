"""
Tests for agent/react_loop.py

Strategy: react_loop.py's only real I/O boundary is _client.models.generate_content
(the Gemini call). Everything else — tool execution, evidence assembly, JSON
parsing, status derivation — is deterministic Python we can exercise directly.

So the approach is:
  1. Unit-test the pure helpers (_extract_json_report) with plain strings.
  2. Unit-test _execute_tool against the real (stubbed) TOOL_REGISTRY.
  3. Mock _client.models.generate_content to return fake Gemini responses and
     drive run_investigation() through its branches: immediate answer,
     multi-turn with tool calls, exhausted loop, and API failure/retry.
  4. Mock run_investigation + service.update_status to test the async run()
     wrapper's status-mapping and error-handling in isolation.

Fake Gemini responses are built as lightweight objects that mimic the
google.genai.types shapes react_loop.py actually accesses:
    response.candidates[0].content.parts -> list of parts
    part.text / part.function_call
    part.function_call.name / .args
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from agent import react_loop


@pytest.fixture(autouse=True)
def _single_client_pool(monkeypatch):
    """
    Every test below patches only react_loop._client.models.generate_content
    and assumes that's the sole I/O boundary. That held when there was one
    Gemini client, but _call_gemini_with_retry now rotates across the full
    _CLIENTS pool (agent/react_loop.py's key-rotation feature) — with more
    than one real key configured in .env, retries and later loop iterations
    land on unpatched, real clients instead of the mock, so multi-call tests
    fail with real SDK errors ("contents are required.") rather than
    exercising the intended retry/loop behavior.

    Pinning _CLIENTS to a single-element list containing _client for the
    duration of this file's tests makes key_idx always resolve to 0 (mod 1),
    so every call goes through the one mocked client regardless of pool
    size in the environment — restoring the original "one I/O boundary"
    test design without touching the production rotation logic.
    """
    monkeypatch.setattr(react_loop, "_CLIENTS", [react_loop._client])
    monkeypatch.setattr(react_loop, "_client_cursor", 0)


# ── Helpers to build fake Gemini responses without depending on the real SDK types ──

def make_text_part(text):
    return SimpleNamespace(text=text, function_call=None)


def make_call_part(name, args):
    return SimpleNamespace(
        text=None,
        function_call=SimpleNamespace(name=name, args=args),
    )


def make_response(parts):
    content = SimpleNamespace(parts=parts)
    candidate = SimpleNamespace(content=content)
    return SimpleNamespace(candidates=[candidate])


# ── 1. _extract_json_report ──────────────────────────────────────────────────

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


# ── 2. _execute_tool ──────────────────────────────────────────────────────────

class TestExecuteTool:
    """
    _execute_tool just dispatches by name and catches exceptions — it doesn't
    care what a specific tool does internally. Real tools like get_sales_data
    are SQLite-backed (see mcp_server/tools/sales.py) and out of scope for a
    unit test of the dispatcher itself, so we register a fake tool for the
    duration of each test rather than depending on a real DB being present.
    """

    def test_known_tool_success(self, monkeypatch):
        def fake_tool(store_id):
            return {"store_id": store_id, "revenue_current_period": 1000.0}

        monkeypatch.setitem(react_loop.TOOL_REGISTRY, "fake_tool", fake_tool)
        result = react_loop._execute_tool("fake_tool", {"store_id": "STORE-001"})
        assert result["store_id"] == "STORE-001"
        assert result["revenue_current_period"] == 1000.0

    def test_unknown_tool(self):
        result = react_loop._execute_tool("not_a_real_tool", {})
        assert result["error"] == "UNKNOWN_TOOL"
        assert result["tool"] == "not_a_real_tool"

    def test_tool_exception_is_caught(self, monkeypatch):
        def fake_tool(store_id):
            raise ValueError("simulated failure")

        monkeypatch.setitem(react_loop.TOOL_REGISTRY, "fake_tool", fake_tool)
        # Missing required arg 'store_id' -> TypeError inside fake_tool's call
        result = react_loop._execute_tool("fake_tool", {})
        assert result["error"] == "TOOL_EXCEPTION"
        assert result["tool"] == "fake_tool"


# ── 3. _call_gemini_with_retry ────────────────────────────────────────────────

class TestCallGeminiWithRetry:
    @patch("agent.react_loop.time.sleep", return_value=None)  # skip real backoff delays
    def test_succeeds_first_try(self, mock_sleep):
        fake_response = make_response([make_text_part("done")])
        with patch.object(
            react_loop._client.models, "generate_content", return_value=fake_response
        ) as mock_call:
            result = react_loop._call_gemini_with_retry(contents=[])
            assert result is fake_response
            assert mock_call.call_count == 1
            mock_sleep.assert_not_called()

    @patch("agent.react_loop.time.sleep", return_value=None)
    def test_retries_then_succeeds(self, mock_sleep):
        fake_response = make_response([make_text_part("done")])
        with patch.object(
            react_loop._client.models,
            "generate_content",
            side_effect=[ConnectionError("boom"), fake_response],
        ) as mock_call:
            result = react_loop._call_gemini_with_retry(contents=[])
            assert result is fake_response
            assert mock_call.call_count == 2
            mock_sleep.assert_called_once()  # backed off once before succeeding

    @patch("agent.react_loop.time.sleep", return_value=None)
    def test_exhausts_retries_raises_gemini_call_error(self, mock_sleep):
        with patch.object(
            react_loop._client.models,
            "generate_content",
            side_effect=ConnectionError("still down"),
        ) as mock_call:
            with pytest.raises(react_loop.GeminiCallError):
                react_loop._call_gemini_with_retry(contents=[])
            assert mock_call.call_count == react_loop.MAX_API_RETRIES
            assert mock_sleep.call_count == react_loop.MAX_API_RETRIES - 1


# ── 4. run_investigation — the full loop, mocking only the Gemini call ───────

class TestRunInvestigation:
    def test_immediate_final_answer_no_tool_calls(self):
        final_text = '{"root_cause": "seasonal dip", "confidence_score": 0.85, "anomaly_category": "sales"}'
        fake_response = make_response([make_text_part(final_text)])

        with patch.object(
            react_loop._client.models, "generate_content", return_value=fake_response
        ):
            result = react_loop.run_investigation("Revenue dropped 20%", "inv-1")

        assert result["reached_final_answer"] is True
        assert result["total_iterations"] == 1
        assert result["root_cause"] == "seasonal dip"
        assert result["confidence_score"] == 0.85
        assert result["status"] == "completed"  # 0.85 >= 0.7 per stubbed evaluate_confidence
        assert result["evidence"] == []

    def test_tool_call_then_final_answer(self, monkeypatch):
        def fake_get_sales_data(store_id):
            return {"store_id": store_id, "revenue_current_period": 500.0, "change_pct": -20.0}

        monkeypatch.setitem(react_loop.TOOL_REGISTRY, "get_sales_data", fake_get_sales_data)

        # Turn 1: Gemini asks for a tool. Turn 2: Gemini gives the final answer.
        call_response = make_response(
            [make_call_part("get_sales_data", {"store_id": "STORE-001"})]
        )
        final_text = '{"root_cause": "confirmed revenue drop", "confidence_score": 0.9}'
        final_response = make_response([make_text_part(final_text)])

        with patch.object(
            react_loop._client.models,
            "generate_content",
            side_effect=[call_response, final_response],
        ):
            result = react_loop.run_investigation("Revenue dropped", "inv-2")

        assert result["total_iterations"] == 2
        assert result["reached_final_answer"] is True
        assert len(result["evidence"]) == 1
        assert result["evidence"][0]["tool"] == "get_sales_data"
        assert result["evidence"][0]["args"] == {"store_id": "STORE-001"}
        assert result["evidence"][0]["finding"]["store_id"] == "STORE-001"
        assert result["evidence"][0]["finding"]["change_pct"] == -20.0
        assert result["status"] == "completed"

    def test_unknown_tool_call_recorded_as_error_but_loop_continues(self):
        call_response = make_response([make_call_part("not_a_real_tool", {})])
        final_response = make_response(
            [make_text_part('{"root_cause": "gave up gracefully", "confidence_score": 0.5}')]
        )
        with patch.object(
            react_loop._client.models,
            "generate_content",
            side_effect=[call_response, final_response],
        ):
            result = react_loop.run_investigation("Something weird", "inv-3")

        assert result["evidence"][0]["finding"]["error"] == "UNKNOWN_TOOL"
        assert result["reached_final_answer"] is True

    def test_loop_exhausted_without_final_answer(self, monkeypatch):
        monkeypatch.setitem(
            react_loop.TOOL_REGISTRY,
            "get_sales_data",
            lambda store_id: {"store_id": store_id, "revenue_current_period": 100.0},
        )
        # Gemini keeps calling tools forever and never stops -> hits MAX_ITERATIONS
        call_response = make_response(
            [make_call_part("get_sales_data", {"store_id": "STORE-001"})]
        )
        with patch.object(
            react_loop._client.models, "generate_content", return_value=call_response
        ) as mock_call:
            result = react_loop.run_investigation("Never-ending anomaly", "inv-4")

        assert mock_call.call_count == react_loop.MAX_ITERATIONS
        assert result["reached_final_answer"] is False
        assert result["status"] == "escalated"
        assert result["confidence_score"] == 0.0
        assert "did not reach a conclusion" in result["root_cause"]
        assert len(result["evidence"]) == react_loop.MAX_ITERATIONS  # one tool call per iteration

    def test_malformed_json_in_final_answer_falls_back_gracefully(self):
        # Final text has no parseable JSON at all
        final_response = make_response([make_text_part("I looked into it but couldn't tell.")])
        with patch.object(
            react_loop._client.models, "generate_content", return_value=final_response
        ):
            result = react_loop.run_investigation("Weird anomaly", "inv-5")

        assert result["reached_final_answer"] is True
        assert result["confidence_score"] == 0.5  # documented default when parsed dict is empty
        assert result["root_cause"] == "I looked into it but couldn't tell."

    @patch("agent.react_loop.time.sleep", return_value=None)
    def test_gemini_call_error_propagates_out_of_run_investigation(self, mock_sleep):
        with patch.object(
            react_loop._client.models,
            "generate_content",
            side_effect=ConnectionError("network down"),
        ):
            with pytest.raises(react_loop.GeminiCallError):
                react_loop.run_investigation("Anomaly", "inv-6")


# ── 5. run() — the async router-facing wrapper ────────────────────────────────

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