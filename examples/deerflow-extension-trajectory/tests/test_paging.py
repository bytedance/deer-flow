import asyncio
from types import SimpleNamespace

import pytest
from deerflow_extension_trajectory.checkpoints import read_page
from deerflow_extension_trajectory.gateway import decode_cursor, encode_cursor
from fastapi import HTTPException


def test_cursor_binds_user_thread_and_rejects_tampering():
    cursor = encode_cursor("u", "t", "c")
    assert decode_cursor(cursor, "u", "t") == "c"
    for token, user, thread in [
        (cursor, "other", "t"),
        (cursor, "u", "other"),
        (cursor + "x", "u", "t"),
        ("broken", "u", "t"),
    ]:
        with pytest.raises(HTTPException) as exc:
            decode_cursor(token, user, thread)
        assert exc.value.status_code == 409


def test_parent_chain_paging_excludes_other_branches_and_repeats():
    def config(cid):
        return {"configurable": {"thread_id": "t", "checkpoint_id": cid}}

    def state(cid, parent, messages):
        return SimpleNamespace(
            config=config(cid),
            parent_config=config(parent) if parent else None,
            values={"messages": messages},
            next=(),
            created_at="now",
        )

    user = {"type": "human", "id": "u", "content": "hello"}
    assistant = {"type": "ai", "id": "a", "content": "hi"}
    states = {
        "a": state("a", None, [user]),
        "b": state("b", "a", [user]),
        "c": state("c", "b", [user, assistant]),
        "other": state("other", "a", []),
    }
    reads = []

    class Accessor:
        async def aget_tuple(self, cfg):
            return states.get(cfg["configurable"]["checkpoint_id"])

        async def aget(self, cfg):
            cid = cfg["configurable"]["checkpoint_id"]
            reads.append(cid)
            return states.get(cid)

    first = asyncio.run(read_page(Accessor(), config("c"), limit=2))
    assert [row["kind"] for row in first["rows"]] == ["assistant"]
    assert first["next_checkpoint"] == "a"
    second = asyncio.run(read_page(Accessor(), config("a")))
    assert [row["kind"] for row in second["rows"]] == ["user"]
    assert second["next_checkpoint"] is None
    assert "other" not in reads
    del states["b"]
    missing = asyncio.run(read_page(Accessor(), config("c")))
    assert missing["warnings"]


def test_raw_full_state_fallback_keeps_compaction_node_evidence():
    def state(cid, parent, messages, summary="", pending=False):
        return SimpleNamespace(
            config={"configurable": {"thread_id": "t", "checkpoint_id": cid}},
            parent_config={"configurable": {"thread_id": "t", "checkpoint_id": parent}}
            if parent
            else None,
            values={"messages": messages, "summary_text": summary},
            next=(),
            created_at="now",
            checkpoint={
                "channel_values": {
                    "branch:to:DeerFlowSummarizationMiddleware.before_model": None
                }
                if pending
                else {}
            },
        )

    user = {"type": "human", "id": "u", "content": "hello"}
    states = {
        "a": state("a", None, [user], pending=True),
        "b": state("b", "a", [], "summary"),
    }

    class Saver:
        async def aget_tuple(self, config):
            return states[config["configurable"]["checkpoint_id"]]

    class RawAccessor:
        checkpointer = Saver()

        async def aget(self, config):
            return await self.checkpointer.aget_tuple(config)

    page = asyncio.run(read_page(RawAccessor(), states["b"].config))
    assert [row["kind"] for row in page["rows"]] == ["user", "compaction"]
