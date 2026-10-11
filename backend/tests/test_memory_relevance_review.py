"""Regression coverage for PR 5251's backend compatibility and IDF review."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from deerflow.agents.lead_agent.prompt import _get_memory_context
from deerflow.agents.memory import MemoryManager
from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.core.relevance import build_idf, lexical_relevance, tokenize


class _LegacyBackend(MemoryManager):
    @classmethod
    def from_config(cls, backend_config, *, mode="middleware", **host_hooks):
        return cls(backend_config=backend_config or {}, mode=mode)

    def add(self, thread_id, messages, *, agent_name=None, user_id=None, trace_id=None):
        pass

    def get_context(self, user_id, *, agent_name=None, thread_id=None):
        return f"memory:{user_id}:{agent_name}:{thread_id}"


@pytest.mark.parametrize("query", [None, "", "database migration"])
def test_old_backend_signature_keeps_prompt_memory(monkeypatch, query):
    manager = _LegacyBackend()
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)
    config = SimpleNamespace(memory=SimpleNamespace(enabled=True, injection_enabled=True, backend_config={}))
    context = _get_memory_context("agent-a", app_config=config, user_id="user-a", query=query)
    assert "<memory>" in context
    assert "memory:user-a:agent-a:None" in context


@pytest.mark.parametrize("query", [None, "", "database migration"])
def test_old_backend_signature_keeps_inherited_async_context(query):
    assert asyncio.run(_LegacyBackend().aget_context("user-a", agent_name="agent-a", thread_id="thread-a", query=query)) == "memory:user-a:agent-a:thread-a"


@pytest.mark.parametrize("accepts_kwargs", [False, True])
def test_query_capable_backend_receives_hint_in_prompt_and_async(monkeypatch, accepts_kwargs):
    calls = []

    def explicit(self, user_id, *, agent_name=None, thread_id=None, query=None):
        calls.append((user_id, agent_name, thread_id, query))
        return "query-aware memory"

    def variadic(self, user_id, *, agent_name=None, thread_id=None, **kwargs):
        return explicit(self, user_id, agent_name=agent_name, thread_id=thread_id, query=kwargs.get("query"))

    class QueryBackend(_LegacyBackend):
        get_context = variadic if accepts_kwargs else explicit

    manager = QueryBackend()
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)
    config = SimpleNamespace(memory=SimpleNamespace(enabled=True, injection_enabled=True))
    assert "query-aware memory" in _get_memory_context("a", app_config=config, user_id="u", query="migration")
    assert asyncio.run(manager.aget_context("u", agent_name="a", thread_id="t", query="migration")) == "query-aware memory"
    assert calls == [("u", "a", None, "migration"), ("u", "a", "t", "migration")]


def test_backend_typeerror_is_not_retried_as_legacy_signature(monkeypatch):
    calls = []

    class BrokenBackend(_LegacyBackend):
        def get_context(self, user_id, *, agent_name=None, thread_id=None, query=None):
            calls.append(query)
            raise TypeError("backend implementation failed")

    manager = BrokenBackend()
    with pytest.raises(TypeError, match="backend implementation failed"):
        asyncio.run(manager.aget_context("u", query="migration"))
    assert calls == ["migration"]
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)
    config = SimpleNamespace(memory=SimpleNamespace(enabled=True, injection_enabled=True))
    assert _get_memory_context(app_config=config, user_id="u", query="migration") == ""
    assert calls == ["migration", "migration"]


def test_uninspectable_legacy_callable_keeps_prompt_memory(monkeypatch):
    class LegacyCallable:
        __signature__ = object()

        def __call__(self, user_id, *, agent_name=None, thread_id=None):
            return "legacy callable memory"

    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: SimpleNamespace(get_context=LegacyCallable()))
    config = SimpleNamespace(memory=SimpleNamespace(enabled=True, injection_enabled=True))
    assert "legacy callable memory" in _get_memory_context(app_config=config, user_id="u", query="migration")


def _corpus():
    contents = ["Python coding conventions", "Python database migration uses Alembic"] + [f"Unrelated cooking recipe {index}" for index in range(8)]
    return [{"id": f"fact_{index}", "content": content, "confidence": 0.7, "category": "context", "createdAt": "2026-01-01T00:00:00Z"} for index, content in enumerate(contents)]


def test_complete_query_coverage_outranks_partial_match_with_corpus_idf():
    facts = _corpus()
    idf = build_idf([tokenize(fact["content"]) for fact in facts])
    partial = lexical_relevance("python database migration", facts[0]["content"], idf=idf)
    complete = lexical_relevance("python database migration", facts[1]["content"], idf=idf)
    assert 0 < partial < complete <= 1


@pytest.mark.parametrize("partial_first", [False, True])
def test_search_top_one_prefers_complete_match_independent_of_input_order(partial_first):
    facts = _corpus()
    if not partial_first:
        facts[0], facts[1] = facts[1], facts[0]
    manager = DeerMem(backend_config={"retrieval_relevance_enabled": True, "retrieval_relevance_weight": 1.0})
    manager._updater = SimpleNamespace(get_memory_data=lambda agent_name=None, *, user_id=None: {"facts": facts})
    result = manager.search("python database migration", top_k=1)
    assert result[0]["content"] == "Python database migration uses Alembic"


@pytest.mark.parametrize(
    "query,partial,complete",
    [
        ("python database migration", "python " * 30, "migration database python additional detail"),
        ("python python database migration", "Python coding conventions", "migration database python"),
        ("python database migration", "python", "migration database python"),
        ("python databases migrations", "python database " * 20, "python database migration"),
    ],
)
def test_partial_matches_cannot_saturate_from_repetition_or_containment(query, partial, complete):
    idf = build_idf([tokenize(text) for text in [partial, complete, "unrelated"]])
    assert lexical_relevance(query, partial, idf=idf) < lexical_relevance(query, complete, idf=idf)


def test_rare_query_terms_keep_more_weight_than_common_terms():
    idf = build_idf([tokenize(text) for text in ["python database migration", "python coding", "python testing", "python packaging"]])
    assert lexical_relevance("python database migration", "database", idf=idf) > lexical_relevance("python database migration", "python", idf=idf)


@pytest.mark.parametrize("query,content", [("PostgreSQL", "Postman collections"), ("authorization", "authentication settings"), ("database", "dataframe columns")])
def test_shared_four_character_prefix_is_not_a_lexical_match(query, content):
    assert lexical_relevance(query, content) == 0.0


@pytest.mark.parametrize("query,content", [("database", "databases"), ("databases", "database"), ("migration", "migrations"), ("migrations", "migration")])
def test_complete_token_prefixes_still_match(query, content):
    assert lexical_relevance(query, content) == 1.0


@pytest.mark.parametrize("unrelated_first", [False, True])
def test_search_prefers_exact_token_over_shared_prefix(unrelated_first):
    facts = [
        {"id": "unrelated", "content": "Postman collections", "confidence": 0.7, "category": "context"},
        {"id": "exact", "content": "PostgreSQL database", "confidence": 0.7, "category": "context"},
    ]
    if not unrelated_first:
        facts.reverse()
    manager = DeerMem(backend_config={"retrieval_relevance_enabled": True, "retrieval_relevance_weight": 1.0})
    manager._updater = SimpleNamespace(get_memory_data=lambda agent_name=None, *, user_id=None: {"facts": facts})
    assert manager.search("PostgreSQL", top_k=1)[0]["id"] == "exact"


def test_absent_query_keeps_forwarding_wrapper_legacy_contract(monkeypatch):
    calls = []
    inner = _LegacyBackend()

    class ForwardingBackend(_LegacyBackend):
        def get_context(self, user_id, **kwargs):
            calls.append(kwargs.copy())
            return inner.get_context(user_id, **kwargs)

    manager = ForwardingBackend()
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)
    config = SimpleNamespace(memory=SimpleNamespace(enabled=True, injection_enabled=True))
    assert "memory:u:a:None" in _get_memory_context("a", app_config=config, user_id="u")
    assert asyncio.run(manager.aget_context("u", agent_name="a", thread_id="t")) == "memory:u:a:t"
    assert calls == [{"agent_name": "a"}, {"agent_name": "a", "thread_id": "t"}]


def _idf_scope(common):
    contents = ["python conventions", "migration conventions"] + [f"{common} background {index}" for index in range(8)]
    return {"facts": [{"id": f"fact_{index}", "content": content, "category": "preference" if index < 2 else "context", "confidence": 0.7} for index, content in enumerate(contents)]}


@pytest.mark.parametrize("guaranteed", [[], ["preference"]])
@pytest.mark.parametrize("reverse", [False, True])
def test_search_and_injection_share_scope_idf_without_cross_scope_leakage(guaranteed, reverse):
    scopes = {("u1", "a"): _idf_scope("python"), ("u2", "a"): _idf_scope("migration"), ("u1", "b"): _idf_scope("migration")}
    if reverse:
        for data in scopes.values():
            data["facts"].reverse()
    original = deepcopy(scopes)
    manager = DeerMem(backend_config={"retrieval_relevance_enabled": True, "retrieval_relevance_weight": 1.0, "token_counting": "char", "guaranteed_categories": guaranteed})
    manager._updater = SimpleNamespace(get_memory_data=lambda agent_name=None, *, user_id=None: scopes[(user_id, agent_name)])
    # Return to the first scope to detect accidental reuse of another user's IDF.
    for user, agent in [("u1", "a"), ("u2", "a"), ("u1", "b"), ("u1", "a")]:
        search = manager.search("python migration", top_k=10, user_id=user, agent_name=agent)
        context = manager.get_context(user, agent_name=agent, query="python migration")
        expected, other = ("migration conventions", "python conventions") if (user, agent) == ("u1", "a") else ("python conventions", "migration conventions")
        assert search[0]["content"] == expected
        assert context.index(expected) < context.index(other)
    assert scopes == original


@pytest.mark.parametrize("enabled,query,weight", [(False, "python migration", 1.0), (True, None, 1.0), (True, "", 1.0), (True, "  ", 1.0), (True, "python migration", 0.0)])
def test_inactive_relevance_does_not_build_injection_idf(monkeypatch, enabled, query, weight):
    def unexpected_idf(corpus):
        pytest.fail("IDF must not be built when lexical relevance is unused")

    monkeypatch.setattr("deerflow.agents.memory.backends.deermem.deer_mem.build_idf", unexpected_idf)
    manager = DeerMem(backend_config={"retrieval_relevance_enabled": enabled, "retrieval_relevance_weight": weight, "token_counting": "char"})
    manager._updater = SimpleNamespace(get_memory_data=lambda agent_name=None, *, user_id=None: _idf_scope("python"))
    assert manager.get_context("u", agent_name="a", query=query) == manager.get_context("u", agent_name="a")


def test_large_scope_idf_is_bounded_and_keeps_rare_fact_within_budget(monkeypatch):
    from deerflow.agents.memory.backends.deermem.deermem.core.prompt import _count_tokens

    corpora = []

    def observed_idf(corpus):
        corpora.append((len(corpus), max(map(len, corpus))))
        return build_idf(corpus)

    monkeypatch.setattr("deerflow.agents.memory.backends.deermem.deer_mem.build_idf", observed_idf)
    facts = [{"id": f"fact_{i}", "content": "python background " * 1000, "category": "context", "confidence": 0.7} for i in range(499)]
    facts.append({"id": "fact_rare", "content": "migration conventions", "category": "context", "confidence": 0.7})
    manager = DeerMem(backend_config={"retrieval_relevance_enabled": True, "retrieval_relevance_weight": 1.0, "token_counting": "char", "max_injection_tokens": 100, "guaranteed_categories": []})
    manager._updater = SimpleNamespace(get_memory_data=lambda agent_name=None, *, user_id=None: {"facts": facts})
    context = manager.get_context("u", agent_name="a", query="python migration")
    assert "migration conventions" in context
    assert _count_tokens(context, use_tiktoken=False) <= 100
    assert corpora == [(500, 128)]
