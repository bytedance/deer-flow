"""Tests for memory retrieval trace persistence."""

import json

from deerflow.agents.lead_agent import prompt as lead_prompt
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
