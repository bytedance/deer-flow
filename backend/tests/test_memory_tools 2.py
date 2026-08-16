"""Tests for memory tool functions (tool-driven memory mode)."""

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
        mock_results = [
            {"id": "fact_abc123", "content": "User likes Python", "category": "preference", "confidence": 0.9, "createdAt": "2026-01-01T00:00:00Z"},
        ]

        def mock_search(query, category=None, limit=10, *, agent_name=None, user_id=None):
            return mock_results

        monkeypatch.setattr(
            "deerflow.agents.memory.tools.search_memory_facts",
            mock_search,
        )
        monkeypatch.setattr("deerflow.agents.memory.tools.resolve_runtime_user_id", lambda runtime: "test-user")

        result_json = memory_search_tool.func(SimpleNamespace(context={}), "Python")
        result = json.loads(result_json)
        assert result["count"] == 1
        assert len(result["results"]) == 1
        assert result["results"][0]["id"] == "fact_abc123"

    def test_empty_results(self, monkeypatch):
        """Should return empty results for no matches."""
        monkeypatch.setattr(
            "deerflow.agents.memory.tools.search_memory_facts",
            lambda *a, **kw: [],
        )
        monkeypatch.setattr("deerflow.agents.memory.tools.resolve_runtime_user_id", lambda runtime: "test-user")

        result_json = memory_search_tool.func(SimpleNamespace(context={}), "nothing")
        result = json.loads(result_json)
        assert result["count"] == 0
        assert result["results"] == []

    def test_runtime_error_returns_error_json(self, monkeypatch):
        """Should return error JSON when search raises RuntimeError."""
        monkeypatch.setattr(
            "deerflow.agents.memory.tools.search_memory_facts",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        monkeypatch.setattr("deerflow.agents.memory.tools.resolve_runtime_user_id", lambda runtime: "test-user")

        result_json = memory_search_tool.func(SimpleNamespace(context={}), "anything")
        result = json.loads(result_json)
        assert "error" in result
        assert result["error"] == "boom"


class TestMemoryAddTool:
    """Tests for memory_add tool handler."""

    def test_adds_fact_and_returns_json(self, monkeypatch):
        """Should add a fact and return fact_id + status."""
        created_fact = {"id": "fact_new123", "content": "User prefers dark mode"}

        def mock_create(content, category="context", confidence=0.5, agent_name=None, *, user_id=None):
            return {"facts": [created_fact]}, created_fact

        monkeypatch.setattr("deerflow.agents.memory.tools.create_memory_fact_with_created_fact", mock_create)
        monkeypatch.setattr("deerflow.agents.memory.tools.get_memory_data", lambda *a, **kw: {"facts": []})
        monkeypatch.setattr("deerflow.agents.memory.tools.resolve_runtime_user_id", lambda runtime: "test-user")

        result_json = memory_add_tool.func(SimpleNamespace(context={}), "User prefers dark mode", category="preference", confidence=0.9)
        result = json.loads(result_json)
        assert result["status"] == "added"
        assert result["fact_id"] == "fact_new123"

    def test_add_returns_created_fact_id_when_storage_reorders_facts(self, monkeypatch):
        """Should not infer the created fact from the final facts ordering."""
        created_fact = {"id": "fact_new123", "content": "User prefers dark mode"}

        def mock_create(content, category="context", confidence=0.5, agent_name=None, *, user_id=None):
            return {"facts": [created_fact, {"id": "fact_old999", "content": "Older fact"}]}, created_fact

        monkeypatch.setattr("deerflow.agents.memory.tools.create_memory_fact_with_created_fact", mock_create)
        monkeypatch.setattr("deerflow.agents.memory.tools.get_memory_data", lambda *a, **kw: {"facts": []})
        monkeypatch.setattr("deerflow.agents.memory.tools.resolve_runtime_user_id", lambda runtime: "test-user")

        result_json = memory_add_tool.func(SimpleNamespace(context={}), "User prefers dark mode")
        result = json.loads(result_json)
        assert result["fact_id"] == "fact_new123"

    def test_uses_runtime_user_id_when_directly_called(self, monkeypatch):
        """Should prefer runtime.context user_id over ContextVar fallback."""
        captured = {}

        def mock_create(content, category="context", confidence=0.5, agent_name=None, *, user_id=None):
            captured["agent_name"] = agent_name
            captured["user_id"] = user_id
            return {"facts": [{"id": "fact_new123", "content": content}]}, {"id": "fact_new123", "content": content}

        monkeypatch.setattr("deerflow.agents.memory.tools.create_memory_fact_with_created_fact", mock_create)
        monkeypatch.setattr("deerflow.agents.memory.tools.get_memory_data", lambda *a, **kw: {"facts": []})

        runtime = SimpleNamespace(context={"user_id": "runtime-user", "agent_name": "code-agent"})
        result_json = memory_add_tool.func(runtime, "User prefers dark mode")
        result = json.loads(result_json)

        assert result["status"] == "added"
        assert captured == {"agent_name": "code-agent", "user_id": "runtime-user"}

    def test_rejects_existing_duplicate_content(self, monkeypatch):
        """Should not persist a fact whose normalized content already exists."""
        create_called = False

        def mock_create(*a, **kw):
            nonlocal create_called
            create_called = True
            return {"facts": [{"id": "fact_new123"}]}, {"id": "fact_new123"}

        monkeypatch.setattr(
            "deerflow.agents.memory.tools.get_memory_data",
            lambda *a, **kw: {"facts": [{"id": "fact_existing", "content": "User prefers dark mode"}]},
        )
        monkeypatch.setattr("deerflow.agents.memory.tools.create_memory_fact_with_created_fact", mock_create)

        result_json = memory_add_tool.func(SimpleNamespace(context={}), "  User prefers dark mode  ")
        result = json.loads(result_json)

        assert "error" in result
        assert create_called is False

    def test_rejects_duplicate_content_outside_search_limit(self, monkeypatch):
        """Should full-scan exact duplicates before persisting a new fact."""
        facts = [
            {
                "id": f"fact_high_{idx}",
                "content": f"User prefers dark mode with variant {idx}",
                "category": "preference",
                "confidence": 1.0 - (idx * 0.01),
            }
            for idx in range(10)
        ]
        facts.append(
            {
                "id": "fact_exact",
                "content": "User prefers dark mode",
                "category": "preference",
                "confidence": 0.1,
            }
        )
        create_called = False

        def mock_get_memory_data(agent_name=None, *, user_id=None):
            return {"facts": facts}

        def mock_create(*a, **kw):
            nonlocal create_called
            create_called = True
            return {"facts": []}, {"id": "fact_new"}

        monkeypatch.setattr("deerflow.agents.memory.tools.get_memory_data", mock_get_memory_data)
        monkeypatch.setattr("deerflow.agents.memory.tools.create_memory_fact_with_created_fact", mock_create)
        monkeypatch.setattr("deerflow.agents.memory.tools.resolve_runtime_user_id", lambda runtime: "test-user")

        result_json = memory_add_tool.func(SimpleNamespace(context={}), "  User prefers dark mode  ")
        result = json.loads(result_json)

        assert result == {"error": "Duplicate fact"}
        assert create_called is False

    def test_duplicate_content_returns_error(self, monkeypatch):
        """Should return error JSON for duplicate content."""

        def mock_create(*a, **kw):
            raise ValueError("Duplicate fact")

        monkeypatch.setattr("deerflow.agents.memory.tools.create_memory_fact_with_created_fact", mock_create)
        monkeypatch.setattr("deerflow.agents.memory.tools.get_memory_data", lambda *a, **kw: {"facts": []})
        monkeypatch.setattr("deerflow.agents.memory.tools.resolve_runtime_user_id", lambda runtime: "test-user")

        result_json = memory_add_tool.func(SimpleNamespace(context={}), "duplicate")
        result = json.loads(result_json)
        assert "error" in result

    def test_empty_content_returns_error(self, monkeypatch):
        """Should return error JSON for empty content."""

        def mock_create(*a, **kw):
            raise ValueError("content")

        monkeypatch.setattr("deerflow.agents.memory.tools.create_memory_fact_with_created_fact", mock_create)
        monkeypatch.setattr("deerflow.agents.memory.tools.get_memory_data", lambda *a, **kw: {"facts": []})
        monkeypatch.setattr("deerflow.agents.memory.tools.resolve_runtime_user_id", lambda runtime: "test-user")

        result_json = memory_add_tool.func(SimpleNamespace(context={}), "")
        result = json.loads(result_json)
        assert "error" in result


class TestMemoryUpdateTool:
    """Tests for memory_update tool handler."""

    def test_updates_fact_and_returns_json(self, monkeypatch):
        """Should update a fact and return JSON."""
        mock_memory = {"facts": [{"id": "fact_abc", "content": "updated content"}]}

        def mock_update(fact_id, content=None, category=None, confidence=None, agent_name=None, *, user_id=None):
            return mock_memory

        monkeypatch.setattr("deerflow.agents.memory.tools.update_memory_fact", mock_update)
        monkeypatch.setattr("deerflow.agents.memory.tools.resolve_runtime_user_id", lambda runtime: "test-user")

        result_json = memory_update_tool.func(SimpleNamespace(context={}), "fact_abc", content="updated content")
        result = json.loads(result_json)
        assert result["status"] == "updated"
        assert result["fact_id"] == "fact_abc"

    def test_invalid_fact_id_returns_error(self, monkeypatch):
        """Should return error JSON for invalid fact_id."""

        def mock_update(*a, **kw):
            raise KeyError("fact_xxx")

        monkeypatch.setattr("deerflow.agents.memory.tools.update_memory_fact", mock_update)
        monkeypatch.setattr("deerflow.agents.memory.tools.resolve_runtime_user_id", lambda runtime: "test-user")

        result_json = memory_update_tool.func(SimpleNamespace(context={}), "fact_xxx", content="nope")
        result = json.loads(result_json)
        assert "error" in result
        assert "fact_xxx" in result["error"]


class TestMemoryDeleteTool:
    """Tests for memory_delete tool handler."""

    def test_deletes_fact_and_returns_json(self, monkeypatch):
        """Should delete a fact and return JSON."""
        mock_memory = {"facts": []}

        def mock_delete(fact_id, agent_name=None, *, user_id=None):
            return mock_memory

        monkeypatch.setattr("deerflow.agents.memory.tools.delete_memory_fact", mock_delete)
        monkeypatch.setattr("deerflow.agents.memory.tools.resolve_runtime_user_id", lambda runtime: "test-user")

        result_json = memory_delete_tool.func(SimpleNamespace(context={}), "fact_abc")
        result = json.loads(result_json)
        assert result["status"] == "deleted"
        assert result["fact_id"] == "fact_abc"

    def test_invalid_fact_id_returns_error(self, monkeypatch):
        """Should return error JSON for invalid fact_id."""

        def mock_delete(*a, **kw):
            raise KeyError("fact_xxx")

        monkeypatch.setattr("deerflow.agents.memory.tools.delete_memory_fact", mock_delete)
        monkeypatch.setattr("deerflow.agents.memory.tools.resolve_runtime_user_id", lambda runtime: "test-user")

        result_json = memory_delete_tool.func(SimpleNamespace(context={}), "fact_xxx")
        result = json.loads(result_json)
        assert "error" in result
        assert "fact_xxx" in result["error"]


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

        # Middleware is appended — it checks enabled internally in after_agent
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
        monkeypatch.setattr(lead_agent_module, "_load_enabled_skills_for_tool_policy", lambda available_skills, *, app_config, user_id=None: [])
        monkeypatch.setattr(lead_agent_module, "filter_tools_by_skill_allowed_tools", lambda tools, skills, always_allowed_tool_names=(): tools)
        monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [_NamedTool("memory_search"), _NamedTool("bash")])

        app_config = SimpleNamespace(
            get_model_config=lambda name: SimpleNamespace(supports_thinking=False, supports_vision=False),
            memory=MemoryConfig(enabled=True, mode="tool"),
            skills=SimpleNamespace(deferred_discovery=False, container_path="/tmp/skills"),
            tool_search=SimpleNamespace(enabled=False, auto_promote_top_k=0),
        )

        agent_kwargs = lead_agent_module._make_lead_agent({"configurable": {"agent_name": "test-agent"}}, app_config=app_config)
        tool_names = [tool.name for tool in agent_kwargs["tools"]]

        assert tool_names.count("memory_search") == 1
        assert "memory_add" in tool_names

    def test_lead_agent_preserves_non_memory_duplicate_tool_names(self, monkeypatch):
        """Memory-tool collision handling should not drop unrelated duplicate tools."""
        from deerflow.agents.lead_agent import agent as lead_agent_module
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
        monkeypatch.setattr(lead_agent_module, "_load_enabled_skills_for_tool_policy", lambda available_skills, *, app_config, user_id=None: [])
        monkeypatch.setattr(lead_agent_module, "filter_tools_by_skill_allowed_tools", lambda tools, skills, always_allowed_tool_names=(): tools)
        monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [_NamedTool("bash"), _NamedTool("bash")])

        app_config = SimpleNamespace(
            get_model_config=lambda name: SimpleNamespace(supports_thinking=False, supports_vision=False),
            memory=MemoryConfig(enabled=True, mode="tool"),
            skills=SimpleNamespace(deferred_discovery=False, container_path="/tmp/skills"),
            tool_search=SimpleNamespace(enabled=False, auto_promote_top_k=0),
        )

        agent_kwargs = lead_agent_module._make_lead_agent({"configurable": {"agent_name": "test-agent"}}, app_config=app_config)
        tool_names = [tool.name for tool in agent_kwargs["tools"]]

        assert tool_names.count("bash") == 2
        assert tool_names.count("memory_add") == 1
