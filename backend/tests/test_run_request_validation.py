"""Contract tests for the LangGraph-compatible run request boundary."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import runs

SUPPORTED_STREAM_MODES = {
    "values",
    "messages-tuple",
    "updates",
    "debug",
    "tasks",
    "checkpoints",
    "custom",
}


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(runs.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("webhook", "https://example.com/callback"),
        ("stream_resumable", False),
        ("on_completion", "complete"),
        ("on_completion", "continue"),
        ("on_completion", "keep"),
        ("on_completion", "delete"),
        ("after_seconds", 1.5),
        ("if_not_exists", "reject"),
        ("feedback_keys", []),
        ("multitask_strategy", "enqueue"),
    ],
)
def test_run_request_rejects_each_unsupported_option_with_exact_422(
    client: TestClient,
    field: str,
    value: Any,
) -> None:
    response = client.post("/api/runs/stream", json={field: value})

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "unsupported_run_option",
                "loc": ["body", field],
                "msg": f"Run option '{field}' is not supported by DeerFlow",
                "input": value,
                "ctx": {"option": field},
            }
        ]
    }


@pytest.mark.parametrize(
    "stream_mode",
    [
        "messages",
        "events",
        "tools",
        ["values", "events"],
        ["events", "tools"],
    ],
)
def test_run_request_rejects_unsupported_stream_modes_with_exact_422(
    client: TestClient,
    stream_mode: str | list[str],
) -> None:
    response = client.post("/api/runs/stream", json={"stream_mode": stream_mode})
    requested = [stream_mode] if isinstance(stream_mode, str) else stream_mode
    unsupported = list(dict.fromkeys(mode for mode in requested if mode not in SUPPORTED_STREAM_MODES))
    mode_list = ", ".join(unsupported)

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "unsupported_stream_mode",
                "loc": ["body", "stream_mode"],
                "msg": f"Unsupported stream mode(s): {mode_list}",
                "input": stream_mode,
                "ctx": {"modes": mode_list},
            }
        ]
    }


def test_run_request_keeps_supported_modes_and_compatibility_defaults() -> None:
    from app.gateway.routers.thread_runs import RunCreateRequest

    body = RunCreateRequest(
        stream_mode=list(SUPPORTED_STREAM_MODES),
        webhook=None,
        stream_resumable=None,
        on_completion=None,
        after_seconds=None,
        if_not_exists="create",
        feedback_keys=None,
    )

    assert set(body.stream_mode or []) == SUPPORTED_STREAM_MODES
    assert body.on_completion is None
    assert body.if_not_exists == "create"


@pytest.mark.parametrize(
    "payload",
    [
        {"multitask_strategy": []},
        {"stream_mode": [{}]},
    ],
)
def test_malformed_option_types_remain_validation_errors(client: TestClient, payload: dict[str, Any]) -> None:
    response = client.post("/api/runs/stream", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "field",
    [
        "multitask_strategy",
        "if_not_exists",
    ],
)
def test_string_run_options_keep_native_type_errors(client: TestClient, field: str) -> None:
    response = client.post("/api/runs/stream", json={field: []})

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "literal_error"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("checkpoint_during", False),
        ("durability", "sync"),
    ],
)
def test_run_request_rejects_unknown_sdk_options_with_exact_422(
    client: TestClient,
    field: str,
    value: Any,
) -> None:
    response = client.post("/api/runs/stream", json={field: value})

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "extra_forbidden",
                "loc": ["body", field],
                "msg": "Extra inputs are not permitted",
                "input": value,
            }
        ]
    }


def test_openapi_stream_mode_enum_matches_runtime_support() -> None:
    app = FastAPI()
    app.include_router(runs.router)
    openapi = app.openapi()
    schemas = openapi["components"]["schemas"]
    stream_mode_schema = schemas["RunCreateRequest"]["properties"]["stream_mode"]

    enums: list[str] = []

    def collect_enums(value: Any) -> None:
        if isinstance(value, dict):
            enum = value.get("enum")
            if isinstance(enum, list):
                enums.extend(item for item in enum if isinstance(item, str))
            for child in value.values():
                collect_enums(child)
        elif isinstance(value, list):
            for child in value:
                collect_enums(child)

    collect_enums(stream_mode_schema)
    collect_enums(schemas["RunStreamMode"])

    assert set(enums) == SUPPORTED_STREAM_MODES
    assert "events" not in enums


def test_openapi_run_option_schema_exposes_only_supported_values() -> None:
    app = FastAPI()
    app.include_router(runs.router)
    schema = app.openapi()["components"]["schemas"]["RunCreateRequest"]
    properties = schema["properties"]

    assert schema["additionalProperties"] is False
    for field in ("webhook", "stream_resumable", "after_seconds", "feedback_keys"):
        assert properties[field]["type"] == "null"
    assert properties["on_completion"]["type"] == "null"
    assert properties["if_not_exists"]["const"] == "create"
    assert properties["multitask_strategy"]["enum"] == ["reject", "rollback", "interrupt"]
