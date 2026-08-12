"""Tests for standalone LangGraph assistant provenance reconciliation."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.gateway.langgraph_studio import reconcile_assistant_provenance


class _FakeAssistants:
    def __init__(self, assistants: list[dict]):
        self.assistants = assistants
        self.patched: list[str] = []

    async def search(self, _conn, **kwargs):
        matches = [assistant for assistant in self.assistants if assistant["metadata"].get("created_by") == kwargs["metadata"]["created_by"]]
        offset = kwargs["offset"]
        limit = kwargs["limit"]
        page = matches[offset : offset + limit]
        next_offset = offset + limit if len(matches) > offset + limit else None

        async def _rows():
            for assistant in page:
                yield assistant

        return _rows(), next_offset

    async def patch(self, _conn, assistant_id, *, metadata, **_kwargs):
        self.patched.append(str(assistant_id))
        assistant = next(item for item in self.assistants if str(item["assistant_id"]) == str(assistant_id))
        assistant["metadata"].update(metadata)

        async def _updated():
            yield assistant

        return _updated()


def _connect():
    @asynccontextmanager
    async def _connection():
        yield SimpleNamespace()

    return _connection()


def test_reconcile_demotes_only_non_registered_system_markers():
    system_id = str(uuid4())
    forged_id = str(uuid4())
    ordinary_id = str(uuid4())
    ops = _FakeAssistants(
        [
            {
                "assistant_id": system_id,
                "metadata": {"created_by": "system"},
            },
            {
                "assistant_id": forged_id,
                "metadata": {
                    "created_by": "system",
                    "user_id": "attacker",
                },
            },
            {
                "assistant_id": ordinary_id,
                "metadata": {"created_by": "user", "user_id": "owner"},
            },
        ]
    )

    count = asyncio.run(
        reconcile_assistant_provenance(
            connect=_connect,
            assistants_ops=ops,
            system_assistant_ids={system_id},
            page_size=1,
        )
    )

    assert count == 1
    assert ops.patched == [forged_id]
    assert ops.assistants[0]["metadata"] == {"created_by": "system"}
    assert ops.assistants[1]["metadata"] == {
        "created_by": "user",
        "user_id": "attacker",
    }


def test_langgraph_config_runs_the_studio_lifespan():
    config = json.loads((Path(__file__).resolve().parents[1] / "langgraph.json").read_text(encoding="utf-8"))

    assert config["http"]["app"].endswith("app/gateway/langgraph_studio.py:langgraph_app")
