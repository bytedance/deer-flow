"""Contract tests for the LangGraph-compatible assistants endpoints."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import assistants_compat


def _assistant(name: str) -> assistants_compat.AssistantResponse:
    return assistants_compat.AssistantResponse(
        assistant_id=name,
        graph_id="lead_agent",
        name=name,
    )


def _make_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    app = FastAPI()
    app.include_router(assistants_compat.router)
    monkeypatch.setattr(
        assistants_compat,
        "_list_assistants",
        lambda: [_assistant("lead_agent"), _assistant("researcher"), _assistant("writer")],
    )
    return app


@pytest.mark.parametrize(
    "body",
    [
        {"limit": 0},
        {"limit": -1},
        {"limit": 1001},
        {"offset": -1},
    ],
)
def test_search_rejects_invalid_pagination(monkeypatch: pytest.MonkeyPatch, body: dict[str, int]) -> None:
    with TestClient(_make_app(monkeypatch)) as client:
        response = client.post("/api/assistants/search", json=body)

    assert response.status_code == 422


def test_search_accepts_contract_maximum_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(_make_app(monkeypatch)) as client:
        response = client.post("/api/assistants/search", json={"limit": 1000})

    assert response.status_code == 200
    assert [assistant["assistant_id"] for assistant in response.json()] == ["lead_agent", "researcher", "writer"]


def test_search_preserves_default_and_positive_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(_make_app(monkeypatch)) as client:
        default_response = client.post("/api/assistants/search")
        offset_response = client.post("/api/assistants/search", json={"offset": 1, "limit": 1})

    assert default_response.status_code == 200
    assert [assistant["assistant_id"] for assistant in default_response.json()] == ["lead_agent", "researcher", "writer"]
    assert offset_response.status_code == 200
    assert [assistant["assistant_id"] for assistant in offset_response.json()] == ["researcher"]

def _make_metadata_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    app = FastAPI()
    app.include_router(assistants_compat.router)
    assistants = [
        assistants_compat.AssistantResponse(
            assistant_id="lead_agent",
            graph_id="lead_agent",
            name="lead_agent",
            metadata={"created_by": "system", "config": {"tags": ["built-in"]}},
        ),
        assistants_compat.AssistantResponse(
            assistant_id="researcher",
            graph_id="lead_agent",
            name="researcher",
            metadata={"created_by": "user", "config": {"tags": ["science"]}, "nullable": None},
        ),
        assistants_compat.AssistantResponse(
            assistant_id="writer",
            graph_id="lead_agent",
            name="writer",
            metadata={"created_by": "user", "config": {"tags": ["writing"]}},
        ),
    ]
    monkeypatch.setattr(assistants_compat, "_list_assistants", lambda: assistants)
    return app


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"metadata": {"created_by": "user"}}, ["researcher", "writer"]),
        ({"metadata": {"created_by": "nobody"}}, []),
        ({"metadata": {"missing_key": "user"}}, []),
        ({"metadata": {"created_by": "User"}}, []),
        ({"metadata": {"nullable": None}}, ["researcher"]),
        ({"metadata": {"missing_key": None}}, []),
        ({"metadata": {"created_by": "user", "config": {"tags": ["science"]}}}, ["researcher"]),
        ({"metadata": {"created_by": "user"}, "offset": 1, "limit": 1}, ["writer"]),
        ({"metadata": {}, "offset": 1, "limit": 1}, ["researcher"]),
        ({"metadata": {"created_by": "user"}, "name": "research", "graph_id": "lead_agent"}, ["researcher"]),
    ],
)
def test_search_filters_by_metadata(
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, object],
    expected: list[str],
) -> None:
    with TestClient(_make_metadata_app(monkeypatch)) as client:
        response = client.post("/api/assistants/search", json=body)

    assert response.status_code == 200
    assert [assistant["assistant_id"] for assistant in response.json()] == expected
