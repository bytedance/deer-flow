from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import empty_checkpoint, uuid6
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.runtime import RunStatus
from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY


def _checkpoint(checkpoint_id: str, messages: list[object], *, metadata: dict | None = None):
    return SimpleNamespace(
        config={
            "configurable": {
                "thread_id": "thread-1",
                "checkpoint_ns": "",
                "checkpoint_id": checkpoint_id,
                "checkpoint_map": None,
            }
        },
        checkpoint={"channel_values": {"messages": messages}},
        metadata=metadata or {},
    )


async def _put_memory_checkpoint(
    checkpointer: InMemorySaver,
    thread_id: str,
    messages: list[object],
    *,
    step: int,
    parent_config: dict | None = None,
    metadata: dict | None = None,
) -> dict:
    checkpoint = empty_checkpoint()
    checkpoint["id"] = str(uuid6())
    checkpoint["channel_values"] = {"messages": messages}
    checkpoint["channel_versions"] = {"messages": step}
    checkpoint_metadata = {
        "step": step,
        "source": "loop",
        "writes": {"test": {"messages": messages}},
        "parents": {},
    }
    checkpoint_metadata.update(metadata or {})
    return await checkpointer.aput(
        parent_config or {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        checkpoint,
        checkpoint_metadata,
        {"messages": step},
    )


async def _collect_checkpoints(checkpointer: InMemorySaver, config: dict) -> list:
    return [checkpoint async for checkpoint in checkpointer.alist(config)]


class FakeCheckpointer:
    def __init__(self, history, *, latest=None, materialized_history=None, materialized_latest=None):
        self.history = history
        self.latest = latest
        self.materialized_history = materialized_history
        self.materialized_latest = materialized_latest
        self.alist_limits = []

    async def aget_tuple(self, config):
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")
        if checkpoint_id:
            return next((item for item in self.history if item.config["configurable"]["checkpoint_id"] == checkpoint_id), None)
        return self.latest or (self.history[0] if self.history else None)

    async def alist(self, config, limit=200):
        self.alist_limits.append(limit)
        for item in self.history[:limit]:
            yield item


def _snapshot(checkpoint_id: str, messages: list[object], *, metadata: dict | None = None):
    return SimpleNamespace(
        values={"messages": messages},
        config={
            "configurable": {
                "thread_id": "thread-1",
                "checkpoint_ns": "",
                "checkpoint_id": checkpoint_id,
                "checkpoint_map": None,
            }
        },
        metadata=metadata or {},
    )


class FakeAccessor:
    def __init__(self, checkpointer: FakeCheckpointer):
        self.checkpointer = checkpointer

    @staticmethod
    def _from_raw(checkpoint):
        return SimpleNamespace(
            values=dict(checkpoint.checkpoint.get("channel_values", {})),
            config=checkpoint.config,
            metadata=checkpoint.metadata,
            parent_config=getattr(checkpoint, "parent_config", None),
        )

    async def aget(self, config):
        materialized_latest = getattr(self.checkpointer, "materialized_latest", None)
        if materialized_latest is not None and not config.get("configurable", {}).get("checkpoint_id"):
            return materialized_latest
        raw = await self.checkpointer.aget_tuple(config)
        return self._from_raw(raw) if raw is not None else SimpleNamespace(values={}, config={}, metadata={})

    async def ahistory(self, config, *, limit=None):
        alist_limits = getattr(self.checkpointer, "alist_limits", None)
        if alist_limits is not None:
            alist_limits.append(limit)
        history = getattr(self.checkpointer, "materialized_history", None)
        if history is None:
            if hasattr(self.checkpointer, "history"):
                history = [self._from_raw(item) for item in self.checkpointer.history]
            else:
                history = [self._from_raw(item) async for item in self.checkpointer.alist(config, limit=limit)]
        return history[:limit]


@pytest.fixture(autouse=True)
def _patch_checkpoint_accessor(monkeypatch):
    from app.gateway.routers import thread_runs

    def build_accessor(request, *, thread_id, assistant_id=None, checkpoint_id=None):
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        if checkpoint_id is not None:
            config["configurable"]["checkpoint_id"] = checkpoint_id
        return FakeAccessor(request.app.state.checkpointer), config

    async def build_thread_accessor(request, *, thread_id, checkpoint_id=None):
        return build_accessor(request, thread_id=thread_id, checkpoint_id=checkpoint_id)

    monkeypatch.setattr(thread_runs, "build_checkpoint_state_accessor", build_accessor)
    monkeypatch.setattr(thread_runs, "build_thread_checkpoint_state_accessor", build_thread_accessor)


class FakeEventStore:
    def __init__(self, rows):
        self.rows = rows

    async def list_messages(self, thread_id, *, limit=50, before_seq=None, after_seq=None):
        return self.rows[-limit:]


class FakeRunManager:
    def __init__(self, records):
        self.records = records

    async def list_by_thread(self, thread_id, *, user_id=None, limit=100):
        return self.records[:limit]


def _request(checkpointer, event_store, *, run_manager=None, user_id="user-1"):
    from app.gateway.auth_disabled import AUTH_SOURCE_SESSION

    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                checkpointer=checkpointer,
                run_event_store=event_store,
                run_manager=run_manager or FakeRunManager([]),
            )
        ),
        state=SimpleNamespace(user=SimpleNamespace(id=user_id), auth_source=AUTH_SOURCE_SESSION),
    )


def test_run_wait_readers_return_materialized_final_values() -> None:
    from app.gateway.routers import runs, thread_runs

    snapshot = SimpleNamespace(
        values={
            "messages": [
                HumanMessage(id="h1", content="question"),
                AIMessage(id="a1", content="answer"),
            ]
        },
        config={
            "configurable": {
                "thread_id": "thread-1",
                "checkpoint_ns": "",
                "checkpoint_id": "ckpt-2",
            }
        },
        parent_config={"configurable": {"checkpoint_id": "ckpt-1"}},
        metadata={"step": 2},
        next=(),
        tasks=(),
        created_at=None,
    )
    accessor = SimpleNamespace(aget=AsyncMock(return_value=snapshot))
    record = SimpleNamespace(
        run_id="run-1",
        thread_id="thread-1",
        task=None,
        status=RunStatus.success,
        error=None,
    )
    request = SimpleNamespace()
    body = thread_runs.RunCreateRequest(
        assistant_id="lead-agent",
        config={"configurable": {"thread_id": "thread-1"}},
    )

    async def _scenario() -> tuple[dict, dict]:
        with (
            patch.object(thread_runs, "get_stream_bridge", return_value=object()),
            patch.object(thread_runs, "get_run_manager", return_value=object()),
            patch.object(thread_runs, "start_run", AsyncMock(return_value=record)),
            patch.object(
                thread_runs,
                "build_checkpoint_state_accessor",
                create=True,
                return_value=(accessor, snapshot.config),
            ),
            patch.object(runs, "get_stream_bridge", return_value=object()),
            patch.object(runs, "get_run_manager", return_value=object()),
            patch.object(runs, "start_run", AsyncMock(return_value=record)),
            patch.object(
                runs,
                "build_checkpoint_state_accessor",
                create=True,
                return_value=(accessor, snapshot.config),
            ),
        ):
            thread_result = await thread_runs.wait_run.__wrapped__("thread-1", body, request)
            stateless_result = await runs.stateless_wait(body, request)
        return thread_result, stateless_result

    thread_result, stateless_result = asyncio.run(_scenario())

    assert [message["id"] for message in thread_result["messages"]] == ["h1", "a1"]
    assert [message["id"] for message in stateless_result["messages"]] == ["h1", "a1"]


def test_run_wait_readers_preserve_terminal_error_without_checkpoint() -> None:
    from app.gateway.routers import runs, thread_runs

    snapshot = SimpleNamespace(
        values={},
        config={"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}},
        parent_config=None,
        metadata={},
        next=(),
        tasks=(),
        created_at=None,
    )
    accessor = SimpleNamespace(aget=AsyncMock(return_value=snapshot))
    record = SimpleNamespace(
        run_id="run-1",
        thread_id="thread-1",
        task=None,
        status=RunStatus.error,
        error="run failed before checkpoint",
    )
    request = SimpleNamespace()
    body = thread_runs.RunCreateRequest(config={"configurable": {"thread_id": "thread-1"}})

    async def _scenario() -> tuple[dict, dict]:
        with (
            patch.object(thread_runs, "get_stream_bridge", return_value=object()),
            patch.object(thread_runs, "get_run_manager", return_value=object()),
            patch.object(thread_runs, "start_run", AsyncMock(return_value=record)),
            patch.object(
                thread_runs,
                "build_checkpoint_state_accessor",
                return_value=(accessor, snapshot.config),
            ),
            patch.object(runs, "get_stream_bridge", return_value=object()),
            patch.object(runs, "get_run_manager", return_value=object()),
            patch.object(runs, "start_run", AsyncMock(return_value=record)),
            patch.object(
                runs,
                "build_checkpoint_state_accessor",
                return_value=(accessor, snapshot.config),
            ),
        ):
            thread_result = await thread_runs.wait_run.__wrapped__("thread-1", body, request)
            stateless_result = await runs.stateless_wait(body, request)
        return thread_result, stateless_result

    thread_result, stateless_result = asyncio.run(_scenario())

    expected = {"status": "error", "error": "run failed before checkpoint"}
    assert thread_result == expected
    assert stateless_result == expected


@pytest.mark.parametrize("route_name", ["thread", "stateless"])
def test_run_wait_readers_preserve_terminal_error_when_accessor_builder_fails(route_name: str) -> None:
    from app.gateway.routers import runs, thread_runs

    record = SimpleNamespace(
        run_id="run-1",
        thread_id="thread-1",
        task=None,
        status=RunStatus.error,
        error="run failed before checkpoint",
    )
    request = SimpleNamespace()
    body = thread_runs.RunCreateRequest(config={"configurable": {"thread_id": "thread-1"}})

    async def _scenario() -> dict:
        if route_name == "thread":
            with (
                patch.object(thread_runs, "get_stream_bridge", return_value=object()),
                patch.object(thread_runs, "get_run_manager", return_value=object()),
                patch.object(thread_runs, "start_run", AsyncMock(return_value=record)),
                patch.object(
                    thread_runs,
                    "build_checkpoint_state_accessor",
                    side_effect=RuntimeError("graph construction failed"),
                ),
            ):
                return await thread_runs.wait_run.__wrapped__("thread-1", body, request)

        with (
            patch.object(runs, "get_stream_bridge", return_value=object()),
            patch.object(runs, "get_run_manager", return_value=object()),
            patch.object(runs, "start_run", AsyncMock(return_value=record)),
            patch.object(
                runs,
                "build_checkpoint_state_accessor",
                side_effect=RuntimeError("graph construction failed"),
            ),
        ):
            return await runs.stateless_wait(body, request)

    result = asyncio.run(_scenario())

    assert result == {"status": "error", "error": "run failed before checkpoint"}


def test_prepare_regenerate_payload_returns_clean_input_and_base_checkpoint():
    from app.gateway.routers import thread_runs

    human = HumanMessage(
        id="human-1",
        content="<uploaded_files>injected</uploaded_files>\n\n/data-analysis analyze data.csv",
        additional_kwargs={
            ORIGINAL_USER_CONTENT_KEY: "/data-analysis analyze data.csv",
            "files": [{"filename": "data.csv", "path": "/mnt/user-data/uploads/data.csv"}],
        },
    )
    ai = AIMessage(id="ai-1", content="answer v1")
    base = _checkpoint("ckpt-base", [])
    after_human = _checkpoint("ckpt-human", [human])
    latest = _checkpoint("ckpt-ai", [human, ai])
    checkpointer = FakeCheckpointer([latest, after_human, base])
    event_store = FakeEventStore(
        [
            {
                "run_id": "run-old",
                "event_type": "llm.ai.response",
                "category": "message",
                "content": {"id": "ai-1", "type": "ai", "content": "answer v1"},
                "metadata": {"caller": "lead_agent"},
            }
        ]
    )

    original_builder = thread_runs.build_thread_checkpoint_state_accessor
    thread_builder = AsyncMock(side_effect=original_builder)
    with patch.object(thread_runs, "build_thread_checkpoint_state_accessor", thread_builder):
        response = asyncio.run(thread_runs._prepare_regenerate_payload("thread-1", "ai-1", _request(checkpointer, event_store)))

    assert [call.kwargs["thread_id"] for call in thread_builder.await_args_list] == ["thread-1", "thread-1"]

    assert response.checkpoint == {
        "checkpoint_ns": "",
        "checkpoint_id": "ckpt-base",
        "checkpoint_map": None,
    }
    assert response.target_run_id == "run-old"
    assert response.metadata == {
        "regenerate_from_message_id": "ai-1",
        "regenerate_from_run_id": "run-old",
        "regenerate_checkpoint_id": "ckpt-base",
    }
    regenerated_human = response.input["messages"][0]
    assert regenerated_human["id"] == "human-1"
    assert regenerated_human["content"] == [{"type": "text", "text": "/data-analysis analyze data.csv"}]
    assert regenerated_human["additional_kwargs"] == {"files": [{"filename": "data.csv", "path": "/mnt/user-data/uploads/data.csv"}]}


def test_prepare_regenerate_payload_does_not_mutate_legacy_single_checkpoint_branch():
    from app.gateway.routers.thread_runs import _prepare_regenerate_payload

    checkpointer = InMemorySaver()
    source_thread_id = "source-thread"
    branch_thread_id = "legacy-branch"
    source_run_id = "source-run"
    human = HumanMessage(id="human-1", content="question", additional_kwargs={"run_id": source_run_id})
    ai = AIMessage(id="ai-1", content="answer")

    async def _seed() -> str:
        source_base_config = await _put_memory_checkpoint(checkpointer, source_thread_id, [], step=0)
        after_human = await _put_memory_checkpoint(
            checkpointer,
            source_thread_id,
            [human],
            step=1,
            parent_config=source_base_config,
        )
        source_head_config = await _put_memory_checkpoint(
            checkpointer,
            source_thread_id,
            [human, ai],
            step=2,
            parent_config=after_human,
        )
        source_head = await checkpointer.aget_tuple(source_head_config)
        assert source_head is not None

        legacy_head = copy.deepcopy(source_head.checkpoint)
        legacy_head_id = str(uuid6())
        legacy_head["id"] = legacy_head_id
        legacy_metadata = copy.deepcopy(source_head.metadata)
        legacy_metadata.update(
            {
                "source": "branch",
                "deerflow_branch": True,
                "branch_parent_thread_id": source_thread_id,
                "branch_parent_checkpoint_id": source_head_config["configurable"]["checkpoint_id"],
                "branch_parent_message_id": "ai-1",
            }
        )
        await checkpointer.aput(
            {"configurable": {"thread_id": branch_thread_id, "checkpoint_ns": ""}},
            legacy_head,
            legacy_metadata,
            dict(legacy_head["channel_versions"]),
        )
        return legacy_head_id

    legacy_head_id = asyncio.run(_seed())
    request = _request(checkpointer, FakeEventStore([]))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(_prepare_regenerate_payload(branch_thread_id, "ai-1", request))

    assert exc.value.status_code == 409
    assert exc.value.detail == "Could not find an addressable checkpoint before the target user message"
    latest = asyncio.run(checkpointer.aget_tuple({"configurable": {"thread_id": branch_thread_id, "checkpoint_ns": ""}}))
    assert latest is not None
    assert latest.config["configurable"]["checkpoint_id"] == legacy_head_id
    branch_history = asyncio.run(_collect_checkpoints(checkpointer, {"configurable": {"thread_id": branch_thread_id, "checkpoint_ns": ""}}))
    assert [item.config["configurable"]["checkpoint_id"] for item in branch_history] == [legacy_head_id]


def test_prepare_regenerate_payload_rejects_legacy_branch_when_source_checkpoint_is_missing():
    from app.gateway.routers.thread_runs import _prepare_regenerate_payload

    checkpointer = InMemorySaver()
    branch_thread_id = "legacy-orphan"
    human = HumanMessage(id="human-1", content="question", additional_kwargs={"run_id": "source-run"})
    ai = AIMessage(id="ai-1", content="answer")

    async def _seed() -> None:
        await _put_memory_checkpoint(
            checkpointer,
            branch_thread_id,
            [human, ai],
            step=1,
            metadata={
                "source": "branch",
                "deerflow_branch": True,
                "branch_parent_thread_id": "deleted-source",
                "branch_parent_checkpoint_id": "missing-checkpoint",
                "branch_parent_message_id": "ai-1",
            },
        )

    asyncio.run(_seed())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            _prepare_regenerate_payload(
                branch_thread_id,
                "ai-1",
                _request(checkpointer, FakeEventStore([])),
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Could not find an addressable checkpoint before the target user message"
    branch_history = asyncio.run(_collect_checkpoints(checkpointer, {"configurable": {"thread_id": branch_thread_id, "checkpoint_ns": ""}}))
    assert len(branch_history) == 1


def test_prepare_regenerate_uses_materialized_history_when_raw_messages_are_omitted():
    from app.gateway.routers.thread_runs import _prepare_regenerate_payload

    earlier_human = HumanMessage(id="human-0", content="earlier question")
    earlier_ai = AIMessage(id="ai-0", content="earlier answer")
    target_human = HumanMessage(id="human-1", content="question")
    target_ai = AIMessage(id="ai-1", content="answer")

    raw_latest = _checkpoint("ckpt-ai", [])
    raw_after_human = _checkpoint("ckpt-human", [])
    raw_base = _checkpoint("ckpt-base", [])
    materialized_history = [
        _snapshot("ckpt-ai", [earlier_human, earlier_ai, target_human, target_ai]),
        _snapshot("ckpt-human", [earlier_human, earlier_ai, target_human]),
        _snapshot("ckpt-base", [earlier_human, earlier_ai]),
    ]
    checkpointer = FakeCheckpointer(
        [raw_latest, raw_after_human, raw_base],
        latest=raw_latest,
        materialized_history=materialized_history,
        materialized_latest=materialized_history[0],
    )
    event_store = FakeEventStore(
        [
            {
                "run_id": "run-target",
                "event_type": "ai_message",
                "category": "message",
                "content": {"id": "ai-1", "type": "ai", "content": "answer"},
                "metadata": {"caller": "lead_agent"},
            }
        ]
    )

    response = asyncio.run(
        _prepare_regenerate_payload(
            "thread-1",
            "ai-1",
            _request(checkpointer, event_store),
        )
    )

    assert response.checkpoint["checkpoint_id"] == "ckpt-base"
    assert response.metadata["regenerate_checkpoint_id"] == "ckpt-base"
    assert response.input["messages"][0]["id"] == "human-1"
    assert checkpointer.alist_limits == [400]


def test_prepare_regenerate_rejects_cyclic_lineage_without_chronological_fallback():
    from app.gateway.routers import thread_runs

    human = HumanMessage(id="human-1", content="question")
    ai = AIMessage(id="ai-1", content="answer")

    def linked_snapshot(checkpoint_id: str, messages: list[object], parent_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            values={"messages": messages},
            config={
                "configurable": {
                    "thread_id": "thread-1",
                    "checkpoint_ns": "",
                    "checkpoint_id": checkpoint_id,
                }
            },
            metadata={},
            parent_config={
                "configurable": {
                    "thread_id": "thread-1",
                    "checkpoint_ns": "",
                    "checkpoint_id": parent_id,
                }
            },
        )

    head = linked_snapshot("head", [human, ai], "cycle")
    cycle = linked_snapshot("cycle", [human], "head")
    wrong_sibling_base = linked_snapshot("wrong-sibling", [], "root")
    by_id = {"head": head, "cycle": cycle}

    async def aget(config):
        return by_id[config["configurable"]["checkpoint_id"]]

    accessor = SimpleNamespace(
        aget=aget,
        ahistory=AsyncMock(return_value=[head, wrong_sibling_base]),
    )
    builder = AsyncMock(
        return_value=(
            accessor,
            {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}},
        )
    )

    with patch.object(thread_runs, "build_thread_checkpoint_state_accessor", builder):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                thread_runs._find_base_checkpoint_before_human(
                    "thread-1",
                    "human-1",
                    _request(FakeCheckpointer([]), FakeEventStore([])),
                    head_checkpoint=head,
                )
            )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Could not safely resolve the checkpoint before the target user message"
    accessor.ahistory.assert_not_awaited()


def test_prepare_regenerate_rejects_dangling_parent_without_chronological_fallback():
    from app.gateway.routers import thread_runs

    human = HumanMessage(id="human-1", content="question")
    ai = AIMessage(id="ai-1", content="answer")
    head = SimpleNamespace(
        values={"messages": [human, ai]},
        config={
            "configurable": {
                "thread_id": "thread-1",
                "checkpoint_ns": "",
                "checkpoint_id": "head",
            }
        },
        metadata={},
        parent_config={
            "configurable": {
                "thread_id": "thread-1",
                "checkpoint_ns": "",
                "checkpoint_id": "missing",
            }
        },
    )
    missing = SimpleNamespace(
        values={},
        config=head.parent_config,
        metadata=None,
        created_at=None,
        parent_config=None,
    )
    accessor = SimpleNamespace(
        aget=AsyncMock(return_value=missing),
        ahistory=AsyncMock(return_value=[head, _snapshot("wrong-sibling", [])]),
    )
    builder = AsyncMock(
        return_value=(
            accessor,
            {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}},
        )
    )

    with patch.object(thread_runs, "build_thread_checkpoint_state_accessor", builder):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                thread_runs._find_base_checkpoint_before_human(
                    "thread-1",
                    "human-1",
                    _request(FakeCheckpointer([]), FakeEventStore([])),
                    head_checkpoint=head,
                )
            )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Could not safely resolve the checkpoint before the target user message"
    accessor.ahistory.assert_not_awaited()


def test_prepare_regenerate_payload_rejects_non_latest_assistant():
    from app.gateway.routers.thread_runs import _prepare_regenerate_payload

    human = HumanMessage(id="human-1", content="question")
    old_ai = AIMessage(id="ai-old", content="old")
    latest_ai = AIMessage(id="ai-latest", content="latest")
    base = _checkpoint("ckpt-base", [])
    after_human = _checkpoint("ckpt-human", [human])
    latest = _checkpoint("ckpt-latest", [human, old_ai, latest_ai])
    checkpointer = FakeCheckpointer([latest, after_human, base])
    event_store = FakeEventStore(
        [
            {
                "run_id": "run-old",
                "event_type": "ai_message",
                "category": "message",
                "content": {"id": "ai-old", "type": "ai", "content": "old"},
                "metadata": {"caller": "lead_agent"},
            }
        ]
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(_prepare_regenerate_payload("thread-1", "ai-old", _request(checkpointer, event_store)))

    assert exc.value.status_code == 409
    assert exc.value.detail == "Only the latest assistant message can be regenerated"


def test_prepare_regenerate_payload_falls_back_to_matching_run_when_events_are_missing():
    from app.gateway.routers.thread_runs import _prepare_regenerate_payload

    human = HumanMessage(id="human-1", content="question")
    ai = AIMessage(id="ai-1", content="answer")
    base = _checkpoint("ckpt-base", [])
    after_human = _checkpoint("ckpt-human", [human])
    latest = _checkpoint("ckpt-ai", [human, ai])
    checkpointer = FakeCheckpointer([latest, after_human, base])
    run_manager = FakeRunManager(
        [
            SimpleNamespace(run_id="run-latest", status=RunStatus.success, last_ai_message="answer"),
            SimpleNamespace(run_id="run-older", status=RunStatus.error, last_ai_message="answer"),
        ]
    )

    response = asyncio.run(
        _prepare_regenerate_payload(
            "thread-1",
            "ai-1",
            _request(checkpointer, FakeEventStore([]), run_manager=run_manager),
        )
    )

    assert response.target_run_id == "run-latest"
    assert response.metadata["regenerate_from_run_id"] == "run-latest"


def test_prepare_regenerate_payload_uses_server_stamped_human_run_id_without_parent_events():
    from app.gateway.routers.thread_runs import _prepare_regenerate_payload

    human = HumanMessage(id="human-1", content="question", additional_kwargs={"run_id": "parent-run"})
    ai = AIMessage(id="ai-1", content="answer")
    base = _checkpoint("ckpt-base", [])
    after_human = _checkpoint("ckpt-human", [human])
    latest = _checkpoint(
        "ckpt-ai",
        [human, ai],
        metadata={
            "deerflow_branch": True,
            "branch_parent_thread_id": "parent-thread",
            "branch_parent_checkpoint_id": "parent-checkpoint",
        },
    )
    checkpointer = FakeCheckpointer([latest, after_human, base])
    event_store = FakeEventStore([])

    response = asyncio.run(_prepare_regenerate_payload("thread-1", "ai-1", _request(checkpointer, event_store)))

    assert response.target_run_id == "parent-run"


def test_prepare_regenerate_payload_rejects_unverified_run_fallback_when_events_are_missing():
    from app.gateway.routers.thread_runs import _prepare_regenerate_payload

    human = HumanMessage(id="human-1", content="question")
    ai = AIMessage(id="ai-1", content="answer")
    base = _checkpoint("ckpt-base", [])
    after_human = _checkpoint("ckpt-human", [human])
    latest = _checkpoint("ckpt-ai", [human, ai])
    checkpointer = FakeCheckpointer([latest, after_human, base])
    run_manager = FakeRunManager(
        [
            SimpleNamespace(run_id="run-latest", status=RunStatus.success, last_ai_message="different"),
        ]
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            _prepare_regenerate_payload(
                "thread-1",
                "ai-1",
                _request(checkpointer, FakeEventStore([]), run_manager=run_manager),
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Could not find source run for assistant message"


def test_prepare_regenerate_payload_requires_addressable_checkpoint_before_human():
    from app.gateway.routers.thread_runs import _prepare_regenerate_payload

    human = HumanMessage(id="human-1", content="question")
    ai = AIMessage(id="ai-1", content="answer")
    latest = _checkpoint("ckpt-ai", [human, ai])
    checkpointer = FakeCheckpointer([latest])
    event_store = FakeEventStore(
        [
            {
                "run_id": "run-old",
                "event_type": "llm.ai.response",
                "category": "message",
                "content": {"id": "ai-1", "type": "ai", "content": "answer"},
                "metadata": {"caller": "lead_agent"},
            }
        ]
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(_prepare_regenerate_payload("thread-1", "ai-1", _request(checkpointer, event_store)))

    assert exc.value.status_code == 409
    assert exc.value.detail == "Could not find an addressable checkpoint before the target user message"
    assert checkpointer.alist_limits == [400]


def test_prepare_regenerate_payload_reports_recent_checkpoint_scan_limit():
    from app.gateway.routers.thread_runs import _prepare_regenerate_payload

    human = HumanMessage(id="human-1", content="question")
    ai = AIMessage(id="ai-1", content="answer")
    latest = _checkpoint("ckpt-latest", [human, ai])
    history_without_human = [_checkpoint(f"ckpt-{index}", []) for index in range(201)]
    checkpointer = FakeCheckpointer(history_without_human, latest=latest)
    event_store = FakeEventStore(
        [
            {
                "run_id": "run-old",
                "event_type": "llm.ai.response",
                "category": "message",
                "content": {"id": "ai-1", "type": "ai", "content": "answer"},
                "metadata": {"caller": "lead_agent"},
            }
        ]
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(_prepare_regenerate_payload("thread-1", "ai-1", _request(checkpointer, event_store)))

    assert exc.value.status_code == 409
    assert exc.value.detail == "Could not locate target user message in recent checkpoint history (limit=200)"
    assert checkpointer.alist_limits == [400]


def test_find_base_checkpoint_ignores_duration_only_checkpoints() -> None:
    from app.gateway.routers.thread_runs import _find_base_checkpoint_before_human

    human = HumanMessage(id="human-1", content="question")
    duration_checkpoints = [
        _checkpoint(
            f"duration-{index}",
            [],
            metadata={"writes": {"runtime_run_duration": {"run_ids": [f"run-{index}"]}}},
        )
        for index in range(200)
    ]
    base = _checkpoint("ckpt-base", [])
    after_human = _checkpoint("ckpt-human", [human])
    checkpointer = FakeCheckpointer([*duration_checkpoints, after_human, base])

    result = asyncio.run(_find_base_checkpoint_before_human("thread-1", "human-1", _request(checkpointer, FakeEventStore([]))))

    assert result.config == base.config
    assert checkpointer.alist_limits == [400]
