"""Tests for the model-agnostic tool-call arg normalization middleware."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import pytest
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from deerflow.agents.lead_agent.agent import _build_middlewares
from deerflow.agents.middlewares.tool_args_normalization_middleware import (
    AUTO_DESCRIPTION_MARKER,
    ToolArgsNormalizationMiddleware,
)
from deerflow.config.app_config import AppConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_model(name: str = "example-model", **extras) -> ModelConfig:
    kwargs = dict(
        name=name,
        display_name=name,
        description=None,
        use="langchain_ollama:ChatOllama",
        model=name,
    )
    kwargs.update(extras)
    return ModelConfig(**kwargs)


@dataclass
class _FakeModelRequest:
    messages: list

    def override(self, *, messages):
        return _FakeModelRequest(messages=messages)


@dataclass
class _FakeModelResponse:
    result: list
    structured_response: Any = None


def _tc(name: str, args: dict, tool_call_id: str = "tc-1") -> dict:
    return {"name": name, "args": args, "id": tool_call_id, "type": "tool_call"}


def _run_with_response(response: Any) -> Any:
    """Drive the middleware once; return whatever it sends downstream."""
    mw = ToolArgsNormalizationMiddleware()

    def handler(_request):
        return response

    return mw.wrap_model_call(_FakeModelRequest(messages=[]), handler)


# ---------------------------------------------------------------------------
# 1. file_path → path alias
# ---------------------------------------------------------------------------


def test_aliases_file_path_to_path_for_write_file():
    ai = AIMessage(
        id="m1",
        content="",
        tool_calls=[
            _tc(
                "write_file",
                {"content": "hi", "file_path": "/mnt/user-data/workspace/x.txt", "description": "d"},
            )
        ],
    )
    result = _run_with_response(_FakeModelResponse(result=[ai]))
    out_args = result.result[0].tool_calls[0]["args"]
    assert out_args["path"] == "/mnt/user-data/workspace/x.txt"
    assert "file_path" not in out_args


def test_aliases_filepath_variant():
    ai = AIMessage(
        id="m1",
        content="",
        tool_calls=[_tc("read_file", {"filepath": "/mnt/host/etc/hosts", "description": "d"})],
    )
    result = _run_with_response(_FakeModelResponse(result=[ai]))
    out_args = result.result[0].tool_calls[0]["args"]
    assert out_args["path"] == "/mnt/host/etc/hosts"
    assert "filepath" not in out_args


def test_path_wins_over_file_path_when_both_present():
    """If model sends both, the schema-correct key takes precedence; alias is dropped."""
    ai = AIMessage(
        id="m1",
        content="",
        tool_calls=[
            _tc(
                "write_file",
                {
                    "path": "/correct",
                    "file_path": "/ignored",
                    "content": "c",
                    "description": "d",
                },
            )
        ],
    )
    result = _run_with_response(_FakeModelResponse(result=[ai]))
    out_args = result.result[0].tool_calls[0]["args"]
    assert out_args["path"] == "/correct"
    assert "file_path" not in out_args


# ---------------------------------------------------------------------------
# 3. Auto-fill missing description
# ---------------------------------------------------------------------------


def test_auto_fills_missing_description():
    ai = AIMessage(
        id="m1",
        content="",
        tool_calls=[_tc("write_file", {"path": "/x", "content": "c"})],
    )
    result = _run_with_response(_FakeModelResponse(result=[ai]))
    out_args = result.result[0].tool_calls[0]["args"]
    assert out_args["description"] == AUTO_DESCRIPTION_MARKER


def test_description_unchanged_when_provided():
    ai = AIMessage(
        id="m1",
        content="",
        tool_calls=[_tc("write_file", {"path": "/x", "content": "c", "description": "real reason"})],
    )
    result = _run_with_response(_FakeModelResponse(result=[ai]))
    assert result.result[0].tool_calls[0]["args"]["description"] == "real reason"


def test_auto_fill_and_alias_rewrite_combined():
    """The exact failure from the observed Magistral thread: file_path + missing description."""
    ai = AIMessage(
        id="m1",
        content="",
        tool_calls=[
            _tc(
                "write_file",
                {"content": "<html/>", "file_path": "/mnt/user-data/workspace/app.html"},
            )
        ],
    )
    result = _run_with_response(_FakeModelResponse(result=[ai]))
    out_args = result.result[0].tool_calls[0]["args"]
    assert out_args == {
        "content": "<html/>",
        "path": "/mnt/user-data/workspace/app.html",
        "description": AUTO_DESCRIPTION_MARKER,
    }


# ---------------------------------------------------------------------------
# 4. No-op paths
# ---------------------------------------------------------------------------


def test_no_op_when_no_tool_calls():
    ai = AIMessage(id="m1", content="plain text")
    original = _FakeModelResponse(result=[ai])
    result = _run_with_response(original)
    assert result is original  # identity preserved, no pointless rebuild


def test_no_op_when_args_already_valid():
    ai = AIMessage(
        id="m1",
        content="",
        tool_calls=[_tc("write_file", {"path": "/x", "content": "c", "description": "d"})],
    )
    original = _FakeModelResponse(result=[ai])
    result = _run_with_response(original)
    assert result is original


def test_non_ai_messages_pass_through_untouched():
    human = HumanMessage(content="hi")
    ai = AIMessage(
        id="m1",
        content="",
        tool_calls=[_tc("write_file", {"file_path": "/x", "content": "c"})],
    )
    result = _run_with_response(_FakeModelResponse(result=[human, ai]))
    assert result.result[0] is human
    assert result.result[1].tool_calls[0]["args"]["path"] == "/x"


def test_unknown_tool_does_not_get_auto_description():
    """For tools we don't recognize, we don't invent a description — surface the real error."""
    ai = AIMessage(
        id="m1",
        content="",
        tool_calls=[_tc("some_mcp_tool", {"query": "foo"})],
    )
    result = _run_with_response(_FakeModelResponse(result=[ai]))
    # No description injected for unknown tools
    assert "description" not in result.result[0].tool_calls[0]["args"]


def test_unknown_tool_still_gets_path_alias_rewrite():
    """file_path is a generic Mistral convention; alias normalization is safe even for unknown tools."""
    ai = AIMessage(
        id="m1",
        content="",
        tool_calls=[_tc("future_tool", {"file_path": "/p"})],
    )
    result = _run_with_response(_FakeModelResponse(result=[ai]))
    out_args = result.result[0].tool_calls[0]["args"]
    assert out_args == {"path": "/p"}


# ---------------------------------------------------------------------------
# 5. Response shape compatibility
# ---------------------------------------------------------------------------


def test_handles_bare_ai_message_response():
    """Middleware handlers may return an AIMessage directly instead of a ModelResponse."""
    ai = AIMessage(
        id="m1",
        content="",
        tool_calls=[_tc("write_file", {"file_path": "/x", "content": "c"})],
    )
    result = _run_with_response(ai)
    assert isinstance(result, AIMessage)
    assert result.tool_calls[0]["args"]["path"] == "/x"
    assert result.tool_calls[0]["args"]["description"] == AUTO_DESCRIPTION_MARKER


def test_preserves_tool_call_id_and_type():
    ai = AIMessage(
        id="m1",
        content="",
        tool_calls=[_tc("write_file", {"file_path": "/x", "content": "c"}, tool_call_id="abc-123")],
    )
    result = _run_with_response(_FakeModelResponse(result=[ai]))
    out_tc = result.result[0].tool_calls[0]
    assert out_tc["id"] == "abc-123"
    assert out_tc["type"] == "tool_call"


def test_mixed_tool_calls_only_mutate_the_broken_one():
    ai = AIMessage(
        id="m1",
        content="",
        tool_calls=[
            _tc("bash", {"command": "ls", "description": "list"}, tool_call_id="ok"),
            _tc("write_file", {"file_path": "/x", "content": "c"}, tool_call_id="broken"),
        ],
    )
    result = _run_with_response(_FakeModelResponse(result=[ai]))
    calls = result.result[0].tool_calls
    assert calls[0]["args"] == {"command": "ls", "description": "list"}
    assert calls[1]["args"] == {
        "path": "/x",
        "content": "c",
        "description": AUTO_DESCRIPTION_MARKER,
    }


# ---------------------------------------------------------------------------
# 6. Middleware is registered unconditionally in _build_middlewares
# ---------------------------------------------------------------------------
#
# The middleware is a model-agnostic safety net (see its module docstring)
# so _build_middlewares must register it for every model configuration.
# This parameter list is the regression guard: it covers the main vendor
# families and their common packaging formats (Ollama tags, HuggingFace
# repo paths, direct API names, AWS Bedrock ARNs). The assertion is the
# same for every entry — extending the list costs one line and documents
# an additional class/provider that DeerFlow should keep covered.
#
# Grouped by vendor-family with the relevant reason annotated:


def _app_config_with(model: ModelConfig) -> AppConfig:
    return AppConfig(
        models=[model],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
    )


def _middleware_names(middlewares: list[AgentMiddleware]) -> list[str]:
    return [type(m).__name__ for m in middlewares]


def _run_build(model_name: str, model: ModelConfig) -> list[AgentMiddleware]:
    app_config = _app_config_with(model)
    with patch("deerflow.agents.lead_agent.agent.get_app_config", return_value=app_config):
        return _build_middlewares(RunnableConfig(configurable={}), model_name=model_name)


# Each row is (human-readable id, model name as it would appear in
# ``config.yaml``). Model names are verbatim so provider naming
# conventions stay visible in the test catalogue.
_REGISTRATION_MATRIX: list[tuple[str, str]] = [
    # --- Mistral AI — historic trigger of the file_path alias + missing description
    ("mistral-magistral-ollama", "magistral:24b"),
    ("mistral-devstral-small-2-ollama", "devstral-small-2:24b"),
    ("mistral-devstral-2-ollama", "devstral-2:24b"),
    ("mistral-mixtral-ollama", "mixtral:8x7b"),
    ("mistral-codestral-ollama", "codestral:22b"),
    ("mistral-ministral-ollama", "ministral:8b"),
    ("mistral-api-direct", "mistral-large-2407"),
    ("mistral-huggingface", "mistralai/Mixtral-8x7B-Instruct-v0.1"),
    ("mistral-bedrock", "mistral.mistral-large-2402-v1:0"),
    # --- Google Gemma 4 — intermittent description-drop on tool calls.
    #     Earlier Gemma generations (Gemma 3, CodeGemma) don't ship with
    #     function-calling support, so they never produce the tool calls
    #     the middleware would operate on — they stay out of the matrix.
    ("gemma4-ollama-default", "gemma4-2b"),
    ("gemma4-ollama-xl", "gemma4-27b"),
    # Major model families without a tracked tool-args quirk are
    # deliberately kept out of this matrix:
    #   - Anthropic Claude, OpenAI GPT: reliably emit tool arguments in
    #     the exact schema DeerFlow's sandbox tools expect — the
    #     middleware is a no-op on them.
    #   - Qwen, Llama, DeepSeek and other open-source families: not
    #     (or not extensively) tested against the quirk, so we have
    #     neither evidence of a problem nor a guarantee of cleanliness;
    #     adding them would be speculative rather than informative.
    # The ``neutral-placeholder`` entry below already guards the
    # gate-removal invariant for any untested family.
    # --- Neutrally-named placeholder: proves the gate really was removed
    #     (would fail if anyone re-introduces a family-whitelist check)
    ("neutral-placeholder", "example-clean-model"),
]


@pytest.mark.parametrize(
    "model_name",
    [pytest.param(name, id=case_id) for case_id, name in _REGISTRATION_MATRIX],
)
def test_normalization_middleware_registered_for_every_model(model_name: str):
    """Registration is model-agnostic. Regression guard against re-introducing
    a family-gate in _build_middlewares."""
    mws = _run_build(model_name, _make_model(model_name))
    assert "ToolArgsNormalizationMiddleware" in _middleware_names(mws)


def test_auto_description_marker_is_model_agnostic():
    """Marker copy reads naturally for any model family."""
    assert "magistral" not in AUTO_DESCRIPTION_MARKER.lower()
    assert "gemma" not in AUTO_DESCRIPTION_MARKER.lower()
    assert "model" in AUTO_DESCRIPTION_MARKER.lower()
