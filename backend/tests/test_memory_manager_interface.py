"""Conformance tests for the MemoryManager interface contract.

Pins the three-tier ABC + from_config + invariant validator + async a* +
callbacks surface so the contract stays stable as backends are added. The
centerpiece is ``_MinimalBackend`` (implements ONLY from_config + add +
get_context) -- it instantiates via the factory and runs with everything else
inherited, proving a new backend needs nothing else. That is the direct
evidence the optimization lowered onboarding cost (no full method surface, no
factory edit).

Each test resets the singleton + restores config so they are order-independent.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import PrivateAttr

from deerflow.agents.memory import MemoryManager, get_memory_manager, reset_memory_manager
from deerflow.agents.memory.manager import MemoryCallbacks
from deerflow.config.memory_config import MemoryConfig, get_memory_config, set_memory_config


class _MinimalBackend(MemoryManager):
    """Implements ONLY tier-1 (add/get_context) + from_config.

    Everything else inherits base defaults -- the minimal onboarding surface a
    new memory system needs. (No search, no management ops, no fact CRUD, no
    cache reload; ``supports_search`` stays False, so it cannot run in tool mode.)
    """

    _adds: list = PrivateAttr(default_factory=list)

    def add(self, thread_id, messages, *, agent_name=None, user_id=None, trace_id=None) -> None:
        self._adds.append((thread_id, user_id))

    def get_context(self, user_id, *, agent_name=None, thread_id=None) -> str:
        return f"ctx:{user_id}"

    @classmethod
    def from_config(cls, backend_config, *, mode="middleware", **host_hooks):
        # Consumes nothing from host_hooks -- a truly minimal backend.
        return cls(backend_config=backend_config or {}, mode=mode)


@pytest.fixture(autouse=True)
def _isolate_memory_manager():
    orig = get_memory_config()
    reset_memory_manager()
    yield
    set_memory_config(orig)
    reset_memory_manager()


def test_minimal_backend_onboards_via_factory_with_only_add_get_context():
    """Centerpiece: a backend implementing ONLY from_config + add + get_context
    instantiates via the factory and runs -- all else inherits defaults. Direct
    evidence that onboarding cost dropped (no full method surface, no factory
    edit)."""
    set_memory_config(MemoryConfig(manager_class=f"{__name__}:_MinimalBackend"))
    manager = get_memory_manager()
    assert isinstance(manager, _MinimalBackend)

    # tier-1 works
    manager.add("t1", [], user_id="u1")
    assert manager._adds == [("t1", "u1")]
    assert manager.get_context("u1") == "ctx:u1"

    # tier-2 inherits defaults: add_nowait delegates to add; shutdown_flush=True;
    # the rest raise NotImplementedError.
    manager.add_nowait("t1", [], user_id="u1")
    assert manager._adds[-1] == ("t1", "u1")
    assert manager.shutdown_flush(1.0) is True
    with pytest.raises(NotImplementedError):
        manager.search("q")
    with pytest.raises(NotImplementedError):
        manager.get_memory(user_id="u")
    with pytest.raises(NotImplementedError):
        manager.clear_memory(user_id="u")
    with pytest.raises(NotImplementedError):
        manager.import_memory({}, user_id="u")
    with pytest.raises(NotImplementedError):
        manager.export_memory(user_id="u")
    with pytest.raises(NotImplementedError):
        manager.delete_memory(user_id="u")

    # tier-3 inherits defaults: warm=None (nothing to warm); B-class no-op;
    # A-class (excl. warm) raise.
    assert manager.warm() is None
    assert manager.on_pre_compress([]) == ""
    assert manager.on_turn_start(1, None) is None
    with pytest.raises(NotImplementedError):
        manager.reload_memory(user_id="u")
    with pytest.raises(NotImplementedError):
        manager.create_fact("x", user_id="u")
    with pytest.raises(NotImplementedError):
        manager.delete_fact("x", user_id="u")
    with pytest.raises(NotImplementedError):
        manager.update_fact("x", user_id="u")


def test_tier1_abstract_enforcement():
    """A backend missing add or get_context cannot instantiate (TypeError at
    construction -- memory is persistent state, missing write/read is a severe
    bug caught eagerly)."""

    class _NoAdd(MemoryManager):
        def get_context(self, user_id, *, agent_name=None, thread_id=None) -> str:
            return ""

    class _NoGet(MemoryManager):
        def add(self, thread_id, messages, *, agent_name=None, user_id=None, trace_id=None) -> None:
            pass

    with pytest.raises(TypeError):
        _NoAdd()
    with pytest.raises(TypeError):
        _NoGet()


def test_invariant_tool_mode_requires_search():
    """mode='tool' + a non-search backend raises at instantiation (the agent
    calls memory_search in tool mode, so a non-search backend is a
    misconfiguration -- fail fast). Middleware mode is fine for any backend."""
    with pytest.raises(ValueError):
        _MinimalBackend(backend_config={}, mode="tool")
    assert _MinimalBackend(backend_config={}, mode="middleware").mode == "middleware"


def test_invariant_tool_mode_factory_path_raises():
    """The invariant also fires on the factory path (mode='tool' + non-search
    backend configured via manager_class)."""
    set_memory_config(MemoryConfig(manager_class=f"{__name__}:_MinimalBackend", mode="tool"))
    with pytest.raises(ValueError):
        get_memory_manager()


class _SearchOverrideForgotFlag(_MinimalBackend):
    """Overrides search() but forgets supports_search=True (flag/impl drift)."""

    def search(self, query, top_k=5, *, user_id=None, agent_name=None, category=None):
        return []


class _FlagWithoutSearchOverride(_MinimalBackend):
    """Sets supports_search=True without overriding search() (flag/impl drift)."""

    supports_search = True


class _ConsistentSearchBackend(_MinimalBackend):
    """Overrides search() AND sets supports_search=True -- consistent, tool-OK."""

    supports_search = True

    def search(self, query, top_k=5, *, user_id=None, agent_name=None, category=None):
        return []


def test_invariant_supports_search_flag_must_match_override():
    """supports_search (ClassVar) must match whether search() is overridden, so
    the flag can't drift from the implementation -- caught at instantiation, not
    as a misleading tool-mode rejection (override-but-forgot-flag) or a runtime
    NotImplementedError on the first memory_search call (flag-without-override)."""
    with pytest.raises(ValueError, match="inconsistent"):
        _SearchOverrideForgotFlag(backend_config={})
    with pytest.raises(ValueError, match="inconsistent"):
        _FlagWithoutSearchOverride(backend_config={})


def test_invariant_consistent_search_backend_runs_in_tool_mode():
    """A backend that overrides search() AND sets supports_search=True is
    consistent and may run in tool mode (the override is the real capability;
    the flag agrees with it)."""
    manager = _ConsistentSearchBackend(backend_config={}, mode="tool")
    assert manager.mode == "tool"
    assert manager.search("q") == []


def test_async_defaults_delegate_to_sync():
    """a* methods default to the sync path (no concurrency benefit); a future
    async LLM client overrides without changing the contract."""
    manager = _MinimalBackend(backend_config={})
    asyncio.run(manager.aadd("t", [], user_id="u"))
    assert manager._adds == [("t", "u")]
    assert asyncio.run(manager.aget_context("u")) == "ctx:u"
    # asearch delegates to search -> raises (default) just like search.
    with pytest.raises(NotImplementedError):
        asyncio.run(manager.asearch("q"))


def test_callbacks_field_optional_and_noop_default():
    """callbacks is an optional field (default None); the base
    MemoryCallbacks.on_memory_llm_call is a no-op, so a backend with no
    callbacks runs without tracing."""
    assert _MinimalBackend(backend_config={}).callbacks is None
    noop = MemoryCallbacks()
    # no-op: mutates nothing, raises nothing
    noop.on_memory_llm_call({}, thread_id="t", user_id="u", trace_id="tr", model_name="m")
    manager = _MinimalBackend(backend_config={}, callbacks=noop)
    assert manager.callbacks is noop


def test_from_config_consumes_host_hooks_it_needs():
    """A backend's from_config consumes the host_hooks it needs; the minimal
    backend consumes none (ignores callbacks / host_llm_factory / etc.). A real
    backend (DeerMem) consumes the ones it uses -- see test_deermem_self_contained."""
    manager = _MinimalBackend.from_config(
        {"some_key": "v"},
        mode="middleware",
        callbacks=MemoryCallbacks(),
        host_llm_factory=lambda: None,
        should_keep_hidden_message=lambda ak: True,
    )
    assert isinstance(manager, _MinimalBackend)
    assert manager.backend_config == {"some_key": "v"}
    assert manager.mode == "middleware"
    # The minimal backend consumes NO host_hooks (callbacks / host_llm_factory /
    # should_keep_hidden_message are all ignored) -- callbacks stays None.
    assert manager.callbacks is None


def test_unsupported_op_raises_for_caller_try_except():
    """Callers (router/client/tools) call tier-3 ops directly and catch
    NotImplementedError (no more hasattr probing). A minimal backend's
    unsupported ops raise, so a caller's try/except degrades cleanly (501 /
    fallback / JSON error)."""
    manager = _MinimalBackend(backend_config={})
    try:
        manager.create_fact("x", user_id="u")
        raise AssertionError("create_fact should have raised NotImplementedError")
    except NotImplementedError:
        pass  # caller returns 501 / JSON error / falls back


def test_only_add_and_get_context_are_abstract():
    """The tier-1 abstract set is exactly {add, get_context} (plus from_config);
    tier-2/3 methods carry defaults so a backend implements only what it supports."""
    assert "add" in MemoryManager.__abstractmethods__
    assert "get_context" in MemoryManager.__abstractmethods__
    assert "from_config" in MemoryManager.__abstractmethods__
    # tier-2/3 are NOT abstract (they have defaults)
    for non_abstract in ("search", "get_memory", "shutdown_flush", "warm", "create_fact", "on_pre_compress"):
        assert non_abstract not in MemoryManager.__abstractmethods__, non_abstract
