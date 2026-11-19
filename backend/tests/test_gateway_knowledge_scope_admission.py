from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage, HumanMessage

from app.gateway.knowledge_scope_admission import admit_message_knowledge_scope
from app.gateway.services import strip_internal_context_keys
from deerflow.config.tool_config import ToolConfig
from deerflow.knowledge_scope import KNOWLEDGE_SCOPE_KEY, KNOWLEDGE_SCOPE_RUNTIME_KEY


def _app_config(provider: str = "deerflow.community.ragflow.tools:knowledge_search_tool"):
    tool_config = ToolConfig(
        name="knowledge_search",
        group="knowledge",
        use=provider,
    )
    return SimpleNamespace(
        knowledge_base=SimpleNamespace(enabled=True),
        get_tool_config=lambda name: tool_config if name == "knowledge_search" else None,
    )


def _agent_config(tool_groups=None):
    return SimpleNamespace(tool_groups=tool_groups)


def _input(message):
    return {"messages": [message]}


def test_admission_canonicalizes_custom_agent_human_message() -> None:
    graph_input = _input(
        HumanMessage(
            content="question",
            additional_kwargs={
                KNOWLEDGE_SCOPE_KEY: {
                    "version": 1,
                    "mode": "selected",
                    "dataset_ids": [" dataset-a ", "dataset-a"],
                }
            },
        )
    )

    admitted = admit_message_knowledge_scope(
        graph_input,
        assistant_id="agriculture-agent",
        app_config=_app_config(),
        agent_config=_agent_config(None),
    )

    assert admitted == {
        "version": 1,
        "mode": "selected",
        "dataset_ids": ["dataset-a"],
    }
    assert graph_input["messages"][0].additional_kwargs[KNOWLEDGE_SCOPE_KEY] == admitted


@pytest.mark.parametrize(
    ("assistant_id", "provider", "tool_groups"),
    [
        (None, "deerflow.community.ragflow.tools:knowledge_search_tool", None),
        ("agent", "unknown:knowledge_search_tool", None),
        ("agent", "deerflow.community.ragflow.tools:knowledge_search_tool", []),
        ("agent", "deerflow.community.ragflow.tools:knowledge_search_tool", ["web"]),
    ],
)
def test_scope_is_rejected_outside_supported_custom_agent(
    assistant_id: str | None,
    provider: str,
    tool_groups: list[str] | None,
) -> None:
    graph_input = _input(
        HumanMessage(
            content="question",
            additional_kwargs={KNOWLEDGE_SCOPE_KEY: {"version": 1, "mode": "all"}},
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        admit_message_knowledge_scope(
            graph_input,
            assistant_id=assistant_id,
            app_config=_app_config(provider),
            agent_config=_agent_config(tool_groups) if assistant_id not in {None, "lead_agent"} else None,
        )

    assert exc_info.value.status_code == 422


def test_admission_accepts_main_agent_with_configured_ragflow_provider() -> None:
    graph_input = _input(
        HumanMessage(
            content="question",
            additional_kwargs={KNOWLEDGE_SCOPE_KEY: {"version": 1, "mode": "all"}},
        )
    )

    admitted = admit_message_knowledge_scope(
        graph_input,
        assistant_id="lead_agent",
        app_config=_app_config(),
        agent_config=None,
    )

    assert admitted == {"version": 1, "mode": "all"}


def test_scope_on_non_human_or_multiple_humans_is_rejected() -> None:
    invalid_ai = _input(
        AIMessage(
            content="answer",
            additional_kwargs={KNOWLEDGE_SCOPE_KEY: {"version": 1, "mode": "all"}},
        )
    )
    with pytest.raises(HTTPException, match="HumanMessage"):
        admit_message_knowledge_scope(
            invalid_ai,
            assistant_id="agent",
            app_config=_app_config(),
            agent_config=_agent_config(),
        )

    duplicate = {
        "messages": [
            HumanMessage(
                content="one",
                additional_kwargs={KNOWLEDGE_SCOPE_KEY: {"version": 1, "mode": "all"}},
            ),
            HumanMessage(
                content="two",
                additional_kwargs={KNOWLEDGE_SCOPE_KEY: {"version": 1, "mode": "all"}},
            ),
        ]
    }
    with pytest.raises(HTTPException, match="one new HumanMessage"):
        admit_message_knowledge_scope(
            duplicate,
            assistant_id="agent",
            app_config=_app_config(),
            agent_config=_agent_config(),
        )


def test_scope_on_an_earlier_human_message_is_rejected() -> None:
    graph_input = {
        "messages": [
            HumanMessage(
                content="historical",
                additional_kwargs={KNOWLEDGE_SCOPE_KEY: {"version": 1, "mode": "all"}},
            ),
            HumanMessage(content="current"),
        ]
    }

    with pytest.raises(HTTPException, match="current HumanMessage"):
        admit_message_knowledge_scope(
            graph_input,
            assistant_id="agent",
            app_config=_app_config(),
            agent_config=_agent_config(),
        )


def test_recovery_scope_replaces_client_forgery_and_legacy_removes_it() -> None:
    graph_input = _input(
        HumanMessage(
            content="question",
            additional_kwargs={KNOWLEDGE_SCOPE_KEY: {"version": 1, "mode": "all"}},
        )
    )
    recovered = admit_message_knowledge_scope(
        graph_input,
        assistant_id="agent",
        app_config=_app_config(),
        agent_config=_agent_config(),
        recovery_scope={"version": 1, "mode": "disabled"},
        recovery=True,
    )
    assert recovered == {"version": 1, "mode": "disabled"}
    assert graph_input["messages"][0].additional_kwargs[KNOWLEDGE_SCOPE_KEY] == recovered

    admitted = admit_message_knowledge_scope(
        graph_input,
        assistant_id="agent",
        app_config=_app_config(),
        agent_config=_agent_config(),
        recovery_scope=None,
        recovery=True,
    )
    assert admitted is None
    assert KNOWLEDGE_SCOPE_KEY not in graph_input["messages"][0].additional_kwargs


def test_free_form_runtime_scope_fields_are_scrubbed() -> None:
    config = {
        "context": {
            KNOWLEDGE_SCOPE_KEY: {"version": 1, "mode": "all"},
            KNOWLEDGE_SCOPE_RUNTIME_KEY: {"version": 1, "mode": "disabled"},
        },
        "configurable": {
            KNOWLEDGE_SCOPE_KEY: {"version": 1, "mode": "all"},
            KNOWLEDGE_SCOPE_RUNTIME_KEY: {"version": 1, "mode": "disabled"},
        },
    }

    strip_internal_context_keys(config)

    assert config == {"context": {}, "configurable": {}}


# -- agent config loading during run admission ------------------------------
# Every run that names a custom agent loads its config here, with or without a
# knowledge scope, so the 422 detail must say what is wrong with the agent.


@pytest.mark.anyio
async def test_scope_agent_lookup_reports_a_missing_agent(monkeypatch) -> None:
    from app.gateway import services

    def _missing(name, *, user_id=None):
        raise FileNotFoundError(name)

    monkeypatch.setattr(services, "load_agent_config", _missing)

    with pytest.raises(HTTPException) as excinfo:
        await services._load_scope_agent_config(assistant_id="Ghost_Agent", user_id="u1")

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail == "Agent 'ghost-agent' not found"


@pytest.mark.anyio
async def test_scope_agent_lookup_reports_an_unreadable_agent_config(monkeypatch) -> None:
    from app.gateway import services

    def _corrupt(name, *, user_id=None):
        raise ValueError("bad yaml")

    monkeypatch.setattr(services, "load_agent_config", _corrupt)

    with pytest.raises(HTTPException) as excinfo:
        await services._load_scope_agent_config(assistant_id="broken-agent", user_id="u1")

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail == "Agent 'broken-agent' configuration could not be loaded"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("agent_name", "detail"),
    [
        ("Bad Name!", "Invalid agent_name 'Bad Name!': must contain only letters, digits, and hyphens after normalization."),
        ("   ", "Invalid agent_name '   ': must contain only letters, digits, and hyphens after normalization."),
        (1, "Invalid agent_name: expected a string, got int."),
    ],
)
async def test_scope_agent_lookup_rejects_an_invalid_agent_name_without_loading(monkeypatch, agent_name, detail) -> None:
    from app.gateway import services

    def _unexpected(name, *, user_id=None):
        raise AssertionError("an invalid agent name must not reach the agent store")

    monkeypatch.setattr(services, "load_agent_config", _unexpected)

    with pytest.raises(HTTPException) as excinfo:
        await services._load_scope_agent_config(assistant_id=agent_name, user_id="u1")

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail == detail


@pytest.mark.anyio
async def test_scope_agent_lookup_bounds_an_oversized_invalid_agent_name(monkeypatch) -> None:
    """Admission echoes the caller's raw ``agent_name``; a huge value must not bloat the 422 or logs."""
    from app.gateway import services

    def _unexpected(name, *, user_id=None):
        raise AssertionError("an invalid agent name must not reach the agent store")

    monkeypatch.setattr(services, "load_agent_config", _unexpected)
    oversized = "Bad Name!" + "x" * 100_000

    with pytest.raises(HTTPException) as excinfo:
        await services._load_scope_agent_config(assistant_id=oversized, user_id="u1")

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail.startswith("Invalid agent_name 'Bad Name!xxx")
    assert excinfo.value.detail.endswith(": must contain only letters, digits, and hyphens after normalization.")
    assert len(excinfo.value.detail) < 400


@pytest.mark.anyio
async def test_scope_agent_lookup_bounds_an_oversized_missing_agent_name(monkeypatch) -> None:
    """A syntactically valid name has no length cap either, so the not-found detail is bounded too."""
    from app.gateway import services

    def _missing(name, *, user_id=None):
        raise FileNotFoundError(name)

    monkeypatch.setattr(services, "load_agent_config", _missing)

    with pytest.raises(HTTPException) as excinfo:
        await services._load_scope_agent_config(assistant_id="a" * 100_000, user_id="u1")

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail.startswith("Agent 'aaa")
    assert excinfo.value.detail.endswith("' not found")
    assert len(excinfo.value.detail) < 400
