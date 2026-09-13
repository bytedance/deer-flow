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
        ("agent", "deerflow.community.lightrag.tools:knowledge_search_tool", None),
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
