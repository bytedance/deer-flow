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

import os
from pathlib import Path

from deerflow.config.file_signature import ConfigSignature, get_config_signature


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
