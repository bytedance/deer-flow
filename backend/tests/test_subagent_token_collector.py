"""Tests for SubagentTokenCollector callback handler."""

from unittest.mock import MagicMock
from uuid import uuid4

from deerflow.subagents.token_collector import SubagentTokenCollector


def _make_llm_response(content="Hello", usage=None):
    """Create a mock LLM response with a message."""
    msg = MagicMock()
    msg.content = content
    msg.usage_metadata = usage

    gen = MagicMock()
    gen.message = msg

    response = MagicMock()
    response.generations = [[gen]]
    return response


def _make_llm_response_from_usages(usages):
    """Create a mock LLM response with one generation per usage entry."""
    generations = []
    for usage in usages:
        msg = MagicMock()
        msg.content = "chunk"
        msg.usage_metadata = usage

        gen = MagicMock()
        gen.message = msg
        generations.append([gen])

    response = MagicMock()
    response.generations = generations
    return response


class TestSubagentTokenCollector:
    def test_collects_usage_from_response(self):
        collector = SubagentTokenCollector(caller="subagent:test")
        usage = {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
        collector.on_llm_end(_make_llm_response("Hi", usage=usage), run_id=uuid4())
        records = collector.snapshot_records()
        assert len(records) == 1
        assert records[0]["caller"] == "subagent:test"
        assert records[0]["input_tokens"] == 100
        assert records[0]["output_tokens"] == 50
        assert records[0]["total_tokens"] == 150
        assert "source_run_id" in records[0]

    def test_total_tokens_zero_uses_input_plus_output(self):
        collector = SubagentTokenCollector(caller="subagent:test")
        usage = {"input_tokens": 200, "output_tokens": 100, "total_tokens": 0}
        collector.on_llm_end(_make_llm_response("Hi", usage=usage), run_id=uuid4())
        records = collector.snapshot_records()
        assert len(records) == 1
        assert records[0]["total_tokens"] == 300

    def test_total_tokens_missing_uses_input_plus_output(self):
        collector = SubagentTokenCollector(caller="subagent:test")
        usage = {"input_tokens": 30, "output_tokens": 20}
        collector.on_llm_end(_make_llm_response("Hi", usage=usage), run_id=uuid4())
        records = collector.snapshot_records()
        assert len(records) == 1
        assert records[0]["total_tokens"] == 50

    def test_dedup_same_run_id(self):
        collector = SubagentTokenCollector(caller="subagent:test")
        run_id = uuid4()
        usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        collector.on_llm_end(_make_llm_response("A", usage=usage), run_id=run_id)
        collector.on_llm_end(_make_llm_response("A", usage=usage), run_id=run_id)
        records = collector.snapshot_records()
        assert len(records) == 1

    def test_no_usage_no_record(self):
        collector = SubagentTokenCollector(caller="subagent:test")
        collector.on_llm_end(_make_llm_response("Hi", usage=None), run_id=uuid4())
        records = collector.snapshot_records()
        assert len(records) == 0

    def test_zero_usage_no_record(self):
        collector = SubagentTokenCollector(caller="subagent:test")
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        collector.on_llm_end(_make_llm_response("Hi", usage=usage), run_id=uuid4())
        records = collector.snapshot_records()
        assert len(records) == 0

    def test_skips_empty_generation_and_records_later_usage(self):
        collector = SubagentTokenCollector(caller="subagent:test")
        response = _make_llm_response_from_usages(
            [
                None,
                {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
            ]
        )

        collector.on_llm_end(response, run_id=uuid4())

        records = collector.snapshot_records()
        assert len(records) == 1
        assert records[0]["total_tokens"] == 30

    def test_snapshot_returns_copy(self):
        collector = SubagentTokenCollector(caller="subagent:test")
        usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        collector.on_llm_end(_make_llm_response("Hi", usage=usage), run_id=uuid4())
        snap1 = collector.snapshot_records()
        snap2 = collector.snapshot_records()
        assert snap1 == snap2
        assert snap1 is not snap2
        # Mutating snapshot does not affect internal records
        snap1.append({"source_run_id": "fake"})
        assert len(collector.snapshot_records()) == 1

    def test_multiple_calls_accumulate(self):
        collector = SubagentTokenCollector(caller="subagent:test")
        usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        collector.on_llm_end(_make_llm_response("A", usage=usage), run_id=uuid4())
        collector.on_llm_end(_make_llm_response("B", usage=usage), run_id=uuid4())
        records = collector.snapshot_records()
        assert len(records) == 2

    def test_different_run_ids_accumulate_separately(self):
        collector = SubagentTokenCollector(caller="subagent:test")
        usage1 = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        usage2 = {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30}
        collector.on_llm_end(_make_llm_response("A", usage=usage1), run_id=uuid4())
        collector.on_llm_end(_make_llm_response("B", usage=usage2), run_id=uuid4())
        records = collector.snapshot_records()
        assert len(records) == 2
        assert records[0]["total_tokens"] == 15
        assert records[1]["total_tokens"] == 30

    def test_message_without_usage_metadata_skipped(self):
        """A response where message has no usage_metadata attribute must be skipped."""
        collector = SubagentTokenCollector(caller="subagent:test")

        msg = MagicMock(spec=[])  # object without usage_metadata
        gen = MagicMock()
        gen.message = msg
        response = MagicMock()
        response.generations = [[gen]]

        collector.on_llm_end(response, run_id=uuid4())
        records = collector.snapshot_records()
        assert len(records) == 0

    def test_generation_without_message_skipped(self):
        """A generation without a message attribute must be skipped."""
        collector = SubagentTokenCollector(caller="subagent:test")

        gen = MagicMock(spec=[])  # object without message
        response = MagicMock()
        response.generations = [[gen]]

        collector.on_llm_end(response, run_id=uuid4())
        records = collector.snapshot_records()
        assert len(records) == 0
