"""Tests for memory tool functions (tool-driven memory mode).

The tools are backend-agnostic: they go through ``get_memory_manager()`` (the
MemoryManager ABC). These tests mock the manager to verify each tool calls the
right ABC method, returns the expected JSON, and handles errors / duplicates /
backends that lack fact-CRUD gracefully. Factory mode-gating (tool vs
middleware) is covered by ``TestModeGating`` at the bottom.
"""

import json
from types import SimpleNamespace

from deerflow.agents.memory.tools import (
    get_memory_tools,
    memory_add_tool,
    memory_delete_tool,
    memory_search_tool,
    memory_update_tool,
)


class _NamedTool:
    def __init__(self, name: str):
        self.name = name


class _MockManager:
    """Configurable MemoryManager stand-in for tool-handler tests."""

    def __init__(
        self,
        *,
        facts=None,
        search_results=None,
        created_fact=None,
        raise_on_create=None,
        raise_on_update=None,
        raise_on_delete=None,
        raise_on_search=None,
        supports_create=True,
        supports_update=True,
        supports_delete=True,
    ):
        self._facts = facts if facts is not None else []
        self._search_results = search_results if search_results is not None else []
        self._created_fact = created_fact or {"id": "fact_new", "content": ""}
        self._raise_on_create = raise_on_create
        self._raise_on_update = raise_on_update
        self._raise_on_delete = raise_on_delete
        self._raise_on_search = raise_on_search
        self._supports_create = supports_create
        self._supports_update = supports_update
        self._supports_delete = supports_delete
        self.calls = []

    def search(self, query, top_k=5, *, user_id=None, agent_name=None, category=None):
        self.calls.append(("search", query, top_k, user_id, agent_name, category))
        if self._raise_on_search:
            raise self._raise_on_search
        # Mirror the real backend: filter by category BEFORE returning, so the
        # tool's category kwarg is honoured server-side (not client-side).
        results = list(self._search_results)
        if category is not None:
            results = [f for f in results if f.get("category") == category]
        return results

    def get_memory(self, *, user_id=None, agent_name=None):
        self.calls.append(("get_memory", user_id, agent_name))
        return {"facts": list(self._facts)}

    def create_fact(self, content, category="context", confidence=0.5, *, agent_name=None, user_id=None):
        self.calls.append(("create_fact", content, category, confidence, agent_name, user_id))
        if self._raise_on_create:
            raise self._raise_on_create
        # Mirrors the real backend: returns (memory_data, fact_id) so the tool uses
        # the id directly instead of re-deriving it by content matching.
        created = dict(self._created_fact)
        created["content"] = content
        created["category"] = category
        created["confidence"] = confidence
        return {"facts": [created] + list(self._facts)}, created.get("id")

    def update_fact(self, fact_id, content=None, category=None, confidence=None, *, agent_name=None, user_id=None):
        self.calls.append(("update_fact", fact_id, content, category, confidence, agent_name, user_id))
        if self._raise_on_update:
            raise self._raise_on_update
        return {"facts": []}

    def delete_fact(self, fact_id, *, agent_name=None, user_id=None):
        self.calls.append(("delete_fact", fact_id, agent_name, user_id))
        if self._raise_on_delete:
            raise self._raise_on_delete
        return {"facts": []}

    # fact-CRUD ops are tier-3 hooks that raise NotImplementedError when
    # unsupported (the tool catches it -> JSON error). Simulate an unsupported
    # backend by replacing each op with a raiser (no more None/hasattr probing).
    def _drop_fact_ops(self):
        if not self._supports_create:
            self.create_fact = self._unsupported("create_fact")
        if not self._supports_update:
            self.update_fact = self._unsupported("update_fact")
        if not self._supports_delete:
            self.delete_fact = self._unsupported("delete_fact")

    @staticmethod
    def _unsupported(name):
        def _raise(*args, **kwargs):
            raise NotImplementedError(f"{name} not supported by _MockManager")

        return _raise


def _install_manager(monkeypatch, manager):
    manager._drop_fact_ops()
    monkeypatch.setattr("deerflow.agents.memory.tools.get_memory_manager", lambda: manager)
    monkeypatch.setattr("deerflow.agents.memory.tools.resolve_runtime_user_id", lambda runtime: "test-user")
    return manager


class TestGetMemoryTools:
    """Tests for get_memory_tools registry."""

    def test_returns_four_tools(self):
        """Should return exactly 4 tools."""
        tools = get_memory_tools()
        assert len(tools) == 4

    def test_tools_have_unique_names(self):
        """All tools should have unique names."""
        tools = get_memory_tools()
        names = [t.name for t in tools]
        assert len(names) == len(set(names))
        assert "memory_search" in names
        assert "memory_add" in names
        assert "memory_update" in names
        assert "memory_delete" in names


class TestMemorySearchTool:
    """Tests for memory_search tool handler."""

    def test_returns_json_with_results(self, monkeypatch):
        """Should return JSON with results and count."""
        results = [
            {"id": "fact_abc123", "content": "User likes Python", "category": "preference", "confidence": 0.9, "createdAt": "2026-01-01T00:00:00Z"},
        ]
        mgr = _install_manager(monkeypatch, _MockManager(search_results=results))

        result_json = memory_search_tool.func(SimpleNamespace(context={}), "Python")
        result = json.loads(result_json)
        assert result["count"] == 1
        assert result["results"][0]["id"] == "fact_abc123"
        # search forwards query + limit + scope to the manager.
        assert mgr.calls[0][0] == "search"
        assert mgr.calls[0][1] == "Python"
        assert mgr.calls[0][2] == 10  # limit -> top_k

    def test_empty_results(self, monkeypatch):
        """Should return empty results for no matches."""
        _install_manager(monkeypatch, _MockManager(search_results=[]))

        result_json = memory_search_tool.func(SimpleNamespace(context={}), "nothing")
        result = json.loads(result_json)
        assert result["count"] == 0
        assert result["results"] == []

    def test_category_filter_forwarded_to_backend(self, monkeypatch):
        """Category kwarg is forwarded to the backend, which filters before slicing."""
        results = [
            {"id": "f1", "content": "likes uv", "category": "preference", "confidence": 0.9},
            {"id": "f2", "content": "uses uv", "category": "context", "confidence": 0.5},
        ]
        mgr = _install_manager(monkeypatch, _MockManager(search_results=results))

        result_json = memory_search_tool.func(SimpleNamespace(context={}), "uv", category="preference", limit=10)
        result = json.loads(result_json)
        assert result["count"] == 1
        assert result["results"][0]["id"] == "f1"
        # category is forwarded to the backend search call (not filtered client-side)
        assert mgr.calls[0][0] == "search"
        assert mgr.calls[0][5] == "preference"  # category kwarg

    def test_runtime_error_returns_error_json(self, monkeypatch):
        """Should return error JSON when search raises."""
        _install_manager(monkeypatch, _MockManager(raise_on_search=RuntimeError("boom")))

        result_json = memory_search_tool.func(SimpleNamespace(context={}), "anything")
        result = json.loads(result_json)
        assert result["error"] == "boom"


class TestMemoryAddTool:
    """Tests for memory_add tool handler."""

    def test_adds_fact_and_returns_json(self, monkeypatch):
        """Should add a fact and return fact_id + status."""
        mgr = _install_manager(monkeypatch, _MockManager(facts=[], created_fact={"id": "fact_new123"}))

        result_json = memory_add_tool.func(SimpleNamespace(context={}), "User prefers dark mode", category="preference", confidence=0.9)
        result = json.loads(result_json)
        assert result["status"] == "added"
        assert result["fact_id"] == "fact_new123"
        # dup-checked via get_memory, then created via create_fact.
        assert ("get_memory", "test-user", None) in mgr.calls
        assert any(c[0] == "create_fact" and c[1] == "User prefers dark mode" for c in mgr.calls)

    def test_add_returns_fact_id_when_storage_reorders_facts(self, monkeypatch):
        """fact_id comes directly from create_fact, not derived from the returned list."""
        created = {"id": "fact_new123", "content": "User prefers dark mode"}
        older = {"id": "fact_old999", "content": "Older fact"}
        # Storage may reorder facts; create_fact returns the id directly so the
        # tool doesn't depend on list position or content matching.
        mgr = _MockManager(facts=[], created_fact=created)
        mgr.create_fact = lambda content, category="context", confidence=0.5, *, agent_name=None, user_id=None: ({"facts": [created, older]}, "fact_new123")
        _install_manager(monkeypatch, mgr)

        result_json = memory_add_tool.func(SimpleNamespace(context={}), "User prefers dark mode")
        result = json.loads(result_json)
        assert result["fact_id"] == "fact_new123"

    def test_add_reports_not_stored_when_cap_evicts_new_fact(self, monkeypatch):
        """When the cap evicts the new fact (create_fact returns None id), report
        'not stored' instead of a dangling id + false 'added'."""
        mgr = _MockManager(facts=[])
        recorded = []

        def fake_create(content, category="context", confidence=0.5, *, agent_name=None, user_id=None):
            recorded.append(content)
            return {"facts": []}, None

        mgr.create_fact = fake_create
        _install_manager(monkeypatch, mgr)

        result_json = memory_add_tool.func(SimpleNamespace(context={}), "low confidence fact", confidence=0.1)
        result = json.loads(result_json)
        assert result == {"error": "Fact was not stored because memory.max_facts kept higher-confidence facts"}
        assert recorded == ["low confidence fact"]

    def test_uses_runtime_scope(self, monkeypatch):
        """Should pass agent_name + user_id from runtime to the manager."""
        captured = {}
        mgr = _MockManager(facts=[], created_fact={"id": "fact_new", "content": "x"})
        orig_create = mgr.create_fact

        def spy(content, category="context", confidence=0.5, *, agent_name=None, user_id=None):
            captured["agent_name"] = agent_name
            captured["user_id"] = user_id
            return orig_create(content, category=category, confidence=confidence, agent_name=agent_name, user_id=user_id)

        mgr.create_fact = spy
        _install_manager(monkeypatch, mgr)

        runtime = SimpleNamespace(context={"agent_name": "code-agent"})
        # resolve_runtime_user_id is monkeypatched to "test-user" by _install_manager;
        # override here to assert the runtime channel flows through.
        import deerflow.agents.memory.tools as tools_mod

        tools_mod.resolve_runtime_user_id = lambda r: "runtime-user"

        result_json = memory_add_tool.func(runtime, "User prefers dark mode")
        result = json.loads(result_json)
        assert result["status"] == "added"
        assert captured == {"agent_name": "code-agent", "user_id": "runtime-user"}

    def test_rejects_existing_duplicate_content(self, monkeypatch):
        """Should not create a fact whose normalized content already exists."""
        existing = [{"id": "fact_existing", "content": "User prefers dark mode"}]
        mgr = _install_manager(monkeypatch, _MockManager(facts=existing))

        result_json = memory_add_tool.func(SimpleNamespace(context={}), "  User prefers dark mode  ")
        result = json.loads(result_json)
        assert result == {"error": "Duplicate fact"}
        assert not any(c[0] == "create_fact" for c in mgr.calls)

    def test_rejects_duplicate_content_outside_top_k(self, monkeypatch):
        """Dup check reads the full memory (get_memory), not a capped search."""
        facts = [{"id": f"fact_{i}", "content": f"variant {i}", "category": "preference", "confidence": 0.9} for i in range(12)]
        facts.append({"id": "fact_exact", "content": "User prefers dark mode", "category": "preference", "confidence": 0.1})
        mgr = _install_manager(monkeypatch, _MockManager(facts=facts))

        result_json = memory_add_tool.func(SimpleNamespace(context={}), "  User prefers dark mode  ")
        result = json.loads(result_json)
        assert result == {"error": "Duplicate fact"}
        assert not any(c[0] == "create_fact" for c in mgr.calls)

    def test_empty_content_returns_error(self, monkeypatch):
        """Should return error JSON for empty content without touching the manager."""
        mgr = _install_manager(monkeypatch, _MockManager())

        result_json = memory_add_tool.func(SimpleNamespace(context={}), "   ")
        result = json.loads(result_json)
        assert "error" in result
        assert not any(c[0] == "create_fact" for c in mgr.calls)

    def test_backend_without_create_fact_returns_error(self, monkeypatch):
        """A backend lacking create_fact (e.g. noop) gets a clear JSON error."""
        _install_manager(monkeypatch, _MockManager(facts=[], supports_create=False))

        result_json = memory_add_tool.func(SimpleNamespace(context={}), "something")
        result = json.loads(result_json)
        assert "error" in result
        assert "create_fact" in result["error"]


class TestMemoryUpdateTool:
    """Tests for memory_update tool handler."""

    def test_updates_fact_and_returns_json(self, monkeypatch):
        """Should update a fact and return JSON."""
        mgr = _install_manager(monkeypatch, _MockManager())

        result_json = memory_update_tool.func(SimpleNamespace(context={}), "fact_abc", content="updated content")
        result = json.loads(result_json)
        assert result["status"] == "updated"
        assert result["fact_id"] == "fact_abc"
        assert any(c[0] == "update_fact" and c[1] == "fact_abc" for c in mgr.calls)

    def test_invalid_fact_id_returns_error(self, monkeypatch):
        """Should return error JSON for invalid fact_id (KeyError)."""
        _install_manager(monkeypatch, _MockManager(raise_on_update=KeyError("fact_xxx")))

        result_json = memory_update_tool.func(SimpleNamespace(context={}), "fact_xxx", content="nope")
        result = json.loads(result_json)
        assert "error" in result
        assert "fact_xxx" in result["error"]

    def test_backend_without_update_fact_returns_error(self, monkeypatch):
        """A backend lacking update_fact gets a clear JSON error."""
        _install_manager(monkeypatch, _MockManager(supports_update=False))

        result_json = memory_update_tool.func(SimpleNamespace(context={}), "fact_abc", content="x")
        result = json.loads(result_json)
        assert "error" in result
        assert "update_fact" in result["error"]


class TestMemoryDeleteTool:
    """Tests for memory_delete tool handler."""

    def test_deletes_fact_and_returns_json(self, monkeypatch):
        """Should delete a fact and return JSON."""
        mgr = _install_manager(monkeypatch, _MockManager())

        result_json = memory_delete_tool.func(SimpleNamespace(context={}), "fact_abc")
        result = json.loads(result_json)
        assert result["status"] == "deleted"
        assert result["fact_id"] == "fact_abc"
        assert any(c[0] == "delete_fact" and c[1] == "fact_abc" for c in mgr.calls)

    def test_invalid_fact_id_returns_error(self, monkeypatch):
        """Should return error JSON for invalid fact_id (KeyError)."""
        _install_manager(monkeypatch, _MockManager(raise_on_delete=KeyError("fact_xxx")))

        result_json = memory_delete_tool.func(SimpleNamespace(context={}), "fact_xxx")
        result = json.loads(result_json)
        assert "error" in result
        assert "fact_xxx" in result["error"]

    def test_backend_without_delete_fact_returns_error(self, monkeypatch):
        """A backend lacking delete_fact gets a clear JSON error."""
        _install_manager(monkeypatch, _MockManager(supports_delete=False))

        result_json = memory_delete_tool.func(SimpleNamespace(context={}), "fact_abc")
        result = json.loads(result_json)
        assert "error" in result
        assert "delete_fact" in result["error"]


class TestModeGating:
    """Integration tests for memory.mode exclusivity."""

    def test_tool_mode_registers_tools_not_middleware(self, monkeypatch):
        """When mode=tool, get_memory_tools are added to extra_tools and
        MemoryMiddleware is NOT in the chain."""
        from deerflow.agents.factory import _assemble_from_features
        from deerflow.agents.features import RuntimeFeatures
        from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
        from deerflow.config.memory_config import MemoryConfig

        tool_config = MemoryConfig(enabled=True, mode="tool")
        monkeypatch.setattr(
            "deerflow.config.memory_config.get_memory_config",
            lambda: tool_config,
        )

        feat = RuntimeFeatures(memory=True)
        chain, extra_tools = _assemble_from_features(feat, name="test-agent")

        middleware_types = [type(m) for m in chain]
        assert MemoryMiddleware not in middleware_types, "MemoryMiddleware should not be in the chain in tool mode"

        tool_names = [t.name for t in extra_tools]
        assert "memory_search" in tool_names
        assert "memory_add" in tool_names
        assert "memory_update" in tool_names
        assert "memory_delete" in tool_names

    def test_explicit_memory_config_drives_factory_mode(self, monkeypatch):
        """Factory mode gating should use the explicit config before ambient globals."""
        from deerflow.agents.factory import _assemble_from_features
        from deerflow.agents.features import RuntimeFeatures
        from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
        from deerflow.config.memory_config import MemoryConfig

        monkeypatch.setattr(
            "deerflow.config.memory_config.get_memory_config",
            lambda: MemoryConfig(enabled=True, mode="middleware"),
        )

        feat = RuntimeFeatures(memory=True, memory_config=MemoryConfig(enabled=True, mode="tool"))
        chain, extra_tools = _assemble_from_features(feat, name="test-agent")

        middleware_types = [type(m) for m in chain]
        tool_names = [t.name for t in extra_tools]
        assert MemoryMiddleware not in middleware_types
        assert "memory_add" in tool_names

    def test_middleware_mode_appends_middleware_not_tools(self, monkeypatch):
        """When mode=middleware (default), MemoryMiddleware IS in the chain
        and memory tools are NOT in extra_tools."""
        from deerflow.agents.factory import _assemble_from_features
        from deerflow.agents.features import RuntimeFeatures
        from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
        from deerflow.config.memory_config import MemoryConfig

        mw_config = MemoryConfig(enabled=True, mode="middleware")
        monkeypatch.setattr(
            "deerflow.config.memory_config.get_memory_config",
            lambda: mw_config,
        )

        feat = RuntimeFeatures(memory=True)
        chain, extra_tools = _assemble_from_features(feat, name="test-agent")

        middleware_types = [type(m) for m in chain]
        assert MemoryMiddleware in middleware_types, "MemoryMiddleware should be in the chain in middleware mode"

        tool_names = [t.name for t in extra_tools]
        assert "memory_search" not in tool_names, "memory_search should not be registered in middleware mode"

    def test_memory_disabled_skips_both(self, monkeypatch):
        """When memory.enabled=False, middleware IS appended but no-ops at
        runtime (the enabled check is inside after_agent, not the factory).
        Tools are never registered because mode is middleware (default)."""
        from deerflow.agents.factory import _assemble_from_features
        from deerflow.agents.features import RuntimeFeatures
        from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
        from deerflow.config.memory_config import MemoryConfig

        disabled_config = MemoryConfig(enabled=False, mode="middleware")
        monkeypatch.setattr(
            "deerflow.config.memory_config.get_memory_config",
            lambda: disabled_config,
        )

        feat = RuntimeFeatures(memory=True)
        chain, extra_tools = _assemble_from_features(feat, name="test-agent")

        # Middleware is appended - it checks enabled internally in after_agent
        middleware_types = [type(m) for m in chain]
        assert MemoryMiddleware in middleware_types
        # Tools should NOT be registered in middleware mode regardless of enabled
        tool_names = [t.name for t in extra_tools]
        assert "memory_search" not in tool_names

    def test_should_use_memory_tools_requires_tool_mode_and_enabled(self):
        """Tool-mode helper should require both mode=tool and enabled=True."""
        from deerflow.config.memory_config import MemoryConfig, should_use_memory_tools

        assert should_use_memory_tools(MemoryConfig(enabled=True, mode="tool")) is True
        assert should_use_memory_tools(MemoryConfig(enabled=False, mode="tool")) is False
        assert should_use_memory_tools(MemoryConfig(enabled=True, mode="middleware")) is False

    def test_tool_mode_disabled_logs_warning_and_uses_middleware(self, monkeypatch, caplog):
        """mode=tool with enabled=False should be visible and still disable tools."""
        from deerflow.agents.factory import _assemble_from_features
        from deerflow.agents.features import RuntimeFeatures
        from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
        from deerflow.config.memory_config import MemoryConfig

        disabled_tool_config = MemoryConfig(enabled=False, mode="tool")
        monkeypatch.setattr(
            "deerflow.config.memory_config.get_memory_config",
            lambda: disabled_tool_config,
        )

        chain, extra_tools = _assemble_from_features(RuntimeFeatures(memory=True), name="test-agent")

        assert MemoryMiddleware in [type(m) for m in chain]
        assert "memory_add" not in [t.name for t in extra_tools]
        assert "memory.mode is 'tool' but memory.enabled is false" in caplog.text

    def test_lead_agent_deduplicates_memory_tools_after_appending(self, monkeypatch):
        """Configured tools should not duplicate tool-mode memory tools."""
        from deerflow.agents.lead_agent import agent as lead_agent_module
        from deerflow.config.authorization_config import AuthorizationConfig
        from deerflow.config.memory_config import MemoryConfig

        monkeypatch.setattr(lead_agent_module, "_resolve_model_name", lambda x=None, **kwargs: "default-model")
        monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: "model")
        monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda *args, **kwargs: [])
        monkeypatch.setattr(lead_agent_module, "apply_prompt_template", lambda **kwargs: "mock_prompt")
        monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)
        monkeypatch.setattr(lead_agent_module, "build_tracing_callbacks", lambda: [])
        monkeypatch.setattr(
            lead_agent_module,
            "load_agent_config",
            lambda name: SimpleNamespace(model=None, skills=None, tool_groups=None),
        )
        monkeypatch.setattr(lead_agent_module, "_load_enabled_available_skills", lambda available_skills, *, app_config, user_id=None: [])
        monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [_NamedTool("memory_search"), _NamedTool("bash")])

        app_config = SimpleNamespace(
            get_model_config=lambda name: SimpleNamespace(supports_thinking=False, supports_vision=False),
            memory=MemoryConfig(enabled=True, mode="tool"),
            skills=SimpleNamespace(deferred_discovery=False, container_path="/tmp/skills"),
            tool_search=SimpleNamespace(enabled=False, auto_promote_top_k=0),
            database=SimpleNamespace(checkpoint_channel_mode="full"),
            authorization=AuthorizationConfig(enabled=False),
        )

        agent_kwargs = lead_agent_module._make_lead_agent({"configurable": {"agent_name": "test-agent"}}, app_config=app_config)
        tool_names = [tool.name for tool in agent_kwargs["tools"]]

        assert tool_names.count("memory_search") == 1
        assert "memory_add" in tool_names

    def test_lead_agent_preserves_non_memory_duplicate_tool_names(self, monkeypatch):
        """Memory-tool collision handling should not drop unrelated duplicate tools."""
        from deerflow.agents.lead_agent import agent as lead_agent_module
        from deerflow.config.authorization_config import AuthorizationConfig
        from deerflow.config.memory_config import MemoryConfig

        monkeypatch.setattr(lead_agent_module, "_resolve_model_name", lambda x=None, **kwargs: "default-model")
        monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: "model")
        monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda *args, **kwargs: [])
        monkeypatch.setattr(lead_agent_module, "apply_prompt_template", lambda **kwargs: "mock_prompt")
        monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)
        monkeypatch.setattr(lead_agent_module, "build_tracing_callbacks", lambda: [])
        monkeypatch.setattr(
            lead_agent_module,
            "load_agent_config",
            lambda name: SimpleNamespace(model=None, skills=None, tool_groups=None),
        )
        monkeypatch.setattr(lead_agent_module, "_load_enabled_available_skills", lambda available_skills, *, app_config, user_id=None: [])
        monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [_NamedTool("bash"), _NamedTool("bash")])

        app_config = SimpleNamespace(
            get_model_config=lambda name: SimpleNamespace(supports_thinking=False, supports_vision=False),
            memory=MemoryConfig(enabled=True, mode="tool"),
            skills=SimpleNamespace(deferred_discovery=False, container_path="/tmp/skills"),
            tool_search=SimpleNamespace(enabled=False, auto_promote_top_k=0),
            database=SimpleNamespace(checkpoint_channel_mode="full"),
            authorization=AuthorizationConfig(enabled=False),
        )

        agent_kwargs = lead_agent_module._make_lead_agent({"configurable": {"agent_name": "test-agent"}}, app_config=app_config)
        tool_names = [tool.name for tool in agent_kwargs["tools"]]

        assert tool_names.count("bash") == 2
        assert tool_names.count("memory_add") == 1
