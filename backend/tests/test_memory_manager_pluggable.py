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
from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest
from pydantic import PrivateAttr

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


def test_tier3_hooks_have_defaults_noop_inherits() -> None:
    """warm/reload/fact CRUD are tier-3 hooks ON the ABC with defaults (no more
    ``hasattr`` probing): noop inherits ``warm``=None (nothing to warm) and
    fact-CRUD/reload raise ``NotImplementedError``. DeerMem overrides the ones
    it supports (covered elsewhere)."""
    set_memory_config(MemoryConfig(manager_class="noop"))
    noop = get_memory_manager()
    assert noop.warm() is None  # inherited default (nothing to warm)
    with pytest.raises(NotImplementedError):
        noop.reload_memory(user_id="u")
    with pytest.raises(NotImplementedError):
        noop.create_fact("x", user_id="u")
    with pytest.raises(NotImplementedError):
        noop.delete_fact("x", user_id="u")
    with pytest.raises(NotImplementedError):
        noop.update_fact("x", user_id="u")
    reset_memory_manager()


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
    manager.create_fact("hello", user_id="u1", agent_name="test-agent")
    # per-user dir created under the injected runtime_home root
    user_dirs = [p.name for p in (tmp_path / "users").iterdir() if p.is_dir()]
    assert len(user_dirs) == 1


def test_shutdown_flush_has_default_and_noop_is_noop_success() -> None:
    """``shutdown_flush`` is a tier-2 method with a default (True -- backends
    without a buffer have nothing to drain), NOT abstract; noop inherits/overrides
    to True. Only ``add`` / ``get_context`` are tier-1 abstract."""
    assert "add" in MemoryManager.__abstractmethods__
    assert "get_context" in MemoryManager.__abstractmethods__
    assert "shutdown_flush" not in MemoryManager.__abstractmethods__
    reset_memory_manager()
    set_memory_config(MemoryConfig(manager_class="noop"))
    noop = get_memory_manager()
    assert noop.shutdown_flush(1.0) is True
    reset_memory_manager()


def test_deermem_shutdown_flush_delegates_to_queue_flush_sync() -> None:
    """DeerMem.shutdown_flush delegates to its queue's bounded flush_sync,
    forwarding the host-owned timeout budget unchanged."""
    reset_memory_manager()
    set_memory_config(MemoryConfig(manager_class="deermem"))
    deermem = get_memory_manager()
    with patch.object(deermem._queue, "flush_sync", return_value=True) as spy:
        assert deermem.shutdown_flush(7.0) is True
        spy.assert_called_once_with(7.0)
    reset_memory_manager()


def test_deermem_shutdown_flush_drains_a_pending_update() -> None:
    """End-to-end: a pending update sitting in DeerMem's queue is drained
    within the timeout on shutdown_flush (the loss-on-exit bug the ABC method
    fixes). The drain skips inter-item sleep so the budget goes to LLM calls."""
    from deerflow.agents.memory.backends.deermem.deermem.core.queue import ConversationContext

    reset_memory_manager()
    set_memory_config(MemoryConfig(manager_class="deermem"))
    deermem = get_memory_manager()
    # Inject a mock updater so no real LLM call is made; both items "succeed".
    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True
    deermem._queue._updater = mock_updater
    deermem._queue._items = [ConversationContext(thread_id=f"t{i}", messages=["m"], agent_name="lead_agent") for i in range(3)]
    assert deermem.shutdown_flush(5.0) is True
    assert deermem._queue.pending_count == 0
    assert mock_updater.update_memory.call_count == 3
    reset_memory_manager()


# ── Host model hot-reload ────────────────────────────────────────────────────
# The manager singleton is built once. A deployment can start before any model
# is configured (fresh install, model added later from Settings) or with a model
# entry that does not build (missing provider package, typo in `use`) and must
# not need a Gateway restart before memory extraction works: the host LLM is
# re-armed while the backend has none, mirroring the existing judge refresh.


class _HostLlmRecordingBackend(MemoryManager):
    """Minimal backend that records ``refresh_llm`` calls.

    ``host_model_present`` stands in for the backend's own state: ``False`` means
    it still has no extraction model (a fresh install, or an entry that failed to
    build) and therefore wants the host fallback.
    """

    host_model_present: ClassVar[bool] = False
    _refreshed: list = PrivateAttr(default_factory=list)

    def needs_host_model(self) -> bool:
        return not self.host_model_present

    def add(self, thread_id, messages, *, agent_name=None, user_id=None, trace_id=None) -> None:
        return None

    def get_context(self, user_id, *, agent_name=None, thread_id=None, query=None) -> str:
        return ""

    def refresh_llm(self, llm) -> None:
        self._refreshed.append(llm)

    @classmethod
    def from_config(cls, backend_config, *, mode="middleware", **host_hooks):
        return cls(backend_config=backend_config or {}, mode=mode)


def _model_signature(*names: str) -> tuple[str, ...]:
    """A signature of the same shape ``_model_set_signature()`` produces.

    One digest per model entry, as the real function returns, so a test can move
    the model set without writing a managed catalog.
    """
    return tuple(f"digest-{name}" for name in names)


_SNAPSHOT = object()
"""Stand-in for the merged ``AppConfig`` a patched read hands back."""


def _patch_model_set(monkeypatch, signature: tuple[str, ...] | None) -> None:
    """Make the refresh see ``signature`` as the merged model set.

    Stubs ``_read_model_set`` -- the *single* read the refresh performs -- rather
    than the digest, so the snapshot that is digested and the one handed to the
    build stay the same object. ``None`` means the catalog cannot be read.
    """
    from deerflow.agents.memory import manager as manager_module

    read = None if signature is None else (_SNAPSHOT, signature)
    monkeypatch.setattr(manager_module, "_read_model_set", lambda: read)


def test_manager_rearms_host_llm_when_the_model_set_appears(monkeypatch) -> None:
    """A model configured after startup must reach memory extraction without a
    restart: the next manager lookup rebuilds the host LLM and injects it."""
    from deerflow.agents.memory import manager as manager_module

    set_memory_config(MemoryConfig(manager_class=f"{__name__}:_HostLlmRecordingBackend"))
    _patch_model_set(monkeypatch, ())
    manager = get_memory_manager()
    assert manager._refreshed == []

    host_llm = object()
    monkeypatch.setattr(manager_module, "_build_host_llm", lambda app_config=None: host_llm)
    _patch_model_set(monkeypatch, _model_signature("deepseek-chat"))

    assert get_memory_manager() is manager
    assert manager._refreshed == [host_llm]


def test_manager_keeps_host_llm_when_the_model_set_is_unchanged(monkeypatch) -> None:
    """While the deployment still has no model, repeated lookups must not rebuild
    (or re-inject) the host LLM: the refresh is signature-gated, not
    unconditional, so an idle no-model deployment does not spin on the factory."""
    from deerflow.agents.memory import manager as manager_module

    set_memory_config(MemoryConfig(manager_class=f"{__name__}:_HostLlmRecordingBackend"))
    builds: list[int] = []
    monkeypatch.setattr(manager_module, "_build_host_llm", lambda app_config=None: builds.append(1) or object())
    _patch_model_set(monkeypatch, ())
    manager = get_memory_manager()

    assert get_memory_manager() is manager
    assert get_memory_manager() is manager
    assert manager._refreshed == []
    assert builds == []


def test_manager_does_not_rearm_a_manager_that_started_with_a_model(monkeypatch) -> None:
    """An armed manager keeps its client: a signature comparison on every call
    would put a merged-config read on the hot path, and a key rotation stays
    restart-only (an accepted, documented limit)."""
    from deerflow.agents.memory import manager as manager_module

    set_memory_config(MemoryConfig(manager_class=f"{__name__}:_HostLlmRecordingBackend"))
    monkeypatch.setattr(_HostLlmRecordingBackend, "host_model_present", True)
    builds: list[int] = []
    monkeypatch.setattr(manager_module, "_build_host_llm", lambda app_config=None: builds.append(1) or object())
    _patch_model_set(monkeypatch, _model_signature("deepseek-chat"))
    manager = get_memory_manager()
    assert manager._refreshed == []

    _patch_model_set(monkeypatch, _model_signature("deepseek-chat", "second"))

    assert get_memory_manager() is manager
    assert manager._refreshed == []
    assert builds == []


def test_manager_retries_after_a_failed_host_model_build(monkeypatch) -> None:
    """A model entry that cannot build a client must not close the self-heal path.

    The failure is not recorded as the armed signature (that would gate the
    refresh off for the process lifetime), the retry is rate-limited so a
    permanently broken entry cannot rebuild on every memory call, and repairing
    the entry re-arms on a later lookup instead of requiring a restart.
    """
    from deerflow.agents.memory import manager as manager_module

    set_memory_config(MemoryConfig(manager_class=f"{__name__}:_HostLlmRecordingBackend"))
    _patch_model_set(monkeypatch, ())
    manager = get_memory_manager()

    signature = _model_signature("deepseek-chat")
    _patch_model_set(monkeypatch, signature)

    def _broken(app_config=None):
        raise RuntimeError("provider package is not installed")

    monkeypatch.setattr(manager_module, "_build_host_llm", _broken)

    assert get_memory_manager() is manager
    assert manager._refreshed == []
    assert manager_module._memory_model_armed_signature is None
    failure = manager_module._memory_model_failure
    assert failure is not None
    assert failure[0] == signature
    assert failure[1] > 0

    # Still inside the retry window for this same model set: no rebuild, no
    # second traceback.
    host_llm = object()
    monkeypatch.setattr(manager_module, "_build_host_llm", lambda app_config=None: host_llm)
    assert get_memory_manager() is manager
    assert manager._refreshed == []

    # Once the window elapses the repaired entry is picked up without a restart.
    manager_module._memory_model_failure = (signature, 0.0)
    assert get_memory_manager() is manager
    assert manager._refreshed == [host_llm]


def test_manager_survives_an_unreadable_model_set(monkeypatch) -> None:
    """Signature computation runs on the memory call path: when the merged config
    cannot be read the refresh must degrade, never raise out of
    ``get_memory_manager()`` (the invariant the judge signature already holds)."""
    from deerflow.agents.memory import manager as manager_module

    set_memory_config(MemoryConfig(manager_class=f"{__name__}:_HostLlmRecordingBackend"))
    _patch_model_set(monkeypatch, None)
    manager = get_memory_manager()

    assert get_memory_manager() is manager
    assert manager._refreshed == []
    failure = manager_module._memory_model_failure
    assert failure is not None and failure[0] is manager_module._UNREADABLE


def test_deermem_refresh_llm_reaches_the_update_queue(tmp_path, monkeypatch) -> None:
    """The backend holds the LLM in two places: the manager-facing attribute and
    the queued updater that actually calls it. A refresh must reach both, or the
    first extraction after a model change still raises "no LLM is configured"."""
    import deerflow.config.runtime_paths as runtime_paths
    from deerflow.agents.memory import manager as manager_module

    monkeypatch.setattr(runtime_paths, "runtime_home", lambda: tmp_path)
    monkeypatch.setattr(manager_module, "_host_default_llm", lambda: None)
    set_memory_config(MemoryConfig(manager_class="deermem"))
    manager = get_memory_manager()
    assert manager._llm is None
    assert manager._updater._llm is None

    host_llm = object()
    manager.refresh_llm(host_llm)

    assert manager._llm is host_llm
    assert manager._updater._llm is host_llm


def test_deermem_refresh_llm_ignores_none(tmp_path, monkeypatch) -> None:
    """``None`` must never replace a working client: unlike the judge, where it
    legitimately means "both sides off", a missing extraction model would turn a
    failed rebuild into silently disabled memory."""
    import deerflow.config.runtime_paths as runtime_paths
    from deerflow.agents.memory import manager as manager_module

    monkeypatch.setattr(runtime_paths, "runtime_home", lambda: tmp_path)
    monkeypatch.setattr(manager_module, "_host_default_llm", lambda: None)
    set_memory_config(MemoryConfig(manager_class="deermem"))
    manager = get_memory_manager()

    host_llm = object()
    manager.refresh_llm(host_llm)
    manager.refresh_llm(None)

    assert manager._llm is host_llm
    assert manager._updater._llm is host_llm


def test_deermem_refresh_llm_keeps_an_explicitly_configured_model(tmp_path, monkeypatch) -> None:
    """``memory.backend_config.model`` wins over the host default: the operator's
    choice must not be replaced by the zero-config fallback on a reload."""
    from types import SimpleNamespace

    import deerflow.config.runtime_paths as runtime_paths
    from deerflow.agents.memory import manager as manager_module

    monkeypatch.setattr(runtime_paths, "runtime_home", lambda: tmp_path)
    monkeypatch.setattr(manager_module, "_host_default_llm", lambda: None)
    set_memory_config(MemoryConfig(manager_class="deermem"))
    manager = get_memory_manager()

    first = object()
    manager.refresh_llm(first)
    assert manager._llm is first

    manager._config.model = SimpleNamespace(model="gpt-4o")
    manager.refresh_llm(object())

    assert manager._llm is first
    assert manager._updater._llm is first


def test_model_set_signature_tracks_names_and_credentials(monkeypatch) -> None:
    """The signature must move when models are added or their connection details
    change, and stay put otherwise -- it is the only trigger for the refresh."""
    from types import SimpleNamespace

    from deerflow.agents.memory import manager as manager_module
    from deerflow.config.model_config import ModelConfig

    def _model(name: str, key: str, *, base_url: str | None = None) -> ModelConfig:
        settings = {"base_url": base_url} if base_url else {}
        return ModelConfig(name=name, use="langchain_openai:ChatOpenAI", model="m", api_key=key, **settings)

    def _config(*models):
        return SimpleNamespace(models=list(models))

    monkeypatch.setattr("deerflow.config.get_app_config", lambda: _config())
    empty = manager_module._read_model_set()[1]
    assert empty == ()

    monkeypatch.setattr("deerflow.config.get_app_config", lambda: _config(_model("deepseek-chat", "sk-one")))
    configured = manager_module._read_model_set()[1]
    assert configured != empty
    assert len(configured) == 1

    monkeypatch.setattr("deerflow.config.get_app_config", lambda: _config(_model("deepseek-chat", "sk-two")))
    rotated = manager_module._read_model_set()[1]
    assert rotated != configured
    assert "sk-one" not in "".join(rotated), "the raw credential must never enter the signature"

    monkeypatch.setattr("deerflow.config.get_app_config", lambda: _config(_model("other-model", "sk-two")))
    assert manager_module._read_model_set()[1] != rotated


def test_model_set_signature_tracks_an_endpoint_edit(monkeypatch) -> None:
    """``base_url`` is the endpoint key the factory actually forwards for the
    documented OpenAI-compatible providers, while ``api_base`` is canonical only
    for classes that declare it. An endpoint edit must invalidate the signature,
    or an in-flight build installs the retired endpoint and closes the gate."""
    from types import SimpleNamespace

    from deerflow.agents.memory import manager as manager_module
    from deerflow.config.model_config import ModelConfig

    def _signature(base_url: str) -> tuple[str, ...] | None:
        model = ModelConfig(name="a", use="langchain_openai:ChatOpenAI", model="m", base_url=base_url, api_key="sk")
        monkeypatch.setattr("deerflow.config.get_app_config", lambda: SimpleNamespace(models=[model]))
        return manager_module._read_model_set()[1]

    first = _signature("https://one.example/v1")
    assert first
    assert _signature("https://two.example/v1") != first
    assert _signature("https://one.example/v1") == first


def test_the_model_set_read_is_none_when_the_config_cannot_be_read(monkeypatch) -> None:
    """``get_app_config`` can raise (a managed catalog that cannot be decrypted).
    The read is a best-effort cache key, so it degrades to ``None`` instead of
    taking memory down with it."""
    from deerflow.agents.memory import manager as manager_module

    def _unreadable():
        raise ValueError("cannot decrypt the managed model catalog")

    monkeypatch.setattr("deerflow.config.get_app_config", _unreadable)

    assert manager_module._read_model_set() is None


def test_manager_does_not_arm_on_a_build_that_yields_no_client(monkeypatch) -> None:
    """A builder that resolves to ``None`` is a failed build: arming on it would
    record a signature with no client behind it and close the retry path."""
    from deerflow.agents.memory import manager as manager_module

    set_memory_config(MemoryConfig(manager_class=f"{__name__}:_HostLlmRecordingBackend"))
    _patch_model_set(monkeypatch, ())
    manager = get_memory_manager()

    _patch_model_set(monkeypatch, _model_signature("deepseek-chat"))
    monkeypatch.setattr(manager_module, "_build_host_llm", lambda app_config=None: None)

    assert get_memory_manager() is manager
    assert manager._refreshed == []
    assert manager_module._memory_model_armed_signature is None


def test_manager_rearms_when_startup_had_a_model_that_could_not_build(monkeypatch) -> None:
    """A deployment that starts with a model entry that does not build is the
    other half of the same bug: the config lists a model, the backend still has
    no client. The gate asks the backend, not the config, so the repair is
    picked up without a restart."""
    from deerflow.agents.memory import manager as manager_module

    set_memory_config(MemoryConfig(manager_class=f"{__name__}:_HostLlmRecordingBackend"))
    _patch_model_set(monkeypatch, _model_signature("broken-entry"))
    monkeypatch.setattr(manager_module, "_build_host_llm", lambda app_config=None: None)

    manager = get_memory_manager()
    # The model set is non-empty, but nothing is armed: the gate must stay open.
    assert manager_module._memory_model_armed_signature is None
    assert manager._refreshed == []

    # The operator fixes the entry (a typo in `use`, a missing package); the next
    # lookup arms the client.
    host_llm = object()
    monkeypatch.setattr(manager_module, "_build_host_llm", lambda app_config=None: host_llm)
    _patch_model_set(monkeypatch, _model_signature("repaired-entry"))

    assert get_memory_manager() is manager
    assert manager._refreshed == [host_llm]


def test_a_changed_model_set_retries_inside_the_failure_window(monkeypatch) -> None:
    """The retry limit is per model set, not global: a different set is a new
    failure surface and must be tried at once instead of waiting out the window
    opened by an earlier, unrelated failure."""
    from deerflow.agents.memory import manager as manager_module

    set_memory_config(MemoryConfig(manager_class=f"{__name__}:_HostLlmRecordingBackend"))
    first = _model_signature("first-entry")
    _patch_model_set(monkeypatch, first)
    monkeypatch.setattr(manager_module, "_build_host_llm", lambda app_config=None: None)

    manager = get_memory_manager()
    # The first lookup after the build is what attempts the re-arm.
    assert get_memory_manager() is manager
    assert manager._refreshed == []
    assert manager_module._memory_model_failure[0] == first

    # Same set while the window is open: skipped.
    assert get_memory_manager() is manager
    assert manager._refreshed == []

    # A different set does not inherit the window.
    host_llm = object()
    monkeypatch.setattr(manager_module, "_build_host_llm", lambda app_config=None: host_llm)
    _patch_model_set(monkeypatch, _model_signature("second-entry"))

    assert get_memory_manager() is manager
    assert manager._refreshed == [host_llm]
    assert manager_module._memory_model_failure is None


def test_a_stale_build_does_not_land_after_a_config_change(monkeypatch) -> None:
    """A client built from a model set that has since changed must be dropped, not
    installed: the operator may have rolled the edit back while it was building."""
    import threading

    from deerflow.agents.memory import manager as manager_module

    set_memory_config(MemoryConfig(manager_class=f"{__name__}:_HostLlmRecordingBackend"))
    _patch_model_set(monkeypatch, _model_signature("first"))
    manager = get_memory_manager()

    building = threading.Event()
    release = threading.Event()

    def _slow_build(app_config=None):
        building.set()
        assert release.wait(5), "the test never released the builder"
        return object()

    monkeypatch.setattr(manager_module, "_build_host_llm", _slow_build)
    results: list = []
    worker = threading.Thread(target=lambda: results.append(get_memory_manager()))
    worker.start()
    try:
        assert building.wait(5), "the builder never started"
        # The config moves on while the client is being built.
        _patch_model_set(monkeypatch, _model_signature("second"))
    finally:
        release.set()
        worker.join(10)

    assert results == [manager]
    assert manager._refreshed == []
    assert manager_module._memory_model_armed_signature is None


def test_a_later_lookup_cannot_reopen_the_one_time_rearm(monkeypatch) -> None:
    """An A -> B -> A catalog sequence must not let a build started under A
    replace the client a later lookup already installed under B: the first
    installed extraction model stays until the manager is reset.
    """
    import threading

    from deerflow.agents.memory import manager as manager_module

    set_memory_config(MemoryConfig(manager_class=f"{__name__}:_HostLlmRecordingBackend"))
    signature_a = _model_signature("catalog-a")
    signature_b = _model_signature("catalog-b")
    _patch_model_set(monkeypatch, signature_a)
    manager = get_memory_manager()

    # Make the recording backend track its own state the way DeerMem does:
    # once a client is installed it no longer needs the host fallback.
    monkeypatch.setattr(type(manager), "needs_host_model", lambda self: not self._refreshed)

    building = threading.Event()
    release = threading.Event()

    def _slow_build(app_config=None):
        building.set()
        assert release.wait(5), "the test never released the builder"
        return object()

    monkeypatch.setattr(manager_module, "_build_host_llm", _slow_build)
    results: list = []
    worker = threading.Thread(target=lambda: results.append(get_memory_manager()))
    worker.start()
    try:
        assert building.wait(5), "the builder never started"
        # A later lookup arms the same backend under B while A's build is paused.
        _patch_model_set(monkeypatch, signature_b)
        monkeypatch.setattr(manager_module, "_build_host_llm", lambda app_config=None: "client-b")
        assert get_memory_manager() is manager
        assert manager._refreshed == ["client-b"]
        # The catalog rolls back to A before the paused build completes.
        _patch_model_set(monkeypatch, signature_a)
    finally:
        release.set()
        worker.join(10)

    assert results == [manager]
    assert manager._refreshed == ["client-b"], "the first installed client must win"
    assert manager_module._memory_model_armed_signature == signature_b


def test_two_threads_arm_the_same_model_set_once(monkeypatch) -> None:
    """Concurrent first lookups may each build a client, but exactly one install
    lands: the revalidation under the lock skips the duplicate."""
    import threading

    from deerflow.agents.memory import manager as manager_module

    set_memory_config(MemoryConfig(manager_class=f"{__name__}:_HostLlmRecordingBackend"))
    _patch_model_set(monkeypatch, _model_signature("shared"))
    manager = get_memory_manager()

    rendezvous = threading.Barrier(2, timeout=5)

    def _build(app_config=None):
        # Both threads are inside the build before either can install.
        rendezvous.wait()
        return object()

    monkeypatch.setattr(manager_module, "_build_host_llm", _build)
    results: list = []
    workers = [threading.Thread(target=lambda: results.append(get_memory_manager())) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(10)

    assert results == [manager, manager]
    assert len(manager._refreshed) == 1


def test_a_backend_that_owns_its_model_never_reads_the_merged_config(monkeypatch) -> None:
    """The re-arm costs nothing when the backend has its own model (an explicit
    ``memory.backend_config.model`` included): the gate is decided from the
    backend's state, so the merged config is never read for it."""
    from deerflow.agents.memory import manager as manager_module

    reads: list[int] = []
    monkeypatch.setattr(manager_module, "_read_model_set", lambda: reads.append(1) or None)
    monkeypatch.setattr(_HostLlmRecordingBackend, "host_model_present", True)
    set_memory_config(MemoryConfig(manager_class=f"{__name__}:_HostLlmRecordingBackend"))

    manager = get_memory_manager()
    assert get_memory_manager() is manager

    assert reads == []
    assert manager_module._memory_model_armed_signature == ()


def test_a_build_for_a_retired_manager_is_not_published(monkeypatch) -> None:
    """A build that lost a ``reset_memory_manager()`` race must be dropped: the
    retired backend no longer serves callers, and arming it would close the gate
    for the manager that replaced it."""
    import threading

    from deerflow.agents.memory import manager as manager_module

    set_memory_config(MemoryConfig(manager_class=f"{__name__}:_HostLlmRecordingBackend"))
    signature = _model_signature("first")
    _patch_model_set(monkeypatch, signature)
    manager = get_memory_manager()

    building = threading.Event()
    release = threading.Event()
    builds = {"count": 0}

    def _slow_build(app_config=None):
        builds["count"] += 1
        if builds["count"] == 1:
            building.set()
            assert release.wait(5), "the test never released the builder"
            return object()
        # The replacement's own first build still has no client.
        return None

    monkeypatch.setattr(manager_module, "_build_host_llm", _slow_build)
    results: list = []
    worker = threading.Thread(target=lambda: results.append(get_memory_manager()))
    worker.start()
    try:
        assert building.wait(5), "the builder never started"
        reset_memory_manager()
        replacement = get_memory_manager()
    finally:
        release.set()
        worker.join(10)

    assert results == [replacement]
    assert manager._refreshed == [], "a retired backend must not be armed"
    assert manager_module._memory_model_armed_signature is None, "the replacement keeps its gate open"

    # The replacement still arms once a client can be built for it.
    host_llm = object()
    monkeypatch.setattr(manager_module, "_build_host_llm", lambda app_config=None: host_llm)
    manager_module._memory_model_failure = None
    assert get_memory_manager() is replacement
    assert replacement._refreshed == [host_llm]


def test_an_unreadable_model_set_is_not_reread_inside_the_retry_window(monkeypatch) -> None:
    """Reading the merged config is what fails, so the ``_UNREADABLE`` deadline
    must be honored before the read: a broken catalog is retried once per window,
    not on every memory call (each attempt is a failed decrypt plus a traceback)."""
    from deerflow.agents.memory import manager as manager_module

    reads: list[int] = []

    def _unreadable():
        reads.append(1)
        return None

    monkeypatch.setattr(manager_module, "_read_model_set", _unreadable)
    set_memory_config(MemoryConfig(manager_class=f"{__name__}:_HostLlmRecordingBackend"))

    manager = get_memory_manager()
    assert get_memory_manager() is manager
    assert get_memory_manager() is manager
    assert len(reads) == 1


def test_the_client_is_built_from_the_snapshot_that_was_digested(monkeypatch) -> None:
    """The digest and the client must describe the same catalog.

    Reading the config twice lets an edit land in between: a catalog that goes
    A -> B -> A makes the revalidation compare A's digest against A's config and
    accept a client built from B -- both look current, so nothing notices.
    """
    from types import SimpleNamespace

    from deerflow.agents.memory import manager as manager_module
    from deerflow.config.model_config import ModelConfig

    snapshot = SimpleNamespace(models=[ModelConfig(name="a", use="langchain_openai:ChatOpenAI", model="m", api_key="sk")])
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: snapshot)
    set_memory_config(MemoryConfig(manager_class=f"{__name__}:_HostLlmRecordingBackend"))

    handed: list = []

    def _build(app_config=None):
        handed.append(app_config)
        return object()

    monkeypatch.setattr(manager_module, "_build_host_llm", _build)
    manager = get_memory_manager()
    # The first lookup builds the singleton; the next one is what re-arms it.
    assert get_memory_manager() is manager

    assert handed == [snapshot], "the build must receive the config the digest was computed from"
    assert len(manager._refreshed) == 1
    assert manager_module._memory_model_armed_signature == manager_module._model_set_signature(snapshot)


def test_build_host_llm_forwards_the_snapshot_to_the_factory(monkeypatch) -> None:
    """The refresh hands the digested snapshot to the builder, but the builder
    must hand that same object to the factory.

    Every other case stubs ``_build_host_llm``, so dropping ``app_config`` there
    would keep them green while an A -> B -> A catalog installs B's client under
    A's digest again.
    """
    import deerflow.models as models_module
    from deerflow.agents.memory import manager as manager_module

    seen: list = []
    monkeypatch.setattr(models_module, "create_chat_model", lambda **kwargs: seen.append(kwargs) or object())
    snapshot = object()

    manager_module._build_host_llm(snapshot)

    assert seen == [{"name": None, "app_config": snapshot}]


def test_a_retired_manager_cannot_publish_a_failure_deadline(monkeypatch) -> None:
    """A read begun before ``reset_memory_manager()`` can fail only after the
    replacement exists. Recording that deadline would make the replacement skip
    an already readable catalog for a full window, so failures are scoped to the
    manager that produced them -- the same identity check the install path has."""
    from types import SimpleNamespace

    from deerflow.agents.memory import manager as manager_module
    from deerflow.config.model_config import ModelConfig

    readable = {"value": False}

    def _config():
        if not readable["value"]:
            raise ValueError("cannot decrypt the managed model catalog")
        return SimpleNamespace(models=[ModelConfig(name="a", use="langchain_openai:ChatOpenAI", model="m", api_key="sk")])

    monkeypatch.setattr("deerflow.config.get_app_config", _config)
    set_memory_config(MemoryConfig(manager_class=f"{__name__}:_HostLlmRecordingBackend"))
    stale = get_memory_manager()

    reset_memory_manager()
    replacement = get_memory_manager()
    assert replacement is not stale

    # The retired backend's read finishes only now, and it failed.
    manager_module._refresh_llm_for_reloaded_models(stale)
    assert manager_module._memory_model_failure is None, "a retired backend's failure must die with it"

    # The replacement sees a readable catalog and arms immediately instead of
    # inheriting the retired backend's window.
    readable["value"] = True
    host_llm = object()
    monkeypatch.setattr(manager_module, "_build_host_llm", lambda app_config=None: host_llm)
    assert get_memory_manager() is replacement
    assert replacement._refreshed == [host_llm]
