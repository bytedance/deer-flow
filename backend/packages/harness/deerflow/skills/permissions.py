"""Filesystem permission helpers for installed skill trees."""

import stat
from pathlib import Path


def make_skill_path_sandbox_readable(path: Path) -> None:
    if path.is_symlink():
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    if path.is_dir():
        path.chmod(mode | 0o555)
    elif path.is_file():
        path.chmod(mode | 0o444)


def make_skill_tree_sandbox_readable(target: Path) -> None:
    make_skill_path_sandbox_readable(target)
    for path in target.rglob("*"):
        make_skill_path_sandbox_readable(path)
