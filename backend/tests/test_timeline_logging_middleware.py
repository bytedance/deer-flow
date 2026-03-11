"""Tests for timeline logging of subagent trajectories."""

from __future__ import annotations

import json
from pathlib import Path

from src.agents.middlewares.timeline_logging_middleware import (
    _file_record_subagent_trajectories,
)


def _read_timeline(timeline_path: Path) -> dict:
    with timeline_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def test_file_timeline_records_subagent_trajectory_changes(tmp_path) -> None:
    thread_id = "thread-1"
    state = {"thread_data": {"outputs_path": str(tmp_path)}}

    trajectories_v1 = {
        "task-1": {
            "task_id": "task-1",
            "status": "completed",
            "messages": [{"type": "ai", "content": "thinking"}],
        }
    }

    _file_record_subagent_trajectories(state, thread_id, trajectories_v1, "after_agent")
    _file_record_subagent_trajectories(state, thread_id, trajectories_v1, "after_agent")

    timeline_path = tmp_path / "agent_timeline.json"
    timeline = _read_timeline(timeline_path)
    subagent_events = [event for event in timeline["events"] if event.get("event") == "subagent_trajectory"]
    assert len(subagent_events) == 1

    trajectories_v2 = {
        "task-1": {
            "task_id": "task-1",
            "status": "completed",
            "messages": [
                {"type": "ai", "content": "thinking"},
                {"type": "tool", "tool_call_id": "c1", "content": "result"},
            ],
        }
    }
    _file_record_subagent_trajectories(state, thread_id, trajectories_v2, "after_agent")

    timeline = _read_timeline(timeline_path)
    subagent_events = [event for event in timeline["events"] if event.get("event") == "subagent_trajectory"]
    assert len(subagent_events) == 2
