"""account_manager 单元测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 把 scripts/ 加入路径，使 account_manager 可导入
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import account_manager


@pytest.fixture(autouse=True)
def tmp_config(tmp_path, monkeypatch):
    """将配置目录重定向到临时目录。"""
    monkeypatch.setattr(account_manager, "_CONFIG_DIR", tmp_path / ".xhs")
    monkeypatch.setattr(
        account_manager, "_ACCOUNTS_FILE", tmp_path / ".xhs" / "accounts.json"
    )


def test_add_account_assigns_port():
    """首个命名账号应分配端口 9223。"""
    account_manager.add_account("work", "工作号")
    port = account_manager.get_account_port("work")
    assert port == 9223


def test_second_account_gets_next_port():
    """第二个账号应分配端口 9224。"""
    account_manager.add_account("work")
    account_manager.add_account("personal")
    assert account_manager.get_account_port("personal") == 9224


def test_get_profile_dir_public():
    """get_profile_dir 应返回正确路径。"""
    account_manager.add_account("work")
    profile = account_manager.get_profile_dir("work")
    assert "work" in profile
    assert "chrome-profile" in profile


def test_get_account_port_unknown_raises():
    """不存在的账号应抛出 ValueError。"""
    with pytest.raises(ValueError, match="不存在"):
        account_manager.get_account_port("ghost")


def test_list_accounts_includes_port():
    """list_accounts 返回结果中应包含 port 字段。"""
    account_manager.add_account("work", "工作")
    accounts = account_manager.list_accounts()
    assert len(accounts) == 1
    assert accounts[0]["port"] == 9223
