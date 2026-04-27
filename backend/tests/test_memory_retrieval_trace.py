"""Tests for memory retrieval trace persistence."""

import json
from unittest.mock import MagicMock

from deerflow.agents.lead_agent import prompt as lead_prompt
from deerflow.agents.memory.retrieval_trace import CandidateFact, build_empty_retrieval_trace, emit_retrieval_trace
from deerflow.config.memory_config import (
    MemoryConfig,
    RetrievalTraceConfig,
    get_memory_config,
    set_memory_config,
)


def test_get_memory_context_emits_retrieval_trace(tmp_path, monkeypatch) -> None:
    original_config = get_memory_config()
    set_memory_config(
        MemoryConfig(
            enabled=True,
            injection_enabled=True,
            retrieval_trace=RetrievalTraceConfig(
                enabled=True,
                storage_path=str(tmp_path / "retrieval_traces.jsonl"),
                max_file_bytes=1024 * 1024,
            ),
        )
    )
    monkeypatch.setattr("deerflow.agents.memory.get_memory_data", lambda agent_name=None: {"facts": [{"id": "fact_1", "content": "Remember this fact", "category": "knowledge", "confidence": 0.9}]})
    try:
        result = lead_prompt._get_memory_context(agent_name="lead")
    finally:
        set_memory_config(original_config)

    trace_path = tmp_path / "retrieval_traces.jsonl"
    assert "<memory>" in result
    assert trace_path.exists()

    lines = trace_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    payload = json.loads(lines[0])
    assert payload["agent_name"] == "lead"
    assert payload["selected_count"] == 1
    assert payload["total_candidates"] == 1
    assert payload["selections"][0]["reason"] == "selected"


def test_get_memory_context_skips_trace_when_disabled(tmp_path, monkeypatch) -> None:
    original_config = get_memory_config()
    set_memory_config(
        MemoryConfig(
            enabled=True,
            injection_enabled=True,
            retrieval_trace=RetrievalTraceConfig(
                enabled=False,
                storage_path=str(tmp_path / "retrieval_traces.jsonl"),
            ),
        )
    )
    monkeypatch.setattr("deerflow.agents.memory.get_memory_data", lambda agent_name=None: {"facts": [{"id": "fact_1", "content": "Remember this fact", "category": "knowledge", "confidence": 0.9}]})
    try:
        result = lead_prompt._get_memory_context(agent_name="lead")
    finally:
        set_memory_config(original_config)

    assert "<memory>" in result
    assert not (tmp_path / "retrieval_traces.jsonl").exists()


def test_emit_retrieval_trace_debug_log_avoids_payload_content(tmp_path, monkeypatch) -> None:
    original_config = get_memory_config()
    set_memory_config(
        MemoryConfig(
            retrieval_trace=RetrievalTraceConfig(
                enabled=True,
                storage_path=str(tmp_path / "retrieval_traces.jsonl"),
                max_file_bytes=1024 * 1024,
            )
        )
    )
    trace = build_empty_retrieval_trace(128)
    trace.trace_id = "trace_123"
    trace.selected_count = 1
    trace.candidates.append(
        CandidateFact(
            fact_id="fact_1",
            content_preview="secret project codename",
            category="context",
            confidence=0.9,
            layer=None,
            created_at=None,
        )
    )
    debug_mock = MagicMock()
    monkeypatch.setattr("deerflow.agents.memory.retrieval_trace.logger.debug", debug_mock)
    try:
        emit_retrieval_trace(trace, agent_name="lead")
    finally:
        set_memory_config(original_config)

    debug_mock.assert_called_once()
    debug_args = " ".join(str(arg) for arg in debug_mock.call_args[0])
    assert "trace_123" in debug_args
    assert "secret project codename" not in debug_args
