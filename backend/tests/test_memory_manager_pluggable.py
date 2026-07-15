"""Pluggable memory manager: the factory resolves the configured backend.

Covers the drop-in contract end-to-end:
- short name -> registered backend (deermem / noop);
- dotted path (``module.Attr`` and ``module:Attr``) -> the same class;
- unknown value -> raise (fail-fast: a wrong store is a silent data-integrity footgun).

Also pins the noop empty-memory behaviour and the ``hasattr`` capability
probing surface (reload_memory + fact CRUD) that the gateway/client rely on.

Each test resets the singleton + backend cache and sets the config, so they
are independent of order.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deerflow.agents.memory import (
    MemoryManager,
    get_memory_manager,
    reset_memory_manager,
)
from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.noop.noop_manager import NoopMemoryManager
from deerflow.config.memory_config import MemoryConfig, get_memory_config, set_memory_config


@pytest.fixture(autouse=True)
def _isolate_memory_manager():
    """Reset the singleton + restore config around every test."""
    orig = get_memory_config()
    reset_memory_manager()
    yield
    set_memory_config(orig)
    reset_memory_manager()


@pytest.mark.parametrize(
    "manager_class, expected",
    [
        ("deermem", DeerMem),
        ("noop", NoopMemoryManager),
        ("deerflow.agents.memory.backends.deermem.deer_mem.DeerMem", DeerMem),
        ("deerflow.agents.memory.backends.deermem.deer_mem:DeerMem", DeerMem),
        ("deerflow.agents.memory.backends.noop.noop_manager.NoopMemoryManager", NoopMemoryManager),
        ("deerflow.agents.memory.backends.noop.noop_manager:NoopMemoryManager", NoopMemoryManager),
    ],
)
def test_resolves_configured_backend(manager_class: str, expected: type[MemoryManager]) -> None:
    set_memory_config(MemoryConfig(manager_class=manager_class))
    manager = get_memory_manager()
    assert isinstance(manager, expected)
    # singleton: a second call returns the same instance
    assert get_memory_manager() is manager


def test_unknown_backend_raises_instead_of_falling_back() -> None:
    """An unknown manager_class is a config error: raise, don't silently fall
    back to DeerMem (memory is persistent state -- a wrong store is a silent
    data-integrity footgun)."""
    set_memory_config(MemoryConfig(manager_class="bogus-backend"))
    with pytest.raises(ValueError, match="bogus-backend"):
        get_memory_manager()


def test_noop_runs_with_empty_memory() -> None:
    set_memory_config(MemoryConfig(manager_class="noop"))
    manager = get_memory_manager()
    assert manager.get_context(user_id="u") == ""
    assert manager.search("anything") == []
    assert manager.get_memory(user_id="u") == {"facts": []}
    # writes are no-ops; memory stays empty
    manager.add("t", [], agent_name=None, user_id="u")
    manager.add_nowait("t", [], agent_name=None, user_id="u")
    assert manager.get_memory(user_id="u") == {"facts": []}


def test_internal_capabilities_are_hasattr_probeable() -> None:
    """reload_memory + fact CRUD + warm exist on DeerMem but not on noop (the ABC omits them)."""
    set_memory_config(MemoryConfig(manager_class="deermem"))
    deermem = get_memory_manager()
    for cap in ("warm", "reload_memory", "create_fact", "delete_fact", "update_fact"):
        assert hasattr(deermem, cap), cap

    reset_memory_manager()
    set_memory_config(MemoryConfig(manager_class="noop"))
    noop = get_memory_manager()
    for cap in ("warm", "reload_memory", "create_fact", "delete_fact", "update_fact"):
        assert not hasattr(noop, cap), cap


def test_deermem_search_works_delete_export_are_stubs() -> None:
    set_memory_config(MemoryConfig(manager_class="deermem"))
    deermem = get_memory_manager()
    # search is implemented (substring match) -- returns a list, does not raise.
    assert isinstance(deermem.search("q", user_id="u"), list)
    # delete_memory / export_memory remain unimplemented stubs this phase.
    with pytest.raises(NotImplementedError):
        deermem.delete_memory(user_id="u")
    with pytest.raises(NotImplementedError):
        deermem.export_memory(user_id="u")


def test_factory_raises_when_storage_path_is_existing_file(tmp_path) -> None:
    """A storage_path that resolves to an existing FILE is a config error: DeerMem
    treats storage_path as a root directory, so a file would make save's mkdir
    raise NotADirectoryError (silent write failure). Fail loud at startup (#1)."""
    file_path = tmp_path / "mem.json"
    file_path.write_text("{}", encoding="utf-8")
    set_memory_config(MemoryConfig(manager_class="deermem", backend_config={"storage_path": str(file_path)}))
    with pytest.raises(ValueError, match="existing file"):
        get_memory_manager()


def test_migration_drops_file_style_legacy_storage_path(caplog) -> None:
    """A legacy top-level storage_path that looks like a file (ends in .json) is
    dropped, not carried verbatim -- DeerMem now treats storage_path as a root
    directory, so carrying 'memory.json' would orphan per-user memory / hit
    NotADirectoryError. Dropping lets the factory inject runtime_home (per-user
    location unchanged). Non-file legacy fields still migrate; empty values are
    skipped silently (#1, #6)."""
    from deerflow.config.memory_config import load_memory_config_from_dict

    with caplog.at_level("WARNING", logger="deerflow.config.memory_config"):
        load_memory_config_from_dict({"storage_path": "memory.json", "max_facts": 50})
    cfg = get_memory_config()
    assert "storage_path" not in cfg.backend_config  # file-style dropped
    assert cfg.backend_config.get("max_facts") == 50  # non-file legacy still migrates
    assert any("looks like a file path" in r.message for r in caplog.records)


def test_empty_storage_path_factory_injects_runtime_home(tmp_path, monkeypatch) -> None:
    """Empty/absent storage_path -> factory injects runtime_home() as the root, so
    per-user memory lands at {runtime_home}/users/{uid}/memory.json (matches
    pre-abstraction per-user location). Pins the zero-config default (reviewer #1)."""
    import deerflow.config.runtime_paths as rp

    monkeypatch.setattr(rp, "runtime_home", lambda: tmp_path)
    set_memory_config(MemoryConfig(manager_class="deermem"))  # no storage_path
    manager = get_memory_manager()
    assert Path(manager._config.storage_path) == tmp_path
    manager.create_fact("hello", user_id="u1")
    # per-user dir created under the injected runtime_home root
    user_dirs = [p.name for p in (tmp_path / "users").iterdir() if p.is_dir()]
    assert len(user_dirs) == 1
