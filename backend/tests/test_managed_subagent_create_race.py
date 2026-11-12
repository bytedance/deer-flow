"""Create-only publication across independent file-store processes."""

from __future__ import annotations

import errno
import multiprocessing

import pytest

from deerflow.config.paths import Paths
from deerflow.persistence.managed_subagents import ManagedSubagentDefinition, ManagedSubagentExistsError
from deerflow.persistence.managed_subagents import file as file_module


def _definition(name, writer):
    return ManagedSubagentDefinition(name=name, description=f"Writer {writer}", system_prompt=f"Instructions from writer {writer}.")


def _create_in_process(home, name, writer, staged, results):
    # Spawn gives each writer its own module-level RLock and path registry.
    paths = Paths(base_dir=home)
    definition = _definition(name, writer)
    original_fsync = file_module.os.fsync

    def fsync_then_wait(fd):
        original_fsync(fd)
        # Both complete files are staged after both writers passed exists().
        # Synchronize the real I/O boundary, without fabricating a collision.
        staged.wait(timeout=30)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(file_module, "get_paths", lambda: paths)
        patch.setattr(file_module.os, "fsync", fsync_then_wait)
        try:
            file_module.FileManagedSubagentStore().create(definition)
        except ManagedSubagentExistsError:
            outcome = "conflict"
        else:
            outcome = "created"
        results.put((writer, outcome))


@pytest.mark.parametrize("same_name", [True, False], ids=["same-name", "different-names"])
def test_independent_process_creates_never_overwrite_a_winner(tmp_path, monkeypatch, same_name):
    paths = Paths(base_dir=tmp_path)
    monkeypatch.setattr(file_module, "get_paths", lambda: paths)
    names = ["researcher", "researcher" if same_name else "reviewer"]
    context = multiprocessing.get_context("spawn")
    staged = context.Barrier(2)
    results = context.Queue()
    workers = [context.Process(target=_create_in_process, args=(tmp_path, name, writer, staged, results)) for writer, name in enumerate(names)]
    try:
        for worker in workers:
            worker.start()
        outcomes = [results.get(timeout=45) for _ in workers]
        for worker in workers:
            worker.join(10)
            assert worker.exitcode == 0

        assert sorted(outcome for _, outcome in outcomes) == (["conflict", "created"] if same_name else ["created", "created"])
        store = file_module.FileManagedSubagentStore()
        for writer, outcome in outcomes:
            if outcome == "created":
                assert store.get(names[writer]) == _definition(names[writer], writer)
        assert len(store.list()) == (1 if same_name else 2)
        assert sorted(path.name for path in paths.managed_subagents_dir.iterdir()) == sorted({f"{name}.json" for name in names})
    finally:
        staged.abort()
        for worker in workers:
            if worker.pid is not None:
                worker.join(5)
                if worker.is_alive():
                    worker.terminate()
                    worker.join(5)
                worker.close()
        results.close()
        results.join_thread()


def test_create_propagates_publication_errors_and_discards_staging(tmp_path, monkeypatch):
    paths = Paths(base_dir=tmp_path)
    monkeypatch.setattr(file_module, "get_paths", lambda: paths)

    def denied_link(*args, **kwargs):
        raise PermissionError(errno.EPERM, "hard links denied")

    monkeypatch.setattr(file_module.os, "link", denied_link)
    with pytest.raises(PermissionError, match="hard links denied"):
        file_module.FileManagedSubagentStore().create(_definition("researcher", 0))

    assert list(paths.managed_subagents_dir.iterdir()) == []
