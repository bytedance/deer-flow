# SPDX-License-Identifier: MIT
"""The Lark CLI runtime binary must never be observable half written."""

from __future__ import annotations

import os

import pytest

from deerflow.integrations.lark_cli import _publish_bytes_atomically


def test_publishes_the_content_and_leaves_no_temp_file(tmp_path):
    target = tmp_path / "lark-cli"

    _publish_bytes_atomically(target, b"#!/bin/sh\necho hi\n")

    assert target.read_bytes() == b"#!/bin/sh\necho hi\n"
    assert list(tmp_path.glob("*.tmp")) == []


def test_a_failed_publish_keeps_the_previous_binary(tmp_path, monkeypatch):
    target = tmp_path / "lark-cli"
    target.write_bytes(b"old runtime")

    def _boom(*args, **kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(os, "replace", _boom)

    with pytest.raises(OSError):
        _publish_bytes_atomically(target, b"new runtime")

    assert target.read_bytes() == b"old runtime"
    assert list(tmp_path.glob("*.tmp")) == []


def test_truncating_write_would_have_destroyed_it(tmp_path):
    """Control: the previous implementation loses the binary in the same failure."""
    target = tmp_path / "lark-cli"
    target.write_bytes(b"old runtime")

    try:
        with open(target, "wb") as handle:
            handle.write(b"new ")
            raise OSError("read-only filesystem")
    except OSError:
        pass

    assert target.read_bytes() != b"old runtime"


def test_the_install_path_uses_the_atomic_publish():
    import inspect

    from deerflow.integrations import lark_cli

    source = inspect.getsource(lark_cli)

    assert "destination.write_bytes(" not in source
    assert "_publish_bytes_atomically(destination" in source
