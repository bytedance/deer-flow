"""Real filesystem churn must preserve credential hardening and publication."""

from __future__ import annotations

import json
import os
import stat
import threading
from pathlib import Path

import pytest

from deerflow.config import paths as paths_module
from deerflow.config.paths import Paths
from deerflow.integrations import lark_cli

pytestmark = [
    pytest.mark.skipif(os.name == "nt", reason="POSIX credential-tree semantics"),
    pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning"),
]


def _seed(base_dir: Path, user_id: str) -> dict[str, Path]:
    root = Paths(base_dir=base_dir).user_dir(user_id) / "integrations" / lark_cli.INTEGRATION_ID
    paths = {"root": root, "config": root / "config", "locks": root / "config" / "locks", "data": root / "data"}
    for directory in paths.values():
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o755)
    for name in ("victim", "survivor"):
        paths[name] = paths["data"] / f"{name}.json"
        paths[name].write_text("{}", encoding="utf-8")
        paths[name].chmod(0o644)
    return paths


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


@pytest.mark.parametrize("boundary", ["lstat", "chmod", "iterdir"])
def test_vanished_descendant_is_skipped_and_survivors_are_hardened(monkeypatch, tmp_path, boundary):
    paths = _seed(tmp_path, "alice")
    victim = paths["victim"]
    if boundary == "iterdir":
        victim = paths["root"] / "transient"
        victim.mkdir()
    injected = []
    original = getattr(Path, boundary)

    def remove_at_boundary(path, *args, **kwargs):
        if path == victim and not injected:
            injected.append(path)
            if boundary == "iterdir":
                path.rmdir()
            else:
                path.unlink()
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, boundary, remove_at_boundary)
    lark_cli.ensure_lark_cli_credential_tree("alice", paths=Paths(base_dir=tmp_path))

    assert injected == [victim], "the walk never reached the injected boundary"
    assert not victim.exists(), "the test must actually remove the candidate"
    for name in ("root", "config", "locks", "data"):
        assert _mode(paths[name]) == 0o700, name
    assert _mode(paths["survivor"]) == 0o600


def test_root_renamed_at_walk_lstat_propagates(monkeypatch, tmp_path):
    root = _seed(tmp_path, "alice")["root"]
    moved = tmp_path / "moved-root"
    injected = []
    armed = threading.Event()
    original_lstat, original_mkdir = Path.lstat, Path.mkdir

    def mkdir(path, *args, **kwargs):
        result = original_mkdir(path, *args, **kwargs)
        if path == root:
            armed.set()
        return result

    def lstat(path):
        if path == root and armed.is_set() and not injected:
            injected.append(path)
            root.rename(moved)
        return original_lstat(path)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(FileNotFoundError):
        lark_cli.ensure_lark_cli_credential_tree("alice", paths=Paths(base_dir=tmp_path))
    assert injected == [root]
    assert moved.is_dir() and not root.exists()


@pytest.mark.parametrize("target", ["root", "victim"])
def test_permission_errors_still_propagate(monkeypatch, tmp_path, target):
    paths = _seed(tmp_path, "alice")
    injected = []
    original = Path.chmod

    def chmod(path, *args, **kwargs):
        if path == paths[target]:
            injected.append(path)
            raise PermissionError("synthetic chmod denial")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "chmod", chmod)
    with pytest.raises(PermissionError, match="synthetic chmod denial"):
        lark_cli.ensure_lark_cli_credential_tree("alice", paths=Paths(base_dir=tmp_path))
    assert injected == [paths[target]]


def test_symlink_descendant_is_still_rejected(tmp_path):
    paths = _seed(tmp_path, "alice")
    outside = tmp_path / "outside"
    outside.mkdir()
    (paths["data"] / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        lark_cli.ensure_lark_cli_credential_tree("alice", paths=Paths(base_dir=tmp_path))


def test_login_result_publication_survives_real_unlink_churn(monkeypatch, tmp_path):
    monkeypatch.setattr(paths_module, "_paths", Paths(base_dir=tmp_path))
    generation = "gen-pub"
    digest = lark_cli._lark_login_code_digest("code-A")
    listed, removed = threading.Event(), threading.Event()
    original_iterdir, original_lstat = Path.iterdir, Path.lstat
    missing_candidates = set()

    # Acquire before seeding loose permissions, so publication's real walk is
    # responsible for fixing them while another thread removes listed files.
    with lark_cli._lark_credential_lock("alice"):
        paths = _seed(tmp_path, "alice")
        victims = {paths["victim"], paths["data"] / "victim-b.json"}
        (paths["data"] / "victim-b.json").write_text("{}", encoding="utf-8")

        def iterdir(path):
            entries = list(original_iterdir(path))
            if path == paths["data"] and not listed.is_set():
                assert victims <= set(entries)
                listed.set()
                assert removed.wait(10), "churn thread did not remove listed files"
            return iter(entries)

        def lstat(path):
            if path in victims and removed.is_set():
                missing_candidates.add(path)
            return original_lstat(path)

        def churn():
            assert listed.wait(10), "publication never enumerated the data directory"
            for victim in victims:
                victim.unlink()
            removed.set()

        monkeypatch.setattr(Path, "iterdir", iterdir)
        monkeypatch.setattr(Path, "lstat", lstat)
        thread = threading.Thread(target=churn, name="lark-credential-churn")
        thread.start()
        try:
            assert lark_cli._write_lark_login_result_once("alice", generation, digest, {"ok": True})
        finally:
            thread.join(10)

    assert not thread.is_alive()
    assert listed.is_set() and removed.is_set()
    assert missing_candidates == victims, "the walk must inspect the removed candidates"
    assert all(not victim.exists() for victim in victims)
    result = lark_cli._lark_login_result_path("alice", generation, digest)
    assert json.loads(result.read_text(encoding="utf-8")) == {"ok": True}
    assert list(paths["root"].glob(".login-result-*.json")) == [result]
    assert not list(paths["root"].glob(f".{result.name}.*"))
    assert _mode(paths["survivor"]) == 0o600
    assert _mode(result) == 0o600
    for name in ("root", "config", "locks", "data"):
        assert _mode(paths[name]) == 0o700, name
