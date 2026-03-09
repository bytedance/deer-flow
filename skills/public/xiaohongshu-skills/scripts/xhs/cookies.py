"""Cookie 文件持久化，对应 Go cookies/cookies.go。"""

from __future__ import annotations

import os
from pathlib import Path


def get_cookies_file_path(account: str = "") -> str:
    """获取 cookies 文件路径。

    优先级：
    1. /tmp/cookies.json（向后兼容）
    2. COOKIES_PATH 环境变量
    3. 多账号模式：~/.xhs/accounts/{account}/cookies.json
    4. ./cookies.json（本地调试）
    """
    if account:
        account_dir = Path.home() / ".xhs" / "accounts" / account
        account_dir.mkdir(parents=True, exist_ok=True)
        return str(account_dir / "cookies.json")

    # 旧路径
    import tempfile

    old_path = os.path.join(tempfile.gettempdir(), "cookies.json")
    if os.path.exists(old_path):
        return old_path

    # 环境变量
    env_path = os.getenv("COOKIES_PATH")
    if env_path:
        return env_path

    return "cookies.json"


def load_cookies(path: str) -> bytes | None:
    """从文件加载 cookies。"""
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def save_cookies(path: str, data: bytes) -> None:
    """保存 cookies 到文件。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def delete_cookies(path: str) -> None:
    """删除 cookies 文件。"""
    import contextlib

    with contextlib.suppress(FileNotFoundError):
        os.remove(path)
