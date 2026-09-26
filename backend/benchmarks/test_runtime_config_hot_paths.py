"""Deterministic, offline benchmarks for runtime and config hot paths."""

from __future__ import annotations

import asyncio

import pytest

from deerflow.config.app_config import AppConfig
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import RunManager

THREAD_COUNT = 100
RUNS_PER_THREAD = 100
TARGET_THREAD_ID = "thread-099"
EVENT_RUN_COUNT = 1_000
TARGET_RUN_ID = "run-0999"
CONFIG_ENTRY_COUNT = 1_000
LOOKUP_BATCH_SIZE = 100


def _event_batch() -> list[dict]:
    events: list[dict] = []
    for run_index in range(EVENT_RUN_COUNT):
        run_id = f"run-{run_index:04d}"
        for event_index, category in enumerate(("lifecycle", "message", "message", "lifecycle")):
            events.append(
                {
                    "thread_id": "event-thread",
                    "run_id": run_id,
                    "event_type": f"{category}.{event_index}",
                    "category": category,
                    "content": f"{run_id}-{event_index}",
                    "created_at": "2026-01-01T00:00:00+00:00",
                }
            )
    return events


def _build_app_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [{"name": f"model-{index:04d}", "use": "pkg:Model", "model": f"m-{index}"} for index in range(CONFIG_ENTRY_COUNT)],
            "tools": [{"name": f"tool-{index:04d}", "group": "default", "use": "pkg:tool"} for index in range(CONFIG_ENTRY_COUNT)],
            "tool_groups": [{"name": f"group-{index:04d}"} for index in range(CONFIG_ENTRY_COUNT)],
        }
    )


@pytest.mark.benchmark(group="memory-run-event-store")
def test_list_messages_by_run(benchmark):
    store = MemoryRunEventStore()
    with asyncio.Runner() as runner:
        runner.run(store.put_batch(_event_batch()))

        def query():
            return runner.run(store.list_messages_by_run("event-thread", TARGET_RUN_ID, limit=2))

        result = benchmark(query)

    assert [event["content"] for event in result] == [f"{TARGET_RUN_ID}-1", f"{TARGET_RUN_ID}-2"]


@pytest.mark.benchmark(group="run-manager")
def test_list_runs_by_thread(benchmark):
    manager = RunManager(worker_id="benchmark-worker")
    with asyncio.Runner() as runner:
        for thread_index in range(THREAD_COUNT):
            thread_id = f"thread-{thread_index:03d}"
            for run_index in range(RUNS_PER_THREAD):
                record = runner.run(manager.create(thread_id))
                timestamp = f"2026-01-01T00:{run_index // 60:02d}:{run_index % 60:02d}+00:00"
                record.created_at = timestamp
                record.updated_at = timestamp

        def query():
            return runner.run(manager.list_by_thread(TARGET_THREAD_ID, limit=25))

        result = benchmark(query)

    assert len(result) == 25
    assert result[0].created_at == "2026-01-01T00:01:39+00:00"


@pytest.mark.benchmark(group="app-config")
def test_app_config_getters_hit(benchmark):
    config = _build_app_config()
    names = range(CONFIG_ENTRY_COUNT - LOOKUP_BATCH_SIZE, CONFIG_ENTRY_COUNT)

    def lookup() -> int:
        found = 0
        for index in names:
            found += config.get_model_config(f"model-{index:04d}") is not None
            found += config.get_tool_config(f"tool-{index:04d}") is not None
            found += config.get_tool_group_config(f"group-{index:04d}") is not None
        return found

    assert benchmark(lookup) == LOOKUP_BATCH_SIZE * 3


@pytest.mark.benchmark(group="app-config")
def test_app_config_getters_miss(benchmark):
    config = _build_app_config()
    names = range(LOOKUP_BATCH_SIZE)

    def lookup() -> int:
        missing = 0
        for index in names:
            missing += config.get_model_config(f"missing-model-{index:04d}") is None
            missing += config.get_tool_config(f"missing-tool-{index:04d}") is None
            missing += config.get_tool_group_config(f"missing-group-{index:04d}") is None
        return missing

    assert benchmark(lookup) == LOOKUP_BATCH_SIZE * 3
