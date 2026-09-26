"""Unit tests for the shared config-file content-signature helper.

``deerflow.config.file_signature.get_config_signature`` was extracted from
verbatim-duplicate implementations that used to live independently in
``deerflow.config.app_config`` and ``deerflow.mcp.cache`` (flagged in review
on PR #4124: "now a verbatim duplicate of
``deerflow/config/app_config.py::_get_config_signature`` / ``_ConfigSignature``
... worth a follow-up to extract both into a small shared helper"). These
tests cover the shared implementation directly, and pin that both former
call sites now delegate to it instead of maintaining independent copies that
can silently drift apart.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from deerflow.config.file_signature import ConfigSignature, get_config_signature, read_config_with_signature


def test_missing_file_returns_none(tmp_path: Path):
    missing = tmp_path / "does-not-exist.json"
    assert get_config_signature(missing) is None


def test_existing_file_returns_full_signature(tmp_path: Path):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"a": 1}', encoding="utf-8")

    signature = get_config_signature(cfg)

    assert signature is not None
    mtime, size, digest = signature
    assert mtime == cfg.stat().st_mtime
    assert size == cfg.stat().st_size
    assert isinstance(digest, str) and len(digest) == 64  # sha256 hexdigest


def test_content_change_changes_signature_even_with_same_mtime_and_size(tmp_path: Path):
    """The digest -- not just mtime/size -- must catch a same-length content
    swap within the same second (the exact hole the sha256 exists to close)."""
    cfg = tmp_path / "config.json"
    cfg.write_text('{"server": "srv1"}', encoding="utf-8")
    before = get_config_signature(cfg)
    assert before is not None
    recorded_mtime, recorded_size = before[0], before[1]

    cfg.write_text('{"server": "srv9"}', encoding="utf-8")  # same length, different content
    os.utime(cfg, (recorded_mtime, recorded_mtime))
    assert cfg.stat().st_mtime == recorded_mtime  # guard: mtime truly unchanged
    assert cfg.stat().st_size == recorded_size  # guard: size truly unchanged too

    after = get_config_signature(cfg)
    assert after is not None
    assert after[0] == before[0]
    assert after[1] == before[1]
    assert after[2] != before[2]  # only the digest catches the swap


def test_signature_type_alias_shape():
    """ConfigSignature is the (mtime, size, sha256) tuple type both call sites share."""
    assert ConfigSignature == tuple[float | None, int | None, str | None]


def test_app_config_and_mcp_cache_share_the_same_implementation():
    """Regression guard for the PR #4124 review finding: both modules must
    delegate to this shared helper rather than maintaining independent
    verbatim copies that can silently drift apart over time.
    """
    import deerflow.config.app_config as app_config_module
    import deerflow.mcp.cache as cache_module

    assert app_config_module._get_config_signature is get_config_signature
    assert cache_module._get_config_signature is get_config_signature
    assert app_config_module._ConfigSignature is ConfigSignature
    assert cache_module._ConfigSignature is ConfigSignature


def test_read_config_with_signature_describes_exactly_the_bytes_it_returns(tmp_path: Path):
    """The returned signature must be derived from the returned bytes, not re-read from disk."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("log_level: info\n", encoding="utf-8")

    data, signature = read_config_with_signature(cfg)

    assert data == b"log_level: info\n"
    assert signature == get_config_signature(cfg)  # a stable file yields the same signature either way
    assert signature[1] == len(data)
    assert signature[2] == hashlib.sha256(data).hexdigest()


def test_read_config_with_signature_raises_for_a_missing_file(tmp_path: Path):
    """Unlike ``get_config_signature`` (a probe), reading for parsing must fail loudly like ``open()`` does."""
    import pytest

    with pytest.raises(FileNotFoundError):
        read_config_with_signature(tmp_path / "missing.yaml")


def test_app_config_cache_loader_reads_through_the_shared_reader():
    """``_load_and_cache_app_config`` must parse the same bytes the shared reader signed."""
    import deerflow.config.app_config as app_config_module
    import deerflow.config.file_signature as file_signature_module

    assert app_config_module._read_config_with_signature is file_signature_module.read_config_with_signature


def test_read_config_with_signature_signs_the_bytes_even_when_stat_is_stale(tmp_path: Path, monkeypatch):
    """Size and digest come from the bytes actually read, not from the stat taken before the read."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("log_level: info\n", encoding="utf-8")
    original_stat = Path.stat
    fired = False

    def stat_then_grow(self: Path, *args, **kwargs):
        nonlocal fired
        result = original_stat(self, *args, **kwargs)
        if self == cfg and not fired:  # the file grows between the stat and the read
            fired = True
            with cfg.open("a", encoding="utf-8") as handle:
                handle.write("# appended after stat\n")
        return result

    monkeypatch.setattr(Path, "stat", stat_then_grow)

    data, signature = read_config_with_signature(cfg)

    assert data.endswith(b"# appended after stat\n")
    assert signature[1] == len(data)
    assert signature[2] == hashlib.sha256(data).hexdigest()


def test_read_config_with_signature_hashes_the_bytes_it_returns_not_a_second_read(tmp_path: Path, monkeypatch):
    """The digest must be computed from the returned bytes; a second read could see a newer revision."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("log_level: info\n", encoding="utf-8")
    original_read_bytes = Path.read_bytes
    fired = False

    def read_then_rewrite(self: Path):
        nonlocal fired
        data = original_read_bytes(self)
        if self == cfg and not fired:  # the file is rewritten right after the first read
            fired = True
            cfg.write_text("log_level: debug\n", encoding="utf-8")
        return data

    monkeypatch.setattr(Path, "read_bytes", read_then_rewrite)

    data, signature = read_config_with_signature(cfg)

    assert data == b"log_level: info\n"
    assert signature[2] == hashlib.sha256(data).hexdigest()
