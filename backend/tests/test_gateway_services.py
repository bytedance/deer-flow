"""Tests for app.gateway.services — run lifecycle service layer."""

from __future__ import annotations

import json

import pytest

from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config


@pytest.fixture
def _stub_app_config():
    """Keep run-context tests independent from a developer-local config.yaml."""
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    yield
    reset_app_config()


def test_format_sse_basic():
    from app.gateway.services import format_sse

    frame = format_sse("metadata", {"run_id": "abc"})
    assert frame.startswith("event: metadata\n")
    assert "data: " in frame
    parsed = json.loads(frame.split("data: ")[1].split("\n")[0])
    assert parsed["run_id"] == "abc"


def test_format_sse_with_event_id():
    from app.gateway.services import format_sse

    frame = format_sse("metadata", {"run_id": "abc"}, event_id="123-0")
    assert "id: 123-0" in frame


def test_format_sse_end_event_null():
    from app.gateway.services import format_sse

    frame = format_sse("end", None)
    assert "data: null" in frame


def test_format_sse_no_event_id():
    from app.gateway.services import format_sse

    frame = format_sse("values", {"x": 1})
    assert "id:" not in frame


def test_sanitize_log_param_strips_control_characters():
    from app.gateway.utils import sanitize_log_param

    assert sanitize_log_param("thread\nid\rwith\x00controls") == "threadidwithcontrols"


def test_normalize_stream_modes_none():
    from app.gateway.services import normalize_stream_modes

    assert normalize_stream_modes(None) == ["values"]


def test_normalize_stream_modes_string():
    from app.gateway.services import normalize_stream_modes

    assert normalize_stream_modes("messages-tuple") == ["messages-tuple"]


def test_normalize_stream_modes_list():
    from app.gateway.services import normalize_stream_modes

    assert normalize_stream_modes(["values", "messages-tuple"]) == ["values", "messages-tuple"]


def test_normalize_stream_modes_empty_list():
    from app.gateway.services import normalize_stream_modes

    assert normalize_stream_modes([]) == ["values"]


def test_normalize_input_none():
    from app.gateway.services import normalize_input

    assert normalize_input(None) == {}


def test_normalize_input_with_messages():
    from app.gateway.services import normalize_input

    result = normalize_input({"messages": [{"role": "user", "content": "hi"}]})
    assert len(result["messages"]) == 1
    assert result["messages"][0].content == "hi"


def test_normalize_input_passthrough():
    from app.gateway.services import normalize_input

    result = normalize_input({"custom_key": "value"})
    assert result == {"custom_key": "value"}


def test_normalize_input_preserves_additional_kwargs_and_id():
    """Regression: gh #3132 — frontend ships uploaded-file metadata in
    additional_kwargs.files (and a client-side message id).  The gateway must
    not strip them before the graph runs, otherwise UploadsMiddleware reports
    "(empty)" for new uploads and the frontend message loses its file chip.
    """
    from langchain_core.messages import HumanMessage

    from app.gateway.services import normalize_input

    files = [{"filename": "a.csv", "size": 100, "path": "/mnt/user-data/uploads/a.csv", "status": "uploaded"}]
    result = normalize_input(
        {
            "messages": [
                {
                    "type": "human",
                    "id": "client-msg-1",
                    "name": "user-input",
                    "content": [{"type": "text", "text": "clean it"}],
                    "additional_kwargs": {"files": files, "custom": "keep-me"},
                }
            ]
        }
    )
    assert len(result["messages"]) == 1
    msg = result["messages"][0]
    assert isinstance(msg, HumanMessage)
    assert msg.id == "client-msg-1"
    assert msg.name == "user-input"
    assert msg.content == [{"type": "text", "text": "clean it"}]
    assert msg.additional_kwargs == {"files": files, "custom": "keep-me"}


@pytest.mark.parametrize(
    "forged_original",
    ["spoofed audit text", [{"type": "text", "text": "spoofed audit text"}]],
)
def test_normalize_input_strips_external_original_user_content(forged_original):
    from app.gateway.services import normalize_input
    from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY

    result = normalize_input(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "actual user input",
                    "additional_kwargs": {
                        ORIGINAL_USER_CONTENT_KEY: forged_original,
                        "custom": "keep-me",
                    },
                }
            ]
        }
    )

    assert result["messages"][0].additional_kwargs == {"custom": "keep-me"}


def test_normalize_input_preserves_trusted_internal_original_user_content():
    from app.gateway.services import normalize_input
    from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY

    result = normalize_input(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "uploaded file context\n\nactual user input",
                    "additional_kwargs": {
                        ORIGINAL_USER_CONTENT_KEY: "actual user input",
                    },
                }
            ]
        },
        trusted_internal=True,
    )

    assert result["messages"][0].additional_kwargs[ORIGINAL_USER_CONTENT_KEY] == "actual user input"


def test_normalize_input_preserves_human_input_response_metadata():
    from langchain_core.messages import HumanMessage

    from app.gateway.services import normalize_input

    response = {
        "version": 1,
        "kind": "human_input_response",
        "source": "ask_clarification",
        "request_id": "clarification:call-abc",
        "response_kind": "option",
        "option_id": "option-2",
        "value": "staging",
    }
    result = normalize_input(
        {
            "messages": [
                {
                    "type": "human",
                    "content": [{"type": "text", "text": "For your clarification, my answer is: staging"}],
                    "additional_kwargs": {"human_input_response": response},
                }
            ]
        }
    )

    msg = result["messages"][0]
    assert isinstance(msg, HumanMessage)
    assert msg.additional_kwargs["human_input_response"] == response


def test_normalize_input_passes_through_basemessage_instances():
    from langchain_core.messages import HumanMessage

    from app.gateway.services import normalize_input

    msg = HumanMessage(content="hello", id="m-1", additional_kwargs={"files": [{"filename": "x"}]})
    result = normalize_input({"messages": [msg]})
    assert result["messages"][0] is msg


def test_normalize_input_rejects_malformed_message_with_400():
    """Boundary validation: ``convert_to_messages`` raises ``ValueError`` when a
    message dict is missing ``role``/``type``/``content``.  ``normalize_input``
    runs inside the gateway HTTP boundary, so a malformed payload should surface
    as a 400 referencing the offending entry — not bubble up as a 500.

    Raised after the Copilot review on PR #3136.
    """
    import pytest
    from fastapi import HTTPException

    from app.gateway.services import normalize_input

    with pytest.raises(HTTPException) as excinfo:
        normalize_input({"messages": [{"role": "human", "content": "ok"}, {"oops": "no role here"}]})
    assert excinfo.value.status_code == 400
    assert "input.messages[1]" in excinfo.value.detail


def test_normalize_input_handles_non_human_roles():
    """The previous implementation collapsed every role to HumanMessage with a
    `# TODO: handle other message types` comment.  Resuming a thread with prior
    AI/tool messages would silently rewrite them as human turns — corrupting
    the conversation.  Use langchain's standard conversion so ai/system/tool
    roles round-trip correctly.
    """
    from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

    from app.gateway.services import normalize_input

    result = normalize_input(
        {
            "messages": [
                {"role": "system", "content": "sys"},
                {"role": "ai", "content": "hi", "id": "ai-1"},
                {"role": "tool", "content": "result", "tool_call_id": "call-1"},
            ]
        }
    )
    types = [type(m) for m in result["messages"]]
    assert types == [SystemMessage, AIMessage, ToolMessage]
    assert result["messages"][1].id == "ai-1"
    assert result["messages"][2].tool_call_id == "call-1"


def test_build_run_config_basic():
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", None, None)
    assert config["configurable"]["thread_id"] == "thread-1"
    assert config["recursion_limit"] == 100


def test_build_run_config_with_overrides():
    from app.gateway.services import build_run_config

    config = build_run_config(
        "thread-1",
        {"configurable": {"model_name": "gpt-4"}, "tags": ["test"]},
        {"user": "alice"},
    )
    assert config["configurable"]["model_name"] == "gpt-4"
    assert config["tags"] == ["test"]
    assert config["metadata"]["user"] == "alice"


def test_build_run_config_context_path_still_sets_configurable_thread_id(_stub_app_config):
    """A caller-supplied context (e.g. request-scoped secrets, #3861) must not
    deprive the checkpointer of configurable.thread_id, which it always needs to
    scope checkpoints. Secrets stay in context; thread_id is mirrored into
    configurable for the checkpointer."""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", {"context": {"secrets": {"ERP_TOKEN": "v"}}}, None)
    assert config["context"]["secrets"] == {"ERP_TOKEN": "v"}
    assert config["context"]["thread_id"] == "thread-1"
    assert config["configurable"]["thread_id"] == "thread-1"
    # Secrets must NOT be mirrored into configurable.
    assert "secrets" not in config["configurable"]


# ---------------------------------------------------------------------------
# recursion_limit clamping: the Gateway must not trust a client-supplied
# recursion_limit verbatim (runaway LLM cost / DoS). See build_run_config.
# ---------------------------------------------------------------------------


def test_build_run_config_clamps_excessive_recursion_limit(_stub_app_config):
    """A huge client recursion_limit is capped at the configured ceiling (default 1000)."""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", {"recursion_limit": 100_000_000}, None)
    assert config["recursion_limit"] == 1000


def test_build_run_config_ceiling_is_configurable(_stub_app_config):
    """The clamp ceiling comes from AppConfig.max_recursion_limit, not a hardcoded value."""
    from app.gateway.services import build_run_config
    from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config

    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "max_recursion_limit": 300}))
    try:
        config = build_run_config("thread-1", {"recursion_limit": 100_000_000}, None)
        assert config["recursion_limit"] == 300
    finally:
        reset_app_config()


def test_build_run_config_allows_recursion_limit_at_ceiling(_stub_app_config):
    """A value at the configured ceiling is preserved unchanged."""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", {"recursion_limit": 1000}, None)
    assert config["recursion_limit"] == 1000


def test_build_run_config_preserves_reasonable_recursion_limit(_stub_app_config):
    """A modest client value below the ceiling is honoured as-is."""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", {"recursion_limit": 250}, None)
    assert config["recursion_limit"] == 250


def test_build_run_config_rejects_invalid_recursion_limit(_stub_app_config):
    """Non-positive / non-int / bool values fall back to the server default."""
    from app.gateway.services import _DEFAULT_RECURSION_LIMIT, build_run_config

    for bad in (0, -5, "1000", 3.5, True, None):
        config = build_run_config("thread-1", {"recursion_limit": bad}, None)
        assert config["recursion_limit"] == _DEFAULT_RECURSION_LIMIT, bad


def test_build_run_config_clamps_recursion_limit_with_context(_stub_app_config):
    """Clamping also applies on the LangGraph >= 0.6.0 context passthrough path."""
    from app.gateway.services import build_run_config

    config = build_run_config(
        "thread-1",
        {"context": {"thread_id": "thread-1"}, "recursion_limit": 999_999},
        None,
    )
    assert config["recursion_limit"] == 1000


# ---------------------------------------------------------------------------
# Regression tests for issue #1644:
# assistant_id not mapped to agent_name → custom agent SOUL.md never loaded
# ---------------------------------------------------------------------------


def test_build_run_config_custom_agent_injects_agent_name():
    """Custom assistant_id must be forwarded as configurable['agent_name']."""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", None, None, assistant_id="finalis")
    assert config["configurable"]["agent_name"] == "finalis"
    assert config["run_name"] == "finalis"


def test_build_run_config_lead_agent_no_agent_name():
    """'lead_agent' assistant_id must NOT inject configurable['agent_name']."""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", None, None, assistant_id="lead_agent")
    assert "agent_name" not in config["configurable"]
    assert "run_name" not in config


def test_build_run_config_none_assistant_id_no_agent_name():
    """None assistant_id must NOT inject configurable['agent_name']."""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", None, None, assistant_id=None)
    assert "agent_name" not in config["configurable"]
    assert "run_name" not in config


def test_build_run_config_explicit_agent_name_not_overwritten():
    """An explicit configurable['agent_name'] in the request must take precedence."""
    from app.gateway.services import build_run_config

    config = build_run_config(
        "thread-1",
        {"configurable": {"agent_name": "explicit-agent"}},
        None,
        assistant_id="other-agent",
    )
    assert config["configurable"]["agent_name"] == "explicit-agent"
    assert config["context"]["agent_name"] == "explicit-agent"
    assert config["run_name"] == "explicit-agent"


def test_build_run_config_context_custom_agent_injects_agent_name():
    """Custom assistant_id must be forwarded as ``agent_name`` in both
    ``context`` and ``configurable`` (issue #3549). Previously only the
    active container was populated, so when the caller sent context-only the
    setup_agent tool — which reads ``ToolRuntime.context`` — saw
    ``agent_name=None`` and wrote SOUL.md to the global base_dir.
    """
    from app.gateway.services import build_run_config

    config = build_run_config(
        "thread-1",
        {"context": {"model_name": "deepseek-v3"}},
        None,
        assistant_id="finalis",
    )

    assert config["context"]["agent_name"] == "finalis"
    assert config["configurable"]["agent_name"] == "finalis"


def test_resolve_agent_factory_returns_make_lead_agent():
    """resolve_agent_factory always returns make_lead_agent regardless of assistant_id."""
    from app.gateway.services import resolve_agent_factory
    from deerflow.agents.lead_agent.agent import make_lead_agent

    assert resolve_agent_factory(None) is make_lead_agent
    assert resolve_agent_factory("lead_agent") is make_lead_agent
    assert resolve_agent_factory("finalis") is make_lead_agent
    assert resolve_agent_factory("custom-agent-123") is make_lead_agent


def test_build_run_config_configurable_custom_agent_dual_writes_agent_name():
    """Regression for issue #3549: even when the caller uses the legacy
    ``configurable`` path, ``agent_name`` must also land in
    ``config['context']`` so LangGraph >=1.1.9 ``ToolRuntime.context`` consumers
    (e.g. ``setup_agent``) observe the same value.
    """
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", None, None, assistant_id="finalis")

    assert config["configurable"]["agent_name"] == "finalis"
    assert config["context"]["agent_name"] == "finalis"


def test_build_run_config_context_explicit_agent_name_not_overwritten():
    """An explicit ``context['agent_name']`` from the request must take
    precedence over the value derived from ``assistant_id`` and be mirrored
    to ``configurable`` so the two containers never diverge.
    """
    from app.gateway.services import build_run_config

    config = build_run_config(
        "thread-1",
        {"context": {"agent_name": "explicit-agent"}},
        None,
        assistant_id="other-agent",
    )

    assert config["context"]["agent_name"] == "explicit-agent"
    assert config["configurable"]["agent_name"] == "explicit-agent"
    assert config["run_name"] == "explicit-agent"


def test_build_run_config_dual_write_matches_merge_run_context_overrides_shape():
    """The shape produced by ``build_run_config`` for a custom agent must be
    indistinguishable from what ``merge_run_context_overrides`` would produce
    when ``agent_name`` is supplied via ``body.context`` — guarding against
    the two code paths drifting apart again (issue #3549).
    """
    from app.gateway.services import build_run_config, merge_run_context_overrides

    via_assistant_id = build_run_config("thread-1", None, None, assistant_id="finalis")

    via_context = build_run_config("thread-1", None, None)
    merge_run_context_overrides(via_context, {"agent_name": "finalis"})

    assert via_assistant_id["configurable"]["agent_name"] == via_context["configurable"]["agent_name"]
    assert via_assistant_id["context"]["agent_name"] == via_context["context"]["agent_name"]


def test_non_interactive_context_override_is_internal_only():
    """Client-supplied ``non_interactive`` must be dropped: it strips the
    ``ask_clarification`` tool, so only the internal scheduler path may set it."""
    from app.gateway.services import build_run_config, merge_run_context_overrides

    config = build_run_config("thread-1", None, None)
    merge_run_context_overrides(config, {"non_interactive": True})

    assert "non_interactive" not in config["configurable"]
    assert "non_interactive" not in config["context"]


def test_non_interactive_context_override_honored_for_internal_caller():
    from app.gateway.services import build_run_config, merge_run_context_overrides

    config = build_run_config("thread-1", None, None)
    merge_run_context_overrides(config, {"non_interactive": True, "model_name": "gpt"}, internal=True)

    assert config["configurable"]["non_interactive"] is True
    assert config["context"]["non_interactive"] is True
    assert config["configurable"]["model_name"] == "gpt"


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Regression tests for issue #1699:
# context field in langgraph-compat requests not merged into configurable
# ---------------------------------------------------------------------------


def test_run_create_request_accepts_context():
    """RunCreateRequest must accept the ``context`` field without dropping it."""
    from app.gateway.routers.thread_runs import RunCreateRequest

    body = RunCreateRequest(
        input={"messages": [{"role": "user", "content": "hi"}]},
        context={
            "model_name": "deepseek-v3",
            "thinking_enabled": True,
            "is_plan_mode": True,
            "subagent_enabled": True,
            "thread_id": "some-thread-id",
        },
    )
    assert body.context is not None
    assert body.context["model_name"] == "deepseek-v3"
    assert body.context["is_plan_mode"] is True
    assert body.context["subagent_enabled"] is True


def test_run_create_request_context_defaults_to_none():
    """RunCreateRequest without context should default to None (backward compat)."""
    from app.gateway.routers.thread_runs import RunCreateRequest

    body = RunCreateRequest(input=None)
    assert body.context is None


def test_apply_checkpoint_to_run_config_writes_checkpoint_fields():
    import asyncio
    from types import SimpleNamespace

    from app.gateway.services import apply_checkpoint_to_run_config

    class FakeCheckpointer:
        def __init__(self):
            self.seen_config = None

        async def aget_tuple(self, config):
            self.seen_config = config
            return SimpleNamespace(config=config, checkpoint={"channel_values": {}})

    checkpointer = FakeCheckpointer()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(checkpointer=checkpointer)))
    body = SimpleNamespace(
        checkpoint={
            "checkpoint_ns": "",
            "checkpoint_id": "ckpt-1",
            "checkpoint_map": {"": "ckpt-1"},
        },
        checkpoint_id=None,
    )
    config = {"configurable": {"thread_id": "thread-1"}}

    asyncio.run(apply_checkpoint_to_run_config(config, body=body, thread_id="thread-1", request=request))

    assert checkpointer.seen_config == {
        "configurable": {
            "thread_id": "thread-1",
            "checkpoint_ns": "",
            "checkpoint_id": "ckpt-1",
            "checkpoint_map": {"": "ckpt-1"},
        }
    }
    assert config["configurable"]["checkpoint_id"] == "ckpt-1"
    assert config["configurable"]["checkpoint_ns"] == ""
    assert config["configurable"]["checkpoint_map"] == {"": "ckpt-1"}


def test_apply_checkpoint_to_run_config_rejects_missing_checkpoint():
    import asyncio
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.gateway.services import apply_checkpoint_to_run_config

    class FakeCheckpointer:
        async def aget_tuple(self, config):
            return None

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(checkpointer=FakeCheckpointer())))
    body = SimpleNamespace(checkpoint=None, checkpoint_id="missing")
    config = {"configurable": {"thread_id": "thread-1"}}

    with pytest.raises(HTTPException) as exc:
        asyncio.run(apply_checkpoint_to_run_config(config, body=body, thread_id="thread-1", request=request))

    assert exc.value.status_code == 404
    assert "missing" in exc.value.detail


def test_context_merges_into_configurable():
    """Context values must be merged into config['configurable'] by start_run.

    Since start_run is async and requires many dependencies, we test the
    merging logic directly by simulating what start_run does.
    """
    from app.gateway.services import build_run_config

    # Simulate the context merging logic from start_run
    config = build_run_config("thread-1", None, None)

    context = {
        "model_name": "deepseek-v3",
        "mode": "ultra",
        "reasoning_effort": "high",
        "thinking_enabled": True,
        "is_plan_mode": True,
        "subagent_enabled": True,
        "max_concurrent_subagents": 5,
        "max_total_subagents": 8,
        "thread_id": "should-be-ignored",
    }

    _CONTEXT_CONFIGURABLE_KEYS = {
        "model_name",
        "mode",
        "thinking_enabled",
        "reasoning_effort",
        "is_plan_mode",
        "subagent_enabled",
        "max_concurrent_subagents",
        "max_total_subagents",
    }
    configurable = config.setdefault("configurable", {})
    for key in _CONTEXT_CONFIGURABLE_KEYS:
        if key in context:
            configurable.setdefault(key, context[key])

    assert config["configurable"]["model_name"] == "deepseek-v3"
    assert config["configurable"]["thinking_enabled"] is True
    assert config["configurable"]["is_plan_mode"] is True
    assert config["configurable"]["subagent_enabled"] is True
    assert config["configurable"]["max_concurrent_subagents"] == 5
    assert config["configurable"]["max_total_subagents"] == 8
    assert config["configurable"]["reasoning_effort"] == "high"
    assert config["configurable"]["mode"] == "ultra"
    # thread_id from context should NOT override the one from build_run_config
    assert config["configurable"]["thread_id"] == "thread-1"
    # Non-allowlisted keys should not appear
    assert "thread_id" not in {k for k in context if k in _CONTEXT_CONFIGURABLE_KEYS}


def test_merge_run_context_overrides_propagates_to_runtime_context():
    """Regression for issue #2677: ``agent_name`` (and other whitelisted keys) from
    ``body.context`` must be propagated into BOTH ``config['configurable']`` and
    ``config['context']``. Previously only ``configurable`` was populated, so after
    the LangGraph 1.1.x upgrade removed the fallback from ``configurable``, the
    ``setup_agent`` tool read ``runtime.context`` with ``agent_name=None`` and
    silently wrote SOUL.md to the global base_dir.
    """
    from app.gateway.services import build_run_config, merge_run_context_overrides

    config = build_run_config("thread-1", None, None)
    merge_run_context_overrides(config, {"agent_name": "my-agent", "is_bootstrap": True, "thread_id": "ignored"})

    assert config["configurable"]["agent_name"] == "my-agent"
    assert config["configurable"]["is_bootstrap"] is True
    assert config["context"]["agent_name"] == "my-agent"
    assert config["context"]["is_bootstrap"] is True
    # Non-whitelisted keys are not forwarded.
    assert "thread_id" not in config["context"]


def test_merge_run_context_overrides_forwards_subagent_total_limit():
    from app.gateway.services import build_run_config, merge_run_context_overrides

    config = build_run_config("thread-1", None, None)
    merge_run_context_overrides(config, {"max_total_subagents": 8})

    assert config["configurable"]["max_total_subagents"] == 8
    assert config["context"]["max_total_subagents"] == 8


def test_merge_run_context_overrides_noop_for_empty_context():
    from app.gateway.services import build_run_config, merge_run_context_overrides

    config = build_run_config("thread-1", None, None)
    before = {k: dict(v) if isinstance(v, dict) else v for k, v in config.items()}
    merge_run_context_overrides(config, None)
    merge_run_context_overrides(config, {})
    assert config == before


def test_merge_run_context_overrides_forwards_context_only_keys():
    """``github_token`` and ``disable_clarification`` must reach ``config['context']``
    (runtime context → ``runtime.context``) so the bash tool and ClarificationMiddleware
    can read them. They must NOT be written to ``config['configurable']`` — that dict is
    persisted in checkpoints, and ``github_token`` is a (short-lived) secret.

    Regression for the GitHub channel: without this, the installation token minted by
    ``ChannelManager._apply_channel_policy`` was silently dropped here, so ``gh``
    fell back to the host's stored keyring creds and authored issues/PRs as the host
    user instead of the App bot.
    """
    from app.gateway.services import build_run_config, merge_run_context_overrides

    config = build_run_config("thread-1", None, None)
    merge_run_context_overrides(
        config,
        {
            "github_token": "ghs_installation_token",
            "disable_clarification": True,
            "agent_name": "coding-llm-gateway",
        },
    )

    # Forwarded into runtime context — what tools/middlewares read.
    assert config["context"]["github_token"] == "ghs_installation_token"
    assert config["context"]["disable_clarification"] is True
    assert config["context"]["agent_name"] == "coding-llm-gateway"

    # NOT written into configurable (checkpoint-persisted).
    assert "github_token" not in config.get("configurable", {})
    assert "disable_clarification" not in config.get("configurable", {})


def test_merge_run_context_overrides_context_only_keys_do_not_override_existing():
    """A token already in ``config['context']`` must not be clobbered by a
    client-supplied one (defense in depth — the manager is the only legitimate
    source, but ``setdefault`` keeps the contract explicit)."""
    from app.gateway.services import build_run_config, merge_run_context_overrides

    config = build_run_config("thread-1", None, None)
    config["context"] = {"github_token": "pre-existing"}
    merge_run_context_overrides(config, {"github_token": "attacker-supplied"})

    assert config["context"]["github_token"] == "pre-existing"


def test_context_does_not_override_existing_configurable():
    """Values already in config.configurable must NOT be overridden by context."""
    from app.gateway.services import build_run_config

    config = build_run_config(
        "thread-1",
        {"configurable": {"model_name": "gpt-4", "is_plan_mode": False}},
        None,
    )

    context = {
        "model_name": "deepseek-v3",
        "is_plan_mode": True,
        "subagent_enabled": True,
    }

    _CONTEXT_CONFIGURABLE_KEYS = {
        "model_name",
        "mode",
        "thinking_enabled",
        "reasoning_effort",
        "is_plan_mode",
        "subagent_enabled",
        "max_concurrent_subagents",
        "max_total_subagents",
    }
    configurable = config.setdefault("configurable", {})
    for key in _CONTEXT_CONFIGURABLE_KEYS:
        if key in context:
            configurable.setdefault(key, context[key])

    # Existing values must NOT be overridden
    assert config["configurable"]["model_name"] == "gpt-4"
    assert config["configurable"]["is_plan_mode"] is False
    # New values should be added
    assert config["configurable"]["subagent_enabled"] is True


def test_inject_authenticated_user_context_overrides_client_user_id():
    """Run context should carry the authenticated user, not client-supplied user_id."""
    from types import SimpleNamespace

    from app.gateway.services import build_run_config, inject_authenticated_user_context

    config = build_run_config("thread-1", None, None)
    config["context"] = {"user_id": "spoofed-client"}
    request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id="auth-user-42")))

    inject_authenticated_user_context(config, request)

    assert config["context"]["user_id"] == "auth-user-42"


def test_merge_run_context_overrides_propagates_user_id():
    """Regression for PR #3294: ``user_id`` from ``body.context`` must land in
    ``config['context']`` so non-web callers (e.g. IM channels) keep their identity
    on ``ToolRuntime.context``.
    """
    from app.gateway.services import build_run_config, merge_run_context_overrides

    config = build_run_config("thread-1", None, None)
    merge_run_context_overrides(config, {"user_id": "channel-user-7"})

    assert config["context"]["user_id"] == "channel-user-7"


def test_merge_run_context_overrides_does_not_clobber_existing_user_id():
    """``merge_run_context_overrides`` must not override an already-stamped
    authenticated ``context.user_id`` with the client-supplied value.
    """
    from app.gateway.services import build_run_config, merge_run_context_overrides

    config = build_run_config("thread-1", {"context": {"user_id": "auth-user-42"}}, None)
    merge_run_context_overrides(config, {"user_id": "spoofed-client"})

    assert config["context"]["user_id"] == "auth-user-42"


def test_inject_authenticated_user_context_skips_internal_role():
    """Regression for PR #3294: internal system-role callers must not overwrite an
    already-present ``context.user_id`` (e.g. a channel-supplied identity), so the
    real end user keeps owning the per-user storage bucket.
    """
    from types import SimpleNamespace

    from app.gateway.services import build_run_config, inject_authenticated_user_context

    config = build_run_config("thread-1", None, None)
    config["context"] = {"user_id": "channel-user-7"}
    request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id="internal-bot", system_role="internal")))

    inject_authenticated_user_context(config, request)

    assert config["context"]["user_id"] == "channel-user-7"


def test_inject_authenticated_user_context_strips_internal_spoofed_attribution():
    """Internal callers must not carry role/oauth attribution from request config
    unless the gateway resolved a trusted owner user server-side.
    """
    from types import SimpleNamespace

    from app.gateway.services import build_run_config, inject_authenticated_user_context

    config = build_run_config(
        "thread-1",
        {
            "context": {
                "user_id": "channel-user-7",
                "user_role": "admin",
                "oauth_provider": "spoofed-provider",
                "oauth_id": "spoofed-subject",
            }
        },
        None,
    )
    request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id="internal-bot", system_role="internal")))

    inject_authenticated_user_context(config, request)

    assert config["context"]["user_id"] == "channel-user-7"
    assert "user_role" not in config["context"]
    assert "oauth_provider" not in config["context"]
    assert "oauth_id" not in config["context"]


async def _capture_start_run_graph_input(body, *, auth_source=None):
    from types import SimpleNamespace
    from unittest.mock import patch

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from app.gateway.services import start_run
    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
    from deerflow.runtime import RunManager
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    run_manager = RunManager(store=MemoryRunStore())
    state = SimpleNamespace(
        stream_bridge=SimpleNamespace(),
        run_manager=run_manager,
        checkpointer=InMemorySaver(),
        store=InMemoryStore(),
        run_event_store=SimpleNamespace(),
        run_events_config=None,
        thread_store=MemoryThreadMetaStore(InMemoryStore()),
    )
    request = SimpleNamespace(
        headers={},
        state=SimpleNamespace(auth_source=auth_source),
        app=SimpleNamespace(state=state),
    )
    captured: dict[str, object] = {}

    async def fake_run_agent(*args, **kwargs):
        captured["graph_input"] = kwargs["graph_input"]

    with (
        patch("app.gateway.services.resolve_agent_factory", return_value=object()),
        patch("app.gateway.services.run_agent", side_effect=fake_run_agent),
    ):
        record = await start_run(body, "thread-command-test", request)
        await record.task

    return captured["graph_input"]


def test_start_run_translates_resume_command_to_langgraph_command(_stub_app_config):
    import asyncio

    from langgraph.types import Command

    from app.gateway.routers.thread_runs import RunCreateRequest

    graph_input = asyncio.run(
        _capture_start_run_graph_input(
            RunCreateRequest(
                input=None,
                command={"resume": {"answer": "approved"}},
            )
        )
    )

    assert isinstance(graph_input, Command)
    assert graph_input.resume == {"answer": "approved"}


def test_start_run_uses_normalized_input_without_command(_stub_app_config):
    import asyncio

    from langchain_core.messages import HumanMessage

    from app.gateway.routers.thread_runs import RunCreateRequest

    graph_input = asyncio.run(
        _capture_start_run_graph_input(
            RunCreateRequest(
                input={"messages": [{"role": "human", "content": "hi"}]},
                command=None,
            )
        )
    )

    assert isinstance(graph_input, dict)
    assert isinstance(graph_input["messages"][0], HumanMessage)
    assert graph_input["messages"][0].content == "hi"


def test_start_run_strips_external_original_user_content(_stub_app_config):
    import asyncio

    from app.gateway.routers.thread_runs import RunCreateRequest
    from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY

    graph_input = asyncio.run(
        _capture_start_run_graph_input(
            RunCreateRequest(
                input={
                    "messages": [
                        {
                            "role": "human",
                            "content": "actual user input",
                            "additional_kwargs": {ORIGINAL_USER_CONTENT_KEY: "spoofed audit text"},
                        }
                    ]
                },
                command=None,
            )
        )
    )

    assert ORIGINAL_USER_CONTENT_KEY not in graph_input["messages"][0].additional_kwargs


def test_start_run_preserves_internal_original_user_content(_stub_app_config):
    import asyncio

    from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL
    from app.gateway.routers.thread_runs import RunCreateRequest
    from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY

    graph_input = asyncio.run(
        _capture_start_run_graph_input(
            RunCreateRequest(
                input={
                    "messages": [
                        {
                            "role": "human",
                            "content": "uploaded file context\n\nactual user input",
                            "additional_kwargs": {ORIGINAL_USER_CONTENT_KEY: "actual user input"},
                        }
                    ]
                },
                command=None,
            ),
            auth_source=AUTH_SOURCE_INTERNAL,
        )
    )

    assert graph_input["messages"][0].additional_kwargs[ORIGINAL_USER_CONTENT_KEY] == "actual user input"


def test_start_run_uses_internal_owner_header_for_persistence(_stub_app_config):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import patch

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME, INTERNAL_SYSTEM_ROLE
    from app.gateway.services import start_run
    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
    from deerflow.runtime import RunManager
    from deerflow.runtime.runs.store.memory import MemoryRunStore
    from deerflow.runtime.user_context import get_effective_user_id

    async def _scenario():
        run_store = MemoryRunStore()
        thread_store = MemoryThreadMetaStore(InMemoryStore())
        await thread_store.create("channel-thread", user_id="default", metadata={"legacy": True})
        run_manager = RunManager(store=run_store)
        state = SimpleNamespace(
            stream_bridge=SimpleNamespace(),
            run_manager=run_manager,
            checkpointer=InMemorySaver(),
            store=InMemoryStore(),
            run_event_store=SimpleNamespace(),
            run_events_config=None,
            thread_store=thread_store,
        )
        request = SimpleNamespace(
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: "owner-1"},
            state=SimpleNamespace(user=SimpleNamespace(id="default", system_role=INTERNAL_SYSTEM_ROLE)),
            app=SimpleNamespace(state=state),
        )
        body = SimpleNamespace(
            assistant_id="lead_agent",
            input={"messages": [{"role": "human", "content": "hi"}]},
            metadata={},
            config=None,
            context=None,
            on_disconnect="cancel",
            multitask_strategy="reject",
            stream_mode=None,
            stream_subgraphs=False,
            interrupt_before=None,
            interrupt_after=None,
        )
        task_context: dict[str, str] = {}

        async def fake_run_agent(*args, **kwargs):
            task_context["user_id"] = get_effective_user_id()

        with (
            patch("app.gateway.services.resolve_agent_factory", return_value=object()),
            patch("app.gateway.services.run_agent", side_effect=fake_run_agent),
        ):
            record = await start_run(body, "channel-thread", request)
            await record.task

        owner_run = await run_store.get(record.run_id, user_id="owner-1")
        default_run = await run_store.get(record.run_id, user_id="default")
        owner_thread = await thread_store.get("channel-thread", user_id="owner-1")
        default_thread = await thread_store.get("channel-thread", user_id="default")
        return owner_run, default_run, owner_thread, default_thread, task_context

    owner_run, default_run, owner_thread, default_thread, task_context = asyncio.run(_scenario())

    assert owner_run is not None
    assert owner_run["user_id"] == "owner-1"
    assert default_run is None
    assert owner_thread is not None
    assert owner_thread["user_id"] == "owner-1"
    assert owner_thread["metadata"] == {"legacy": True}
    assert default_thread is None
    assert task_context["user_id"] == "owner-1"


def test_start_run_stamps_internal_owner_guardrail_attribution(_stub_app_config):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import patch

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME, INTERNAL_SYSTEM_ROLE
    from app.gateway.services import start_run
    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
    from deerflow.runtime import RunManager
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    class _Provider:
        async def get_user(self, user_id: str):
            assert user_id == "owner-1"
            return SimpleNamespace(
                id="owner-1",
                system_role="user",
                oauth_provider="keycloak",
                oauth_id="subject-123",
            )

    async def _scenario():
        thread_store = MemoryThreadMetaStore(InMemoryStore())
        await thread_store.create("channel-thread", user_id="owner-1", metadata={})
        run_manager = RunManager(store=MemoryRunStore())
        state = SimpleNamespace(
            stream_bridge=SimpleNamespace(),
            run_manager=run_manager,
            checkpointer=InMemorySaver(),
            store=InMemoryStore(),
            run_event_store=SimpleNamespace(),
            run_events_config=None,
            thread_store=thread_store,
        )
        request = SimpleNamespace(
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: "owner-1"},
            state=SimpleNamespace(user=SimpleNamespace(id="default", system_role=INTERNAL_SYSTEM_ROLE)),
            app=SimpleNamespace(state=state),
        )
        body = SimpleNamespace(
            assistant_id="lead_agent",
            input={"messages": [{"role": "human", "content": "hi"}]},
            metadata={},
            config={
                "context": {
                    "user_role": "admin",
                    "oauth_provider": "spoofed-provider",
                    "oauth_id": "spoofed-subject",
                }
            },
            context={"user_id": "spoofed-client"},
            on_disconnect="cancel",
            multitask_strategy="reject",
            stream_mode=None,
            stream_subgraphs=False,
            interrupt_before=None,
            interrupt_after=None,
        )
        captured_context: dict[str, object] = {}

        async def fake_run_agent(*args, **kwargs):
            captured_context.update(kwargs["config"]["context"])

        with (
            patch("app.gateway.services.get_local_provider", return_value=_Provider()),
            patch("app.gateway.services.resolve_agent_factory", return_value=object()),
            patch("app.gateway.services.run_agent", side_effect=fake_run_agent),
        ):
            record = await start_run(body, "channel-thread", request)
            await record.task

        return captured_context

    context = asyncio.run(_scenario())

    assert context["user_id"] == "owner-1"
    assert context["user_role"] == "user"
    assert context["oauth_provider"] == "keycloak"
    assert context["oauth_id"] == "subject-123"


def test_launch_scheduled_thread_run_marks_context_non_interactive(_stub_app_config):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import patch

    from app.gateway.services import launch_scheduled_thread_run

    async def _scenario():
        captured: dict[str, object] = {}

        async def fake_start_run(body, thread_id, request):
            captured["thread_id"] = thread_id
            captured["context"] = body.context
            captured["metadata"] = body.metadata
            return SimpleNamespace(run_id="run-1", thread_id=thread_id)

        with patch("app.gateway.services.start_run", side_effect=fake_start_run):
            result = await launch_scheduled_thread_run(
                thread_id="thread-scheduled",
                assistant_id="lead_agent",
                prompt="Run in background",
                app=SimpleNamespace(state=SimpleNamespace()),
                owner_user_id="user-1",
                metadata={"scheduled_task_id": "task-1"},
            )
        return captured, result

    captured, result = asyncio.run(_scenario())

    assert captured["thread_id"] == "thread-scheduled"
    assert captured["context"] == {"non_interactive": True, "user_id": "user-1"}
    assert captured["metadata"] == {"scheduled_task_id": "task-1"}
    assert result == {"run_id": "run-1", "thread_id": "thread-scheduled"}


# ---------------------------------------------------------------------------
# build_run_config — context / configurable precedence (LangGraph >= 0.6.0)
# ---------------------------------------------------------------------------


def test_build_run_config_with_context():
    """When caller sends 'context', prefer it over 'configurable'."""
    from app.gateway.services import build_run_config

    config = build_run_config(
        "thread-1",
        {"context": {"user_id": "u-42", "thread_id": "thread-1"}},
        None,
    )
    assert "context" in config
    assert config["context"]["user_id"] == "u-42"
    assert config["context"]["thread_id"] == "thread-1"
    # configurable carries thread_id for the checkpointer; user context stays in context.
    assert config["configurable"] == {"thread_id": "thread-1"}
    assert config["recursion_limit"] == 100


def test_build_run_config_context_injects_thread_id():
    from app.gateway.services import build_run_config

    config = build_run_config(
        "T-deadbeef-42",
        {"context": {"user_id": "u-1", "thinking_enabled": True}},
        None,
    )

    assert config["context"]["user_id"] == "u-1"
    assert config["context"]["thinking_enabled"] is True
    assert config["context"]["thread_id"] == "T-deadbeef-42"
    assert config["configurable"] == {"thread_id": "T-deadbeef-42"}


def test_build_run_config_null_context_becomes_empty_context():
    """When caller sends context=null, treat it as an empty context object."""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", {"context": None}, None)

    assert config["context"] == {"thread_id": "thread-1"}
    assert config["configurable"] == {"thread_id": "thread-1"}


def test_build_run_config_rejects_non_mapping_context():
    """When caller sends a non-object context, raise a clear error instead of a TypeError."""
    import pytest

    from app.gateway.services import build_run_config

    with pytest.raises(ValueError, match="context"):
        build_run_config("thread-1", {"context": "bad-context"}, None)


def test_build_run_config_null_context_custom_agent_injects_agent_name():
    """Custom assistant_id must be injected into both containers even when the
    request started in context-only mode with ``context=null`` .
    """
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", {"context": None}, None, assistant_id="finalis")

    assert config["context"]["agent_name"] == "finalis"
    assert config["configurable"]["agent_name"] == "finalis"


def test_build_run_config_context_plus_configurable_warns(caplog):
    """When caller sends both 'context' and 'configurable', prefer 'context' and log a warning."""
    import logging

    from app.gateway.services import build_run_config

    with caplog.at_level(logging.WARNING, logger="app.gateway.services"):
        config = build_run_config(
            "thread-1",
            {
                "context": {"user_id": "u-42"},
                "configurable": {"model_name": "gpt-4"},
            },
            None,
        )
    assert "context" in config
    assert config["context"]["user_id"] == "u-42"
    # context wins: caller's configurable (model_name) is dropped, but thread_id is
    # still set for the checkpointer.
    assert config["configurable"] == {"thread_id": "thread-1"}
    assert "model_name" not in config["configurable"]
    assert any("both 'context' and 'configurable'" in r.message for r in caplog.records)


def test_build_run_config_context_passthrough_other_keys():
    """Non-conflicting keys from request_config are still passed through when context is used."""
    from app.gateway.services import build_run_config

    config = build_run_config(
        "thread-1",
        {"context": {"thread_id": "thread-1"}, "tags": ["prod"]},
        None,
    )
    assert config["context"]["thread_id"] == "thread-1"
    assert config["configurable"] == {"thread_id": "thread-1"}
    assert config["tags"] == ["prod"]


def test_build_run_config_no_request_config():
    """When request_config is None, fall back to basic configurable with thread_id."""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-abc", None, None)
    assert config["configurable"] == {"thread_id": "thread-abc"}
    assert "context" not in config


def test_strip_internal_context_keys_scrubs_config_smuggled_non_interactive():
    """A non-internal client must not force ``non_interactive`` via the free-form
    ``body.config`` either — ``build_run_config`` copies ``config.context`` and
    ``config.configurable`` verbatim, so the assembled config gets scrubbed."""
    from app.gateway.services import build_run_config, strip_internal_context_keys

    via_context = build_run_config("thread-1", {"context": {"non_interactive": True, "model_name": "gpt"}}, None)
    strip_internal_context_keys(via_context)
    assert "non_interactive" not in via_context["context"]
    assert via_context["context"]["model_name"] == "gpt"

    via_configurable = build_run_config("thread-1", {"configurable": {"non_interactive": True}}, None)
    strip_internal_context_keys(via_configurable)
    assert "non_interactive" not in via_configurable["configurable"]
