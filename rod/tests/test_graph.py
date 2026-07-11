"""
Tests for agent/graph.py — the LangGraph StateGraph that replaced the
manual while-loop previously in agent/react_loop.py.

Strategy mirrors the old test_react_loop.py's approach for the loop: the
graph's only real I/O boundary is _LLMS[i].invoke(messages) (the Gemini
call via ChatGoogleGenerativeAI). Everything else — tool dispatch, evidence
assembly, JSON parsing, status derivation, iteration capping — is
deterministic and driven directly:
  1. Unit-test _call_llm_with_retry's retry/backoff against a mocked
     single-client pool.
  2. Drive run_investigation() end-to-end through its branches (immediate
     answer, multi-turn with tool calls, unknown tool, exhausted loop,
     malformed final JSON, API failure) by mocking _LLMS to return
     pre-built AIMessage objects in sequence.
"""
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool as lc_tool

from agent import graph


@pytest.fixture(autouse=True)
def _single_llm_pool(monkeypatch):
    """
    Pin _LLMS to a single mocked client for the duration of this file's
    tests, same rationale as react_loop.py's old _single_client_pool
    fixture: _call_llm_with_retry rotates across the whole _LLMS pool, and
    with more than one real key configured in .env, retries/later
    iterations would otherwise land on real, unpatched clients.
    """
    fake_llm = MagicMock()
    monkeypatch.setattr(graph, "_LLMS", [fake_llm])
    monkeypatch.setattr(graph, "_client_cursor", 0)
    return fake_llm


def make_final(text):
    return AIMessage(content=text, tool_calls=[])


def make_call(name, args, call_id="call_1"):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


# ── 1. _call_llm_with_retry ────────────────────────────────────────────────

class TestCallLlmWithRetry:
    @patch("agent.graph.time.sleep", return_value=None)
    def test_succeeds_first_try(self, mock_sleep, _single_llm_pool):
        fake_response = make_final("done")
        _single_llm_pool.invoke.return_value = fake_response

        result = graph._call_llm_with_retry(messages=[])

        assert result is fake_response
        assert _single_llm_pool.invoke.call_count == 1
        mock_sleep.assert_not_called()

    @patch("agent.graph.time.sleep", return_value=None)
    def test_retries_then_succeeds(self, mock_sleep, _single_llm_pool):
        fake_response = make_final("done")
        _single_llm_pool.invoke.side_effect = [ConnectionError("boom"), fake_response]

        result = graph._call_llm_with_retry(messages=[])

        assert result is fake_response
        assert _single_llm_pool.invoke.call_count == 2
        mock_sleep.assert_called_once()

    @patch("agent.graph.time.sleep", return_value=None)
    def test_exhausts_retries_raises_graph_call_error(self, mock_sleep, _single_llm_pool):
        _single_llm_pool.invoke.side_effect = ConnectionError("still down")

        with pytest.raises(graph.GraphCallError):
            graph._call_llm_with_retry(messages=[])

        assert _single_llm_pool.invoke.call_count == graph.MAX_API_RETRIES
        assert mock_sleep.call_count == graph.MAX_API_RETRIES - 1


# ── 2. run_investigation — the full graph, mocking only the LLM ──────────────

class TestRunInvestigation:
    def test_immediate_final_answer_no_tool_calls(self, _single_llm_pool):
        final_text = '{"root_cause": "seasonal dip", "confidence_score": 0.85, "anomaly_category": "sales"}'
        _single_llm_pool.invoke.return_value = make_final(final_text)

        result = graph.run_investigation("Revenue dropped 20%", "inv-1")

        assert result["reached_final_answer"] is True
        assert result["total_iterations"] == 1
        assert result["root_cause"] == "seasonal dip"
        assert result["confidence_score"] == 0.85
        assert result["status"] == "completed"
        assert result["evidence"] == []

    def test_tool_call_then_final_answer(self, monkeypatch, _single_llm_pool):
        @lc_tool
        def get_sales_data(store_id: str) -> dict:
            """fake get_sales_data for this test"""
            return {"store_id": store_id, "revenue_current_period": 500.0, "change_pct": -20.0}

        monkeypatch.setitem(graph.TOOL_MAP, "get_sales_data", get_sales_data)

        final_text = '{"root_cause": "confirmed revenue drop", "confidence_score": 0.9}'
        _single_llm_pool.invoke.side_effect = [
            make_call("get_sales_data", {"store_id": "STORE-001"}),
            make_final(final_text),
        ]

        result = graph.run_investigation("Revenue dropped", "inv-2")

        assert result["total_iterations"] == 2
        assert result["reached_final_answer"] is True
        assert len(result["evidence"]) == 1
        assert result["evidence"][0]["tool"] == "get_sales_data"
        assert result["evidence"][0]["args"] == {"store_id": "STORE-001"}
        assert result["evidence"][0]["finding"]["store_id"] == "STORE-001"
        assert result["evidence"][0]["finding"]["change_pct"] == -20.0
        assert result["status"] == "completed"

    def test_unknown_tool_call_recorded_as_error_but_loop_continues(self, _single_llm_pool):
        _single_llm_pool.invoke.side_effect = [
            make_call("not_a_real_tool", {}),
            make_final('{"root_cause": "gave up gracefully", "confidence_score": 0.5}'),
        ]

        result = graph.run_investigation("Something weird", "inv-3")

        assert result["evidence"][0]["finding"]["error"] == "UNKNOWN_TOOL"
        assert result["reached_final_answer"] is True

    def test_loop_exhausted_without_final_answer(self, monkeypatch, _single_llm_pool):
        @lc_tool
        def get_sales_data(store_id: str) -> dict:
            """fake get_sales_data for this test"""
            return {"store_id": store_id, "revenue_current_period": 100.0}

        monkeypatch.setitem(graph.TOOL_MAP, "get_sales_data", get_sales_data)

        # Model keeps calling tools forever and never stops -> hits MAX_ITERATIONS.
        # Must build a fresh AIMessage per call (not a single reused return_value):
        # LangGraph's add_messages reducer keys appended messages by their .id, and
        # reusing the same object would get the same id assigned on first append,
        # so later "appends" of that identical object would replace it in place
        # instead of growing the list — a test-mock artifact, not a real Gemini
        # behavior (every real API response is a distinct object).
        _single_llm_pool.invoke.side_effect = (
            lambda *args, **kwargs: make_call("get_sales_data", {"store_id": "STORE-001"})
        )

        result = graph.run_investigation("Never-ending anomaly", "inv-4")

        assert _single_llm_pool.invoke.call_count == graph.MAX_ITERATIONS
        assert result["reached_final_answer"] is False
        assert result["status"] == "escalated"
        assert result["confidence_score"] == 0.0
        assert "did not reach a conclusion" in result["root_cause"]
        assert len(result["evidence"]) == graph.MAX_ITERATIONS  # one tool call per iteration

    def test_malformed_json_in_final_answer_falls_back_gracefully(self, _single_llm_pool):
        _single_llm_pool.invoke.return_value = make_final("I looked into it but couldn't tell.")

        result = graph.run_investigation("Weird anomaly", "inv-5")

        assert result["reached_final_answer"] is True
        assert result["confidence_score"] == 0.5  # documented default when parsed dict is empty
        assert result["root_cause"] == "I looked into it but couldn't tell."

    @patch("agent.graph.time.sleep", return_value=None)
    def test_graph_call_error_propagates_out_of_run_investigation(self, mock_sleep, _single_llm_pool):
        _single_llm_pool.invoke.side_effect = ConnectionError("network down")

        with pytest.raises(graph.GraphCallError):
            graph.run_investigation("Anomaly", "inv-6")
