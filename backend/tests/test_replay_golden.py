"""Layer 1 of the record/replay e2e: replay a recorded trace through the **real
gateway** with a deterministic ``ReplayChatModel`` (no API key, no network) and
assert the streamed SSE event sequence matches a committed golden.

This catches backend protocol drift: if a change alters the shape/sequence of
SSE the gateway emits for the recorded scenario, this test goes red. The replay
model serves the recorded assistant turns by input hash, so direct-tool and
lead-to-subagent scenarios reproduce offline.

Recorded fixtures are produced by ``scripts/record_gateway.py`` +
``scripts/build_fixture_from_jsonl.py`` (manual, needs a key); small deterministic
orchestration scenarios can also supply purpose-built model decisions.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest
from _replay_fixture import REPLAY_MODEL_BLOCK, ReplayRunResult, build_config_yaml, drive_gateway, prepare_hermetic_extras

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "replay"


def _install_real_subagent_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace conftest's cycle-breaking executor mock for this E2E scenario.

    The full gateway import resolves the production import graph first. Importing
    the executor afterwards avoids the circular import that ``tests/conftest.py``
    protects lightweight unit tests from, while letting the already-imported task
    tool execute the real implementation. ``monkeypatch`` restores the mocked
    module, its parent-package binding, and every patched attribute after the test.
    """
    import deerflow.subagents as subagents_package

    task_tool_module = importlib.import_module("deerflow.tools.builtins.task_tool")

    module_name = "deerflow.subagents.executor"
    # Importing a child module also writes ``executor`` onto its parent package.
    # Track that dictionary entry explicitly so teardown cannot leave the real
    # executor reachable after ``sys.modules`` has been restored to conftest's mock.
    monkeypatch.setitem(subagents_package.__dict__, "executor", None)
    monkeypatch.delitem(subagents_package.__dict__, "executor")
    monkeypatch.delitem(sys.modules, module_name)
    executor_module = importlib.import_module(module_name)

    for name in ("SubagentExecutor", "SubagentResult"):
        monkeypatch.setattr(subagents_package, name, getattr(executor_module, name))
    for name in (
        "SubagentExecutor",
        "SubagentStatus",
        "cleanup_background_task",
        "get_background_task_result",
        "request_cancel_background_task",
    ):
        monkeypatch.setattr(task_tool_module, name, getattr(executor_module, name))


def _reset_process_singletons(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalidate process-wide caches so the test-only config/home take effect.

    Same set the real-server e2e resets (see test_setup_agent_http_e2e_real_server).
    """
    from deerflow.config import app_config as app_config_module
    from deerflow.config import paths as paths_module
    from deerflow.persistence import engine as engine_module

    for module, attr in (
        (app_config_module, "_app_config"),
        (app_config_module, "_app_config_path"),
        (app_config_module, "_app_config_mtime"),
        (paths_module, "_paths_singleton"),
        (engine_module, "_engine"),
        (engine_module, "_session_factory"),
    ):
        monkeypatch.setattr(module, attr, None, raising=False)


def _run_replay_scenario(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    scenario: str,
    mode: str,
) -> tuple[Path, ReplayRunResult]:
    fixture_path = FIXTURE_DIR / f"{scenario}.{mode}.json"
    events_path = FIXTURE_DIR / f"{scenario}.{mode}.events.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("DEER_FLOW_HOME", str(home))
    monkeypatch.setenv("DEERFLOW_REPLAY_FIXTURE", str(fixture_path))

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(build_config_yaml(model_block=REPLAY_MODEL_BLOCK, home=home), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(cfg_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(prepare_hermetic_extras(home)))

    _reset_process_singletons(monkeypatch)
    from deerflow.config import app_config as app_config_module

    cfg = app_config_module.get_app_config()
    cfg.database.sqlite_dir = str(home / "db")

    # Fail loud on a replay miss. The gateway swallows a hash-miss into a normal
    # assistant error message, so the SSE *shapes* below stay green on a stale
    # fixture — the miss list is the only reliable signal at this layer.
    import replay_provider

    from app.gateway.app import create_app

    if fixture.get("requires_real_subagent"):
        _install_real_subagent_executor(monkeypatch)

    replay_provider.reset_replay_misses()

    replay_run = drive_gateway(
        create_app(),
        prompt=fixture["prompt"],
        context=fixture["context"],
        stream_mode=fixture.get("stream_mode"),
    )
    events = replay_run.event_shapes

    assert events, "replay produced no SSE events"
    assert events[0]["event"] == "metadata", f"first event should be metadata, got {events[0]!r}"
    assert events[-1]["event"] == "end", f"last event should be end (run completed), got {events[-1]!r}"

    misses = replay_provider.replay_misses()
    assert not misses, f"replay miss ({len(misses)}): the fixture is stale vs the current system prompt or agent graph. Re-record it (see backend/docs/REPLAY_E2E.md). Missed hashes: {misses}"

    # Regenerate the committed golden after re-recording the fixture:
    #   DEERFLOW_WRITE_GOLDEN=1 uv run pytest tests/test_replay_golden.py
    if os.environ.get("DEERFLOW_WRITE_GOLDEN"):
        events_path.write_text(json.dumps({"scenario": scenario, "mode": mode, "events": events}, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        golden = json.loads(events_path.read_text(encoding="utf-8"))["events"]
        # Guards backend SSE protocol drift: the event name + payload-key sequence
        # must match the committed golden. (Replay divergence is caught by the miss
        # assertion above, not here — a swallowed miss keeps the shapes identical.)
        assert events == golden, f"SSE event-shape sequence drifted from the golden.\ngot  ({len(events)}): {[e['event'] for e in events]}\nwant ({len(golden)}): {[e['event'] for e in golden]}"

    return home, replay_run


def _final_assistant_message(events: list[dict]) -> dict | None:
    for event in reversed(events):
        if event["event"] != "values" or not isinstance(event["data"], dict):
            continue
        messages = event["data"].get("messages")
        if not isinstance(messages, list):
            continue
        for message in reversed(messages):
            if not isinstance(message, dict) or message.get("type") != "ai":
                continue
            content = message.get("content")
            if isinstance(content, str) and content:
                return message
    return None


@pytest.mark.no_auto_user
def test_replay_write_read_file_ultra_matches_golden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _run_replay_scenario(tmp_path, monkeypatch, scenario="write_read_file", mode="ultra")


@pytest.mark.no_auto_user
def test_replay_subagent_file_task_ultra_matches_golden_and_semantics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home, replay_run = _run_replay_scenario(tmp_path, monkeypatch, scenario="subagent_file_task", mode="ultra")

    task_events = [event["data"] for event in replay_run.events if event["event"] == "custom" and isinstance(event["data"], dict) and str(event["data"].get("type", "")).startswith("task_")]
    assert task_events, "expected task lifecycle events in the custom stream"
    task_event_types = [event["type"] for event in task_events]

    assert task_event_types[0] == "task_started"
    assert "task_running" in task_event_types
    assert task_event_types[-1] == "task_completed"
    assert not {"task_failed", "task_cancelled", "task_timed_out"}.intersection(task_event_types)
    assert {event["task_id"] for event in task_events} == {"call_subagent_replay_task"}
    assert task_events[-1]["result"] == "hi from subagent replay."

    workspace_files = list(home.glob(f"users/*/threads/{replay_run.thread_id}/user-data/workspace/subagent-note.txt"))
    assert len(workspace_files) == 1
    assert workspace_files[0].read_text(encoding="utf-8") == "hi from subagent replay."

    final_assistant = _final_assistant_message(replay_run.events)
    assert final_assistant is not None
    assert final_assistant.get("id") == "replay-lead-final"
    assert final_assistant.get("content") == "hi from subagent replay."
