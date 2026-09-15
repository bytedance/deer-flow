"""Regression tests for issue #3098.

After several runs, a custom agent's run intermittently failed with::

    Run ... failed: Agent config not found:
    /app/backend/.deer-flow/users/<userid>/agents/<name>/config.yaml

Root cause: the file-backed agent store resolves the agent's directory through
``resolve_agent_dir`` (per-user dir first, legacy fallback) and only afterwards
checks for ``config.yaml`` — a TOCTOU window. ``FileAgentStore.update`` /
``create`` stage the new config to a temp file and commit it with an atomic
``os.replace``; the replace unlinks the old path an instant before linking the
new one. A run whose directory resolution lands inside that window (e.g. while
a concurrent ``update_agent`` tool call or a ``PUT /api/agents/{name}``
self-update rewrites ``config.yaml``) resolves to the default per-user path
where no config exists and raises ``FileNotFoundError``.

Fix: ``FileAgentStore.get`` probes the resolved path first; when
``config.yaml`` is missing there but exists in the *other* layout (per-user vs
legacy), it reads that copy instead of failing. The window shrinks from
"resolution result is stale" to "config.yaml absent from both layouts at this
instant" — and a mid-replace reader now sees either the old or the new config,
never "not found".
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
import yaml

from deerflow.persistence.agents import file as file_module
from deerflow.persistence.agents.file import FileAgentStore


@pytest.fixture()
def store_home(tmp_path: Path, monkeypatch):
    """Root the file store at a temp base dir via the module's get_paths seam."""
    from deerflow.config.paths import Paths

    paths = Paths(base_dir=tmp_path)
    monkeypatch.setattr(file_module._ac, "get_paths", lambda: paths)
    return tmp_path


def _write_agent(base_dir: Path, name: str, *, user_id: str, description: str = "v1") -> Path:
    agent_dir = base_dir / "users" / user_id / "agents" / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "config.yaml").write_text(
        yaml.safe_dump({"name": name, "description": description}, sort_keys=False),
        encoding="utf-8",
    )
    (agent_dir / "SOUL.md").write_text("You are helpful.", encoding="utf-8")
    return agent_dir


def test_get_reads_config_present_in_the_other_layout(store_home):
    """resolve_agent_dir fell back to the per-user default (the race window):
    the config still exists at the legacy layout — get must read it, not raise."""
    name = "efficiency-analysis"
    user_id = "user-1"
    # Legacy-only layout: the per-user resolution never matches, so get()
    # resolves to the legacy dir on its own. To simulate the *stale
    # resolution* branch directly, resolve_agent_dir is made to return the
    # (empty) per-user default path while the config lives legacy-side.
    legacy_dir = store_home / "agents" / name
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "config.yaml").write_text(
        yaml.safe_dump({"name": name, "description": "legacy"}, sort_keys=False),
        encoding="utf-8",
    )

    store = FileAgentStore()
    # Baseline: resolves to the legacy dir normally.
    assert store.get(name, user_id=user_id).description == "legacy"

    # Now simulate the race: resolution observed no config.yaml anywhere and
    # returned the per-user default path, but the legacy config still exists.
    per_user_default = store_home / "users" / user_id / "agents" / name
    import unittest.mock as mock

    import deerflow.persistence.agents.file as fm

    def stale_resolve(agent_name, *, user_id=None):
        # get() receives the stale per-user default path.
        return per_user_default

    with mock.patch.object(fm, "resolve_agent_dir", side_effect=stale_resolve):
        cfg = store.get(name, user_id=user_id)
    assert cfg.name == name
    assert cfg.description == "legacy"


def test_get_survives_concurrent_atomic_config_rewrite(store_home):
    """Hammer get() while update() atomically replaces config.yaml — the
    reader must always see the old or the new config, never FileNotFoundError
    (#3098's "read while being rewritten" race)."""
    name = "efficiency-analysis"
    user_id = "user-1"
    _write_agent(store_home, name, user_id=user_id, description="v0")

    store = FileAgentStore()
    errors: list[BaseException] = []
    stop = threading.Event()

    def writer() -> None:
        i = 0
        while not stop.is_set():
            i += 1
            store.update(name, {"name": name, "description": f"v{i}"}, None, user_id=user_id)

    def reader() -> None:
        try:
            while not stop.is_set():
                cfg = store.get(name, user_id=user_id)
                assert cfg.name == name
                assert cfg.description.startswith("v")
        except BaseException as e:  # noqa: BLE001 — captured for assertion below
            errors.append(e)

    write_thread = threading.Thread(target=writer)
    read_threads = [threading.Thread(target=reader) for _ in range(4)]
    write_thread.start()
    for t in read_threads:
        t.start()
    # Let the race run long enough to interleave replace() with resolution.
    stop.wait(0.5)
    stop.set()
    write_thread.join()
    for t in read_threads:
        t.join()

    assert not errors, f"concurrent reads during atomic rewrite raised: {errors[:3]}"


def test_get_still_raises_when_config_truly_absent(store_home):
    """The fallback must not mask a genuinely missing agent."""
    store = FileAgentStore()
    with pytest.raises(FileNotFoundError, match="Agent (directory|config) not found"):
        store.get("no-such-agent", user_id="user-1")


def test_get_still_raises_for_unparseable_config(store_home):
    """A corrupt config.yaml in the resolved dir must surface ValueError, not
    be silently bypassed by the alternate-layout fallback."""
    name = "broken-agent"
    user_id = "user-1"
    agent_dir = _write_agent(store_home, name, user_id=user_id)
    (agent_dir / "config.yaml").write_text("name: [unclosed", encoding="utf-8")

    store = FileAgentStore()
    with pytest.raises(ValueError, match="Failed to parse agent config"):
        store.get(name, user_id=user_id)
