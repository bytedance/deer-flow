"""Atomic publication shared by managed model and image catalogs."""

import os
from pathlib import Path

import pytest

from deerflow.config.encrypted_catalog import EncryptedCatalog


@pytest.mark.parametrize("replace_fails", [False, True])
def test_catalog_write_cleanup_cannot_override_publication_result(tmp_path, monkeypatch, replace_fails):
    target = tmp_path / "catalog.enc"

    def failed_cleanup(_path, *, missing_ok=False):
        raise OSError("synthetic cleanup failure")

    def failed_replace(_source, _target):
        raise OSError("synthetic replace failure")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", failed_cleanup)
        if replace_fails:
            patch.setattr(os, "replace", failed_replace)
            with pytest.raises(OSError, match="synthetic replace failure"):
                EncryptedCatalog.write_bytes(target, b"new catalog")
        else:
            EncryptedCatalog.write_bytes(target, b"new catalog")

    if replace_fails:
        assert not target.exists()
    else:
        assert target.read_bytes() == b"new catalog"
