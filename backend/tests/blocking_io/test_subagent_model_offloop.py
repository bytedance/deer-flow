"""A subagent must build its chat model off the loop it is executed on.

``SubagentExecutor._create_agent`` is awaited from ``_aexecute`` on the
persistent isolated subagent loop that every concurrent delegated task shares --
not the Gateway request loop. It constructed the chat model inline, and
provider construction can read local credentials -- the Codex provider loads the
Codex CLI ``auth.json`` while it is built -- so every delegated task did
synchronous file IO on that loop before its first model call. The real Codex
provider is built here so that IO stays inside the strict gate; inference never
runs.
"""

from __future__ import annotations

import importlib
import json
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from deerflow.agents.middlewares import tool_error_handling_middleware
from deerflow.models.openai_codex_provider import CodexChatModel

pytestmark = pytest.mark.asyncio

_MISSING = object()


@contextmanager
def _real_subagent_executor() -> Iterator[SimpleNamespace]:
    """Import the real executor despite the suite-level circular-import mock.

    ``deerflow.models`` and ``deerflow.agents`` stay real here: this test builds
    an actual Codex provider and patches the real middleware builder.
    """
    original_executor = sys.modules.get("deerflow.subagents.executor", _MISSING)
    parent_module = sys.modules.get("deerflow.subagents")
    original_parent_executor = getattr(parent_module, "executor", _MISSING) if parent_module is not None else _MISSING

    sys.modules.pop("deerflow.subagents.executor", None)
    try:
        module = importlib.import_module("deerflow.subagents.executor")
        yield module
    finally:
        if original_executor is _MISSING:
            sys.modules.pop("deerflow.subagents.executor", None)
        else:
            sys.modules["deerflow.subagents.executor"] = original_executor

        if parent_module is not None:
            if original_parent_executor is _MISSING:
                try:
                    delattr(parent_module, "executor")
                except AttributeError:
                    pass
            else:
                parent_module.executor = original_parent_executor


def _codex_config():
    from deerflow.config.app_config import AppConfig

    return AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [
                {
                    "name": "fixture-codex",
                    "model": "fixture-model",
                    "use": "deerflow.models.openai_codex_provider:CodexChatModel",
                }
            ],
            "memory": {"enabled": False},
        }
    )


@pytest.fixture
def credential_reads(tmp_path, monkeypatch):
    """Real Codex credential loading, with the thread of every read recorded."""
    credentials = tmp_path / "auth.json"
    credentials.write_text(json.dumps({"access_token": "fixture-token", "account_id": "fixture-account"}), encoding="utf-8")
    monkeypatch.setenv("CODEX_AUTH_PATH", str(credentials))
    reads = []
    original_load = CodexChatModel._load_codex_auth

    def record(self):
        reads.append(threading.get_ident())
        return original_load(self)

    monkeypatch.setattr(CodexChatModel, "_load_codex_auth", record)
    return reads


async def test_subagent_builds_its_chat_model_off_the_loop(credential_reads, monkeypatch):
    from deerflow.subagents.config import SubagentConfig

    loop_thread = threading.get_ident()
    with _real_subagent_executor() as executor_module:
        # The anchoring line is the model build; keep the middleware chain and
        # the compiled graph out of the test.
        monkeypatch.setattr(tool_error_handling_middleware, "build_subagent_runtime_middlewares", lambda **kwargs: [])
        monkeypatch.setattr(
            executor_module,
            "create_agent",
            lambda **kwargs: SimpleNamespace(get_graph=lambda: SimpleNamespace(nodes={})),
        )
        executor = executor_module.SubagentExecutor(
            config=SubagentConfig(name="probe", description="probe", model="fixture-codex"),
            tools=[],
            app_config=_codex_config(),
        )

        await executor._create_agent(tools=[])

    assert credential_reads, "the Codex provider was never constructed"
    assert all(ident != loop_thread for ident in credential_reads), "provider construction blocks the subagent loop"
