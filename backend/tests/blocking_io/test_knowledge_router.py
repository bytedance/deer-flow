"""Regression anchors: the knowledge catalog must not block the event loop.

Both retrieval-catalog handlers load the custom agent's config to decide
whether it may select a knowledge scope. That read goes through the sync agent
store — file IO on the ``file`` backend, a sync SQLAlchemy round trip on the
``db`` backend — so it is offloaded via ``asyncio.to_thread``. If it regresses
onto the event loop, the strict Blockbuster gate raises ``BlockingError``.

The handlers are driven end to end (not the scope helper) so the anchors fail
if a call site stops awaiting the offloaded load. ``@require_permission`` is
bypassed via ``__wrapped__``; RAGFlow is replaced with an in-memory fake.
Imports sit at module top so import-time IO runs at collection, outside the
gate.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine

from app.gateway.knowledge_scope_admission import RAGFLOW_KNOWLEDGE_SEARCH_PROVIDER
from app.gateway.routers import knowledge
from deerflow.config.paths import get_paths
from deerflow.persistence.agents.model import AgentRow
from deerflow.persistence.agents.sql import SqlAgentStore
from deerflow.persistence.base import Base
from deerflow.runtime.user_context import get_effective_user_id

pytestmark = pytest.mark.asyncio

# The undecorated coroutines (``require_permission`` uses ``functools.wraps``).
_list_datasets = knowledge.list_retrieval_catalog_datasets.__wrapped__
_list_documents = knowledge.list_retrieval_catalog_documents.__wrapped__

_AGENT = "kb-agent"


@pytest.fixture(autouse=True)
def _isolate_agent_store_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DEER_FLOW_CONFIG_PATH", raising=False)
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.app_config._legacy_config_candidates", lambda: ())
    monkeypatch.setattr("deerflow.config.paths._paths", None)


def _seed_file_agent() -> None:
    agent_dir = get_paths().user_agent_dir(get_effective_user_id(), _AGENT)
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "config.yaml").write_text(f"name: {_AGENT}\ntool_groups: [knowledge]\n", encoding="utf-8")


def _seed_db_agent(tmp_path: Path) -> SqlAgentStore:
    url = f"sqlite:///{tmp_path}/agents.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine, tables=[AgentRow.__table__])
    engine.dispose()
    store = SqlAgentStore(url)
    store.create(_AGENT, {"name": _AGENT, "tool_groups": ["knowledge"]}, None, user_id=get_effective_user_id())
    return store


@pytest.fixture(params=["file", "db"])
def seeded_agent_store(request, tmp_path: Path, monkeypatch) -> None:
    # Sync fixture: seeding runs before the loop starts, so only the handlers'
    # own IO is exercised on it.
    if request.param == "file":
        _seed_file_agent()
        return
    store = _seed_db_agent(tmp_path)
    monkeypatch.setattr("deerflow.persistence.agents.get_agent_store", lambda: store)


def _config() -> SimpleNamespace:
    tool = SimpleNamespace(
        use=RAGFLOW_KNOWLEDGE_SEARCH_PROVIDER,
        model_extra={
            "base_url": "http://ragflow.test",
            "api_key": "ragflow-secret",
            "timeout": 30,
            "datasets": ["dataset-1"],
        },
    )
    return SimpleNamespace(
        knowledge_base=SimpleNamespace(enabled=True, scope_selection_enabled=True),
        get_tool_config=lambda name: tool if name == "knowledge_search" else None,
    )


def _fake_ragflow(monkeypatch) -> SimpleNamespace:
    ragflow = SimpleNamespace(
        list_datasets=AsyncMock(
            return_value=[
                {
                    "id": "dataset-1",
                    "name": "Policies",
                    "embedding_model": "embed-a",
                    "chunk_count": 3,
                }
            ]
        ),
        list_documents=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "total": 1,
                    "docs": [{"id": "doc-1", "name": "Ready.pdf", "run": "DONE", "chunk_count": 2}],
                },
            }
        ),
    )
    monkeypatch.setattr(knowledge, "_build_retrieval_client", lambda settings: ragflow)
    return ragflow


@pytest.mark.usefixtures("seeded_agent_store")
async def test_catalog_handlers_do_not_block_event_loop(monkeypatch) -> None:
    _fake_ragflow(monkeypatch)

    datasets = await _list_datasets(
        request=None,
        agent_name=_AGENT,
        page=1,
        page_size=20,
        search="",
        config=_config(),
    )
    documents = await _list_documents(
        "dataset-1",
        request=None,
        agent_name=_AGENT,
        page=1,
        page_size=20,
        search="",
        config=_config(),
    )

    assert datasets["items"] == [{"id": "dataset-1", "name": "Policies", "selectable": True}]
    assert documents["items"] == [{"id": "doc-1", "name": "Ready.pdf", "selectable": True}]


async def test_unknown_agent_is_not_found_without_blocking_event_loop(monkeypatch) -> None:
    ragflow = _fake_ragflow(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        await _list_datasets(
            request=None,
            agent_name="missing-agent",
            page=1,
            page_size=20,
            search="",
            config=_config(),
        )

    assert exc_info.value.status_code == 404
    ragflow.list_datasets.assert_not_awaited()
