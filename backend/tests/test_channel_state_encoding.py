"""Pin the cross-platform byte contract for IM channel JSON state writers."""

import ast
import json
from pathlib import Path

import pytest

CHANNELS = Path(__file__).parents[1] / "app" / "channels"


def _state_io_calls(filename: str, class_name: str, method_name: str, call_name: str) -> list[ast.Call]:
    module = ast.parse((CHANNELS / filename).read_text(encoding="utf-8"))
    owner = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(node for node in owner.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name)
    calls = [node for node in ast.walk(method) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == call_name]
    assert calls, f"{filename}:{class_name}.{method_name} has no {call_name} call"
    return calls


@pytest.mark.parametrize(
    ("filename", "class_name", "method_name", "call_name"),
    [
        ("store.py", "JsonChannelStore", "_save", "NamedTemporaryFile"),
        ("runtime_config_store.py", "ChannelRuntimeConfigStore", "_save", "NamedTemporaryFile"),
        ("buzz_seen_events.py", "BuzzSeenEventStore", "_write_snapshot", "NamedTemporaryFile"),
        ("wechat.py", "WechatChannel", "_save_auth_state", "NamedTemporaryFile"),
    ],
)
def test_json_channel_state_writers_pin_utf8_and_lf(filename: str, class_name: str, method_name: str, call_name: str) -> None:
    for call in _state_io_calls(filename, class_name, method_name, call_name):
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        for name, expected in (("encoding", "utf-8"), ("newline", "")):
            value = keywords.get(name)
            assert isinstance(value, ast.Constant) and value.value == expected, f"{filename}:{call.lineno} must pin {name}={expected!r}"


def test_json_channel_store_writes_utf8_lf_bytes(tmp_path: Path) -> None:
    from app.channels.store import JsonChannelStore

    path = tmp_path / "channels" / "store.json"
    store = JsonChannelStore(path)
    store._set_sync("微信:资源", "thread-讨论", "用户")

    text = path.read_bytes().decode("utf-8")
    assert "\r" not in text
    assert "\\u5fae\\u4fe1" in text
    entry = json.loads(text)["微信:资源"]
    assert entry["thread_id"] == "thread-讨论"
    assert entry["user_id"] == "用户"


def test_discord_state_read_is_explicitly_utf8() -> None:
    for call in _state_io_calls("discord.py", "DiscordChannel", "_load_active_threads", "read_text"):
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        encoding = keywords.get("encoding")
        assert isinstance(encoding, ast.Constant) and encoding.value == "utf-8"


def test_discord_thread_mappings_publish_utf8_lf_bytes(tmp_path: Path) -> None:
    import threading

    from app.channels.discord import DiscordChannel

    channel = DiscordChannel.__new__(DiscordChannel)
    channel._thread_store_lock = threading.Lock()
    channel._active_threads = {"微信:资源": {"thread_id": "thread-讨论"}}
    channel._thread_store_path = tmp_path / "discord-threads.json"

    channel._persist_thread_mappings()

    text = channel._thread_store_path.read_bytes().decode("utf-8")
    assert "\r" not in text
    assert json.loads(text)["微信:资源"]["thread_id"] == "thread-讨论"


def test_wechat_cursor_state_publishes_utf8_lf_bytes(tmp_path: Path) -> None:
    from app.channels.wechat import WechatChannel

    channel = WechatChannel.__new__(WechatChannel)
    channel._cursor_path = tmp_path / "wechat-cursor.json"
    channel._get_updates_buf = "游标-1"

    channel._save_state()

    text = channel._cursor_path.read_bytes().decode("utf-8")
    assert "\r" not in text
    assert json.loads(text) == {"get_updates_buf": "游标-1"}


def _method_calls(filename: str, class_name: str, method_name: str) -> list[ast.Call]:
    module = ast.parse((CHANNELS / filename).read_text(encoding="utf-8"))
    owner = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(node for node in owner.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name)
    return [node for node in ast.walk(method) if isinstance(node, ast.Call)]


@pytest.mark.parametrize(
    ("filename", "class_name", "method_name"),
    [
        ("discord.py", "DiscordChannel", "_persist_thread_mappings"),
        ("wechat.py", "WechatChannel", "_save_state"),
    ],
)
def test_json_channel_state_writers_publish_through_the_helper(filename: str, class_name: str, method_name: str) -> None:
    """Platform-independent: the call shape, not just the bytes it happens to emit.

    CI runs with ``PYTHONUTF8=1``, so a regression to ``write_text(...)`` without
    ``encoding=`` would still produce valid UTF-8 there; only a source-level check
    catches it on every platform.
    """
    calls = _method_calls(filename, class_name, method_name)
    names = [call.func.attr if isinstance(call.func, ast.Attribute) else call.func.id for call in calls if isinstance(call.func, (ast.Attribute, ast.Name))]
    assert "publish_bytes_atomically" in names, f"{filename}:{class_name}.{method_name} must publish through the helper"

    for call in calls:
        if not isinstance(call.func, ast.Attribute) or call.func.attr not in {"write_text", "write_bytes"}:
            continue
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        encoding = keywords.get("encoding")
        assert isinstance(encoding, ast.Constant) and encoding.value == "utf-8", f"{filename}:{call.lineno} writes text without an explicit utf-8 encoding"
