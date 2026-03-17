"""Tests for long-horizon memory summary retrieval."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.agents.memory.long_horizon_store import (
    query_hypothesis_validation_memory,
    query_long_horizon_memory,
    record_hypothesis_validation_result,
    update_long_horizon_memory,
)
from src.agents.middlewares.memory_middleware import MemoryMiddleware


class _Msg:
    def __init__(self, msg_type: str, content: str):
        self.type = msg_type
        self.content = content
        self.tool_calls = []


def _memory_cfg() -> SimpleNamespace:
    return SimpleNamespace(
        enabled=True,
        long_horizon_enabled=True,
        long_horizon_storage_path=".deer-flow/memory_long_horizon.json",
        long_horizon_max_entries=500,
        long_horizon_summary_chars=900,
        long_horizon_injection_enabled=True,
        long_horizon_top_k=5,
        long_horizon_min_similarity=0.01,
        long_horizon_injection_max_chars=2400,
        long_horizon_embedding_dim=192,
        long_horizon_cross_thread_enabled=True,
        long_horizon_topic_memory_enabled=True,
        long_horizon_topic_top_k=2,
        long_horizon_project_memory_enabled=True,
        long_horizon_project_top_k=2,
        long_horizon_current_thread_boost=0.08,
        long_horizon_project_boost=0.12,
        long_horizon_topic_overlap_boost=0.03,
        long_horizon_hypothesis_memory_enabled=True,
        long_horizon_hypothesis_top_k=2,
        long_horizon_hypothesis_max_entries=400,
        long_horizon_hypothesis_failure_boost=0.08,
    )


def test_long_horizon_store_update_and_query(tmp_path: Path) -> None:
    with (
        patch("src.agents.memory.long_horizon_store.get_memory_config", return_value=_memory_cfg()),
        patch("src.agents.memory.long_horizon_store.get_paths", return_value=SimpleNamespace(base_dir=tmp_path)),
    ):
        update_long_horizon_memory(
            "thread-1",
            [
                _Msg("human", "We need to keep Introduction core motivation around causal interpretability."),
                _Msg("ai", "I will preserve intro motivation and use it in Discussion."),
            ],
        )

        hits = query_long_horizon_memory(
            "discussion should reflect causal interpretability motivation",
            thread_id="thread-1",
        )

    assert len(hits) >= 1
    assert "causal" in hits[0]["summary"].lower()


def test_memory_middleware_injects_long_horizon_block() -> None:
    middleware = MemoryMiddleware()
    runtime = SimpleNamespace(context={"configurable": {"thread_id": "thread-1"}})
    state = {"messages": [_Msg("human", "请写 discussion 并保持 introduction 的立意")]}

    with (
        patch("src.agents.middlewares.memory_middleware.get_memory_config", return_value=_memory_cfg()),
        patch(
            "src.agents.memory.long_horizon_store.query_long_horizon_memory",
            return_value=[{"summary": "Introduction 核心立意：强调因果解释性", "score": 0.88}],
        ),
        patch(
            "src.agents.memory.long_horizon_store.format_long_horizon_injection",
            return_value="<long_horizon_memory>\n- (0.880) Introduction 核心立意\n</long_horizon_memory>",
        ),
    ):
        update = middleware.before_model(state, runtime)

    assert update is not None
    injected = update["messages"][0]
    assert injected.additional_kwargs.get("deerflow_injected") == "long_horizon_memory"
    assert "<long_horizon_memory>" in str(injected.content)


def test_long_horizon_query_can_retrieve_project_memory_across_threads(tmp_path: Path) -> None:
    with (
        patch("src.agents.memory.long_horizon_store.get_memory_config", return_value=_memory_cfg()),
        patch("src.agents.memory.long_horizon_store.get_paths", return_value=SimpleNamespace(base_dir=tmp_path)),
    ):
        update_long_horizon_memory(
            "thread-project-a",
            [
                _Msg(
                    "human",
                    "project_id: proj-alpha. Please keep the control vs ablation narrative with figure path /research-writing/compiled/proj-alpha-results.md",
                ),
                _Msg("ai", "Acknowledged. I will keep proj-alpha control/ablation constraints in future revisions."),
            ],
        )
        update_long_horizon_memory(
            "thread-project-b",
            [
                _Msg("human", "Continue writing discussion for project_id proj-alpha and preserve control-ablation caveats."),
                _Msg("ai", "I will continue with proj-alpha and preserve those caveats."),
            ],
        )

        hits = query_long_horizon_memory(
            "Need project_id proj-alpha memory for control and ablation continuity.",
            thread_id="thread-project-b",
        )

    assert len(hits) >= 1
    assert any("proj-alpha" in str(item.get("summary", "")).lower() for item in hits)
    assert any(item.get("memory_kind") in {"entry", "project"} for item in hits)


def test_hypothesis_validation_history_can_be_recalled(tmp_path: Path) -> None:
    with (
        patch("src.agents.memory.long_horizon_store.get_memory_config", return_value=_memory_cfg()),
        patch("src.agents.memory.long_horizon_store.get_paths", return_value=SimpleNamespace(base_dir=tmp_path)),
    ):
        record_hypothesis_validation_result(
            thread_id="thread-idea-a",
            project_id="proj-facs",
            section_id="discussion",
            hypothesis_id="H-old",
            statement="FACS trend indicates a late-stage activation signal.",
            validation_status="failed",
            rationale="Signal was previously treated as noise due to low sample size.",
            evidence_ids=["ev-facs-1"],
            citation_ids=["10.1000/facs-old"],
        )
        record_hypothesis_validation_result(
            thread_id="thread-idea-b",
            project_id="proj-facs",
            section_id="discussion",
            hypothesis_id="H-new",
            statement="Follow-up cohort reproduces activation trend under stronger controls.",
            validation_status="supported",
            rationale="Replication cohort confirms directionality.",
            evidence_ids=["ev-facs-2"],
            citation_ids=["10.1000/facs-new"],
        )
        hits = query_hypothesis_validation_memory(
            "New idea: maybe the old FACS activation trend was not just noise.",
            thread_id="thread-idea-b",
            project_id="proj-facs",
            top_k=3,
            include_statuses=["failed"],
        )

    assert hits
    assert hits[0]["validation_status"] == "failed"
    assert "facs" in hits[0]["summary"].lower()

