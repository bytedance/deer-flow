import os
import stat

import pytest

from deerflow.skills.permissions import make_skill_tree_sandbox_readable, make_skill_written_path_sandbox_readable


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


_POSIX_MODE_BITS_REASON = "Windows chmod only toggles the read-only bit, so the 0o644/0o755 modes asserted here are never observable"

requires_posix_mode_bits = pytest.mark.skipif(os.name == "nt", reason=_POSIX_MODE_BITS_REASON)


@requires_posix_mode_bits
def test_skill_tree_readability_includes_hidden_paths_and_removes_sandbox_write(tmp_path):
    root = tmp_path / "demo-skill"
    hidden_dir = root / ".hidden"
    scripts_dir = root / "scripts"
    hidden_dir.mkdir(parents=True)
    scripts_dir.mkdir()
    env_file = root / ".env"
    hidden_file = hidden_dir / ".secret"
    script_file = scripts_dir / "run.sh"
    env_file.write_text("secret", encoding="utf-8")
    hidden_file.write_text("secret", encoding="utf-8")
    script_file.write_text("#!/bin/sh\n", encoding="utf-8")

    root.chmod(0o777)
    hidden_dir.chmod(0o777)
    scripts_dir.chmod(0o777)
    env_file.chmod(0o666)
    hidden_file.chmod(0o600)
    script_file.chmod(0o777)

    make_skill_tree_sandbox_readable(root)

    assert _mode(root) == 0o755
    assert _mode(hidden_dir) == 0o755
    assert _mode(scripts_dir) == 0o755
    assert _mode(env_file) == 0o644
    assert _mode(hidden_file) == 0o644
    assert _mode(script_file) == 0o755


def test_written_path_readability_is_limited_to_written_path(tmp_path):
    root = tmp_path / "demo-skill"
    ref_dir = root / "references"
    sibling_dir = root / "templates"
    ref_dir.mkdir(parents=True)
    sibling_dir.mkdir()
    target = ref_dir / "guide.md"
    sibling = sibling_dir / "note.md"
    target.write_text("guide", encoding="utf-8")
    sibling.write_text("note", encoding="utf-8")

    root.chmod(0o700)
    ref_dir.chmod(0o700)
    target.chmod(0o600)
    sibling_dir.chmod(0o700)
    sibling.chmod(0o600)

    make_skill_written_path_sandbox_readable(root, target)

    # The resolve()/relative_to() traversal is the platform-sensitive part
    # (drive letters, case-insensitive roots, symlinks), so keep it executing
    # on Windows where the chmod effects themselves are not observable.
    assert target.read_text(encoding="utf-8") == "guide"
    assert sibling.read_text(encoding="utf-8") == "note"

    if os.name == "nt":
        pytest.skip(_POSIX_MODE_BITS_REASON)

    assert _mode(root) == 0o755
    assert _mode(ref_dir) == 0o755
    assert _mode(target) == 0o644
    assert _mode(sibling_dir) == 0o700
    assert _mode(sibling) == 0o600
