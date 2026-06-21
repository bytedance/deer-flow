from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import defect_workflow


class _FakeAsyncClient:
    def __init__(self, response: httpx.Response, calls: list[dict[str, Any]]) -> None:
        self._response = response
        self._calls = calls

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self._calls.append({"method": method, "url": url, **kwargs})
        return self._response


def _client(monkeypatch, response: httpx.Response) -> tuple[TestClient, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    monkeypatch.setenv("EHM_CLOSED_LOOP_BASE_URL", "http://ehm.local/closed-loop-api")
    monkeypatch.setenv("EHM_WORKFLOW_BASE_URL", "http://ehm.local/workflow-api")

    def fake_async_client(*_args: Any, **_kwargs: Any) -> _FakeAsyncClient:
        return _FakeAsyncClient(response, calls)

    monkeypatch.setattr(defect_workflow.httpx, "AsyncClient", fake_async_client)

    app = FastAPI()
    app.include_router(defect_workflow.router)
    return TestClient(app), calls


def test_list_todos_forwards_auth_and_query_params(monkeypatch) -> None:
    response = httpx.Response(
        200,
        json={"success": True, "data": {"rows": []}},
        request=httpx.Request("GET", "http://ehm.local"),
    )
    client, calls = _client(monkeypatch, response)

    resp = client.get(
        "/api/defect-workflow/tasks/todo?pageNo=2&pageSize=5",
        headers={"Authorization": "Bearer user-token"},
    )

    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert calls == [
        {
            "method": "GET",
            "url": "http://ehm.local/closed-loop-api/api/v1/defects/tasks/todo",
            "headers": {"Authorization": "Bearer user-token", "Accept": "application/json"},
            "params": [("pageNo", "2"), ("pageSize", "5")],
            "json": None,
        }
    ]


def test_form_context_uses_workflow_base_url(monkeypatch) -> None:
    response = httpx.Response(
        200,
        json={"taskId": "90055"},
        request=httpx.Request("GET", "http://ehm.local"),
    )
    client, calls = _client(monkeypatch, response)

    resp = client.get(
        "/api/defect-workflow/tasks/90055/form-context",
        headers={"Authorization": "Bearer user-token"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"taskId": "90055"}
    assert calls[0]["url"] == "http://ehm.local/workflow-api/task-forms/tasks/90055/context"


def test_form_context_accepts_control_characters_from_workflow(monkeypatch) -> None:
    response = httpx.Response(
        200,
        content=b'{"taskId":"90055","formSchema":{"widgetList":[{"type":"textarea","options":{"label":"line\nbreak"}}]}}',
        headers={"Content-Type": "application/json"},
        request=httpx.Request("GET", "http://ehm.local"),
    )
    client, _calls = _client(monkeypatch, response)

    resp = client.get(
        "/api/defect-workflow/tasks/90055/form-context",
        headers={"Authorization": "Bearer user-token"},
    )

    assert resp.status_code == 200
    assert resp.json()["formSchema"]["widgetList"][0]["options"]["label"] == "line\nbreak"


def test_submit_forwards_action_form_data_and_comment(monkeypatch) -> None:
    response = httpx.Response(
        200,
        json={"success": True},
        request=httpx.Request("POST", "http://ehm.local"),
    )
    client, calls = _client(monkeypatch, response)

    resp = client.post(
        "/api/defect-workflow/defects/178/workflow-tasks/90055/submit",
        headers={"Authorization": "Bearer user-token"},
        json={
            "action": "REJECT",
            "formData": {"maintenancePlan": "retry"},
            "comment": "need more info",
        },
    )

    assert resp.status_code == 200
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == (
        "http://ehm.local/closed-loop-api/api/v1/defects/178/"
        "workflow-tasks/90055/submit"
    )
    assert calls[0]["json"] == {
        "action": "REJECT",
        "formData": {"maintenancePlan": "retry"},
        "comment": "need more info",
    }


def test_missing_token_returns_401(monkeypatch) -> None:
    response = httpx.Response(200, json={"unused": True}, request=httpx.Request("GET", "http://ehm.local"))
    client, calls = _client(monkeypatch, response)

    resp = client.get("/api/defect-workflow/tasks/todo")

    assert resp.status_code == 401
    assert calls == []


def test_upstream_server_error_maps_to_502(monkeypatch) -> None:
    response = httpx.Response(
        500,
        json={"success": False, "message": "boom"},
        request=httpx.Request("GET", "http://ehm.local"),
    )
    client, _calls = _client(monkeypatch, response)

    resp = client.get(
        "/api/defect-workflow/tasks/todo",
        headers={"Authorization": "Bearer user-token"},
    )

    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert detail["upstream_status"] == 500
    assert detail["upstream"]["message"] == "boom"
