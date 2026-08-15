import logging
from types import SimpleNamespace

import pytest

from deerflow.skills.security_scanner import _extract_json_object, scan_skill_content


def _make_env(monkeypatch, response_content):
    config = SimpleNamespace(skill_evolution=SimpleNamespace(moderation_model_name=None))
    fake_response = SimpleNamespace(content=response_content)

    class FakeModel:
        async def ainvoke(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            return fake_response

    model = FakeModel()

    def _fake_create_chat_model(**kwargs):
        model.create_kwargs = kwargs
        return model

    monkeypatch.setattr("deerflow.skills.security_scanner.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.security_scanner.create_chat_model", _fake_create_chat_model)
    return model


def _make_traced_env(monkeypatch, *, model_name, response_content='{"decision":"allow","reason":"ok"}'):
    """Like ``_make_env`` but with a concrete moderation model name and a known
    effective user, so Langfuse trace metadata (model tag + user_id) is assertable.
    """
    config = SimpleNamespace(skill_evolution=SimpleNamespace(moderation_model_name=model_name))
    fake_response = SimpleNamespace(content=response_content)

    class FakeModel:
        async def ainvoke(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            return fake_response

    model = FakeModel()

    def _fake_create_chat_model(**kwargs):
        model.create_kwargs = kwargs
        return model

    monkeypatch.setattr("deerflow.skills.security_scanner.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.security_scanner.create_chat_model", _fake_create_chat_model)
    monkeypatch.setattr("deerflow.skills.security_scanner.get_effective_user_id", lambda: "scanner-user")
    return model


def _enable_langfuse_env(monkeypatch):
    for name in ("LANGFUSE_TRACING", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("DEER_FLOW_ENV", "production")


SKILL_CONTENT = "---\nname: demo-skill\ndescription: demo\n---\n"


# --- _extract_json_object unit tests ---


def test_extract_json_plain():
    assert _extract_json_object('{"decision":"allow","reason":"ok"}') == {"decision": "allow", "reason": "ok"}


def test_extract_json_markdown_fence():
    raw = '```json\n{"decision": "allow", "reason": "ok"}\n```'
    assert _extract_json_object(raw) == {"decision": "allow", "reason": "ok"}


def test_extract_json_fence_no_language():
    raw = '```\n{"decision": "allow", "reason": "ok"}\n```'
    assert _extract_json_object(raw) == {"decision": "allow", "reason": "ok"}


def test_extract_json_prose_wrapped():
    raw = 'Looking at this content I conclude: {"decision": "allow", "reason": "clean"} and that is final.'
    assert _extract_json_object(raw) == {"decision": "allow", "reason": "clean"}


def test_extract_json_nested_braces_in_reason():
    raw = '{"decision": "allow", "reason": "no issues with {placeholder} found"}'
    assert _extract_json_object(raw) == {"decision": "allow", "reason": "no issues with {placeholder} found"}


def test_extract_json_nested_braces_code_snippet():
    raw = 'Here is my review: {"decision": "block", "reason": "contains {\\"x\\": 1} code injection"}'
    assert _extract_json_object(raw) == {"decision": "block", "reason": 'contains {"x": 1} code injection'}


def test_extract_json_returns_none_for_garbage():
    assert _extract_json_object("no json here") is None


def test_extract_json_returns_none_for_unclosed_brace():
    assert _extract_json_object('{"decision": "allow"') is None


# --- scan_skill_content integration tests ---


@pytest.mark.anyio
async def test_scan_skill_content_passes_run_name_to_model(monkeypatch):
    model = _make_env(monkeypatch, '{"decision":"allow","reason":"ok"}')
    result = await scan_skill_content(SKILL_CONTENT, executable=False)
    assert result.decision == "allow"
    assert model.kwargs["config"] == {"run_name": "security_agent"}


@pytest.mark.anyio
async def test_scan_skill_content_blocks_when_model_unavailable(monkeypatch):
    config = SimpleNamespace(skill_evolution=SimpleNamespace(moderation_model_name=None))
    monkeypatch.setattr("deerflow.skills.security_scanner.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.security_scanner.create_chat_model", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    result = await scan_skill_content(SKILL_CONTENT, executable=False)

    assert result.decision == "block"
    assert "unavailable" in result.reason


@pytest.mark.anyio
async def test_scan_allows_markdown_fenced_response(monkeypatch):
    _make_env(monkeypatch, '```json\n{"decision": "allow", "reason": "clean"}\n```')
    result = await scan_skill_content(SKILL_CONTENT, executable=False)
    assert result.decision == "allow"
    assert result.reason == "clean"


@pytest.mark.anyio
async def test_scan_normalizes_decision_case(monkeypatch):
    _make_env(monkeypatch, '{"decision": "Allow", "reason": "looks fine"}')
    result = await scan_skill_content(SKILL_CONTENT, executable=False)
    assert result.decision == "allow"


@pytest.mark.anyio
async def test_scan_normalizes_uppercase_decision(monkeypatch):
    _make_env(monkeypatch, '{"decision": "BLOCK", "reason": "dangerous"}')
    result = await scan_skill_content(SKILL_CONTENT, executable=False)
    assert result.decision == "block"


@pytest.mark.anyio
async def test_scan_handles_nested_braces_in_reason(monkeypatch):
    _make_env(monkeypatch, '{"decision": "allow", "reason": "no issues with {placeholder}"}')
    result = await scan_skill_content(SKILL_CONTENT, executable=False)
    assert result.decision == "allow"
    assert "{placeholder}" in result.reason


@pytest.mark.anyio
async def test_scan_handles_prose_wrapped_json(monkeypatch):
    _make_env(monkeypatch, 'I reviewed the content: {"decision": "allow", "reason": "safe"}\nDone.')
    result = await scan_skill_content(SKILL_CONTENT, executable=False)
    assert result.decision == "allow"


@pytest.mark.anyio
async def test_scan_distinguishes_unparseable_from_unavailable(monkeypatch):
    _make_env(monkeypatch, "I can't decide, this is just prose without any JSON at all.")
    result = await scan_skill_content(SKILL_CONTENT, executable=False)
    assert result.decision == "block"
    assert "unparseable" in result.reason


@pytest.mark.anyio
async def test_scan_distinguishes_unparseable_executable(monkeypatch):
    _make_env(monkeypatch, "no json here")
    result = await scan_skill_content(SKILL_CONTENT, executable=True)
    # Even for executable content, unparseable uses the unparseable message
    assert result.decision == "block"
    assert "unparseable" in result.reason


# --- tracing wiring: in-graph vs standalone (see the INVARIANT in
# packages/harness/deerflow/agents/lead_agent/agent.py and the Tracing System
# section of backend/AGENTS.md) ---


@pytest.mark.anyio
async def test_scan_skill_content_forwards_attach_tracing_to_the_model(monkeypatch):
    """In-graph callers pass ``attach_tracing=False``; it must reach the factory.

    The graph root already attached the callbacks, so attaching again at the model
    emits duplicate spans and blocks the Langfuse handler's ``propagate_attributes``
    path, meaning session_id/user_id never land on the trace.
    """
    model = _make_env(monkeypatch, '{"decision":"allow","reason":"ok"}')
    result = await scan_skill_content(SKILL_CONTENT, executable=False, attach_tracing=False)
    assert result.decision == "allow"
    assert model.create_kwargs["attach_tracing"] is False


@pytest.mark.anyio
async def test_scan_skill_content_attaches_model_tracing_by_default(monkeypatch):
    """Standalone callers (Gateway skill routes, installer) have no graph root to
    inherit from, so the default keeps model-level attachment.

    Anchors the other direction of the change: narrowing the fix into an
    unconditional ``attach_tracing=False`` would silently drop their spans.
    """
    model = _make_env(monkeypatch, '{"decision":"allow","reason":"ok"}')
    result = await scan_skill_content(SKILL_CONTENT, executable=False)
    assert result.decision == "allow"
    assert model.create_kwargs["attach_tracing"] is True


@pytest.mark.anyio
async def test_scan_skill_content_injects_langfuse_metadata_when_standalone(monkeypatch):
    """Standalone scans (Gateway routes, installer) own the trace root, so they must
    inject Langfuse attribution themselves -- the other half of the standalone pattern
    that already attaches model-level callbacks here, mirroring oneshot_llm / the goal
    evaluator / MemoryUpdater (Tracing System INVARIANT in backend/AGENTS.md). Without
    it the skill-moderation trace has no user/session/name attribution (the #4252
    follow-up gap).
    """
    from deerflow.config.tracing_config import reset_tracing_config

    _enable_langfuse_env(monkeypatch)
    reset_tracing_config()
    model = _make_traced_env(monkeypatch, model_name="moderation-model")
    try:
        result = await scan_skill_content(SKILL_CONTENT, executable=False)
    finally:
        reset_tracing_config()

    assert result.decision == "allow"
    config = model.kwargs["config"]
    assert config["run_name"] == "security_agent"
    metadata = config.get("metadata") or {}
    assert metadata.get("langfuse_user_id") == "scanner-user"
    assert metadata.get("langfuse_trace_name") == "security_agent"
    # Skill moderation is not thread-scoped, so session_id stays None (matches
    # oneshot_llm's thread_id=None); the key must still be present for the handler.
    assert "langfuse_session_id" in metadata
    assert metadata["langfuse_session_id"] is None
    tags = metadata.get("langfuse_tags") or []
    assert "model:moderation-model" in tags
    assert "env:production" in tags


@pytest.mark.anyio
async def test_scan_skill_content_omits_langfuse_metadata_when_in_graph(monkeypatch):
    """In-graph scans pass attach_tracing=False and inherit attribution from the graph
    root, so the injection must be gated on attach_tracing. Anchors the narrowing
    direction: an unconditional inject (dropping the guard) would double-attribute
    against the root trace and turn this red, even though Langfuse is enabled.
    """
    from deerflow.config.tracing_config import reset_tracing_config

    _enable_langfuse_env(monkeypatch)
    reset_tracing_config()
    model = _make_traced_env(monkeypatch, model_name="moderation-model")
    try:
        result = await scan_skill_content(SKILL_CONTENT, executable=False, attach_tracing=False)
    finally:
        reset_tracing_config()

    assert result.decision == "allow"
    assert model.kwargs["config"] == {"run_name": "security_agent"}


def _make_unavailable_env(monkeypatch, *, security_fail_closed):
    config = SimpleNamespace(
        skill_evolution=SimpleNamespace(
            moderation_model_name=None,
            security_fail_closed=security_fail_closed,
        )
    )
    monkeypatch.setattr("deerflow.skills.security_scanner.get_app_config", lambda: config)
    monkeypatch.setattr(
        "deerflow.skills.security_scanner.create_chat_model",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )


@pytest.mark.anyio
async def test_fail_open_allows_non_executable_when_model_unavailable(monkeypatch):
    _make_unavailable_env(monkeypatch, security_fail_closed=False)
    result = await scan_skill_content(SKILL_CONTENT, executable=False)
    assert result.decision == "warn"
    assert "unavailable" in result.reason


@pytest.mark.anyio
async def test_fail_open_still_blocks_executable_when_model_unavailable(monkeypatch):
    _make_unavailable_env(monkeypatch, security_fail_closed=False)
    result = await scan_skill_content(SKILL_CONTENT, executable=True)
    assert result.decision == "block"
    assert "executable" in result.reason


@pytest.mark.anyio
async def test_fail_closed_blocks_non_executable_when_model_unavailable(monkeypatch):
    _make_unavailable_env(monkeypatch, security_fail_closed=True)
    result = await scan_skill_content(SKILL_CONTENT, executable=False)
    assert result.decision == "block"
    assert "unavailable" in result.reason


@pytest.mark.anyio
async def test_fail_open_logs_operator_visible_warning(monkeypatch, caplog):
    _make_unavailable_env(monkeypatch, security_fail_closed=False)
    with caplog.at_level(logging.WARNING, logger="deerflow.skills.security_scanner"):
        result = await scan_skill_content(SKILL_CONTENT, executable=False)
    assert result.decision == "warn"
    assert "failing open" in caplog.text
