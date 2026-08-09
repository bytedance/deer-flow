"""只读 Coding 子 Agent 的 Worktree 完整性校验。"""

import hashlib
import subprocess
from pathlib import Path


class WorktreeIntegrityError(RuntimeError):
    """无法计算或验证 Git Worktree 指纹。"""


def _git_bytes(worktree: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(worktree), *args],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode(errors="replace").strip()
        raise WorktreeIntegrityError(detail or "git command failed")
    return completed.stdout


def capture_worktree_fingerprint(worktree: str) -> str:
    """计算所有 Git 可见改动和非忽略未跟踪文件内容的稳定指纹。"""
    root = Path(worktree).resolve()
    digest = hashlib.sha256()
    digest.update(_git_bytes(root, "rev-parse", "HEAD"))
    digest.update(_git_bytes(root, "diff", "--binary", "HEAD", "--"))

    untracked = _git_bytes(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
    for raw_path in sorted(path for path in untracked if path):
        relative = raw_path.decode(errors="surrogateescape")
        path = root / relative
        digest.update(raw_path)
        if path.is_symlink():
            digest.update(str(path.readlink()).encode(errors="surrogateescape"))
        elif path.is_file():
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()
