"""Filesystem permission helpers for installed skill trees."""

import stat
from pathlib import Path


def make_skill_path_sandbox_readable(path: Path) -> None:
    if path.is_symlink():
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    without_sandbox_write = mode & ~(stat.S_IWGRP | stat.S_IWOTH)
    if path.is_dir():
        path.chmod(without_sandbox_write | 0o555)
    elif path.is_file():
        path.chmod(without_sandbox_write | 0o444)


def make_skill_tree_sandbox_readable(target: Path) -> None:
    make_skill_path_sandbox_readable(target)
    for path in target.rglob("*"):
        make_skill_path_sandbox_readable(path)


def make_skill_written_path_sandbox_readable(skill_root: Path, target: Path) -> None:
    resolved_root = skill_root.resolve()
    resolved_target = target.resolve()
    resolved_target.relative_to(resolved_root)

    make_skill_path_sandbox_readable(resolved_root)
    current = resolved_root
    for part in resolved_target.parent.relative_to(resolved_root).parts:
        current = current / part
        make_skill_path_sandbox_readable(current)
    make_skill_path_sandbox_readable(resolved_target)
