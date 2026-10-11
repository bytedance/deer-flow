# SPDX-License-Identifier: MIT
"""The Lark skill file and manifest must not be left half written either."""

from __future__ import annotations

import inspect

from deerflow.integrations import lark_cli


def test_skill_file_and_manifest_use_the_atomic_publish():
    """Both writes must go through the helper the runtime files already use."""
    source = inspect.getsource(lark_cli)

    # A truncating write here left a partial skill file or an unparseable manifest,
    # and the manifest carries the content hash the install is verified against.
    assert "skill_file.write_text(" not in source
    assert "(root / LARK_CLI_MANIFEST_FILE).write_text(" not in source
    assert "_publish_bytes_atomically(skill_file," in source
    assert "_publish_bytes_atomically(\n        root / LARK_CLI_MANIFEST_FILE," in source


def test_the_helper_is_still_the_one_used_for_the_runtime_files():
    source = inspect.getsource(lark_cli)

    assert "_publish_bytes_atomically(destination" in source
    assert "_publish_bytes_atomically(launcher" in source
