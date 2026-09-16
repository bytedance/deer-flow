"""``context.conversation_references`` is the same explicit grant as the top-level field.

LangGraph SDK clients build a fixed run body and drop unknown top-level fields,
so the web UI cannot send ``conversation_references`` there. The ``context``
object does reach the Gateway. The request model lifts the key out of it before
any run context is assembled, so it is consumed at admission and never forwarded.
"""

from __future__ import annotations

import asyncio
import json
from collections import UserList, deque
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from app.gateway.authz import AuthContext
from app.gateway.run_models import MAX_CONVERSATION_REFERENCES, RunCreateRequest
from deerflow.config.app_config import AppConfig


def test_context_references_are_lifted_into_the_request_and_removed_from_context():
    body = RunCreateRequest(context={"conversation_references": ["source"], "thinking_enabled": True})
    assert body.conversation_references == ["source"]
    assert body.context == {"thinking_enabled": True}


@pytest.mark.parametrize("value", [None, []])
def test_empty_context_references_grant_nothing_and_leave_no_key(value):
    body = RunCreateRequest(context={"conversation_references": value, "mode": "flash"})
    assert body.conversation_references == []
    assert body.context == {"mode": "flash"}


@pytest.mark.parametrize(
    "invalid",
    ["source", [""], [1], ["x" * 2049], ["s"] * (MAX_CONVERSATION_REFERENCES + 1), {"thread": "source"}],
)
def test_context_references_keep_the_top_level_bounds(invalid):
    with pytest.raises(ValidationError) as exc:
        RunCreateRequest(context={"conversation_references": invalid})
    assert exc.value.errors()
    assert all(error["loc"][0] == "conversation_references" for error in exc.value.errors())


def test_top_level_and_context_references_together_are_rejected():
    with pytest.raises(ValidationError) as exc:
        RunCreateRequest(conversation_references=["source"], context={"conversation_references": ["source"]})
    assert [error["type"] for error in exc.value.errors()] == ["conversation_references_conflict"]


def test_a_malformed_top_level_value_reports_its_type_error_not_the_conflict():
    with pytest.raises(ValidationError) as exc:
        RunCreateRequest(conversation_references="source", context={"conversation_references": ["source"]})
    assert [(error["type"], error["loc"]) for error in exc.value.errors()] == [("list_type", ("conversation_references",))]


@pytest.mark.parametrize(
    "top_level",
    [
        ("source",),
        {"source"},
        frozenset({"source"}),
        deque(["source"]),
        UserList(["source"]),
        dict.fromkeys(["source"]).keys(),
        (item for item in ("source",)),
    ],
    ids=["tuple", "set", "frozenset", "deque", "UserList", "dict_keys", "generator"],
)
def test_everything_the_field_would_coerce_also_reports_the_conflict(top_level):
    # Pydantic's lax mode coerces many iterables into the list field, so a
    # direct Python caller must not slip both grants past the conflict check.
    # The guard asks pydantic itself instead of enumerating types.
    with pytest.raises(ValidationError) as exc:
        RunCreateRequest(conversation_references=top_level, context={"conversation_references": ["source"]})
    assert [error["type"] for error in exc.value.errors()] == ["conversation_references_conflict"]


@pytest.mark.parametrize("top_level", [0, False, 1.5, {"thread": "source"}, b"source"], ids=["zero", "false", "float", "dict", "bytes"])
def test_values_the_field_rejects_still_report_their_own_type_error(top_level):
    with pytest.raises(ValidationError) as exc:
        RunCreateRequest(conversation_references=top_level, context={"conversation_references": ["source"]})
    assert [(error["type"], error["loc"]) for error in exc.value.errors()] == [("list_type", ("conversation_references",))]


@pytest.mark.parametrize(
    "top_level",
    [[""], [1], range(3), dict.fromkeys(["source"]).values(), dict.fromkeys(["source"]).items()],
    ids=["empty_item", "int_item", "range", "dict_values", "dict_items"],
)
def test_invalid_items_at_the_top_level_report_the_item_error_not_the_conflict(top_level):
    # The guard probes with the field's own annotation, so whatever the field
    # coerces as a container but rejects per item (a range, dict views, a bad
    # string) is reported at the item's index rather than as a conflict.
    with pytest.raises(ValidationError) as exc:
        RunCreateRequest(conversation_references=top_level, context={"conversation_references": ["source"]})
    errors = exc.value.errors()
    assert errors
    assert all(error["loc"][0] == "conversation_references" and isinstance(error["loc"][1], int) for error in errors)
    assert not any(error["type"] == "conversation_references_conflict" for error in errors)


def test_a_one_shot_iterator_with_a_bad_item_still_reports_the_item_error():
    # The probe must not consume a generator and leave the field an exhausted
    # one that coerces to [] and validates silently with the key left in context.
    with pytest.raises(ValidationError) as exc:
        RunCreateRequest(conversation_references=(item for item in ["", "source"]), context={"conversation_references": ["source"]})
    errors = exc.value.errors()
    assert [error["loc"] for error in errors] == [("conversation_references", 0)]
    assert not any(error["type"] == "conversation_references_conflict" for error in errors)


def test_a_one_shot_iterator_of_valid_items_is_read_once_and_kept():
    body = RunCreateRequest(conversation_references=(item for item in ["source"]), context={"thinking_enabled": True})
    assert body.conversation_references == ["source"]
    with pytest.raises(ValidationError) as exc:
        RunCreateRequest(conversation_references=(item for item in ["source"]), context={"conversation_references": ["other"]})
    assert [error["type"] for error in exc.value.errors()] == ["conversation_references_conflict"]


def test_an_empty_top_level_list_does_not_conflict_with_context():
    body = RunCreateRequest(conversation_references=[], context={"conversation_references": ["source"]})
    assert body.conversation_references == ["source"]
    assert body.context == {}


def test_max_references_matches_the_field_bound():
    assert RunCreateRequest(conversation_references=["s"] * MAX_CONVERSATION_REFERENCES).conversation_references == ["s"] * MAX_CONVERSATION_REFERENCES
    with pytest.raises(ValidationError):
        RunCreateRequest(conversation_references=["s"] * (MAX_CONVERSATION_REFERENCES + 1))


def test_start_run_grants_through_context_without_forwarding_the_key(monkeypatch):
    from test_gateway_services import _make_start_run_persistence_context

    from app.gateway import services
    from deerflow.config.app_config import reset_app_config, set_app_config
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    async def exercise():
        request, _, threads = _make_start_run_persistence_context()
        user = SimpleNamespace(id="alice", system_role="admin", role="admin")
        request.state.user = user
        request.state.auth = AuthContext(user, ["runs:create", "runs:read"])
        request.state.auth_source = "session"
        request.url = "https://deerflow.example/api/threads/current/runs"
        await threads.create("source", user_id="alice")
        captured = []

        async def fake_run_agent(*args, **kwargs):
            captured.append(kwargs)

        monkeypatch.setattr(services, "run_agent", fake_run_agent)
        monkeypatch.setattr(services, "resolve_agent_factory", lambda *_: object())

        body = RunCreateRequest(
            input={"messages": [{"role": "user", "content": "Read the reference"}]},
            context={"conversation_references": ["source"], "thinking_enabled": True},
        )
        record = await services.start_run(body, "current", request)
        await record.task
        assert callable(captured[0]["ctx"].conversation_reader)
        assert any(isinstance(m, HumanMessage) and "source" in str(m.content) for m in captured[0]["graph_input"]["messages"])
        # The run record keeps the references exactly like the top-level field.
        assert record.kwargs["conversation_references"] == ["source"]
        assert "__conversation_reader" not in json.dumps(record.kwargs)
        # Other context keys still flow; the references never reach the run context or the checkpointed configurable.
        config = captured[0]["config"]
        assert config["context"]["thinking_enabled"] is True
        assert "conversation_references" not in config["context"]
        assert "conversation_references" not in config["configurable"]

        # Copies smuggled through the free-form RunnableConfig grant nothing.
        smuggled = await services.start_run(
            RunCreateRequest(
                input={"messages": [{"role": "user", "content": "again"}]},
                config={"configurable": {"conversation_references": ["source"]}, "context": {"conversation_references": ["source"]}},
            ),
            "smuggled",
            request,
        )
        await smuggled.task
        assert captured[1]["ctx"].conversation_reader is None
        assert "conversation_references" not in (smuggled.kwargs or {})

        # Idempotent replay compares the lifted references like the top-level field.
        keyed = await services.start_run(body, "idempotent", request, idempotency_key="ctx-key")
        await keyed.task
        assert await services.start_run(body, "idempotent", request, idempotency_key="ctx-key") is keyed
        changed = RunCreateRequest(input=body.input, context={"conversation_references": ["other"], "thinking_enabled": True})
        with pytest.raises(HTTPException) as conflict:
            await services.start_run(changed, "idempotent", request, idempotency_key="ctx-key")
        assert conflict.value.status_code == 409

    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "tools": [{"name": "read_conversation", "group": "conversation", "use": "deerflow.tools.conversation:read_conversation"}]}))
    user_token = set_current_user(SimpleNamespace(id="alice"))
    try:
        asyncio.run(exercise())
    finally:
        reset_current_user(user_token)
        reset_app_config()
