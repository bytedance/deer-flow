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


def _assistant_with_meta(name: str, **metadata: object) -> assistants_compat.AssistantResponse:
    return assistants_compat.AssistantResponse(
        assistant_id=name,
        graph_id="lead_agent",
        name=name,
        metadata=dict(metadata),
    )


def _make_app(
    monkeypatch: pytest.MonkeyPatch,
    assistants: list[assistants_compat.AssistantResponse] | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(assistants_compat.router)
    monkeypatch.setattr(
        assistants_compat,
        "_list_assistants",
        lambda: assistants if assistants is not None else [_assistant("lead_agent"), _assistant("researcher"), _assistant("writer")],
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


def test_search_filters_by_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    assistants = [
        _assistant_with_meta("lead_agent", created_by="system"),
        _assistant_with_meta("researcher", created_by="user"),
        _assistant_with_meta("writer", created_by="user"),
    ]
    with TestClient(_make_app(monkeypatch, assistants)) as client:
        response = client.post("/api/assistants/search", json={"metadata": {"created_by": "user"}})

    assert response.status_code == 200
    assert [assistant["assistant_id"] for assistant in response.json()] == ["researcher", "writer"]


def test_search_metadata_filter_with_no_matches_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    assistants = [_assistant_with_meta("lead_agent", created_by="system")]
    with TestClient(_make_app(monkeypatch, assistants)) as client:
        response = client.post("/api/assistants/search", json={"metadata": {"created_by": "nobody"}})

    assert response.status_code == 200
    assert response.json() == []


def test_search_metadata_filter_requires_every_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    assistants = [
        _assistant_with_meta("researcher", created_by="user", scope="team"),
        _assistant_with_meta("writer", created_by="user"),
    ]
    with TestClient(_make_app(monkeypatch, assistants)) as client:
        response = client.post("/api/assistants/search", json={"metadata": {"created_by": "user", "scope": "team"}})

    assert response.status_code == 200
    assert [assistant["assistant_id"] for assistant in response.json()] == ["researcher"]


def test_search_metadata_filter_missing_key_does_not_match_null(monkeypatch: pytest.MonkeyPatch) -> None:
    assistants = [
        _assistant_with_meta("lead_agent", scope=None),
        _assistant_with_meta("researcher", scope="team"),
        _assistant_with_meta("writer"),
    ]
    with TestClient(_make_app(monkeypatch, assistants)) as client:
        response = client.post("/api/assistants/search", json={"metadata": {"scope": None}})

    assert response.status_code == 200
    # Only the assistant that explicitly stores `scope: null` matches; a missing
    # key is not conflated with an explicit null.
    assert [assistant["assistant_id"] for assistant in response.json()] == ["lead_agent"]


def test_search_metadata_filter_does_not_equate_a_boolean_with_a_number(monkeypatch: pytest.MonkeyPatch) -> None:
    assistants = [
        _assistant_with_meta("flagged", archived=True),
        _assistant_with_meta("counted", archived=1),
    ]
    with TestClient(_make_app(monkeypatch, assistants)) as client:
        boolean_response = client.post("/api/assistants/search", json={"metadata": {"archived": True}})
        number_response = client.post("/api/assistants/search", json={"metadata": {"archived": 1}})

    assert boolean_response.status_code == 200
    assert number_response.status_code == 200
    # `True == 1` in Python; the filter has to keep JSON `true` and `1` apart.
    assert [assistant["assistant_id"] for assistant in boolean_response.json()] == ["flagged"]
    assert [assistant["assistant_id"] for assistant in number_response.json()] == ["counted"]


def test_search_empty_metadata_filter_does_not_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(_make_app(monkeypatch)) as client:
        response = client.post("/api/assistants/search", json={"metadata": {}})

    assert response.status_code == 200
    assert [assistant["assistant_id"] for assistant in response.json()] == ["lead_agent", "researcher", "writer"]
