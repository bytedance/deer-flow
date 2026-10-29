"""End-to-end verification for update_agent's user_id resolution.

PR #2784 hardened setup_agent to prefer runtime.context["user_id"] over the
contextvar. update_agent had the same latent gap: it unconditionally called
get_effective_user_id() at module level, so any scenario where the contextvar
was unavailable while runtime.context carried user_id (a background task
scheduled outside the request task, a worker pool that doesn't copy_context,
checkpoint resume on a different task) would silently route writes to
users/default/agents/...

These tests are load-bearing under @no_auto_user (contextvar empty):

- The negative-control test confirms the fixture actually puts the tool in
  the regime where the contextvar fallback would land in users/default/.
  Without that, the positive test would be vacuously satisfied.
- The positive test verifies update_agent honours runtime.context["user_id"]
  injected by inject_authenticated_user_context in the gateway. Before the
  fix in this PR, this test failed; now it passes.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
import yaml
from _agent_e2e_helpers import build_single_tool_call_model
from langchain_core.messages import HumanMessage

from app.gateway.services import (
    build_run_config,
    inject_authenticated_user_context,
    merge_run_context_overrides,
)
from deerflow.runtime.runs.worker import _build_runtime_context, _install_runtime_context


def _make_request(user_id_str: str | None) -> SimpleNamespace:
    user = SimpleNamespace(id=UUID(user_id_str), email="alice@local") if user_id_str else None
    return SimpleNamespace(state=SimpleNamespace(user=user))


def _assemble_config(*, body_context: dict | None, request_user_id: str | None, thread_id: str) -> dict:
    config = build_run_config(thread_id, {"recursion_limit": 50}, None, assistant_id="lead_agent")
    merge_run_context_overrides(config, body_context)
    inject_authenticated_user_context(config, _make_request(request_user_id))
    return config


def _seed_existing_agent(tmp_path: Path, user_id: str, agent_name: str, soul: str = "# Original"):
    """Pre-create an agent on disk for update_agent to overwrite."""
    agent_dir = tmp_path / "users" / user_id / "agents" / agent_name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "config.yaml").write_text(
        yaml.dump({"name": agent_name, "description": "old"}, allow_unicode=True),
        encoding="utf-8",
    )
    (agent_dir / "SOUL.md").write_text(soul, encoding="utf-8")
    return agent_dir


def _make_paths_mock(tmp_path: Path):
    paths = MagicMock()
    paths.base_dir = tmp_path
    paths.agent_dir = lambda name: tmp_path / "agents" / name
    paths.user_agent_dir = lambda user_id, name: tmp_path / "users" / user_id / "agents" / name
    return paths


def _patch_update_agent_dependencies(tmp_path: Path):
    """update_agent reads load_agent_config + get_app_config — stub them
    minimally so the tool can run without a real config file or LLM."""
    fake_model_cfg = SimpleNamespace(name="fake-model")
    fake_app_cfg = MagicMock()
    fake_app_cfg.get_model_config = lambda name: fake_model_cfg if name == "fake-model" else None

    return [
        patch(
            "deerflow.tools.builtins.update_agent_tool.get_paths",
            return_value=_make_paths_mock(tmp_path),
        ),
        patch(
            "deerflow.tools.builtins.update_agent_tool.get_app_config",
            return_value=fake_app_cfg,
        ),
        # load_agent_config (used by update_agent to read existing config) also
        # reads paths via its own module-level get_paths reference. Patch it too
        # or the tool returns "Agent does not exist" before touching disk.
        patch(
            "deerflow.config.agents_config.get_paths",
            return_value=_make_paths_mock(tmp_path),
        ),
    ]


def _build_update_graph(*, soul_payload: str):
    from langchain.agents import create_agent

    from deerflow.tools.builtins.update_agent_tool import update_agent

    fake_model = build_single_tool_call_model(
        tool_name="update_agent",
        tool_args={"soul": soul_payload, "description": "refined"},
        tool_call_id="call_update_1",
        final_text="updated",
    )
    return create_agent(model=fake_model, tools=[update_agent], system_prompt="updater")


# ---------------------------------------------------------------------------
# Negative control — proves the test environment puts update_agent in the
# regime where the contextvar fallback would land in default/.
# ---------------------------------------------------------------------------


@pytest.mark.no_auto_user
def test_update_agent_falls_back_to_default_when_no_inject_and_no_contextvar(tmp_path: Path):
    """No request.state.user, no contextvar — update_agent must look in
    users/default/agents/. We seed the file there so the tool succeeds and
    we know which directory it actually consulted."""
    from langgraph.runtime import Runtime

    _seed_existing_agent(tmp_path, "default", "fallback-target")

    config = _assemble_config(
        body_context={"agent_name": "fallback-target"},
        request_user_id=None,  # no auth, inject is no-op
        thread_id="thread-update-1",
    )
    runtime_ctx = _build_runtime_context("thread-update-1", "run-1", config.get("context"), None)
    _install_runtime_context(config, runtime_ctx)
    runtime = Runtime(context=runtime_ctx, store=None)
    config.setdefault("configurable", {})["__pregel_runtime"] = runtime

    graph = _build_update_graph(soul_payload="# Fallback Updated")

    with ExitStack() as stack:
        for p in _patch_update_agent_dependencies(tmp_path):
            stack.enter_context(p)
        graph.invoke(
            {"messages": [HumanMessage(content="update fallback-target")]},
            config=config,
        )

    soul = (tmp_path / "users" / "default" / "agents" / "fallback-target" / "SOUL.md").read_text()
    assert soul == "# Fallback Updated", "Sanity: tool should have written under default/"


# ---------------------------------------------------------------------------
# Regression guard — passes on this branch, would fail on main before the fix.
# ---------------------------------------------------------------------------


@pytest.mark.no_auto_user
def test_update_agent_should_use_runtime_context_user_id_when_contextvar_missing(tmp_path: Path):
    """update_agent prefers the authenticated user_id carried in
    runtime.context (placed there by inject_authenticated_user_context)
    over the contextvar — same contract as setup_agent (PR #2784).

    Before this PR's fix, update_agent unconditionally called
    get_effective_user_id() and landed in default/ whenever the contextvar
    was unavailable. This test pins the corrected behaviour.
    """
    from langgraph.runtime import Runtime

    auth_uid = "abcdef01-2345-6789-abcd-ef0123456789"

    # Seed the agent in BOTH locations so we can prove which one was opened.
    auth_dir = _seed_existing_agent(tmp_path, auth_uid, "shared-name", soul="# Auth Original")
    default_dir = _seed_existing_agent(tmp_path, "default", "shared-name", soul="# Default Original")

    config = _assemble_config(
        body_context={"agent_name": "shared-name"},
        request_user_id=auth_uid,
        thread_id="thread-update-2",
    )
    runtime_ctx = _build_runtime_context("thread-update-2", "run-2", config.get("context"), None)
    assert runtime_ctx["user_id"] == auth_uid, "Pre-condition: inject must have placed user_id into runtime_ctx"

    _install_runtime_context(config, runtime_ctx)
    runtime = Runtime(context=runtime_ctx, store=None)
    config.setdefault("configurable", {})["__pregel_runtime"] = runtime

    graph = _build_update_graph(soul_payload="# Auth Updated")

    with ExitStack() as stack:
        for p in _patch_update_agent_dependencies(tmp_path):
            stack.enter_context(p)
        graph.invoke(
            {"messages": [HumanMessage(content="update shared-name")]},
            config=config,
        )

    auth_soul = (auth_dir / "SOUL.md").read_text()
    default_soul = (default_dir / "SOUL.md").read_text()

    assert auth_soul == "# Auth Updated", f"REGRESSION: update_agent ignored runtime.context['user_id']={auth_uid!r} and routed the write to users/default/ instead. auth_soul={auth_soul!r}, default_soul={default_soul!r}"
    assert default_soul == "# Default Original", "REGRESSION: update_agent corrupted the shared default-user agent. It should have written under the authenticated user's path."


# ---------------------------------------------------------------------------
# Positive — when contextvar IS the auth user (the normal HTTP case), things
# already work. Pin it as a regression guard so future refactors don't
# accidentally break the contextvar path in pursuit of the runtime-context fix.
# ---------------------------------------------------------------------------


def test_update_agent_uses_contextvar_when_present(tmp_path: Path, monkeypatch):
    """The normal HTTP case: contextvar is set by auth_middleware. This must
    keep working regardless of how runtime.context is populated."""
    from types import SimpleNamespace as _SN

    from deerflow.runtime.user_context import reset_current_user, set_current_user

    auth_uid = "11112222-3333-4444-5555-666677778888"
    user = _SN(id=auth_uid, email="ctxvar@local")

    _seed_existing_agent(tmp_path, auth_uid, "ctxvar-agent", soul="# Original")

    from langgraph.runtime import Runtime

    config = _assemble_config(
        body_context={"agent_name": "ctxvar-agent"},
        request_user_id=auth_uid,
        thread_id="thread-update-3",
    )
    runtime_ctx = _build_runtime_context("thread-update-3", "run-3", config.get("context"), None)
    _install_runtime_context(config, runtime_ctx)
    runtime = Runtime(context=runtime_ctx, store=None)
    config.setdefault("configurable", {})["__pregel_runtime"] = runtime

    graph = _build_update_graph(soul_payload="# CtxVar Updated")

    with ExitStack() as stack:
        for p in _patch_update_agent_dependencies(tmp_path):
            stack.enter_context(p)
        token = set_current_user(user)
        try:
            final = graph.invoke(
                {"messages": [HumanMessage(content="update ctxvar-agent")]},
                config=config,
            )
        finally:
            reset_current_user(token)

    # surface the tool's reply for debug if it errored
    tool_replies = [m.content for m in final["messages"] if getattr(m, "type", "") == "tool"]
    soul = (tmp_path / "users" / auth_uid / "agents" / "ctxvar-agent" / "SOUL.md").read_text()
    assert soul == "# CtxVar Updated", f"tool replies: {tool_replies}"
