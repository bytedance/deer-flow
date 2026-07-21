"""Phase-2 (self-contained DeerMem) tests.

Covers: DI construction (owns storage/updater/queue/llm), zero-config defaults,
``trace_id`` threading to the optional ``tracing_callback``, langfuse being
optional, ``hide_from_ui`` default-skip + hook-keep, empty ``storage_class``
(portable default), and portability -- ``backends/deermem/`` has exactly one
``from deerflow`` line (the ABC contract) and can be vendored into another agent
by copying the folder and repointing that one line.

Storage is isolated via ``$DEERMEM_DATA_DIR`` -> ``tmp_path``; the LLM is a fake
injected onto the updater so no network is needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.core.message_processing import (
    filter_messages_for_memory,
)
from deerflow.agents.memory.backends.deermem.deermem.core.storage import FileMemoryStorage
from deerflow.agents.memory.backends.deermem.deermem.core.updater import _trim_facts_to_max


@pytest.fixture
def deermem_data_dir(tmp_path, monkeypatch):
    """Isolate DeerMem storage under tmp_path via $DEERMEM_DATA_DIR."""
    d = tmp_path / "deermem_data"
    d.mkdir()
    monkeypatch.setenv("DEERMEM_DATA_DIR", str(d))
    yield d


class _FakeLLM:
    """Returns a fixed memory-update JSON so no real LLM/network is needed."""

    def __init__(self, payload: str | None = None) -> None:
        self._payload = payload or '{"user":{},"history":{},"newFacts":[],"factsToRemove":[]}'

    def invoke(self, prompt, config=None):
        return type("R", (), {"content": self._payload})()


def _deermem_with_fake_llm(backend_config=None, payload=None) -> DeerMem:
    dm = DeerMem(backend_config=backend_config)
    fake = _FakeLLM(payload)
    dm._llm = fake
    dm._updater._llm = fake
    return dm


def test_di_construction_owns_dependencies():
    dm = DeerMem(backend_config={"max_facts": 50, "storage_path": "/tmp/x"})
    assert dm._config.max_facts == 50
    assert dm._storage is not None and dm._updater is not None and dm._queue is not None
    # dependencies are wired (DI), not globals:
    assert dm._updater._storage is dm._storage
    assert dm._queue._updater is dm._updater


def test_zero_config_defaults_run_non_llm_ops(deermem_data_dir):
    dm = DeerMem(backend_config=None)  # zero config
    assert dm._llm is None  # no model -> no LLM
    dm.import_memory(
        {"version": "1.0", "lastUpdated": "", "user": {}, "history": {}, "facts": [{"id": "f", "content": "x", "category": "c", "confidence": 0.5, "createdAt": "", "source": "m"}]},
        user_id="u",
    )
    assert "x" in dm.get_context(user_id="u")
    assert dm.get_memory(user_id="u")["facts"][0]["content"] == "x"


def test_import_without_agent_name_persists_facts_in_default_markdown_bucket(deermem_data_dir):
    dm = DeerMem(backend_config=None)
    dm.import_memory(
        {
            "user": {},
            "history": {},
            "facts": [
                {
                    "id": "fact_default_import",
                    "content": "imported through the default manager scope",
                    "category": "context",
                    "confidence": 0.8,
                    "source": "import",
                }
            ],
        },
        user_id="alice",
    )

    assert [fact["id"] for fact in dm.get_memory(user_id="alice")["facts"]] == ["fact_default_import"]
    facts_root = deermem_data_dir / "users" / "alice" / "agents" / "__default__" / "facts"
    assert [path.stem for path in facts_root.glob("**/*.md")] == ["fact_default_import"]


def test_import_empty_summary_sections_replace_existing_summaries_with_complete_defaults(deermem_data_dir):
    dm = DeerMem(backend_config=None)
    existing = dm.get_memory(user_id="alice")
    existing["user"]["workContext"] = {"summary": "old work", "updatedAt": "old"}
    existing["user"]["personalContext"] = {"summary": "old personal", "updatedAt": "old"}
    existing["history"]["recentMonths"] = {"summary": "old history", "updatedAt": "old"}
    dm.import_memory(existing, user_id="alice")

    imported = dm.import_memory({"user": {}, "history": {}, "facts": []}, user_id="alice")

    assert imported["user"] == {
        "workContext": {"summary": "", "updatedAt": ""},
        "personalContext": {"summary": "", "updatedAt": ""},
        "topOfMind": {"summary": "", "updatedAt": ""},
    }
    assert imported["history"] == {
        "recentMonths": {"summary": "", "updatedAt": ""},
        "earlierContext": {"summary": "", "updatedAt": ""},
        "longTermBackground": {"summary": "", "updatedAt": ""},
    }


def test_trace_id_threads_through_to_tracing_callback(deermem_data_dir):
    calls = []

    def tracer(cfg, *, thread_id, user_id, trace_id, model_name):
        calls.append((thread_id, trace_id, model_name))

    dm = _deermem_with_fake_llm({"tracing_callback": tracer, "model": {"provider": "openai", "model": "gpt-x", "api_key": "k", "base_url": "u"}})
    dm.add(
        thread_id="t1",
        messages=[HumanMessage(content="hi"), AIMessage(content="hello")],
        agent_name=None,
        user_id="u1",
        trace_id="trace-42",
    )
    dm._queue.flush()
    assert calls and calls[0] == ("t1", "trace-42", "gpt-x")


def test_default_passive_update_persists_fact_in_reserved_default_bucket(deermem_data_dir):
    dm = _deermem_with_fake_llm(payload='{"user":{},"history":{},"newFacts":[{"content":"Default agent fact","category":"context","confidence":0.9}],"factsToRemove":[]}')

    dm.add(
        thread_id="default-thread",
        messages=[HumanMessage(content="remember this"), AIMessage(content="understood")],
        user_id="alice",
    )
    dm._queue.flush()

    assert [fact["content"] for fact in dm.get_memory(user_id="alice")["facts"]] == ["Default agent fact"]
    facts_root = deermem_data_dir / "users" / "alice" / "agents" / "__default__" / "facts"
    assert list(facts_root.glob("**/*.md"))


def test_clear_all_memory_removes_global_summaries_and_every_agent_fact(deermem_data_dir):
    dm = DeerMem()
    imported = dm.get_memory(user_id="alice")
    imported["user"]["workContext"] = {"summary": "shared profile", "updatedAt": "now"}
    imported["facts"] = [
        {
            "id": "fact_default",
            "content": "default fact",
            "category": "context",
            "confidence": 0.9,
            "createdAt": "2026-01-01T00:00:00Z",
            "source": "manual",
        }
    ]
    dm.import_memory(imported, user_id="alice")
    dm.create_fact("custom fact", agent_name="custom-agent", user_id="alice")
    custom_dir = deermem_data_dir / "users" / "alice" / "agents" / "custom-agent"
    config_path = custom_dir / "config.yaml"
    config_path.write_text("name: custom-agent\n", encoding="utf-8")

    cleared = dm.clear_memory(user_id="alice")

    assert cleared["user"]["workContext"]["summary"] == ""
    assert cleared["facts"] == []
    assert dm.get_memory(agent_name="custom-agent", user_id="alice")["facts"] == []
    assert config_path.read_text(encoding="utf-8") == "name: custom-agent\n"


def test_scoped_clear_preserves_shared_summaries(deermem_data_dir):
    dm = DeerMem()
    imported = dm.get_memory(user_id="alice")
    imported["user"]["workContext"] = {"summary": "shared profile", "updatedAt": "now"}
    dm.import_memory(imported, user_id="alice")
    dm.create_fact("custom fact", agent_name="custom-agent", user_id="alice")

    cleared = dm.clear_memory(agent_name="custom-agent", user_id="alice")

    assert cleared["facts"] == []
    assert cleared["user"]["workContext"]["summary"] == "shared profile"
    assert dm.get_memory(user_id="alice")["user"]["workContext"]["summary"] == "shared profile"


def test_tracing_callback_optional_no_langfuse(deermem_data_dir):
    dm = _deermem_with_fake_llm({"model": {"provider": "openai", "model": "gpt-x", "api_key": "k", "base_url": "u"}})
    assert dm._config.tracing_callback is None  # langfuse not hard-required
    dm.add(
        thread_id="t2",
        messages=[HumanMessage(content="hi"), AIMessage(content="hello")],
        agent_name=None,
        user_id="u2",
        trace_id="t-99",
    )
    dm._queue.flush()  # no callback, no error, update completes


def test_hide_from_ui_default_skip_hook_keeps():
    hidden = HumanMessage(content="secret", additional_kwargs={"hide_from_ui": True})
    normal = HumanMessage(content="hi")
    ai = AIMessage(content="hello")
    # default (no hook) -> hide_from_ui skipped
    assert hidden not in filter_messages_for_memory([hidden, normal, ai])
    # hook returns True -> hidden kept
    assert hidden in filter_messages_for_memory([hidden, normal, ai], should_keep_hidden_message=lambda ak: True)


def test_storage_class_empty_uses_filememorystorage():
    # empty storage_class (default) -> FileMemoryStorage directly, no importlib (portable, zero noise)
    dm = DeerMem(backend_config=None)
    assert dm._config.storage_class == ""
    assert isinstance(dm._storage, FileMemoryStorage)


def test_portability_only_abc_contract_imports_deerflow():
    """backends/deermem/ has exactly ONE `from deerflow` line: the ABC contract in deer_mem.py."""
    import deerflow.agents.memory.backends.deermem as pkg

    root = Path(pkg.__file__).parent
    deerflow_imports = []
    for p in root.rglob("*.py"):
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("from deerflow") or s.startswith("import deerflow"):
                deerflow_imports.append((p.relative_to(root).as_posix(), s))
    assert len(deerflow_imports) == 1, deerflow_imports
    assert deerflow_imports[0][0] == "deer_mem.py"
    assert "memory.manager import MemoryConflictError, MemoryCorruptionError, MemoryManager" in deerflow_imports[0][1]


# Minimal vendored host contract (what another agent would ship). DeerMem only
# needs this ABC -- nothing else from a host.
_VENDORED_MANAGER_PY = '''
"""Vendored host contract (minimal ABC) for the portability demo."""
from abc import ABC, abstractmethod
from typing import Any

class MemoryManager(ABC):
    def __init__(self, backend_config: dict | None = None) -> None:
        self._backend_config = backend_config
    @abstractmethod
    def add(self, thread_id, messages, *, agent_name=None, user_id=None, trace_id=None) -> None: ...
    @abstractmethod
    def add_nowait(self, thread_id, messages, *, agent_name=None, user_id=None) -> None: ...
    @abstractmethod
    def get_context(self, user_id, *, agent_name=None, thread_id=None) -> str: ...
    @abstractmethod
    def search(self, query, top_k=5, *, user_id=None, agent_name=None) -> list: ...
    @abstractmethod
    def get_memory(self, *, user_id=None, agent_name=None) -> dict: ...
    @abstractmethod
    def delete_memory(self, *, user_id=None, agent_name=None) -> None: ...
    @abstractmethod
    def clear_memory(self, *, user_id=None, agent_name=None) -> dict: ...
    @abstractmethod
    def import_memory(self, memory_data, *, user_id=None, agent_name=None) -> dict: ...
    @abstractmethod
    def export_memory(self, *, user_id=None, agent_name=None) -> dict: ...

class MemoryConflictError(RuntimeError): ...
class MemoryCorruptionError(RuntimeError): ...
'''


def test_portability_vendor_to_other_agent(tmp_path, monkeypatch):
    """Copy backends/deermem/ into a temp package, repoint the ONE ABC import to
    a vendored manager, import, and run a round-trip -- proves copy + 1-line +
    run portability (zero deerflow dependency at runtime)."""
    import importlib
    import shutil

    import deerflow.agents.memory.backends.deermem as pkg

    src = Path(pkg.__file__).parent
    # Vendored host package with a minimal manager.py (the contract).
    host_pkg = tmp_path / "otheragent"
    host_pkg.mkdir()
    (host_pkg / "__init__.py").write_text("", encoding="utf-8")
    (host_pkg / "manager.py").write_text(_VENDORED_MANAGER_PY, encoding="utf-8")
    # Copy the DeerMem backend folder.
    dst_pkg = tmp_path / "otheragent_deermem"
    shutil.copytree(src, dst_pkg)
    # Repoint the single ABC-contract import line to the vendored manager.
    deer_mem_file = dst_pkg / "deer_mem.py"
    text = deer_mem_file.read_text(encoding="utf-8")
    contract_import = "from deerflow.agents.memory.manager import MemoryConflictError, MemoryCorruptionError, MemoryManager"
    assert contract_import in text
    text = text.replace(
        contract_import,
        "from otheragent.manager import MemoryConflictError, MemoryCorruptionError, MemoryManager",
    )
    deer_mem_file.write_text(text, encoding="utf-8")

    monkeypatch.setenv("DEERMEM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        mod = importlib.import_module("otheragent_deermem.deer_mem")
        assert hasattr(mod, "DeerMem")
        dm = mod.DeerMem(backend_config=None)  # zero config, self._llm=None
        dm.import_memory(
            {"version": "1.0", "lastUpdated": "", "user": {}, "history": {}, "facts": [{"id": "f", "content": "y", "category": "c", "confidence": 0.5, "createdAt": "", "source": "m"}]},
            user_id="ua",
        )
        assert "y" in dm.get_context(user_id="ua")
    finally:
        for k in [k for k in list(sys.modules) if k.startswith("otheragent_deermem") or k == "otheragent"]:
            sys.modules.pop(k, None)


def test_per_user_memory_path_matches_host_safe_user_id(deermem_data_dir):
    """Pin the per-user memory path across the abstraction.

    DeerMem writes memory to ``{storage_path}/users/{safe_user_id}/memory.json``
    where ``safe_user_id`` is byte-identical to the host's ``make_safe_user_id``.
    The factory injects ``runtime_home()`` (= base_dir) as ``storage_path``, so
    the on-disk path is ``{base_dir}/users/{uid}/memory.json`` -- identical to
    pre-abstraction. This locks that equivalence so a future change to DeerMem's
    path / safe_user_id logic can't silently orphan existing per-user memory
    (risk:high, persistent state).
    """
    from deerflow.config.paths import make_safe_user_id

    user_id = "test-user-123@example.com"
    # storage_path mirrors what the host factory injects (runtime_home / base_dir)
    dm = DeerMem(backend_config={"storage_path": str(deermem_data_dir)})
    dm.create_fact("User prefers concise answers", category="preference", agent_name="default", user_id=user_id)

    expected_safe = make_safe_user_id(user_id)
    expected_file = deermem_data_dir / "users" / expected_safe / "memory.json"
    assert expected_file.is_file(), f"memory not at expected per-user path: {expected_file}"
    # DeerMem used the host-identical safe_user_id (not some other encoding).
    user_dirs = [p.name for p in (deermem_data_dir / "users").iterdir() if p.is_dir()]
    assert user_dirs == [expected_safe], f"safe_user_id diverged from host: {user_dirs}"


def test_trim_facts_to_max_coerces_non_float_confidence():
    """Non-float stored confidence must not crash the max_facts trim sort.

    Regression: the vendored copy used ``key=lambda f: f.get("confidence", 0)``
    which raised TypeError comparing None/str against float once ``len > max_facts``
    (legacy / imported facts with abnormal confidence). This is the #4034 intent
    that the module-skipped test files never exercised against the vendored
    updater; pinning it here so the rename can't silently drop the coercion again.
    """
    facts = [
        {"id": "a", "confidence": None},
        {"id": "b", "confidence": "0.9"},  # numeric string
        {"id": "c", "confidence": 0.8},
        {"id": "d", "confidence": "high"},  # non-numeric
    ]
    # No TypeError; coerced ranking: b("0.9"->0.9) > c(0.8) > a(None->0.5)=d("high"->0.5).
    kept = _trim_facts_to_max(facts, max_facts=2)
    assert [f["id"] for f in kept] == ["b", "c"]
    # Below the cap -> returned unchanged (no sort, no crash).
    assert _trim_facts_to_max(facts, max_facts=10) == facts


def test_create_fact_trims_to_max_and_signals_eviction(deermem_data_dir):
    """create_fact enforces max_facts and signals eviction via None fact_id.

    Regression: the vendored ``create_memory_fact`` only appended (no trim), so
    manual / tool adds could grow memory past max_facts. Now it trims (highest
    confidence wins) and returns ``None`` when the cap evicts the new fact, so
    the tool reports "not stored" instead of a dangling id + false "added".
    """
    # DeerMemConfig enforces max_facts >= 10, so fill the cap with 10 high-conf facts.
    dm = DeerMem(backend_config={"max_facts": 10, "storage_path": str(deermem_data_dir)})
    for i in range(10):
        _, fid = dm.create_fact(f"high{i}", category="context", confidence=0.9, user_id="u1")
        assert fid is not None

    # Cap is full (10 facts); a lower-confidence 11th is evicted, not stored.
    memory_data, evicted_id = dm.create_fact("low_evicted", category="context", confidence=0.1, user_id="u1")
    assert evicted_id is None
    assert "low_evicted" not in {f["content"] for f in memory_data["facts"]}
    assert len(memory_data["facts"]) == 10


def test_search_survives_non_float_confidence(deermem_data_dir):
    """DeerMem.search ranks by _coerce_source_confidence, so non-float stored
    confidence (null / string / non-numeric, reachable via import / legacy) must
    not crash the sort. Re-adds the regression guard deleted with the monolithic
    test_search_memory_facts_sort_survives_non_float_stored_confidence."""
    dm = DeerMem(backend_config={"storage_path": str(deermem_data_dir)})
    # create_fact validates confidence to float, so seed non-float via import
    # (simulating imported / legacy data that bypasses _validate_confidence).
    dm.import_memory(
        {
            "user": {},
            "history": {},
            "facts": [
                {"id": "a", "content": "alpha matching query", "confidence": None},
                {"id": "b", "content": "bravo matching query", "confidence": "0.9"},
                {"id": "c", "content": "charlie matching query", "confidence": "high"},
            ],
        },
        user_id="u1",
    )
    results = dm.search("query", top_k=10, user_id="u1")
    # No TypeError; all three match "query"; ranked by coerced confidence desc:
    # b("0.9"->0.9) > a(None->0.5)=c("high"->0.5), stable so a before c.
    assert [r["id"] for r in results] == ["b", "a", "c"]


def test_is_human_clarification_response_matches_host_read():
    """The standalone mirror must agree with the host's read_human_input_response
    so hidden-message filtering doesn't diverge between production (host hook) and
    standalone / test (mirror default). Pins drift (#5)."""

    from deerflow.agents.human_input import read_human_input_response
    from deerflow.agents.memory.backends.deermem.deermem.core.message_processing import _is_human_clarification_response

    def payload(**overrides):
        base = {"version": 1, "kind": "human_input_response", "source": "s", "request_id": "r", "value": "v", "response_kind": "text"}
        base.update(overrides)
        return {"human_input_response": base}

    cases = [
        {},
        {"human_input_response": {}},
        payload(),  # valid text response
        payload(response_kind="option", option_id="o1"),  # valid option response
        payload(response_kind="option"),  # option without option_id -> not valid
        payload(value=""),  # empty value -> not valid
        payload(source=""),  # empty source -> not valid
        payload(version=2),  # wrong version -> not valid
        payload(kind="other"),  # wrong kind -> not valid
        {"human_input_response": "not a mapping"},
        {"other_key": 1},  # no human_input_response key
    ]
    for ak in cases:
        host_keeps = read_human_input_response(ak) is not None
        mirror_keeps = _is_human_clarification_response(ak)
        assert host_keeps == mirror_keeps, f"divergence on {ak!r}: host={host_keeps} mirror={mirror_keeps}"


def test_build_llm_returns_none_when_no_model_configured():
    """Zero-config (no model_config, or model_config with no model) -> None.
    Non-LLM ops still work; an update raises at runtime."""
    from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemModelConfig
    from deerflow.agents.memory.backends.deermem.deermem.core.llm import build_llm

    assert build_llm(None) is None
    assert build_llm(DeerMemModelConfig()) is None  # model=None default


def test_build_llm_degrades_to_none_on_init_failure(caplog):
    """build_llm degrades to None (with a WARNING) when init_chat_model fails,
    mirroring _host_default_llm -- so a misconfigured explicit ``model`` does
    NOT crash app startup. Memory CRUD/read/search still work; extraction is
    disabled; an update raises at runtime with the underlying error logged."""
    from unittest.mock import patch

    from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemModelConfig
    from deerflow.agents.memory.backends.deermem.deermem.core.llm import build_llm

    model_config = DeerMemModelConfig(provider="openai", model="bogus-model", api_key="k")
    llm_logger = "deerflow.agents.memory.backends.deermem.deermem.core.llm"

    with patch("langchain.chat_models.init_chat_model", side_effect=RuntimeError("boom")):
        with caplog.at_level("WARNING", logger=llm_logger):
            result = build_llm(model_config)

    assert result is None
    assert any("build_llm failed" in r.message for r in caplog.records)


def test_from_backend_config_warns_on_unknown_keys(caplog):
    """Unknown backend_config keys log a WARNING so a typo (e.g. ``storage_pat``
    missing the ``h``) does not silently fall back to the default and write
    memory to an unintended location. Mirrors the host layer's
    load_memory_config_from_dict warning."""
    from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig

    cfg_logger = "deerflow.agents.memory.backends.deermem.deermem.config"
    with caplog.at_level("WARNING", logger=cfg_logger):
        cfg = DeerMemConfig.from_backend_config({"storage_path": "/tmp/x", "storage_pat": "/tmp/y"})

    # known key parsed; unknown key ignored but warned about
    assert cfg.storage_path == "/tmp/x"
    assert any("Unknown backend_config keys" in r.message for r in caplog.records)
    assert any("storage_pat" in r.message for r in caplog.records)


def test_from_backend_config_silent_on_known_keys(caplog):
    """No warning when every key is known (regression guard for the typo warning)."""
    from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig

    cfg_logger = "deerflow.agents.memory.backends.deermem.deermem.config"
    with caplog.at_level("WARNING", logger=cfg_logger):
        DeerMemConfig.from_backend_config({"storage_path": "/tmp/x", "max_facts": 20})
    assert not any("Unknown backend_config keys" in r.message for r in caplog.records)


def test_from_backend_config_null_values_fall_back_to_defaults():
    """Explicit YAML ``null`` values must behave like omitted keys, not crash.

    ``config.example.yaml`` ships ``backend_config.model:`` as a bare key with
    commented children, which YAML parses to ``None`` (and ``make
    config-upgrade`` writes it out as an explicit ``model: null``). Non-Optional
    fields like ``model: DeerMemModelConfig`` reject an explicit ``None`` even
    though the omitted key would use the field default — so the shipped example
    config crashed every run with a DeerMemConfig ValidationError."""
    from deerflow.agents.memory.backends.deermem.deermem.config import (
        DeerMemConfig,
        DeerMemModelConfig,
    )

    cfg = DeerMemConfig.from_backend_config({"model": None, "debounce_seconds": None, "storage_path": "/tmp/x"})

    # None entries fall back to field defaults; real values still parse
    assert isinstance(cfg.model, DeerMemModelConfig)
    assert cfg.model.model is None  # default = no extraction LLM configured
    assert cfg.debounce_seconds == DeerMemConfig().debounce_seconds
    assert cfg.storage_path == "/tmp/x"


def test_from_backend_config_null_values_do_not_warn_as_unknown(caplog):
    """Dropped ``None`` entries are known keys — they must not trip the
    unknown-key typo warning."""
    from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig

    cfg_logger = "deerflow.agents.memory.backends.deermem.deermem.config"
    with caplog.at_level("WARNING", logger=cfg_logger):
        DeerMemConfig.from_backend_config({"model": None})
    assert not any("Unknown backend_config keys" in r.message for r in caplog.records)
